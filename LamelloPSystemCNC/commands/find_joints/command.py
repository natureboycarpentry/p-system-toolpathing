"""
Find tab of the Lamello Joints command (Design workspace).

Select components, bodies or faces (or nothing, for the whole assembly) and the
add-in finds every place a panel end touches another panel's face
(lib/joints.find_joint_drafts). Review the list, untick any you don't want,
set the connector type / end offset / count once, and OK saves them all as
joints, exactly as if each had been picked in Define Joints. Joints that
already exist are listed unticked; ticking one replaces it.

Hosted by commands/joints/command.py, which imports it lazily.
"""

import adsk.core
import adsk.fusion

from lib import joint_math as jm
from lib import joint_preview
from lib import joints as jt
from lib.path_geometry import CLAMEX_COMPONENT_NAME
from lib.settings import load_settings, save_settings
from lib.toolpath_def import DEFAULT_CONNECTOR_TYPE
from lib.ui_helpers import read_dropdown, select_dropdown

from commands.define_joints.command import (
    SETTING_COUNT,
    SETTING_END_OFFSET,
    SETTING_TYPE,
    _preview_edge_cutter_diameter,
)

INPUT_PARTS = 'fjParts'
INPUT_TYPE = 'fjConnectorType'
INPUT_END_OFFSET = 'fjEndOffset'
INPUT_COUNT = 'fjCount'
INPUT_TABLE = 'fjTable'
INPUT_INFO = 'fjInfo'
ROW_PREFIX = 'fjRow_'


class _State:
    def __init__(self):
        self.drafts = []
        self.existing = []  # existing joint id (or None) per draft
        self.skipped_faces = 0
        self.scanned_parts = 0
        self.whole_assembly = True
        self.generation = 0
        self.highlight = None  # index of the selected row, or None
        self.edge_cutter_diameter_mm = jm.NOMINAL_EDGE_CUTTER_DIAMETER_MM


def _design():
    return adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)


# --- gathering faces ---------------------------------------------------------

def _skip_occurrence(occurrence):
    if jt.is_arranged_occurrence(occurrence):
        return True
    return occurrence.component.name.startswith(CLAMEX_COMPONENT_NAME)


def _body_faces(body):
    try:
        if not body.isVisible or not body.isSolid:
            return []
    except Exception:
        pass
    return [body.faces.item(index) for index in range(body.faces.count)]


def _occurrence_tree_faces(occurrence, parts):
    """Faces of an occurrence and everything below it (proxies)."""
    if _skip_occurrence(occurrence):
        return []
    faces = []
    bodies = occurrence.bRepBodies
    if bodies.count:
        parts.add(occurrence.fullPathName)
    for index in range(bodies.count):
        faces.extend(_body_faces(bodies.item(index)))
    children = occurrence.childOccurrences
    for index in range(children.count):
        faces.extend(_occurrence_tree_faces(children.item(index), parts))
    return faces


def _gather_faces(design, inputs, state):
    """Candidate faces from the selection, or from the whole assembly if empty."""
    sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(INPUT_PARTS))
    parts = set()
    faces = []
    count = sel.selectionCount if sel else 0
    state.whole_assembly = count == 0
    if state.whole_assembly:
        root = design.rootComponent
        for index in range(root.occurrences.count):
            faces.extend(_occurrence_tree_faces(root.occurrences.item(index), parts))
    else:
        for index in range(count):
            entity = sel.selection(index).entity
            occurrence = adsk.fusion.Occurrence.cast(entity)
            body = adsk.fusion.BRepBody.cast(entity)
            face = adsk.fusion.BRepFace.cast(entity)
            if occurrence:
                faces.extend(_occurrence_tree_faces(occurrence, parts))
            elif body:
                if body.assemblyContext:
                    parts.add(body.assemblyContext.fullPathName)
                faces.extend(_body_faces(body))
            elif face:
                if face.assemblyContext:
                    parts.add(face.assemblyContext.fullPathName)
                faces.append(face)
    # Same face picked twice (e.g. a face and its component) must not pair with itself.
    unique = []
    seen = set()
    for face in faces:
        key = (face.assemblyContext.fullPathName if face.assemblyContext else '', face.tempId)
        if key not in seen:
            seen.add(key)
            unique.append(face)
    state.scanned_parts = len(parts)
    return unique


# --- table / info --------------------------------------------------------------

def _read_values(inputs):
    end_offset = adsk.core.DistanceValueCommandInput.cast(inputs.itemById(INPUT_END_OFFSET))
    count = adsk.core.IntegerSpinnerCommandInput.cast(inputs.itemById(INPUT_COUNT))
    connector = adsk.core.DropDownCommandInput.cast(inputs.itemById(INPUT_TYPE))
    return {
        'end_offset_mm': end_offset.value * 10.0 if end_offset else jm.DEFAULT_END_OFFSET_MM,
        'count': count.value if count else jm.DEFAULT_CONNECTOR_COUNT,
        'connector_type': read_dropdown(connector, DEFAULT_CONNECTOR_TYPE),
    }


