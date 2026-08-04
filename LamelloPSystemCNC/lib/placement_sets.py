"""
In-memory placement set state for the multi-set command dialog.

Each tab (Side/Flat) owns a PlacementSetState with a table of sets and detail
inputs synced to in-memory dicts for preview and generation.
"""

import adsk.core
import adsk.fusion

from lib.toolpath_def import (
    DEFAULT_CONNECTOR_TYPE,
    DEFAULT_CUTTER_Z_REFERENCE,
    DEFAULT_DRILL_CLEARANCE_MM,
    default_flat_op_prefix,
    default_op_prefix,
    migrate_cutter_z_reference,
)
from lib.ui_helpers import read_dropdown, select_dropdown

MODE_SIDE = 'side'
MODE_FLAT = 'flat'

INPUT_SETUP = 'setup'
INPUT_PREVIEW = 'previewEnabled'

TAB_SETUP_TOOL = 'setupToolTab'
TAB_SIDE = 'sideTab'
TAB_FLAT = 'flatTab'


class ModeInputIds:
    """Prefixed command input IDs for one milling tab (side or flat)."""

    def __init__(self, mode):
        prefix = f'{mode}_'
        self.SETS_TABLE = f'{prefix}placementSetsTable'
        self.SET_ADD = f'{prefix}setAdd'
        self.SET_DELETE = f'{prefix}setDelete'
        self.ANCHOR_POINTS = f'{prefix}anchorPoints'
        self.REFERENCE_AXIS = f'{prefix}referenceAxis'
        self.CONNECTOR_TYPE = f'{prefix}connectorType'
        self.FLIP_FEED = f'{prefix}flipFeed'
        self.FLIP_Z = f'{prefix}flipZ'
        self.CUTTER_Z_REFERENCE = f'{prefix}cutterZReference'
        self.OP_PREFIX = f'{prefix}opPrefix'
        self.DRILL_HOLES = f'{prefix}drillHoles'
        self.DRILL_CLEARANCE = f'{prefix}drillClearance'
        self.ROW_LABEL_PREFIX = f'{prefix}setLabel_'
        self.ROW_SUMMARY_PREFIX = f'{prefix}setSummary_'


def _default_op_prefix_for_mode(mode, connector_type):
    if mode == MODE_FLAT:
        return default_flat_op_prefix(connector_type)
    return default_op_prefix(connector_type)


def empty_set(mode, defaults=None):
    """Return a new empty placement set dict."""
    defaults = defaults or {}
    connector_type = defaults.get('connector_type', DEFAULT_CONNECTOR_TYPE)
    data = {
        'anchor_points': [],
        'reference_axis': None,
        'flip_feed': defaults.get('flip_feed', False),
        'flip_z': defaults.get('flip_z', False),
        'connector_type': connector_type,
        'op_prefix': defaults.get('op_prefix') or _default_op_prefix_for_mode(mode, connector_type),
    }
    if mode == MODE_SIDE:
        data.update(
            {
                'cutter_z_reference': migrate_cutter_z_reference(
                    defaults.get('cutter_z_reference', DEFAULT_CUTTER_Z_REFERENCE)
                ),
                'drill_holes': defaults.get('drill_holes', False),
                'drill_clearance_mm': defaults.get('drill_clearance_mm', DEFAULT_DRILL_CLEARANCE_MM),
            }
        )
    return data


def _is_anchor_entity(entity):
    if not entity:
        return False
    if 'JointOrigin' in entity.objectType:
        return True
    if adsk.fusion.SketchPoint.cast(entity):
        return True
    if adsk.fusion.BRepVertex.cast(entity):
        return True
    if adsk.fusion.ConstructionPoint.cast(entity):
        return True
    return False


def _clear_selection(sel):
    if not sel:
        return
    try:
        sel.clearSelection()
    except Exception:
        try:
            sel.isVisible = False
            sel.isVisible = True
        except Exception:
            pass


def _repopulate_selection(sel, entities):
    _clear_selection(sel)
    if not sel:
        return
    for entity in entities or []:
        try:
            sel.addSelection(entity)
        except Exception:
            pass


def _set_single_selection(sel, entity):
    _clear_selection(sel)
    if sel and entity:
        try:
            sel.addSelection(entity)
        except Exception:
            pass


def _clamp_single_selection(sel):
    """Keep only the last entity when Fusion ignores max=1 selection limits."""
    if not sel or sel.selectionCount <= 1:
        return
    last = sel.selection(sel.selectionCount - 1).entity
    _set_single_selection(sel, last)


