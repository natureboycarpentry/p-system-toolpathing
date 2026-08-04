"""
Lamello P-System CNC Toolpath Addin command registration.

start()/stop() only register the Manufacture Add-Ins button. Heavy dialog and
CAM imports load lazily when the command is first invoked.
"""

import traceback

import adsk.core

# CMD_ID is kept stable across releases so existing toolbar customizations keep working.
CMD_ID = 'ClamexGenerateToolpathsCmd'
CMD_NAME = 'Lamello P-System CNC Toolpath Addin'
CMD_DESC = 'Generate Lamello P-System connector toolpaths at selected anchor points'
ADDIN_TITLE = 'Lamello P-System'
_handlers = []


def _resource_folder():
    return './resources'


def _find_addins_panel(ui):
    panel = ui.allToolbarPanels.itemById('CAMScriptsAddinsPanel')
    if not panel:
        cam_ws = ui.workspaces.itemById('CAMEnvironment')
        if cam_ws:
            panel = cam_ws.toolbarPanels.itemById('CAMScriptsAddinsPanel')
    return panel


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        ui = adsk.core.Application.get().userInterface
        try:
            from commands.generate_clamex import command as command_module

            command_module.handle_command_created(args, _handlers)
        except Exception:
            ui.messageBox(
                f'{ADDIN_TITLE} dialog failed:\n{traceback.format_exc()}',
                ADDIN_TITLE,
            )


def start():
    ui = adsk.core.Application.get().userInterface

    # Recreate the command definition each start so a stale definition (old name,
    # old icon, stacked commandCreated handlers) never survives a reload.
    cmd_def = ui.commandDefinitions.itemById(CMD_ID)
    if cmd_def:
        panel = _find_addins_panel(ui)
        if panel:
            control = panel.controls.itemById(CMD_ID)
            if control:
                control.deleteMe()
        cmd_def.deleteMe()
    cmd_def = ui.commandDefinitions.addButtonDefinition(
        CMD_ID, CMD_NAME, CMD_DESC, _resource_folder()
    )

    on_created = CommandCreatedHandler()
    cmd_def.commandCreated.add(on_created)
    _handlers.append(on_created)

    panel = _find_addins_panel(ui)
    if panel:
        control = panel.controls.itemById(CMD_ID)
        if not control:
            panel.controls.addCommand(cmd_def)


def stop():
    ui = adsk.core.Application.get().userInterface
    cmd_def = ui.commandDefinitions.itemById(CMD_ID)
    if cmd_def:
        panel = _find_addins_panel(ui)
        if panel:
            control = panel.controls.itemById(CMD_ID)
            if control:
                control.deleteMe()
        cmd_def.deleteMe()
    _handlers.clear()