def _row_checkbox(inputs, state, index):
    return adsk.core.BoolValueCommandInput.cast(
        inputs.itemById(f'{ROW_PREFIX}{state.generation}_{index}')
    )


def _ticked(inputs, state):
    ticked = []
    for index, draft in enumerate(state.drafts):
        checkbox = _row_checkbox(inputs, state, index)
        if checkbox and checkbox.value:
            ticked.append((draft, state.existing[index]))
    return ticked


def _rebuild_table(inputs, state):
    table = adsk.core.TableCommandInput.cast(inputs.itemById(INPUT_TABLE))
    table.clear()
    state.generation += 1
    sub = table.commandInputs
    for index, draft in enumerate(state.drafts):
        existing = state.existing[index]
        prefix = f'{state.generation}_{index}'
        checkbox = sub.addBoolValueInput(f'{ROW_PREFIX}{prefix}', '', True, '', not existing)
        checkbox.tooltip = 'Tick to save this joint when you press OK.'
        # A button, not read-only text: Fusion fires no event for a plain row
        # click, so the name is what the user clicks to highlight the parts.
        name = sub.addBoolValueInput(f'fjName_{prefix}', '', False, '', False)
        name.text = draft.label()
        name.tooltip = 'Click to highlight the two parts (Edge-slot part → Face-cavity part).'
        detail = f'{draft.frame["length_mm"]:.0f} mm'
        detail += ' · exists' if existing else ' · new'
        info = sub.addStringValueInput(f'fjDetail_{prefix}', '', detail)
        info.isReadOnly = True
        info.tooltip = (
            'A joint is already stored here; tick to replace it with these settings.'
            if existing
            else 'Joint length along the contact.'
        )
        table.addCommandInput(checkbox, index, 0)
        table.addCommandInput(name, index, 1)
        table.addCommandInput(info, index, 2)
    table.minimumVisibleRows = min(max(len(state.drafts), 3), 14)


def _rescan(inputs, state):
    design = _design()
    faces = _gather_faces(design, inputs, state)
    state.drafts, state.skipped_faces = jt.find_joint_drafts(faces)
    state.highlight = None
    state.existing = [jt.find_existing_joint_id(draft) for draft in state.drafts]
    _rebuild_table(inputs, state)
    _update_info(inputs, state)


def _update_info(inputs, state):
    info = adsk.core.TextBoxCommandInput.cast(inputs.itemById(INPUT_INFO))
    if not info:
        return
    scope = (
        'Nothing selected: scanning <b>every part</b> in the assembly'
        if state.whole_assembly
        else f'Scanning <b>{state.scanned_parts}</b> selected part(s)'
    )
    lines = [scope + ' (Arrange copies and Clamex Toolpaths are ignored).']
    if not state.drafts:
        lines.append(
            'No touching panel ends found. Panels must be separate components whose end '
            'face touches the other panel (within 0.5 mm).'
        )
    else:
        existing = sum(1 for joint_id in state.existing if joint_id)
        ticked = len(_ticked(inputs, state))
        lines.append(f'Found <b>{len(state.drafts)}</b> joint(s); <b>{ticked}</b> ticked to save.')
        if state.highlight is not None and state.highlight < len(state.drafts):
            selected = state.drafts[state.highlight]
            lines.append(
                f'Selected: <b>{selected.edge_component.name}</b> (Edge slot, orange) → '
                f'<b>{selected.face_component.name}</b> (Face cavity, blue).'
            )
        else:
            lines.append('Click a joint\'s name to highlight its two parts.')
        if existing:
            lines.append(f'{existing} already exist and are unticked; tick to replace them.')
        values = _read_values(inputs)
        short = sum(
            1 for draft, _id in _ticked(inputs, state)
            if jm.connector_positions(
                draft.frame['length_mm'], values['end_offset_mm'], values['count']
            )[1]
        )
        if short:
            lines.append(
                f'<b>Note:</b> {short} ticked joint(s) are too short for these end offsets '
                'and get one centred connector.'
            )
    if state.skipped_faces:
        lines.append(f'{state.skipped_faces} face(s) not in a component were skipped.')
    info.formattedText = '<br>'.join(lines)


# --- tab interface (hosted by commands/joints/command.py) ------------------------

LABEL = 'Find'
TOOLTIP = 'Find every touching panel end in a selection (or the whole assembly) and save them in bulk.'


def new_state():
    state = _State()
    state.edge_cutter_diameter_mm = _preview_edge_cutter_diameter()
    return state