def _read_anchors(sel):
    from lib.transform import placement_anchor_point

    anchors = []
    if not sel:
        return anchors
    for index in range(sel.selectionCount):
        entity = sel.selection(index).entity
        if not _is_anchor_entity(entity):
            continue
        try:
            placement_anchor_point(entity)
            anchors.append(entity)
        except Exception:
            continue
    return anchors


def _summary_text(set_data, mode):
    anchor_count = len(set_data.get('anchor_points') or [])
    has_feed = set_data.get('reference_axis') is not None

    if anchor_count == 0:
        anchor_part = 'No anchors'
    elif anchor_count == 1:
        anchor_part = '1 anchor'
    else:
        anchor_part = f'{anchor_count} anchors'

    axis_part = 'feed set' if has_feed else 'feed pending'
    connector = set_data.get('connector_type', DEFAULT_CONNECTOR_TYPE)
    summary = f'{anchor_part}, {connector}, {axis_part}'
    if mode == MODE_SIDE and set_data.get('drill_holes'):
        summary += ', drill'
    return summary


def _set_is_valid(set_data, mode):
    from lib.transform import reference_axis_direction

    if not set_data.get('anchor_points'):
        return False
    if not set_data.get('reference_axis'):
        return False
    try:
        reference_axis_direction(set_data['reference_axis'])
    except Exception:
        return False
    return True


def _read_clearance_mm(clearance_input, default):
    if not clearance_input:
        return default
    try:
        value = float(str(clearance_input.value).strip())
        if value <= 0:
            return default
        return value
    except (TypeError, ValueError):
        return default


