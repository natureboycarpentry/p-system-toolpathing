"""
Find Joints command (Design workspace).

Select components, bodies or faces (or nothing, for the whole assembly) and the
add-in finds every place a panel end touches another panel's face
(lib/joints.find_joint_drafts). Review the list, untick any you don't want,
set the connector type / end offset / count once, and OK saves them all as
joints, exactly as if each had been picked in Define Joints. Joints that
already exist are listed unticked; ticking one replaces it.

Imported lazily from entry.py.
"""

import traceback

import adsk.core
import adsk.fusion

from lib import joint_math as jm
from lib import joint_preview
from lib import joints as jt
from lib.errors import UserFacingError
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

TITLE = 'Lamello P-System – Find Joints'

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
        name = sub.addStringValueInput(f'fjName_{prefix}', '', draft.label())
        name.isReadOnly = True
        name.tooltip = 'Edge-slot part → Face-cavity part'
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


# --- command -------------------------------------------------------------------

def handle_command_created(args, handlers):
    ui = adsk.core.Application.get().userInterface
    try:
        event_args = adsk.core.CommandCreatedEventArgs.cast(args)
        cmd = event_args.command
        if not _design():
            raise UserFacingError('Switch to the Design workspace to find joints.')

        saved = load_settings()
        inputs = cmd.commandInputs
        cmd.okButtonText = 'Save joints'

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

        state = _State()
        state.edge_cutter_diameter_mm = _preview_edge_cutter_diameter()

        for event, handler in (
            (cmd.activate, _ActivateHandler(state)),
            (cmd.inputChanged, _InputChangedHandler(state)),
            (cmd.validateInputs, _ValidateHandler(state)),
            (cmd.executePreview, _PreviewHandler(state)),
            (cmd.execute, _ExecuteHandler(state)),
            (cmd.destroy, _DestroyHandler()),
        ):
            event.add(handler)
            handlers.append(handler)
    except UserFacingError as exc:
        ui.messageBox(str(exc), TITLE)
    except Exception:
        ui.messageBox(f'{TITLE} failed:\n{traceback.format_exc()}', TITLE)


class _ActivateHandler(adsk.core.CommandEventHandler):
    """Take over whatever was selected before the command started, then scan."""

    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        try:
            inputs = adsk.core.CommandEventArgs.cast(args).command.commandInputs
            sel = adsk.core.SelectionCommandInput.cast(inputs.itemById(INPUT_PARTS))
            ui = adsk.core.Application.get().userInterface
            for index in range(ui.activeSelections.count):
                entity = ui.activeSelections.item(index).entity
                if (
                    adsk.fusion.Occurrence.cast(entity)
                    or adsk.fusion.BRepBody.cast(entity)
                    or adsk.fusion.BRepFace.cast(entity)
                ):
                    sel.addSelection(entity)
            _rescan(inputs, self._state)
        except Exception:
            adsk.core.Application.get().log(f'{TITLE} activate: {traceback.format_exc()}')


class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        try:
            event_args = adsk.core.InputChangedEventArgs.cast(args)
            if event_args.input.id == INPUT_PARTS:
                _rescan(event_args.inputs, self._state)
            else:
                _update_info(event_args.inputs, self._state)
        except Exception:
            adsk.core.Application.get().log(f'{TITLE} inputChanged: {traceback.format_exc()}')


class _ValidateHandler(adsk.core.ValidateInputsEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        event_args = adsk.core.ValidateInputsEventArgs.cast(args)
        event_args.areInputsValid = bool(_ticked(event_args.inputs, self._state))


class _PreviewHandler(adsk.core.CommandEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        try:
            event_args = adsk.core.CommandEventArgs.cast(args)
            inputs = event_args.command.commandInputs
            design = _design()
            joint_preview.clear(design)
            ticked = _ticked(inputs, self._state)
            replaced = {joint_id for _draft, joint_id in ticked if joint_id}
            joint_preview.draw_existing(design, skip_joint_ids=replaced)
            values = _read_values(inputs)
            for draft, _joint_id in ticked:
                world_points, _warning = jt.layout_world_points(
                    draft, values['end_offset_mm'], values['count']
                )
                joint_preview.draw_draft(
                    design,
                    draft,
                    world_points,
                    values['connector_type'],
                    self._state.edge_cutter_diameter_mm,
                )
            event_args.isValidResult = False
        except Exception:
            adsk.core.Application.get().log(f'{TITLE} preview: {traceback.format_exc()}')


class _ExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        app = adsk.core.Application.get()
        try:
            inputs = adsk.core.CommandEventArgs.cast(args).command.commandInputs
            design = _design()
            joint_preview.clear(design)
            values = _read_values(inputs)
            ticked = _ticked(inputs, self._state)
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
            app.userInterface.messageBox(message, TITLE)
        except Exception:
            app.userInterface.messageBox(f'{TITLE} failed:\n{traceback.format_exc()}', TITLE)


class _DestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            joint_preview.clear(_design())
        except Exception:
            pass
