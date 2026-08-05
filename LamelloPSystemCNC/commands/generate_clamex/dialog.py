"""
Command dialog inputs for the Lamello P-System CNC Toolpath Addin.

Builds the Setup / Edge / Face tabs plus the global
Preview checkbox, reads preview/generation values, and routes inputChanged
events to placement-set and tool-parameter state.
"""

import adsk.core
import adsk.cam
import adsk.fusion

from lib.cam_ops import (
    find_tool_by_description,
    list_document_tools,
    list_milling_setups,
    tool_flute_length_mm,
)
from lib.errors import UserFacingError
from lib.example_tools import (
    SAMPLE_DRILL_DESCRIPTION,
    SAMPLE_FLAT_DESCRIPTION,
    SAMPLE_PREFERRED_BY_SECTION,
    SAMPLE_SIDE_DESCRIPTION,
    add_example_tools,
    format_add_result_message,
    prompt_add_example_tools_if_empty,
)
from lib.placement_sets import (
    MODE_FLAT,
    MODE_SIDE,
    TAB_FLAT,
    TAB_SETUP_TOOL,
    TAB_SIDE,
    DialogState,
    INPUT_ADD_EXAMPLE_TOOLS,
    INPUT_PREVIEW,
    INPUT_SETUP,
    PlacementSetState,
    _default_op_prefix_for_mode,
    _is_anchor_entity,
    automatic_op_prefixes,
    migrate_op_prefix,
    mode_display_label,
)
from lib.settings import load_settings, settings_prefix
from lib.tool_params import (
    SECTION_DRILL,
    SECTION_FLAT,
    SECTION_SIDE,
    ToolParamsController,
)
from lib.toolpath_def import (
    CUTTER_Z_REFERENCE_OPTIONS,
    DEFAULT_CONNECTOR_TYPE,
    DEFAULT_CUTTER_Z_REFERENCE,
    DEFAULT_DRILL_CLEARANCE_MM,
    half_flute_mm,
    migrate_cutter_z_reference,
)
from lib.ui_helpers import read_dropdown, select_dropdown

# ConstructionAxes is not a valid SelectionCommandInput filter (Fusion API
# Selection Filters list). Construction lines cover the selectable case;
# reference_axis_direction still accepts ConstructionAxis if provided.
_REFERENCE_AXIS_FILTERS = (
    'LinearEdges',
    'SketchLines',
    'ConstructionLines',
)

# Edge cut-in uses the inward normal of the face being machined into.
_CUT_IN_FACE_FILTERS = ('PlanarFaces',)

_ANCHOR_POINT_FILTERS = (
    'JointOrigins',
    'SketchPoints',
    'Vertices',
    'ConstructionPoints',
)

def resolve_side_half_flute_mm(inputs, dialog_state):
    """Absolute half side-cutter flute length (mm) for cutter Z offsets."""
    controller = dialog_state.tool_controller if dialog_state else None
    if not controller:
        return half_flute_mm(None)
    description = controller.selected_description(inputs, SECTION_SIDE)
    cam = adsk.cam.CAM.cast(adsk.core.Application.get().activeProduct)
    tool = find_tool_by_description(cam, description) if cam and description else None
    return half_flute_mm(tool_flute_length_mm(tool))


def _load_cutter_z_reference(saved, prefix):
    """Resolve cutter Z reference from settings, migrating legacy bool keys."""
    key = f'{prefix}cutter_z_reference'
    if key in saved:
        return migrate_cutter_z_reference(saved[key])
    if 'cutter_z_reference' in saved:
        return migrate_cutter_z_reference(saved['cutter_z_reference'])
    legacy = saved.get(
        f'{prefix}tool_thickness_offset',
        saved.get(
            'tool_thickness_offset',
            saved.get('tool_half_thickness_offset'),
        ),
    )
    if legacy is None:
        return DEFAULT_CUTTER_Z_REFERENCE
    return migrate_cutter_z_reference(legacy)