class PlacementSetState:
    """Manages placement sets for one tab (side or flat)."""

    def __init__(self, mode, defaults=None):
        self.mode = mode
        self.ids = ModeInputIds(mode)
        self._defaults = defaults or {}
        self.sets = []
        self.active_index = -1
        self._syncing = False
        self._next_row_id = 1

    @property
    def syncing(self):
        return self._syncing

    def _table(self, inputs):
        return adsk.core.TableCommandInput.cast(inputs.itemById(self.ids.SETS_TABLE))

    def _detail_inputs(self, inputs):
        detail = {
            'anchors': adsk.core.SelectionCommandInput.cast(inputs.itemById(self.ids.ANCHOR_POINTS)),
            'feed': adsk.core.SelectionCommandInput.cast(inputs.itemById(self.ids.REFERENCE_AXIS)),
            'connector_type': adsk.core.DropDownCommandInput.cast(
                inputs.itemById(self.ids.CONNECTOR_TYPE)
            ),
            'flip_feed': adsk.core.BoolValueCommandInput.cast(inputs.itemById(self.ids.FLIP_FEED)),
            'flip_z': adsk.core.BoolValueCommandInput.cast(inputs.itemById(self.ids.FLIP_Z)),
            'op_prefix': adsk.core.StringValueCommandInput.cast(inputs.itemById(self.ids.OP_PREFIX)),
        }
        if self.mode == MODE_SIDE:
            detail.update(
                {
                    'cutter_z_reference': adsk.core.DropDownCommandInput.cast(
                        inputs.itemById(self.ids.CUTTER_Z_REFERENCE)
                    ),
                    'drill_holes': adsk.core.BoolValueCommandInput.cast(
                        inputs.itemById(self.ids.DRILL_HOLES)
                    ),
                    'drill_clearance': adsk.core.StringValueCommandInput.cast(
                        inputs.itemById(self.ids.DRILL_CLEARANCE)
                    ),
                }
            )
        return detail

    def save_detail_from_inputs(self, inputs):
        if self._syncing or self.active_index < 0 or self.active_index >= len(self.sets):
            return
        detail = self._detail_inputs(inputs)
        set_data = self.sets[self.active_index]

        set_data['anchor_points'] = _read_anchors(detail['anchors'])

        _clamp_single_selection(detail['feed'])
        if detail['feed'] and detail['feed'].selectionCount == 1:
            set_data['reference_axis'] = detail['feed'].selection(0).entity
        else:
            set_data['reference_axis'] = None

        if detail['connector_type']:
            set_data['connector_type'] = read_dropdown(
                detail['connector_type'],
                DEFAULT_CONNECTOR_TYPE,
            )

        if detail['flip_feed']:
            set_data['flip_feed'] = detail['flip_feed'].value

        if detail['flip_z']:
            set_data['flip_z'] = detail['flip_z'].value

        if detail['op_prefix']:
            prefix = detail['op_prefix'].value.strip()
            set_data['op_prefix'] = prefix or _default_op_prefix_for_mode(
                self.mode,
                set_data.get('connector_type'),
            )

        if self.mode == MODE_SIDE:
            if detail['cutter_z_reference']:
                set_data['cutter_z_reference'] = migrate_cutter_z_reference(
                    read_dropdown(
                        detail['cutter_z_reference'],
                        DEFAULT_CUTTER_Z_REFERENCE,
                    )
                )
            if detail['drill_holes']:
                set_data['drill_holes'] = detail['drill_holes'].value
            if detail['drill_clearance']:
                set_data['drill_clearance_mm'] = _read_clearance_mm(
                    detail['drill_clearance'],
                    set_data.get('drill_clearance_mm', DEFAULT_DRILL_CLEARANCE_MM),
                )

    def load_detail_to_inputs(self, inputs):
        if self.active_index < 0 or self.active_index >= len(self.sets):
            return

        set_data = self.sets[self.active_index]
        detail = self._detail_inputs(inputs)

        self._syncing = True
        try:
            _repopulate_selection(detail['anchors'], set_data.get('anchor_points'))
            _set_single_selection(detail['feed'], set_data.get('reference_axis'))

            if detail['connector_type']:
                select_dropdown(
                    detail['connector_type'],
                    set_data.get('connector_type', DEFAULT_CONNECTOR_TYPE),
                )

            if detail['flip_feed']:
                detail['flip_feed'].value = set_data.get('flip_feed', False)
            if detail['flip_z']:
                detail['flip_z'].value = set_data.get('flip_z', False)
            if detail['op_prefix']:
                detail['op_prefix'].value = set_data.get(
                    'op_prefix',
                    _default_op_prefix_for_mode(self.mode, set_data.get('connector_type')),
                )

            if self.mode == MODE_SIDE:
                if detail['cutter_z_reference']:
                    select_dropdown(
                        detail['cutter_z_reference'],
                        set_data.get('cutter_z_reference', DEFAULT_CUTTER_Z_REFERENCE),
                    )
                if detail['drill_holes']:
                    detail['drill_holes'].value = set_data.get('drill_holes', False)
                if detail['drill_clearance']:
                    detail['drill_clearance'].value = str(
                        set_data.get('drill_clearance_mm', DEFAULT_DRILL_CLEARANCE_MM)
                    )
        finally:
            self._syncing = False

    def update_row_summary(self, inputs, row_index=None):
        table = self._table(inputs)
        if not table:
            return
        row_index = self.active_index if row_index is None else row_index
        if row_index < 0 or row_index >= len(self.sets):
            return
        label_input = table.getInputAtPosition(row_index, 0)
        if label_input:
            label_input.value = f'Set {row_index + 1}'
        summary_input = table.getInputAtPosition(row_index, 1)
        if summary_input:
            summary_input.text = _summary_text(self.sets[row_index], self.mode)

    def update_all_summaries(self, inputs):
        for index in range(len(self.sets)):
            self.update_row_summary(inputs, index)

    def add_table_row(self, table, row_index):
        cmd_inputs = adsk.core.CommandInputs.cast(table.commandInputs)
        row_id = self._next_row_id
        self._next_row_id += 1

        label_input = cmd_inputs.addStringValueInput(
            f'{self.ids.ROW_LABEL_PREFIX}{row_id}',
            '',
            f'Set {row_index + 1}',
        )
        label_input.isReadOnly = True

        summary_input = cmd_inputs.addTextBoxCommandInput(
            f'{self.ids.ROW_SUMMARY_PREFIX}{row_id}',
            '',
            _summary_text(self.sets[row_index], self.mode),
            1,
            True,
        )

        table.addCommandInput(label_input, row_index, 0)
        table.addCommandInput(summary_input, row_index, 1)
        return row_id

    def clear_selection_ui(self, inputs):
        """Clear anchor/feed selectors only; set data remains in memory."""
        detail = self._detail_inputs(inputs)
        self._syncing = True
        try:
            _clear_selection(detail['anchors'])
            _clear_selection(detail['feed'])
        finally:
            self._syncing = False

    def _clear_detail_inputs(self, inputs):
        detail = self._detail_inputs(inputs)
        self._syncing = True
        try:
            _clear_selection(detail['anchors'])
            _clear_selection(detail['feed'])
            if detail['connector_type']:
                select_dropdown(detail['connector_type'], DEFAULT_CONNECTOR_TYPE)
            if detail['flip_feed']:
                detail['flip_feed'].value = self._defaults.get('flip_feed', False)
            if detail['flip_z']:
                detail['flip_z'].value = self._defaults.get('flip_z', False)
            if detail['op_prefix']:
                detail['op_prefix'].value = _default_op_prefix_for_mode(
                    self.mode,
                    self._defaults.get('connector_type', DEFAULT_CONNECTOR_TYPE),
                )
            if self.mode == MODE_SIDE:
                if detail['cutter_z_reference']:
                    select_dropdown(
                        detail['cutter_z_reference'],
                        self._defaults.get('cutter_z_reference', DEFAULT_CUTTER_Z_REFERENCE),
                    )
                if detail['drill_holes']:
                    detail['drill_holes'].value = self._defaults.get('drill_holes', False)
                if detail['drill_clearance']:
                    detail['drill_clearance'].value = str(
                        self._defaults.get('drill_clearance_mm', DEFAULT_DRILL_CLEARANCE_MM)
                    )
        finally:
            self._syncing = False

    def _pending_ui_selections(self, inputs):
        detail = self._detail_inputs(inputs)
        anchors = _read_anchors(detail['anchors'])
        feed = None
        if detail['feed'] and detail['feed'].selectionCount == 1:
            feed = detail['feed'].selection(0).entity
        return anchors, feed

    def ensure_set_for_editing(self, inputs):
        """Create the first set when the user starts selecting anchors or feed."""
        if not self.sets:
            self.add_set(inputs, seed_from_ui=True)

    def _ensure_set_from_ui_if_needed(self, inputs):
        if self.sets:
            return
        anchors, feed = self._pending_ui_selections(inputs)
        if anchors or feed:
            self.add_set(inputs, seed_from_ui=True)

    def add_set(self, inputs, seed_from_ui=False):
        if self.active_index >= 0:
            self.save_detail_from_inputs(inputs)

        is_first_set = not self.sets

        if self.sets and self.active_index >= 0:
            current = self.sets[self.active_index]
            connector_type = current.get('connector_type', DEFAULT_CONNECTOR_TYPE)
            inherit = {
                'flip_feed': current.get('flip_feed', False),
                'flip_z': current.get('flip_z', False),
                'connector_type': connector_type,
                'op_prefix': _default_op_prefix_for_mode(self.mode, connector_type),
            }
            if self.mode == MODE_SIDE:
                inherit.update(
                    {
                        'cutter_z_reference': current.get(
                            'cutter_z_reference',
                            DEFAULT_CUTTER_Z_REFERENCE,
                        ),
                        'drill_holes': current.get('drill_holes', False),
                        'drill_clearance_mm': current.get(
                            'drill_clearance_mm',
                            DEFAULT_DRILL_CLEARANCE_MM,
                        ),
                    }
                )
        else:
            inherit = dict(self._defaults)

        new_set = empty_set(self.mode, inherit)
        if is_first_set and seed_from_ui:
            pending_anchors, pending_feed = self._pending_ui_selections(inputs)
            if pending_anchors:
                new_set['anchor_points'] = pending_anchors
            if pending_feed:
                new_set['reference_axis'] = pending_feed

        self.sets.append(new_set)

        table = self._table(inputs)
        row_index = table.rowCount
        self.add_table_row(table, row_index)
        self.active_index = row_index
        table.selectedRow = row_index
        self.load_detail_to_inputs(inputs)
        self.update_all_summaries(inputs)

    def delete_set(self, inputs):
        if not self.sets:
            return False

        table = self._table(inputs)
        row_index = table.selectedRow
        if row_index < 0:
            row_index = self.active_index
        if row_index < 0 or row_index >= len(self.sets):
            return False

        table.deleteRow(row_index)
        self.sets.pop(row_index)

        if not self.sets:
            self.active_index = -1
            self._clear_detail_inputs(inputs)
            return True

        self.active_index = min(row_index, len(self.sets) - 1)
        table.selectedRow = self.active_index
        self.load_detail_to_inputs(inputs)
        self.update_all_summaries(inputs)
        return True

    def select_row(self, inputs, row_index):
        if row_index < 0 or row_index >= len(self.sets):
            return
        if row_index == self.active_index:
            return

        self.save_detail_from_inputs(inputs)
        self.active_index = row_index
        table = self._table(inputs)
        if table:
            table.selectedRow = row_index
        self.load_detail_to_inputs(inputs)

    def is_row_input(self, input_id):
        return input_id.startswith(self.ids.ROW_LABEL_PREFIX) or input_id.startswith(
            self.ids.ROW_SUMMARY_PREFIX
        )

    def row_index_from_input(self, inputs, changed_input):
        table = self._table(inputs)
        if not table:
            return -1
        _, row, _, _, _ = table.getPosition(changed_input)
        return row

    def is_consistent_from_memory(self):
        for set_data in self.sets:
            if not set_data.get('anchor_points') and not set_data.get('reference_axis'):
                continue
            if not _set_is_valid(set_data, self.mode):
                return False
        return True

    def valid_sets_from_memory(self):
        return [dict(set_data) for set_data in self.sets if _set_is_valid(set_data, self.mode)]

    def required_generation_sets(self, inputs, sync_from_ui=True):
        """Valid sets for the active tab after reading UI; raises if not ready.

        Pass sync_from_ui=False when the tab's selection inputs are not visible
        (another tab is active) so cleared UI does not wipe in-memory sets.
        """
        if sync_from_ui:
            self.save_detail_from_inputs(inputs)
        if not self.is_consistent_from_memory():
            label = 'Side' if self.mode == MODE_SIDE else 'Flat'
            raise RuntimeError(
                f'Each {label} placement set needs at least one anchor point and a feed axis.'
            )
        sets = self.valid_sets_from_memory()
        if not sets:
            label = 'Side' if self.mode == MODE_SIDE else 'Flat'
            raise RuntimeError(f'Configure at least one valid {label} placement set.')
        return sets

    def preview_sets(self, inputs, sync_from_ui=True):
        if sync_from_ui:
            self._ensure_set_from_ui_if_needed(inputs)
            self.save_detail_from_inputs(inputs)
        return [dict(set_data) for set_data in self.sets if set_data.get('anchor_points')]

    def seed_first_set_anchors(self, inputs, entities):
        if not entities:
            return
        if not self.sets:
            self.add_set(inputs, seed_from_ui=False)
        set_data = self.sets[self.active_index]
        existing = list(set_data.get('anchor_points') or [])
        for entity in entities:
            if entity not in existing:
                existing.append(entity)
        set_data['anchor_points'] = existing
        self.load_detail_to_inputs(inputs)
        self.update_all_summaries(inputs)

    def owns_input(self, input_id):
        return input_id.startswith(f'{self.mode}_')


