"""
Command dialog inputs for Generate Clamex Toolpaths.

Builds Side/Flat tabs, reads preview/generation values, and routes inputChanged
events to placement-set state.
"""

import adsk.core
import adsk.cam
import adsk.fusion

from lib.cam_ops import list_document_tools, list_milling_setups
from lib.placement_sets import (
    MODE_FLAT,
    MODE_SIDE,
    TAB_FLAT,
    TAB_SIDE,
    DialogState,
    INPUT_SETUP,
    PlacementSetState,
    _is_anchor_entity,
)
from lib.settings import load_settings, settings_prefix
from lib.toolpath_def import (
    DEFAULT_CONNECTOR_TYPE,
    DEFAULT_DRILL_CLEARANCE_MM,
    default_flat_op_prefix,
    default_op_prefix,
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


def _read_setup_name(inputs):
    setup_dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById(INPUT_SETUP))
    return read_dropdown(setup_dropdown)


def _read_tool_for_mode(inputs, mode):
    ids = PlacementSetState(mode).ids
    tool_dropdown = adsk.core.DropDownCommandInput.cast(inputs.itemById(ids.TOOL))
    return read_dropdown(tool_dropdown)


def _load_set_defaults(saved, mode):
    """Map persisted settings to per-set defaults for one tab."""
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
        'drill_tool_description': saved.get(
            f'{prefix}drill_tool_description',
            saved.get('drill_tool_description'),
        ),
        'drill_clearance_mm': saved.get(
            f'{prefix}drill_clearance_mm',
            saved.get('drill_clearance_mm', DEFAULT_DRILL_CLEARANCE_MM),
        ),
        'tool_description': saved.get(
            f'{prefix}tool_description',
            saved.get('tool_description'),
        ),
    }


def update_drill_input_visibility(inputs):
    """Show side-tab drill tool and clearance inputs when drill is enabled."""
    ids = PlacementSetState(MODE_SIDE).ids
    drill_enabled = adsk.core.BoolValueCommandInput.cast(inputs.itemById(ids.DRILL_HOLES))
    drill_tool = adsk.core.DropDownCommandInput.cast(inputs.itemById(ids.DRILL_TOOL))
    drill_clearance = adsk.core.StringValueCommandInput.cast(inputs.itemById(ids.DRILL_CLEARANCE))
    visible = bool(drill_enabled and drill_enabled.value)
    if drill_tool:
        drill_tool.isVisible = visible
    if drill_clearance:
        drill_clearance.isVisible = visible


def activate_tab_inputs(inputs, dialog_state, inactive_state=None):
    """Restore the active tab's detail UI after a tab switch."""
    dialog_state.active_state().load_detail_to_inputs(inputs)
    if dialog_state.active_mode == MODE_SIDE:
        update_drill_input_visibility(inputs)
    if inactive_state:
        inactive_state.clear_selection_ui(inputs)


def _build_mode_inputs(parent_inputs, cam, mode, set_defaults, tools):
    """Build placement-set UI inside a tab. Returns PlacementSetState."""
    state = PlacementSetState(mode, set_defaults)
    ids = state.ids

    table = parent_inputs.addTableCommandInput(ids.SETS_TABLE, 'Placement sets', 2, '1:2')
    table.maximumVisibleRows = 6

    add_button = parent_inputs.addBoolValueInput(ids.SET_ADD, 'Add set', False, '', False)
    table.addToolbarCommandInput(add_button)
    delete_button = parent_inputs.addBoolValueInput(ids.SET_DELETE, 'Delete set', False, '', False)
    table.addToolbarCommandInput(delete_button)

    sel = parent_inputs.addSelectionInput(
        ids.ANCHOR_POINTS,
        'Anchor points',
        'Select one or more Joint Origins, sketch points, vertices, or construction points',
    )
    for filter_name in _ANCHOR_POINT_FILTERS:
        sel.addSelectionFilter(filter_name)
    sel.setSelectionLimits(0, 0)

    axis_sel = parent_inputs.addSelectionInput(
        ids.REFERENCE_AXIS,
        'Feed axis',
        'Select a linear edge, sketch line, or construction line/axis for slot direction',
    )
    for filter_name in _REFERENCE_AXIS_FILTERS:
        axis_sel.addSelectionFilter(filter_name)
    axis_sel.setSelectionLimits(0, 0)

    connector_dropdown = parent_inputs.addDropDownCommandInput(
        ids.CONNECTOR_TYPE,
        'Connector type',
        adsk.core.DropDownStyles.TextListDropDownStyle,
    )
    connector_dropdown.listItems.add('P14', False, '')
    connector_dropdown.listItems.add('P10', False, '')
    select_dropdown(
        connector_dropdown,
        set_defaults.get('connector_type', DEFAULT_CONNECTOR_TYPE),
    )

    parent_inputs.addBoolValueInput(
        ids.FLIP_FEED,
        'Flip feed',
        True,
        '',
        set_defaults.get('flip_feed', False),
    )

    parent_inputs.addBoolValueInput(
        ids.FLIP_Z,
        'Flip Z',
        True,
        '',
        set_defaults.get('flip_z', False),
    )

    if mode == MODE_SIDE:
        parent_inputs.addBoolValueInput(
            ids.TOOL_THICKNESS_OFFSET,
            'Tool thickness offset',
            True,
            '',
            set_defaults.get('tool_thickness_offset', True),
        )

    default_prefix = (
        default_op_prefix(set_defaults.get('connector_type'))
        if mode == MODE_SIDE
        else default_flat_op_prefix(set_defaults.get('connector_type'))
    )
    parent_inputs.addStringValueInput(
        ids.OP_PREFIX,
        'Operation name prefix',
        set_defaults.get('op_prefix') or default_prefix,
    )

    if mode == MODE_SIDE:
        parent_inputs.addBoolValueInput(
            ids.DRILL_HOLES,
            'Drill key holes',
            True,
            '',
            set_defaults.get('drill_holes', False),
        )

        drill_tool_dropdown = parent_inputs.addDropDownCommandInput(
            ids.DRILL_TOOL,
            'Drill tool',
            adsk.core.DropDownStyles.TextListDropDownStyle,
        )
        for desc, _tool in tools:
            drill_tool_dropdown.listItems.add(desc, False, '')
        select_dropdown(drill_tool_dropdown, set_defaults.get('drill_tool_description'))

        parent_inputs.addStringValueInput(
            ids.DRILL_CLEARANCE,
            'Clearance above anchor (mm)',
            str(set_defaults.get('drill_clearance_mm', DEFAULT_DRILL_CLEARANCE_MM)),
        )

    tool_dropdown = parent_inputs.addDropDownCommandInput(
        ids.TOOL,
        'Tool',
        adsk.core.DropDownStyles.TextListDropDownStyle,
    )
    for desc, _tool in tools:
        tool_dropdown.listItems.add(desc, False, '')
    select_dropdown(tool_dropdown, set_defaults.get('tool_description'))

    return state