def _read_setup_name(inputs):
    setup_dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById(INPUT_SETUP))
    return read_dropdown(setup_dropdown)


def read_preview_enabled(inputs):
    """Return the state of the global Preview checkbox (defaults to on)."""
    checkbox = adsk.core.BoolValueCommandInput.cast(inputs.itemById(INPUT_PREVIEW))
    if not checkbox:
        return True
    return bool(checkbox.value)


def _milling_tab_visible(inputs, mode):
    """True when the given milling tab is the visible tab (its selection UI is live)."""
    tab_id = TAB_SIDE if mode == MODE_SIDE else TAB_FLAT
    tab = adsk.core.TabCommandInput.cast(inputs.itemById(tab_id))
    return bool(tab and tab.isActive)


def _load_set_defaults(saved, mode):
    """Map persisted settings to per-set defaults for one milling tab."""
    prefix = settings_prefix(mode)
    connector_type = saved.get(
        f'{prefix}connector_type',
        saved.get('connector_type', DEFAULT_CONNECTOR_TYPE),
    )
    return {
        'flip_feed': saved.get(
            f'{prefix}flip_feed',
            saved.get('flip_feed', not saved.get('positive_direction', True)),
        ),
        'flip_z': saved.get(
            f'{prefix}flip_z',
            saved.get('flip_z', not saved.get('depth_positive_direction', True)),
        ),
        'cutter_z_reference': _load_cutter_z_reference(saved, prefix),
        'connector_type': connector_type,
        'op_prefix': migrate_op_prefix(
            mode,
            saved.get(f'{prefix}op_prefix', saved.get('op_prefix')),
            connector_type,
        ),
        'drill_holes': saved.get(f'{prefix}drill_holes', saved.get('drill_holes', False)),
        'drill_clearance_mm': saved.get(
            f'{prefix}drill_clearance_mm',
            saved.get('drill_clearance_mm', DEFAULT_DRILL_CLEARANCE_MM),
        ),
    }


def update_drill_input_visibility(inputs):
    """Show the side-tab drill clearance input only while drilling is enabled."""
    ids = PlacementSetState(MODE_SIDE).ids
    drill_enabled = adsk.core.BoolValueCommandInput.cast(inputs.itemById(ids.DRILL_HOLES))
    drill_clearance = adsk.core.StringValueCommandInput.cast(inputs.itemById(ids.DRILL_CLEARANCE))
    visible = bool(drill_enabled and drill_enabled.value)
    if drill_clearance:
        drill_clearance.isVisible = visible


def activate_tab_inputs(inputs, dialog_state, inactive_state=None):
    """Restore the active tab's detail UI after a tab switch."""
    dialog_state.active_state().load_detail_to_inputs(inputs)
    if dialog_state.active_mode == MODE_SIDE:
        update_drill_input_visibility(inputs)
    if inactive_state:
        inactive_state.clear_selection_ui(inputs)


