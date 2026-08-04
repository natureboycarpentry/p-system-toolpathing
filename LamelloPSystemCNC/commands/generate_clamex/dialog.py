"""
Command dialog inputs for the Lamello P-System CNC Toolpath Addin.

Builds the Setup / Side / Flat tabs plus the global
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
from lib.placement_sets import (
    MODE_FLAT,
    MODE_SIDE,
    TAB_FLAT,
    TAB_SETUP_TOOL,
    TAB_SIDE,
    DialogState,
    INPUT_PREVIEW,
    INPUT_SETUP,
    PlacementSetState,
    _default_op_prefix_for_mode,
    _is_anchor_entity,
)
from lib.settings import load_settings, settings_prefix
from lib.tool_params import (
    SECTION_DRILL,
    SECTION_FLAT,
    SECTION_SIDE,
    ToolParamsController,
)
from lib.toolpath_def import (
    DEFAULT_CONNECTOR_TYPE,
    DEFAULT_DRILL_CLEARANCE_MM,
    TOOL_HALF_THICKNESS_OFFSET_MM,
    half_tool_thickness_offset_mm,
)
from lib.ui_helpers import read_dropdown, select_dropdown

_REFERENCE_AXIS_FILTERS = (
    'LinearEdges',
    'SketchLines',
    'ConstructionLines',
)

_ANCHOR_POINT_FILTERS = (
    'JointOrigins',
    'SketchPoints',
    'Vertices',
    'ConstructionPoints',
)

def _format_half_thickness_display(half_offset_mm):
    """Format the magnitude of the half-thickness offset for the grey readout."""
    magnitude = abs(float(half_offset_mm))
    text = f'{magnitude:.3f}'.rstrip('0').rstrip('.')
    return f'{text} mm'


def resolve_side_half_thickness_offset_mm(inputs, dialog_state):
    """Half side-cutter flute length as a signed depth offset (mm)."""
    controller = dialog_state.tool_controller if dialog_state else None
    if not controller:
        return TOOL_HALF_THICKNESS_OFFSET_MM
    description = controller.selected_description(inputs, SECTION_SIDE)
    cam = adsk.cam.CAM.cast(adsk.core.Application.get().activeProduct)
    tool = find_tool_by_description(cam, description) if cam and description else None
    return half_tool_thickness_offset_mm(tool_flute_length_mm(tool))


def update_tool_thickness_offset_display(inputs, dialog_state):
    """Refresh the grey half-thickness readout next to the Side offset checkbox."""
    ids = dialog_state.side_state.ids
    display = adsk.core.StringValueCommandInput.cast(
        inputs.itemById(ids.TOOL_THICKNESS_OFFSET_VALUE)
    )
    if not display:
        return
    offset_mm = resolve_side_half_thickness_offset_mm(inputs, dialog_state)
    display.value = _format_half_thickness_display(offset_mm)


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
    return {
        'flip_feed': saved.get(
            f'{prefix}flip_feed',
            saved.get('flip_feed', not saved.get('positive_direction', True)),
        ),
        'flip_z': saved.get(
            f'{prefix}flip_z',
            saved.get('flip_z', not saved.get('depth_positive_direction', True)),
        ),
        'tool_thickness_offset': saved.get(
            f'{prefix}tool_thickness_offset',
            saved.get(
                'tool_thickness_offset',
                saved.get('tool_half_thickness_offset', True),
            ),
        ),
        'connector_type': saved.get(
            f'{prefix}connector_type',
            saved.get('connector_type', DEFAULT_CONNECTOR_TYPE),
        ),
        'op_prefix': saved.get(f'{prefix}op_prefix', saved.get('op_prefix')),
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
    mode_label = 'Side' if mode == MODE_SIDE else 'Flat'

    table = parent_inputs.addTableCommandInput(ids.SETS_TABLE, 'Placement sets', 2, '1:2')
    table.maximumVisibleRows = 6
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

    axis_sel = parent_inputs.addSelectionInput(
        ids.REFERENCE_AXIS,
        'Feed axis',
        'Select a linear edge, sketch line, or construction line/axis for slot direction',
    )
    axis_sel.tooltip = (
        'Linear edge, sketch line, or construction line that sets the machining '
        'direction along the connector. Use Flip feed to reverse it.'
    )
    for filter_name in _REFERENCE_AXIS_FILTERS:
        axis_sel.addSelectionFilter(filter_name)
    axis_sel.setSelectionLimits(0, 0)

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
        tool_offset = parent_inputs.addBoolValueInput(
            ids.TOOL_THICKNESS_OFFSET,
            'Tool thickness offset',
            True,
            '',
            set_defaults.get('tool_thickness_offset', True),
        )
        tool_offset.tooltip = (
            'Offset the path by half the side cutter flute length so the T-slot '
            'walls are cut at the correct depth.'
        )
        # Read-only (grey) half-flute readout from the Setup tab Side tool.
        offset_value = parent_inputs.addStringValueInput(
            ids.TOOL_THICKNESS_OFFSET_VALUE,
            '',
            _format_half_thickness_display(TOOL_HALF_THICKNESS_OFFSET_MM),
        )
        offset_value.isReadOnly = True
        offset_value.tooltip = (
            'Half the flute length of the Side tool selected on the Setup tab '
            '(applied as the depth offset when the checkbox above is on).'
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
    """Build the Setup / Side / Flat tabs and the Preview footer. Returns DialogState."""
    saved = load_settings(addin_dir)

    setups = list_milling_setups(cam)
    if not setups:
        raise UserFacingError(
            'No CAM setups found, please first create a CAM setup and define WCS, '
            'then re-run the add-in'
        )

    tools = list_document_tools(cam)
    if not tools:
        raise UserFacingError(
            'No tools found in the document tool library, please add the required '
            'milling tools to a setup, then re-run the add-in'
        )

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
    controller.build_section(
        setup_inputs,
        SECTION_SIDE,
        'Side tool',
        'Side tool parameters',
        tools,
        saved.get('side_tool_description', saved.get('tool_description')),
        tooltip=(
            'Document-library tool used for Side Trace operations. '
            'The parameters below belong to this tool.'
        ),
    )
    controller.build_section(
        setup_inputs,
        SECTION_FLAT,
        'Flat tool',
        'Flat tool parameters',
        tools,
        saved.get('flat_tool_description', saved.get('tool_description')),
        tooltip=(
            'Document-library tool used for Flat (top-face cavity) Trace operations. '
            'The parameters below belong to this tool.'
        ),
    )
    controller.build_section(
        setup_inputs,
        SECTION_DRILL,
        'Drill tool',
        'Drill tool parameters',
        tools,
        saved.get('side_drill_tool_description', saved.get('drill_tool_description')),
        tooltip=(
            'Document-library tool used for optional Side key-hole Drill operations. '
            'The parameters below belong to this tool.'
        ),
    )

    # Tabs 2 and 3: milling tabs
    side_tab = inputs.addTabCommandInput(TAB_SIDE, 'Side')
    flat_tab = inputs.addTabCommandInput(TAB_FLAT, 'Flat')

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
    controller.refresh_all(inputs, cam)
    update_tool_thickness_offset_display(inputs, dialog_state)
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
        values['tool_half_thickness_offset_mm'] = resolve_side_half_thickness_offset_mm(
            inputs,
            dialog_state,
        )
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
    label = 'Side' if mode == MODE_SIDE else 'Flat'
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
        values['tool_half_thickness_offset_mm'] = resolve_side_half_thickness_offset_mm(
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
    known_defaults = {
        _default_op_prefix_for_mode(state.mode, connector)
        for connector in ('P14', 'P10')
    }
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
        if input_id == controller.dropdown_id(SECTION_SIDE):
            update_tool_thickness_offset_display(inputs, dialog_state)
            preview_requested = True
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