class DialogState:
    """Setup/Side/Flat tab state for the command dialog."""

    def __init__(self, side_state, flat_state):
        self.side_state = side_state
        self.flat_state = flat_state
        self.active_mode = MODE_SIDE
        # The Setup tab is first, so it is visible when the dialog opens.
        self.visible_tab = TAB_SETUP_TOOL
        self.tool_controller = None

    @property
    def syncing(self):
        return self.active_state().syncing

    def active_state(self):
        if self.active_mode == MODE_FLAT:
            return self.flat_state
        return self.side_state

    def state_for_input(self, input_id):
        if input_id.startswith(f'{MODE_FLAT}_'):
            return self.flat_state
        if input_id.startswith(f'{MODE_SIDE}_'):
            return self.side_state
        return self.active_state()

    def state_for_tab(self, tab_id):
        if tab_id == TAB_FLAT:
            return self.flat_state
        if tab_id == TAB_SIDE:
            return self.side_state
        return None

    def set_active_mode_from_tab(self, input_id):
        if input_id == TAB_FLAT:
            self.active_mode = MODE_FLAT
            return True
        if input_id == TAB_SIDE:
            self.active_mode = MODE_SIDE
            return True
        return False

    def sync_active_mode_from_inputs(self, inputs):
        """Track the visible milling tab; keeps the last milling mode when the
        Setup tab is active."""
        side_tab = adsk.core.TabCommandInput.cast(inputs.itemById(TAB_SIDE))
        flat_tab = adsk.core.TabCommandInput.cast(inputs.itemById(TAB_FLAT))
        if side_tab and side_tab.isActive:
            self.active_mode = MODE_SIDE
        elif flat_tab and flat_tab.isActive:
            self.active_mode = MODE_FLAT