def _build_mode_inputs(parent_inputs, mode, set_defaults):
    """Build placement-set UI inside a milling tab. Returns PlacementSetState."""
    state = PlacementSetState(mode, set_defaults)
    ids = state.ids
    mode_label = mode_display_label(mode)

    table = parent_inputs.addTableCommandInput(ids.SETS_TABLE, 'Placement sets', 2, '1:2')
    table.maximumVisibleRows = 6
    if mode == MODE_SIDE:
        table.tooltip = (
            f'Batches of anchors machined with the same cut-in face and options. '
            f'Each row is one {mode_label} placement set.'
        )
    else:
        table.tooltip = (
            f'Batches of anchors machined with the same feed axis and options. '
            f'Each row is one {mode_label} placement set.'
        )

    add_button = parent_inputs.addBoolValueInput(ids.SET_ADD, 'Add set', False, '', False)
    add_button.tooltip = 'Add another placement set to this tab.'
    table.addToolbarCommandInput(add_button)
    delete_button = parent_inputs.addBoolValueInput(ids.SET_DELETE, 'Delete set', False, '', False)
    delete_button.tooltip = 'Remove the selected placement set.'
    table.addToolbarCommandInput(delete_button)

    sel = parent_inputs.addSelectionInput(
        ids.ANCHOR_POINTS,
        'Anchor points',
        'Select one or more Joint Origins, sketch points, vertices, or construction points',
    )
    sel.tooltip = (
        'Points that locate each connector. Joint Origins, sketch points, '
        'vertices, and construction points are supported.'
    )
    for filter_name in _ANCHOR_POINT_FILTERS:
        sel.addSelectionFilter(filter_name)
    sel.setSelectionLimits(0, 0)

    if mode == MODE_SIDE:
        axis_sel = parent_inputs.addSelectionInput(
            ids.REFERENCE_AXIS,
            'Cut-in face',
            'Select the planar face being cut into',
        )
        axis_sel.tooltip = (
            'Planar face the edge cutter enters. Cut-in follows the inward face '
            'normal (into the solid). Use Flip feed to reverse it.'
        )
        for filter_name in _CUT_IN_FACE_FILTERS:
            axis_sel.addSelectionFilter(filter_name)
    else:
        axis_sel = parent_inputs.addSelectionInput(
            ids.REFERENCE_AXIS,
            'Feed axis',
            'Select a linear edge, sketch line, or construction line for slot direction',
        )
        axis_sel.tooltip = (
            'Linear edge, sketch line, or construction line that sets the machining '
            'direction along the connector. Use Flip feed to reverse it.'
        )
        for filter_name in _REFERENCE_AXIS_FILTERS:
            axis_sel.addSelectionFilter(filter_name)
    # At most one feed / cut-in reference; empty allowed while editing a set.
    axis_sel.setSelectionLimits(0, 1)

    connector_dropdown = parent_inputs.addDropDownCommandInput(
        ids.CONNECTOR_TYPE,
        'Connector type',
        adsk.core.DropDownStyles.TextListDropDownStyle,
    )
    connector_dropdown.tooltip = (
        'P-System connector size. P14 and P10 use different geometry offsets; '
        'changing it also updates the operation name prefix while it is still '
        'on the automatic default.'
    )
    connector_dropdown.listItems.add('P14', False, '')
    connector_dropdown.listItems.add('P10', False, '')
    select_dropdown(
        connector_dropdown,
        set_defaults.get('connector_type', DEFAULT_CONNECTOR_TYPE),
    )

    flip_feed = parent_inputs.addBoolValueInput(
        ids.FLIP_FEED,
        'Flip feed',
        True,
        '',
        set_defaults.get('flip_feed', False),
    )
    if mode == MODE_SIDE:
        flip_feed.tooltip = (
            'Reverse cut-in direction relative to the face normal '
            '(into vs out of the solid).'
        )
    else:
        flip_feed.tooltip = 'Reverse the machining direction along the feed axis.'

    flip_z = parent_inputs.addBoolValueInput(
        ids.FLIP_Z,
        'Flip Z',
        True,
        '',
        set_defaults.get('flip_z', False),
    )
    flip_z.tooltip = (
        'Reverse the depth direction relative to the setup WCS Z axis '
        '(machine into rather than out of the part).'
    )

    if mode == MODE_SIDE:
        cutter_z = parent_inputs.addDropDownCommandInput(
            ids.CUTTER_Z_REFERENCE,
            'Cutter Z Reference',
            adsk.core.DropDownStyles.TextListDropDownStyle,
        )
        cutter_z.tooltip = (
            'Which part of the edge-cutter flute is the Z reference. '
            'Flute Top / Bottom offset the path by ±½ flute length; '
            'Flute Centre applies no offset.'
        )
        for option in CUTTER_Z_REFERENCE_OPTIONS:
            cutter_z.listItems.add(option, False, '')
        select_dropdown(
            cutter_z,
            set_defaults.get('cutter_z_reference', DEFAULT_CUTTER_Z_REFERENCE),
        )

    op_prefix = parent_inputs.addStringValueInput(
        ids.OP_PREFIX,
        'Operation name prefix',
        set_defaults.get('op_prefix') or _default_op_prefix_for_mode(
            mode,
            set_defaults.get('connector_type'),
        ),
    )
    op_prefix.tooltip = (
        f'Prefix for generated CAM operation names, e.g. "P14 - {mode_label} - JO1". '
        'Follows the connector type automatically until you type a custom prefix.'
    )

    if mode == MODE_SIDE:
        drill_holes = parent_inputs.addBoolValueInput(
            ids.DRILL_HOLES,
            'Drill key holes',
            True,
            '',
            set_defaults.get('drill_holes', False),
        )
        drill_holes.tooltip = (
            'Also create Drill operations for the connector tightening hole. '
            'Uses the Drill tool from the Setup tab.'
        )

        drill_clearance = parent_inputs.addStringValueInput(
            ids.DRILL_CLEARANCE,
            'Clearance above anchor (mm)',
            str(set_defaults.get('drill_clearance_mm', DEFAULT_DRILL_CLEARANCE_MM)),
        )
        drill_clearance.tooltip = (
            'Drill retract/clearance height above the anchor plane, in millimetres.'
        )

    return state


