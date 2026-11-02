"""
Manage Joints command (Design workspace).

Lists every joint stored in the design (lib/joints.collect_joints) in a table:
which part gets the Edge slot, which gets the Face cavity, connector type and
count, and whether a half is missing (broken: a part was deleted or re-made).
Selecting a row highlights that joint on the canvas; ticked rows are drawn red
and deleted (both halves) on OK.

Imported lazily from entry.py.
"""

import traceback

import adsk.core
import adsk.fusion

from lib import joint_preview
from lib import joints as jt
from lib.errors import UserFacingError

TITLE = 'Lamello P-System – Manage Joints'

INPUT_TABLE = 'mjTable'
INPUT_MARK_BROKEN = 'mjMarkBroken'
INPUT_MARK_ALL = 'mjMarkAll'
INPUT_INFO = 'mjInfo'
ROW_PREFIX = 'mjRow_'


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
    lines.append('Select a row to highlight it. Tick rows to delete them (shown red).')
    if marked:
        lines.append(f'<b>{marked}</b> marked for deletion.')
    info.formattedText = '<br>'.join(lines)


def _add_row(table, index, joint):
    sub = table.commandInputs
    checkbox = sub.addBoolValueInput(f'{ROW_PREFIX}{index}', '', True, '', joint['broken'])
    checkbox.tooltip = 'Tick to delete this joint (both halves) when you press OK.'
    name = sub.addStringValueInput(f'mjName_{index}', '', joint['label'])
    name.isReadOnly = True
    name.tooltip = 'Edge-slot part → Face-cavity part'
    detail = f'{joint["connector_type"]} × {joint["count"]}'
    if joint['broken']:
        detail += '  ⚠ broken'
    info = sub.addStringValueInput(f'mjDetail_{index}', '', detail)
    info.isReadOnly = True
    table.addCommandInput(checkbox, index, 0)
    table.addCommandInput(name, index, 1)
    table.addCommandInput(info, index, 2)


def handle_command_created(args, handlers):
    ui = adsk.core.Application.get().userInterface
    try:
        event_args = adsk.core.CommandCreatedEventArgs.cast(args)
        cmd = event_args.command
        design = _design()
        if not design:
            raise UserFacingError('Switch to the Design workspace to manage joints.')

        state = _State()
        state.joints = jt.collect_joints(design)
        try:
            from commands.define_joints.command import _preview_edge_cutter_diameter

            state.edge_cutter_diameter_mm = _preview_edge_cutter_diameter()
        except Exception:
            pass

        inputs = cmd.commandInputs
        cmd.okButtonText = 'Delete marked'

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

        for event, handler in (
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


class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        try:
            event_args = adsk.core.InputChangedEventArgs.cast(args)
            inputs = event_args.inputs
            changed = event_args.input
            state = self._state
            if changed.id == INPUT_MARK_BROKEN:
                for index, joint in enumerate(state.joints):
                    _row_checkbox(inputs, index).value = joint['broken']
            elif changed.id == INPUT_MARK_ALL:
                mark = len(_marked_ids(inputs, state)) < len(state.joints)
                for index in range(len(state.joints)):
                    _row_checkbox(inputs, index).value = mark
            elif changed.id == INPUT_TABLE or changed.id.startswith(ROW_PREFIX):
                table = adsk.core.TableCommandInput.cast(inputs.itemById(INPUT_TABLE))
                row = table.selectedRow if table else -1
                if changed.id.startswith(ROW_PREFIX):
                    row = int(changed.id[len(ROW_PREFIX):])
                if 0 <= row < len(state.joints):
                    state.highlight_id = state.joints[row]['id']
            _update_info(inputs, state)
        except Exception:
            adsk.core.Application.get().log(f'{TITLE} inputChanged: {traceback.format_exc()}')


class _ValidateHandler(adsk.core.ValidateInputsEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        event_args = adsk.core.ValidateInputsEventArgs.cast(args)
        event_args.areInputsValid = bool(_marked_ids(event_args.inputs, self._state))


class _PreviewHandler(adsk.core.CommandEventHandler):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def notify(self, args):
        try:
            event_args = adsk.core.CommandEventArgs.cast(args)
            design = _design()
            joint_preview.clear(design)
            joint_preview.draw_managed(
                design,
                self._state.joints,
                highlight_id=self._state.highlight_id,
                marked_ids=_marked_ids(event_args.command.commandInputs, self._state),
                edge_cutter_diameter_mm=self._state.edge_cutter_diameter_mm,
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
            marked = _marked_ids(inputs, self._state)
            for joint_id in marked:
                jt.delete_joint(design, joint_id)
            app.userInterface.messageBox(f'Deleted {len(marked)} joint(s).', TITLE)
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
