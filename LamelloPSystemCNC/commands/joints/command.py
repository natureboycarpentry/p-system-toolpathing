"""
Lamello Joints command (Design workspace): one dialog, three tabs.

- Find (commands/find_joints): detect every touching panel end and save in bulk.
- Define (commands/define_joints): pick two touching faces for one joint.
- Manage (commands/manage_joints): list, highlight and delete stored joints.

This module owns the command and its events and forwards each one to the
active tab's module (build / activate / input_changed / is_valid / preview /
execute). OK acts on the active tab only.

Imported lazily from entry.py.
"""

import traceback

import adsk.core
import adsk.fusion

from commands.define_joints import command as define_tab
from commands.find_joints import command as find_tab
from commands.manage_joints import command as manage_tab
from lib import joint_preview
from lib.errors import UserFacingError

TITLE = 'Lamello P-System – Joints'
TAB_PREFIX = 'ljTab_'

# Order = tab order; the first tab is the default.
TABS = (
    ('find', find_tab),
    ('define', define_tab),
    ('manage', manage_tab),
)


def _design():
    return adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)


class _Host:
    def __init__(self):
        self.states = {}

    def active(self, inputs):
        """(module, state) of the active tab; the first tab if Fusion reports none."""
        for key, module in TABS:
            tab = adsk.core.TabCommandInput.cast(inputs.itemById(TAB_PREFIX + key))
            if tab and tab.isActive:
                return module, self.states[key]
        key, module = TABS[0]
        return module, self.states[key]


def _command_inputs(event_input):
    """Top-level inputs of the command (event inputs may be a tab's children)."""
    return event_input.parentCommand.commandInputs


def _preselection():
    ui = adsk.core.Application.get().userInterface
    entities = []
    for index in range(ui.activeSelections.count):
        entity = ui.activeSelections.item(index).entity
        if (
            adsk.fusion.Occurrence.cast(entity)
            or adsk.fusion.BRepBody.cast(entity)
            or adsk.fusion.BRepFace.cast(entity)
        ):
            entities.append(entity)
    return entities


def handle_command_created(args, handlers):
    ui = adsk.core.Application.get().userInterface
    try:
        event_args = adsk.core.CommandCreatedEventArgs.cast(args)
        cmd = event_args.command
        if not _design():
            raise UserFacingError('Switch to the Design workspace to work with joints.')

        host = _Host()
        inputs = cmd.commandInputs
        for key, module in TABS:
            host.states[key] = module.new_state()
            tab = inputs.addTabCommandInput(TAB_PREFIX + key, module.LABEL)
            tab.tooltip = module.TOOLTIP
            module.build(tab.children, host.states[key])

        for event, handler in (
            (cmd.activate, _ActivateHandler(host)),
            (cmd.inputChanged, _InputChangedHandler(host)),
            (cmd.validateInputs, _ValidateHandler(host)),
            (cmd.executePreview, _PreviewHandler(host)),
            (cmd.execute, _ExecuteHandler(host)),
            (cmd.destroy, _DestroyHandler()),
        ):
            event.add(handler)
            handlers.append(handler)
    except UserFacingError as exc:
        ui.messageBox(str(exc), TITLE)
    except Exception:
        ui.messageBox(f'{TITLE} failed:\n{traceback.format_exc()}', TITLE)


class _ActivateHandler(adsk.core.CommandEventHandler):
    """Route the pre-selection: exactly two faces -> Define, anything else -> Find (default)."""

    def __init__(self, host):
        super().__init__()
        self._host = host

    def notify(self, args):
        try:
            inputs = adsk.core.CommandEventArgs.cast(args).command.commandInputs
            entities = _preselection()
            faces = [e for e in entities if adsk.fusion.BRepFace.cast(e)]
            use_define = len(entities) == len(faces) == 2
            define_tab.activate(inputs, self._host.states['define'], faces if use_define else [])
            find_tab.activate(inputs, self._host.states['find'], [] if use_define else entities)
            if use_define:
                adsk.core.TabCommandInput.cast(inputs.itemById(TAB_PREFIX + 'define')).activate()
        except Exception:
            adsk.core.Application.get().log(f'{TITLE} activate: {traceback.format_exc()}')


class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self, host):
        super().__init__()
        self._host = host

    def notify(self, args):
        try:
            changed = adsk.core.InputChangedEventArgs.cast(args).input
            if changed.id.startswith(TAB_PREFIX):
                return
            inputs = _command_inputs(changed)
            module, state = self._host.active(inputs)
            module.input_changed(inputs, changed, state)
        except Exception:
            adsk.core.Application.get().log(f'{TITLE} inputChanged: {traceback.format_exc()}')


class _ValidateHandler(adsk.core.ValidateInputsEventHandler):
    def __init__(self, host):
        super().__init__()
        self._host = host

    def notify(self, args):
        event_args = adsk.core.ValidateInputsEventArgs.cast(args)
        try:
            inputs = event_args.inputs
            module, state = self._host.active(inputs)
            event_args.areInputsValid = bool(module.is_valid(inputs, state))
        except Exception:
            event_args.areInputsValid = False


class _PreviewHandler(adsk.core.CommandEventHandler):
    def __init__(self, host):
        super().__init__()
        self._host = host

    def notify(self, args):
        try:
            event_args = adsk.core.CommandEventArgs.cast(args)
            inputs = event_args.command.commandInputs
            design = _design()
            joint_preview.clear(design)
            module, state = self._host.active(inputs)
            module.preview(inputs, state, design)
            event_args.isValidResult = False
        except Exception:
            adsk.core.Application.get().log(f'{TITLE} preview: {traceback.format_exc()}')


class _ExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, host):
        super().__init__()
        self._host = host

    def notify(self, args):
        ui = adsk.core.Application.get().userInterface
        try:
            inputs = adsk.core.CommandEventArgs.cast(args).command.commandInputs
            design = _design()
            joint_preview.clear(design)
            module, state = self._host.active(inputs)
            message = module.execute(inputs, state, design)
            if message:
                ui.messageBox(message, TITLE)
        except UserFacingError as exc:
            ui.messageBox(str(exc), TITLE)
        except Exception:
            ui.messageBox(f'{TITLE} failed:\n{traceback.format_exc()}', TITLE)


class _DestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            joint_preview.clear(_design())
        except Exception:
            pass