def build_dialog_inputs(inputs, cam, addin_dir):
    """Build the Setup / Edge / Face tabs and the Preview footer. Returns DialogState."""
    saved = load_settings(addin_dir)

    setups = list_milling_setups(cam)
    if not setups:
        raise UserFacingError(
            'No CAM setups found, please first create a CAM setup and define WCS, '
            'then re-run the add-in'
        )

    tools = prompt_add_example_tools_if_empty(cam, addin_dir)

    # Tab 1: Setup (setup + tool selection and parameters)
    setup_tool_tab = inputs.addTabCommandInput(TAB_SETUP_TOOL, 'Setup')
    setup_inputs = setup_tool_tab.children

    setup_dropdown = setup_inputs.addDropDownCommandInput(
        INPUT_SETUP,
        'Setup',
        adsk.core.DropDownStyles.TextListDropDownStyle,
    )
    setup_dropdown.tooltip = (
        'Milling setup whose WCS defines the depth (+Z) direction for all '
        'generated operations.'
    )
    for setup in setups:
        setup_dropdown.listItems.add(setup.name, False, '')
    select_dropdown(setup_dropdown, saved.get('setup_name'))

    controller = ToolParamsController()
    tool_names = {desc for desc, _tool in tools}
    side_default = saved.get('side_tool_description', saved.get('tool_description'))
    if not side_default or side_default not in tool_names:
        if SAMPLE_SIDE_DESCRIPTION in tool_names:
            side_default = SAMPLE_SIDE_DESCRIPTION
    flat_default = saved.get('flat_tool_description', saved.get('tool_description'))
    if not flat_default or flat_default not in tool_names:
        if SAMPLE_FLAT_DESCRIPTION in tool_names:
            flat_default = SAMPLE_FLAT_DESCRIPTION
    drill_default = saved.get(
        'side_drill_tool_description', saved.get('drill_tool_description')
    )
    if not drill_default or drill_default not in tool_names:
        if SAMPLE_DRILL_DESCRIPTION in tool_names:
            drill_default = SAMPLE_DRILL_DESCRIPTION

    controller.build_section(
        setup_inputs,
        SECTION_SIDE,
        'Edge tool',
        'Edge tool parameters',
        tools,
        side_default,
        tooltip=(
            'Document-library tool used for Edge Trace operations. '
            'The parameters below belong to this tool.'
        ),
    )
    controller.build_section(
        setup_inputs,
        SECTION_FLAT,
        'Face tool',
        'Face tool parameters',
        tools,
        flat_default,
        tooltip=(
            'Document-library tool used for Face (top-face cavity) Trace operations. '
            'The parameters below belong to this tool.'
        ),
    )
    controller.build_section(
        setup_inputs,
        SECTION_DRILL,
        'Drill tool',
        'Drill tool parameters',
        tools,
        drill_default,
        tooltip=(
            'Document-library tool used for optional Edge key-hole Drill operations. '
            'The parameters below belong to this tool.'
        ),
    )

    add_samples = setup_inputs.addBoolValueInput(
        INPUT_ADD_EXAMPLE_TOOLS,
        'Add sample tools',
        False,
        '',
        False,
    )
    add_samples.tooltip = (
        'Add the bundled Lamello sample tools (side cutter, vertical cutter, '
        'and drill) to this document\'s tool library. Tools that already exist '
        'by name are skipped.'
    )

    # Tabs 2 and 3: milling tabs (user-facing Edge / Face; ids remain side/flat)
    side_tab = inputs.addTabCommandInput(TAB_SIDE, 'Edge')
    flat_tab = inputs.addTabCommandInput(TAB_FLAT, 'Face')

    side_state = _build_mode_inputs(
        side_tab.children,
        MODE_SIDE,
        _load_set_defaults(saved, MODE_SIDE),
    )
    flat_state = _build_mode_inputs(
        flat_tab.children,
        MODE_FLAT,
        _load_set_defaults(saved, MODE_FLAT),
    )

    # Global footer: Preview toggle below the tabs.
    try:
        inputs.addSeparatorCommandInput('previewSeparator')
    except Exception:
        pass
    preview_checkbox = inputs.addBoolValueInput(
        INPUT_PREVIEW,
        'Preview',
        True,
        '',
        bool(saved.get('preview_enabled', True)),
    )
    preview_checkbox.tooltip = (
        'Show live preview sketches of the toolpaths while this dialog is open.'
    )

    update_drill_input_visibility(inputs)

    dialog_state = DialogState(side_state, flat_state)
    dialog_state.tool_controller = controller
    dialog_state.addin_dir = addin_dir
    controller.refresh_all(inputs, cam)
    activate_tab_inputs(inputs, dialog_state)
    return dialog_state