def build_dialog_inputs(inputs, cam, addin_dir):
    """Add Side/Flat tabs, set tables, and global CAM inputs. Returns DialogState."""
    saved = load_settings(addin_dir)
    tools = list_document_tools(cam)
    if not tools:
        raise RuntimeError('No tools in the document library. Add a tool to the setup first.')

    side_tab = inputs.addTabCommandInput(TAB_SIDE, 'Side', '')
    flat_tab = inputs.addTabCommandInput(TAB_FLAT, 'Flat', '')

    side_state = _build_mode_inputs(
        side_tab.children,
        cam,
        MODE_SIDE,
        _load_set_defaults(saved, MODE_SIDE),
        tools,
    )
    flat_state = _build_mode_inputs(
        flat_tab.children,
        cam,
        MODE_FLAT,
        _load_set_defaults(saved, MODE_FLAT),
        tools,
    )

    setups = list_milling_setups(cam)
    if not setups:
        raise RuntimeError('No CAM setups found. Create a milling setup before running this command.')

    setup_dropdown = inputs.addDropDownCommandInput(
        INPUT_SETUP,
        'Setup',
        adsk.core.DropDownStyles.TextListDropDownStyle,
    )
    for setup in setups:
        setup_dropdown.listItems.add(setup.name, False, '')
    select_dropdown(setup_dropdown, saved.get('setup_name'))

    update_drill_input_visibility(inputs)

    dialog_state = DialogState(side_state, flat_state)
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
    sets = state.preview_sets(inputs)
    if not sets:
        return None
    return {
        'mode': mode,
        'placement_sets': sets,
        'setup_name': setup_name,
    }


def read_dialog_values(inputs, dialog_state):
    dialog_state.sync_active_mode_from_inputs(inputs)
    setup_name = _read_setup_name(inputs)
    if not setup_name:
        raise RuntimeError('Select a Setup.')

    active_state = dialog_state.active_state()
    sets = active_state.required_generation_sets(inputs)
    tool_description = _read_tool_for_mode(inputs, dialog_state.active_mode)
    if not tool_description:
        label = 'Side' if dialog_state.active_mode == MODE_SIDE else 'Flat'
        raise RuntimeError(f'Select a {label} tool.')

    return {
        'mode': dialog_state.active_mode,
        'sets': sets,
        'setup_name': setup_name,
        'tool_description': tool_description,
    }


def handle_input_changed(changed_input, inputs, dialog_state, command):
    if dialog_state.syncing:
        return False

    input_id = changed_input.id
    preview_requested = False

    if input_id in (TAB_SIDE, TAB_FLAT):
        outgoing = dialog_state.active_state()
        outgoing.save_detail_from_inputs(inputs)
        dialog_state.sync_active_mode_from_inputs(inputs)
        dialog_state.set_active_mode_from_tab(input_id)
        activate_tab_inputs(inputs, dialog_state, inactive_state=outgoing)
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
            if input_id == INPUT_SETUP or state.owns_input(input_id):
                if input_id in (state.ids.ANCHOR_POINTS, state.ids.REFERENCE_AXIS):
                    state.ensure_set_for_editing(inputs)
                state.save_detail_from_inputs(inputs)
                state.update_row_summary(inputs)
                if state.owns_input(input_id):
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
