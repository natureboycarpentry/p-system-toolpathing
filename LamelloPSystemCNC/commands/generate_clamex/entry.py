"""
Lamello P-System CNC Toolpath Addin command registration.

start()/stop() only register toolbar buttons. Heavy dialog and CAM imports load
lazily (importlib) when a command is first invoked.

Commands:
- Manual toolpaths (Manufacture > Milling > 3D): the original Setup / Edge / Face dialog.
- Generate from Joints (Manufacture > Milling > 3D): machine joints stored on parts.
- Define Joints (Design > Solid > Assemble): pick two touching faces to store a joint.
- Manage Joints (Design > Solid > Assemble): list, highlight and delete stored joints.
- Find Joints (Design > Solid > Assemble): detect every touching panel end in a selection.
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
MANAGE_JOINTS_CMD_ID = 'LamelloManageJointsCmd'
FIND_JOINTS_CMD_ID = 'LamelloFindJointsCmd'

# Panel spec: (candidate panel ids, workspace id, panel names to match, fallback id).
# Ids are tried first, then a panel in the workspace whose name matches, then the
# workspace's ADD-INS panel so the button is never lost.
_CAM_3D_PANEL = (
    ('CAM3DPanel', 'CAM3DPanelMilling'),
    'CAMEnvironment',
    ('3d',),
    'CAMScriptsAddinsPanel',
)
_DESIGN_ASSEMBLE_PANEL = (
    ('AssemblePanel', 'AssembleJointsPanel'),
    'FusionSolidEnvironment',
    ('assemble',),
    'SolidScriptsAddinsPanel',
)
_CAM_PANEL = _CAM_3D_PANEL

COMMANDS = (
    {
        'id': CMD_ID,
        'name': CMD_NAME,
        'description': CMD_DESC,
        'module': 'commands.generate_clamex.command',
        'panel': _CAM_3D_PANEL,
    },
    {
        'id': JOINTS_GENERATE_CMD_ID,
        'name': 'Lamello – Generate from Joints',
        'description': (
            'Generate Lamello P-System Edge / Face toolpaths for every joint stored on '
            'the parts in a setup (works on Arrange layouts)'
        ),
        'module': 'commands.joint_generate.command',
        'panel': _CAM_3D_PANEL,
    },
    {
        'id': DEFINE_JOINTS_CMD_ID,
        'name': 'Lamello – Define Joints',
        'description': (
            'Pick two touching panel faces to place Lamello P-System connectors; the '
            'joint follows the parts through Arrange'
        ),
        'module': 'commands.define_joints.command',
        'panel': _DESIGN_ASSEMBLE_PANEL,
    },
    {
        'id': FIND_JOINTS_CMD_ID,
        'name': 'Lamello – Find Joints',
        'description': (
            'Select components (or nothing for the whole assembly) and find every place a '
            'panel end touches another panel, then save them all as Lamello joints'
        ),
        'module': 'commands.find_joints.command',
        'panel': _DESIGN_ASSEMBLE_PANEL,
    },
    {
        'id': MANAGE_JOINTS_CMD_ID,
        'name': 'Lamello – Manage Joints',
        'description': (
            'List every Lamello joint in the design, highlight one on the canvas, and '
            'delete joints you no longer need (including broken ones)'
        ),
        'module': 'commands.manage_joints.command',
        'panel': _DESIGN_ASSEMBLE_PANEL,
    },
)

_handlers = []


def _resource_folder():
    return './resources'


def _find_panel(ui, panel_spec):
    panel_ids, workspace_id, names, fallback_id = panel_spec
    for panel_id in panel_ids:
        panel = ui.allToolbarPanels.itemById(panel_id)
        if panel:
            return panel
    workspace = ui.workspaces.itemById(workspace_id)
    if workspace:
        try:
            panels = workspace.toolbarPanels
            for index in range(panels.count):
                panel = panels.item(index)
                if (panel.name or '').strip().lower() in names:
                    return panel
        except Exception:
            pass
    panel = ui.allToolbarPanels.itemById(fallback_id)
    if not panel and workspace:
        panel = workspace.toolbarPanels.itemById(fallback_id)
    return panel


def _find_addins_panel(ui):
    """Manufacture panel used by the manual command (kept for backwards compatibility)."""
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
    # Remove the button from its current panel and from the ADD-INS panel used by
    # earlier versions, so a move never leaves a stale duplicate behind.
    panels = [_find_panel(ui, spec['panel'])]
    fallback_id = spec['panel'][3]
    panels.append(ui.allToolbarPanels.itemById(fallback_id))
    for panel in panels:
        if not panel:
            continue
        control = panel.controls.itemById(spec['id'])
        if control:
            control.deleteMe()
    cmd_def = ui.commandDefinitions.itemById(spec['id'])
    if cmd_def:
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