def seed_anchor_selection(inputs, dialog_state):
    dialog_state.sync_active_mode_from_inputs(inputs)
    ids = dialog_state.active_state().ids
    detail = adsk.core.SelectionCommandInput.cast(inputs.itemById(ids.ANCHOR_POINTS))
    if detail and detail.selectionCount > 0:
        return

    ui = adsk.core.Application.get().userInterface
    entities = []
    for index in range(ui.activeSelections.count):
        entity = ui.activeSelections.item(index).entity
        if _is_anchor_entity(entity):
            entities.append(entity)

    dialog_state.active_state().seed_first_set_anchors(inputs, entities)


def read_preview_values(inputs, dialog_state):
    dialog_state.sync_active_mode_from_inputs(inputs)
    setup_name = _read_setup_name(inputs)
    mode = dialog_state.active_mode
    state = dialog_state.active_state()
    sets = state.preview_sets(inputs, sync_from_ui=_milling_tab_visible(inputs, mode))
    if not sets:
        return None
    values = {
        'mode': mode,
        'placement_sets': sets,
        'setup_name': setup_name,
    }
    if mode == MODE_SIDE:
        values['side_half_flute_mm'] = resolve_side_half_flute_mm(
            inputs,
            dialog_state,
        )

    # Selected CAM tools for tool-body cut preview (diameter / flute length).
    cam = adsk.cam.CAM.cast(adsk.core.Application.get().activeProduct)
    controller = dialog_state.tool_controller if dialog_state else None
    if cam and controller:
        side_desc = controller.selected_description(inputs, SECTION_SIDE)
        flat_desc = controller.selected_description(inputs, SECTION_FLAT)
        drill_desc = controller.selected_description(inputs, SECTION_DRILL)
        values['side_tool'] = (
            find_tool_by_description(cam, side_desc) if side_desc else None
        )
        values['flat_tool'] = (
            find_tool_by_description(cam, flat_desc) if flat_desc else None
        )
        values['drill_tool'] = (
            find_tool_by_description(cam, drill_desc) if drill_desc else None
        )
    else:
        values['side_tool'] = None
        values['flat_tool'] = None
        values['drill_tool'] = None
    return values


