"""
Lamello P-System CNC Toolpath Addin command registration.

start()/stop() only register toolbar buttons. Heavy dialog and CAM imports load
lazily (importlib) when a command is first invoked.

Commands:
- Manual toolpaths (Manufacture > Milling > 3D): the original Setup / Edge / Face dialog.
- Generate from Joints (Manufacture > Milling > 3D): machine joints stored on parts.
- Joints (Design > Solid > Assemble): one dialog with Define (pick two faces),
  Find (detect every touching panel end) and Manage (list / delete) tabs.
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
# The tabbed Joints command keeps the original Define Joints id so a pinned
# button keeps working.
JOINTS_CMD_ID = 'LamelloDefineJointsCmd'
# Separate Find / Manage buttons from earlier builds; removed on start.
LEGACY_CMD_IDS = ('LamelloFindJointsCmd', 'LamelloManageJointsCmd')

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
        'id': JOINTS_CMD_ID,
        'name': 'Lamello – Joints',
        'description': (
            'Define, find and manage Lamello P-System joints: pick two touching faces, '
            'detect every touching panel end in a selection, or list and delete stored '
            'joints. Joints follow the parts through Arrange.'
        ),
        'module': 'commands.joints.command',
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
    for cmd_id in LEGACY_CMD_IDS:
        _remove_command(ui, {'id': cmd_id, 'panel': _DESIGN_ASSEMBLE_PANEL})
    for spec in COMMANDS:
        _remove_command(ui, spec)
        _add_command(ui, spec)


def stop():
    ui = adsk.core.Application.get().userInterface
    for spec in COMMANDS:
        _remove_command(ui, spec)
    _handlers.clear()