def build(inputs, state):
    """Add the Find tab's inputs to *inputs* (the tab's children)."""
    saved = load_settings()

    parts = inputs.addSelectionInput(
        INPUT_PARTS, 'Parts', 'Select components, bodies or faces (or nothing for all)'
    )
    parts.addSelectionFilter('Occurrences')
    parts.addSelectionFilter('SolidBodies')
    parts.addSelectionFilter('PlanarFaces')
    parts.setSelectionLimits(0, 0)
    parts.tooltip = (
        'Components (pick them in the browser), bodies or faces to search for joints. '
        'Leave empty to search the whole assembly.'
    )

    connector = inputs.addDropDownCommandInput(
        INPUT_TYPE, 'Connector type', adsk.core.DropDownStyles.TextListDropDownStyle
    )
    connector.listItems.add('P14', False, '')
    connector.listItems.add('P10', False, '')
    select_dropdown(connector, saved.get(SETTING_TYPE, DEFAULT_CONNECTOR_TYPE))

    end_offset_mm = float(saved.get(SETTING_END_OFFSET, jm.DEFAULT_END_OFFSET_MM))
    end_offset = inputs.addDistanceValueCommandInput(
        INPUT_END_OFFSET, 'End offset', adsk.core.ValueInput.createByReal(end_offset_mm / 10.0)
    )
    try:
        end_offset.minimumValue = 0.0
        end_offset.isMinimumValueInclusive = True
    except Exception:
        pass
    end_offset.tooltip = 'Distance from each end of every joint to its first and last connector.'

    count = inputs.addIntegerSpinnerCommandInput(
        INPUT_COUNT,
        'Connectors',
        1,
        jm.MAX_CONNECTOR_COUNT,
        1,
        int(saved.get(SETTING_COUNT, jm.DEFAULT_CONNECTOR_COUNT)),
    )
    count.tooltip = 'Connectors per joint, evenly spaced between the end offsets.'

    table = inputs.addTableCommandInput(INPUT_TABLE, 'Joints found', 3, '1:7:4')
    table.maximumVisibleRows = 14

    inputs.addTextBoxCommandInput(INPUT_INFO, '', '', 5, True)


def activate(inputs, state, entities):
    """Seed the selection with pre-selected parts, then scan."""
    sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(INPUT_PARTS))
    for entity in entities:
        sel.addSelection(entity)
    _rescan(inputs, state)


def _row_index(inputs, changed, state):
    """Row the user just clicked: from a row input's id, else the table selection."""
    if changed.id == INPUT_TABLE:
        table = adsk.core.TableCommandInput.cast(inputs.itemById(INPUT_TABLE))
        return table.selectedRow if table else -1
    if changed.id.startswith(('fjRow_', 'fjName_', 'fjDetail_')):
        generation, _sep, index = changed.id.split('_', 1)[1].partition('_')
        if generation == str(state.generation) and index.isdigit():
            return int(index)
    return -1


def input_changed(inputs, changed, state):
    if changed.id == INPUT_PARTS:
        _rescan(inputs, state)
        return
    row = _row_index(inputs, changed, state)
    if 0 <= row < len(state.drafts):
        state.highlight = row
    _update_info(inputs, state)


def is_valid(inputs, state):
    return bool(_ticked(inputs, state))


def preview(inputs, state, design):
    ticked = _ticked(inputs, state)
    replaced = {joint_id for _draft, joint_id in ticked if joint_id}
    joint_preview.draw_existing(design, skip_joint_ids=replaced)
    values = _read_values(inputs)
    drafts = [draft for draft, _joint_id in ticked]
    if state.highlight is not None and state.highlight < len(state.drafts):
        selected = state.drafts[state.highlight]
        joint_preview.highlight_parts(
            design,
            (
                (selected.edge_face, joint_preview.COLOR_EDGE_CUT),
                (selected.mate_face, joint_preview.COLOR_FACE_CUT),
            ),
        )
        if selected not in drafts:
            drafts.append(selected)  # show its connectors even while unticked
    for draft in drafts:
        world_points, _warning = jt.layout_world_points(
            draft, values['end_offset_mm'], values['count']
        )
        joint_preview.draw_draft(
            design,
            draft,
            world_points,
            values['connector_type'],
            state.edge_cutter_diameter_mm,
        )


def execute(inputs, state, design):
    """Save every ticked joint. Returns the message to show."""
    values = _read_values(inputs)
    ticked = _ticked(inputs, state)
    for draft, _joint_id in ticked:
        jt.save_joint(
            design, draft, values['connector_type'], values['end_offset_mm'], values['count']
        )
    save_settings(
        global_settings={
            SETTING_TYPE: values['connector_type'],
            SETTING_END_OFFSET: round(values['end_offset_mm'], 3),
            SETTING_COUNT: values['count'],
        }
    )
    replaced = sum(1 for _draft, joint_id in ticked if joint_id)
    message = f'Saved {len(ticked)} joint(s).'
    if replaced:
        message += f' {replaced} replaced an existing joint.'
    return message