def read_dialog_values(inputs, dialog_state):
    dialog_state.sync_active_mode_from_inputs(inputs)
    setup_name = _read_setup_name(inputs)
    if not setup_name:
        raise RuntimeError('Select a Setup on the Setup tab.')

    mode = dialog_state.active_mode
    active_state = dialog_state.active_state()
    sets = active_state.required_generation_sets(
        inputs,
        sync_from_ui=_milling_tab_visible(inputs, mode),
    )

    controller = dialog_state.tool_controller
    label = mode_display_label(mode)
    section = SECTION_SIDE if mode == MODE_SIDE else SECTION_FLAT
    tool_description = controller.selected_description(inputs, section)
    if not tool_description:
        raise RuntimeError(f'Select a {label} tool on the Setup tab.')

    drill_tool_description = controller.selected_description(inputs, SECTION_DRILL)
    if mode == MODE_SIDE and not drill_tool_description:
        if any(set_data.get('drill_holes') for set_data in sets):
            raise RuntimeError('Select a Drill tool on the Setup tab.')

    values = {
        'mode': mode,
        'sets': sets,
        'setup_name': setup_name,
        'tool_description': tool_description,
        'drill_tool_description': drill_tool_description,
    }
    if mode == MODE_SIDE:
        values['side_half_flute_mm'] = resolve_side_half_flute_mm(
            inputs,
            dialog_state,
        )
    return values


def _auto_update_op_prefix(inputs, state):
    """Follow the connector type with the default op prefix unless customized.

    If the prefix field currently holds any automatic default for this mode
    (P14 or P10 variant) or is blank, rewrite it to the default for the newly
    selected connector type. User-typed prefixes are left untouched.
    """
    connector_dropdown = adsk.core.DropDownCommandInput.cast(
        inputs.itemById(state.ids.CONNECTOR_TYPE)
    )
    prefix_input = adsk.core.StringValueCommandInput.cast(
        inputs.itemById(state.ids.OP_PREFIX)
    )
    if not connector_dropdown or not prefix_input:
        return

    new_connector = read_dropdown(connector_dropdown, DEFAULT_CONNECTOR_TYPE)
    current = (prefix_input.value or '').strip()
    known_defaults = automatic_op_prefixes(state.mode)
    if not current or current in known_defaults:
        prefix_input.value = _default_op_prefix_for_mode(state.mode, new_connector)


