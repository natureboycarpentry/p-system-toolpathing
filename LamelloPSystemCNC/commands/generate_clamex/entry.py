"""
Lamello P-System CNC Toolpath Addin command registration.

start()/stop() only register toolbar buttons. Heavy dialog and CAM imports load
lazily (importlib) when a command is first invoked.

Commands:
- Manual toolpaths (Manufacture ADD-INS): the original Setup / Edge / Face dialog.
- Generate from Joints (Manufacture ADD-INS): machine joints stored on parts.
- Define Joints (Design ADD-INS): pick two touching faces to store a joint.
"""

import importlib
import traceback

import adsk.core

# CMD_ID is kept stable across releases so existing toolbar customizations keep working.
CMD_ID = 'ClamexGenerateToolpathsCmd'
CMD_NAME = 'Lamello P-System CNC Toolpath Addin'
CMD_DESC = 'Generate Lamello P-System connector toolpaths at selected anchor points'
ADDIN_TITLE = 'Lamello P-System'

JOINTS_GENERATE_CMD_ID = 'LamelloGenerateFromJointsCmd'
DEFINE_JOINTS_CMD_ID = 'LamelloDefineJointsCmd'

_CAM_PANEL = ('CAMScriptsAddinsPanel', 'CAMEnvironment')
_DESIGN_PANEL = ('SolidScriptsAddinsPanel', 'FusionSolidEnvironment')

COMMANDS = (
    {
        'id': CMD_ID,
        'name': CMD_NAME,
        'description': CMD_DESC,
        'module': 'commands.generate_clamex.command',
        'panel': _CAM_PANEL,
    },
    {
        'id': JOINTS_GENERATE_CMD_ID,
        'name': 'Lamello – Generate from Joints',
        'description': (
            'Generate Lamello P-System Edge / Face toolpaths for every joint stored on '
            'the parts in a setup (works on Arrange layouts)'
        ),
        'module': 'commands.joint_generate.command',
        'panel': _CAM_PANEL,
    },
    {
        'id': DEFINE_JOINTS_CMD_ID,
        'name': 'Lamello – Define Joints',
        'description': (
            'Pick two touching panel faces to place Lamello P-System connectors; the '
            'joint follows the parts through Arrange'
        ),
        'module': 'commands.define_joints.command',
        'panel': _DESIGN_PANEL,
    },
)

_handlers = []


def _resource_folder():
    return './resources'


def _find_panel(ui, panel_spec):
    panel_id, workspace_id = panel_spec
    panel = ui.allToolbarPanels.itemById(panel_id)
    if not panel:
        workspace = ui.workspaces.itemById(workspace_id)
        if workspace:
            panel = workspace.toolbarPanels.itemById(panel_id)
    return panel


def _find_addins_panel(ui):
    """Manufacture ADD-INS panel (kept for backwards compatibility)."""
    return _find_panel(ui, _CAM_PANEL)


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self, module_name):
        super().__init__()
        self._module_name = module_name

    def notify(self, args):
        ui = adsk.core.Application.get().userInterface
        try:
            command_module = importlib.import_module(self._module_name)
            command_module.handle_command_created(args, _handlers)
        except Exception:
            ui.messageBox(
                f'{ADDIN_TITLE} dialog failed:\n{traceback.format_exc()}',
                ADDIN_TITLE,
            )


def _remove_command(ui, spec):
    cmd_def = ui.commandDefinitions.itemById(spec['id'])
    if cmd_def:
        panel = _find_panel(ui, spec['panel'])
        if panel:
            control = panel.controls.itemById(spec['id'])
            if control:
                control.deleteMe()
        cmd_def.deleteMe()


def _add_command(ui, spec):
    cmd_def = ui.commandDefinitions.addButtonDefinition(
        spec['id'], spec['name'], spec['description'], _resource_folder()
    )
    on_created = CommandCreatedHandler(spec['module'])
    cmd_def.commandCreated.add(on_created)
    _handlers.append(on_created)

    # Pin to the ADD-INS toolbar strip (not only the panel overflow).
    # isPromoted mirrors "Pin to Toolbar"; isPromotedByDefault keeps it after a
    # toolbar reset. Icons come from ./resources (16/32/64).
    panel = _find_panel(ui, spec['panel'])
    if panel:
        control = panel.controls.itemById(spec['id'])
        if not control:
            control = panel.controls.addCommand(cmd_def)
        if control:
            control.isPromotedByDefault = True
            control.isPromoted = True


def start():
    ui = adsk.core.Application.get().userInterface
    # Recreate definitions each start so a stale definition (old name, old icon,
    # stacked commandCreated handlers) never survives a reload.
    for spec in COMMANDS:
        _remove_command(ui, spec)
        _add_command(ui, spec)


def stop():
    ui = adsk.core.Application.get().userInterface
    for spec in COMMANDS:
        _remove_command(ui, spec)
    _handlers.clear()
