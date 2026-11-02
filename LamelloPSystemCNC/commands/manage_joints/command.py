"""
Manage tab of the Lamello Joints command (Design workspace).

Lists every joint stored in the design (lib/joints.collect_joints) in a table:
which part gets the Edge slot, which gets the Face cavity, connector type and
count, and whether a half is missing (broken: a part was deleted or re-made).
Clicking a joint's name highlights it on the canvas; ticked rows are drawn red
and deleted (both halves) on OK.

Hosted by commands/joints/command.py, which imports it lazily.
"""

import adsk.core
import adsk.fusion

from lib import joint_preview
from lib import joints as jt

INPUT_TABLE = 'mjTable'
INPUT_MARK_BROKEN = 'mjMarkBroken'
INPUT_MARK_ALL = 'mjMarkAll'
INPUT_INFO = 'mjInfo'
ROW_PREFIX = 'mjRow_'
NAME_PREFIX = 'mjName_'


class _State:
    def __init__(self):
        self.joints = []
        self.highlight_id = None
        self.edge_cutter_diameter_mm = None


def _design():
    return adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)


def _row_checkbox(inputs, index):
    return adsk.core.BoolValueCommandInput.cast(inputs.itemById(f'{ROW_PREFIX}{index}'))


def _marked_ids(inputs, state):
    marked = set()
    for index, joint in enumerate(state.joints):
        checkbox = _row_checkbox(inputs, index)
        if checkbox and checkbox.value:
            marked.add(joint['id'])
    return marked


def _update_info(inputs, state):
    info = adsk.core.TextBoxCommandInput.cast(inputs.itemById(INPUT_INFO))
    if not info:
        return
    if not state.joints:
        info.formattedText = 'No joints are stored in this design yet.'
        return
    broken = sum(1 for joint in state.joints if joint['broken'])
    connectors = sum(joint['count'] for joint in state.joints)
    marked = len(_marked_ids(inputs, state))
    lines = [f'<b>{len(state.joints)}</b> joint(s), <b>{connectors}</b> connector(s).']
    if broken:
        lines.append(
            f'<b>{broken}</b> broken: one half is missing (its part was deleted or re-made). '
            'Broken joints are skipped by Generate.'
        )
    selected = next((j for j in state.joints if j['id'] == state.highlight_id), None)
    if selected:
        edge = selected['edge'][0].name if selected['edge'] else 'missing'
        face = selected['face'][0].name if selected['face'] else 'missing'
        lines.append(
            f'Selected: <b>{edge}</b> (Edge slot, orange) → <b>{face}</b> (Face cavity, blue).'
        )
    else:
        lines.append('Click a joint\'s name to highlight its two parts.')
    lines.append('Tick rows to delete them (shown red).')
    if marked:
        lines.append(f'<b>{marked}</b> marked for deletion.')
    info.formattedText = '<br>'.join(lines)


def _add_row(table, index, joint):
    sub = table.commandInputs
    checkbox = sub.addBoolValueInput(f'{ROW_PREFIX}{index}', '', True, '', joint['broken'])
    checkbox.tooltip = 'Tick to delete this joint (both halves) when you press OK.'
    # A button, not read-only text: Fusion fires no event for a plain row
    # click, so the name is what the user clicks to highlight the joint.
    name = sub.addBoolValueInput(f'{NAME_PREFIX}{index}', '', False, '', False)
    name.text = joint['label']
    name.tooltip = 'Click to highlight this joint (Edge-slot part → Face-cavity part).'
    detail = f'{joint["connector_type"]} × {joint["count"]}'
    if joint['broken']:
        detail += '  ⚠ broken'
    info = sub.addStringValueInput(f'mjDetail_{index}', '', detail)
    info.isReadOnly = True
    table.addCommandInput(checkbox, index, 0)
    table.addCommandInput(name, index, 1)
    table.addCommandInput(info, index, 2)


# --- tab interface (hosted by commands/joints/command.py) ------------------------

LABEL = 'Manage'
TOOLTIP = 'List every joint in the design, highlight one, and delete the ones you no longer need.'


def new_state():
    state = _State()
    state.joints = jt.collect_joints(_design())
    try:
        from commands.define_joints.command import _preview_edge_cutter_diameter

        state.edge_cutter_diameter_mm = _preview_edge_cutter_diameter()
    except Exception:
        pass
    return state


def build(inputs, state):
    """Add the Manage tab's inputs to *inputs* (the tab's children)."""
    table = inputs.addTableCommandInput(INPUT_TABLE, 'Joints', 3, '1:7:4')
    table.maximumVisibleRows = 14
    table.minimumVisibleRows = min(max(len(state.joints), 3), 14)
    for index, joint in enumerate(state.joints):
        _add_row(table, index, joint)

    mark_broken = table.commandInputs.addBoolValueInput(
        INPUT_MARK_BROKEN, 'Mark broken', False, '', False
    )
    mark_broken.text = 'Mark broken'
    mark_broken.tooltip = 'Tick only the joints that have a missing half.'
    mark_all = table.commandInputs.addBoolValueInput(INPUT_MARK_ALL, 'Mark all', False, '', False)
    mark_all.text = 'Mark all / none'
    mark_all.tooltip = 'Tick every joint, or clear every tick if all are ticked.'
    table.addToolbarCommandInput(mark_broken)
    table.addToolbarCommandInput(mark_all)

    inputs.addTextBoxCommandInput(INPUT_INFO, '', '', 5, True)
    _update_info(inputs, state)


def input_changed(inputs, changed, state):
    if changed.id == INPUT_MARK_BROKEN:
        for index, joint in enumerate(state.joints):
            _row_checkbox(inputs, index).value = joint['broken']
    elif changed.id == INPUT_MARK_ALL:
        mark = len(_marked_ids(inputs, state)) < len(state.joints)
        for index in range(len(state.joints)):
            _row_checkbox(inputs, index).value = mark
    elif changed.id == INPUT_TABLE or changed.id.startswith((ROW_PREFIX, NAME_PREFIX)):
        table = adsk.core.TableCommandInput.cast(inputs.itemById(INPUT_TABLE))
        row = table.selectedRow if table else -1
        for prefix in (ROW_PREFIX, NAME_PREFIX):
            if changed.id.startswith(prefix):
                row = int(changed.id[len(prefix):])
        if 0 <= row < len(state.joints):
            state.highlight_id = state.joints[row]['id']
    _update_info(inputs, state)


def is_valid(inputs, state):
    return bool(_marked_ids(inputs, state))


def preview(inputs, state, design):
    joint_preview.draw_managed(
        design,
        state.joints,
        highlight_id=state.highlight_id,
        marked_ids=_marked_ids(inputs, state),
        edge_cutter_diameter_mm=state.edge_cutter_diameter_mm,
    )


def execute(inputs, state, design):
    """Delete every ticked joint. Returns the message to show."""
    marked = _marked_ids(inputs, state)
    for joint_id in marked:
        jt.delete_joint(design, joint_id)
    return f'Deleted {len(marked)} joint(s).'
