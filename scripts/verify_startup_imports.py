#!/usr/bin/env python3
"""Static check that startup imports stay light (no Fusion required).

Simulates Fusion's add-in load path:
  LamelloPSystemCNC.py imports only adsk.core, then run() loads entry.start().

This script verifies that importing commands.generate_clamex.entry does NOT
pull in the heavy command/dialog/lib stack. Autodesk still requires measuring
real load time in Fusion with APPLOG_FOR_PERFORMANCE=yes (target < 0.005s).

Run from the repo root:
  python3 scripts/verify_startup_imports.py
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDIN = ROOT / 'LamelloPSystemCNC'

FORBIDDEN_AFTER_ENTRY = (
    'commands.generate_clamex.command',
    'commands.generate_clamex.dialog',
    'lib.cam_ops',
    'lib.path_geometry',
    'lib.preview',
    'lib.tool_body',
    'lib.toolpath_def',
    'adsk.cam',
    'adsk.fusion',
)


def install_adsk_stub() -> None:
    adsk = types.ModuleType('adsk')
    core = types.ModuleType('adsk.core')

    class _Base:
        def __init__(self, *args, **kwargs):
            pass

    class Application:
        @staticmethod
        def get():
            return Application()

        @property
        def userInterface(self):
            return UserInterface()

    class UserInterface:
        def __init__(self):
            self.commandDefinitions = CommandDefinitions()
            self.allToolbarPanels = ToolbarPanels()
            self.workspaces = Workspaces()

        def messageBox(self, *args, **kwargs):
            pass

    class CommandDefinitions:
        def itemById(self, _id):
            return None

        def addButtonDefinition(self, *args, **kwargs):
            return CommandDefinition()

    class CommandDefinition:
        def __init__(self):
            self.commandCreated = Event()

        def deleteMe(self):
            pass

    class Event:
        def add(self, _handler):
            pass

    class ToolbarPanels:
        def itemById(self, _id):
            return ToolbarPanel()

    class ToolbarPanel:
        def __init__(self):
            self.controls = Controls()

    class Controls:
        def itemById(self, _id):
            return None

        def addCommand(self, _cmd):
            pass

    class Workspaces:
        def itemById(self, _id):
            return None

    class CommandCreatedEventHandler(_Base):
        pass

    core.Application = Application
    core.CommandCreatedEventHandler = CommandCreatedEventHandler
    adsk.core = core
    sys.modules['adsk'] = adsk
    sys.modules['adsk.core'] = core


def main() -> int:
    install_adsk_stub()
    addin_dir = str(ADDIN)
    if addin_dir not in sys.path:
        sys.path.insert(0, addin_dir)

    # Drop any prior add-in modules so the check is clean.
    for name in list(sys.modules):
        if name == 'lib' or name.startswith('lib.') or name == 'commands' or name.startswith('commands.'):
            del sys.modules[name]

    entry = importlib.import_module('commands.generate_clamex.entry')
    # Touch start() so registration path is exercised against stubs.
    entry.start()

    loaded_forbidden = [name for name in FORBIDDEN_AFTER_ENTRY if name in sys.modules]
    if loaded_forbidden:
        print('FAIL: heavy modules loaded during entry.start():')
        for name in loaded_forbidden:
            print(f'  - {name}')
        return 1

    print('OK: entry.start() did not import command/dialog/lib/CAM modules.')
    print('Still measure real Fusion load time with APPLOG_FOR_PERFORMANCE=yes')
    print('and confirm "ran script" for LamelloPSystemCNC is under 0.005 seconds.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