def handle_input_changed(changed_input, inputs, dialog_state, command):
    if dialog_state.syncing:
        return False

    input_id = changed_input.id
    preview_requested = False
    controller = dialog_state.tool_controller

    if input_id in (TAB_SETUP_TOOL, TAB_SIDE, TAB_FLAT):
        previous_tab = dialog_state.visible_tab
        if previous_tab != input_id:
            outgoing = dialog_state.state_for_tab(previous_tab)
            if outgoing:
                outgoing.save_detail_from_inputs(inputs)
                outgoing.clear_selection_ui(inputs)
            dialog_state.visible_tab = input_id
            if dialog_state.set_active_mode_from_tab(input_id):
                activate_tab_inputs(inputs, dialog_state)
            preview_requested = True
    elif controller and controller.owns_input(input_id):
        cam = adsk.cam.CAM.cast(adsk.core.Application.get().activeProduct)
        if cam:
            controller.handle_input_changed(changed_input, inputs, cam)
        if input_id in (
            controller.dropdown_id(SECTION_SIDE),
            controller.dropdown_id(SECTION_FLAT),
            controller.dropdown_id(SECTION_DRILL),
        ):
            # Tool diameter/flute drives cut-preview solids / offset.
            preview_requested = True
    elif input_id == INPUT_ADD_EXAMPLE_TOOLS:
        bool_input = adsk.core.BoolValueCommandInput.cast(changed_input)
        if bool_input and bool_input.value:
            bool_input.value = False
            cam = adsk.cam.CAM.cast(adsk.core.Application.get().activeProduct)
            ui = adsk.core.Application.get().userInterface
            try:
                added, skipped = add_example_tools(cam, dialog_state.addin_dir)
                tools = list_document_tools(cam)
                if controller:
                    controller.refresh_tool_lists(
                        inputs, tools, SAMPLE_PREFERRED_BY_SECTION
                    )
                    controller.refresh_all(inputs, cam)
                ui.messageBox(
                    format_add_result_message(added, skipped),
                    'Lamello P-System',
                )
                preview_requested = True
            except UserFacingError as exc:
                ui.messageBox(str(exc), 'Lamello P-System')
    elif input_id == INPUT_SETUP:
        # Setup WCS drives the preview depth axis.
        preview_requested = True
    elif input_id == INPUT_PREVIEW:
        preview_requested = True
    else:
        dialog_state.sync_active_mode_from_inputs(inputs)

        if input_id == dialog_state.side_state.ids.SET_ADD:
            if changed_input.value:
                dialog_state.side_state.add_set(inputs)
                changed_input.value = False
                update_drill_input_visibility(inputs)
                preview_requested = True
        elif input_id == dialog_state.side_state.ids.SET_DELETE:
            if changed_input.value:
                dialog_state.side_state.delete_set(inputs)
                changed_input.value = False
                update_drill_input_visibility(inputs)
                preview_requested = True
        elif input_id == dialog_state.flat_state.ids.SET_ADD:
            if changed_input.value:
                dialog_state.flat_state.add_set(inputs)
                changed_input.value = False
                preview_requested = True
        elif input_id == dialog_state.flat_state.ids.SET_DELETE:
            if changed_input.value:
                dialog_state.flat_state.delete_set(inputs)
                changed_input.value = False
                preview_requested = True
        elif dialog_state.side_state.is_row_input(input_id):
            row_index = dialog_state.side_state.row_index_from_input(inputs, changed_input)
            if row_index >= 0:
                dialog_state.active_mode = MODE_SIDE
                dialog_state.side_state.select_row(inputs, row_index)
                update_drill_input_visibility(inputs)
                preview_requested = True
        elif dialog_state.flat_state.is_row_input(input_id):
            row_index = dialog_state.flat_state.row_index_from_input(inputs, changed_input)
            if row_index >= 0:
                dialog_state.active_mode = MODE_FLAT
                dialog_state.flat_state.select_row(inputs, row_index)
                preview_requested = True
        else:
            state = dialog_state.state_for_input(input_id)
            if state.owns_input(input_id):
                if input_id in (state.ids.ANCHOR_POINTS, state.ids.REFERENCE_AXIS):
                    state.ensure_set_for_editing(inputs)
                if input_id == state.ids.CONNECTOR_TYPE:
                    _auto_update_op_prefix(inputs, state)
                state.save_detail_from_inputs(inputs)
                state.update_row_summary(inputs)
                dialog_state.active_mode = state.mode
                if input_id == state.ids.DRILL_HOLES:
                    update_drill_input_visibility(inputs)
                preview_requested = True

    if preview_requested and command:
        try:
            command.doExecutePreview()
        except Exception:
            pass

    return preview_requested
