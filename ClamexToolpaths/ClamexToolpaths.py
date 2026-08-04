"""
Clamex Toolpaths Fusion 360 add-in entry point.

Adds the add-in directory to sys.path, purges cached lib/commands modules on
Stop/Run, and delegates lifecycle to commands.generate_clamex.entry.
"""

import os
import sys
import traceback

import adsk.core

ADDIN_DIR = os.path.dirname(os.path.realpath(__file__))
if ADDIN_DIR not in sys.path:
    sys.path.insert(0, ADDIN_DIR)


def _purge_addin_modules():
    """Drop cached imports so Stop/Run loads the latest source files."""
    for name in list(sys.modules):
        if name == 'lib' or name.startswith('lib.'):
            del sys.modules[name]
        elif name == 'commands' or name.startswith('commands.'):
            del sys.modules[name]


def _load_generate_entry():
    from commands.generate_clamex import entry as generate_clamex_entry
    return generate_clamex_entry


def run(context):
    ui = None
    try:
        _purge_addin_modules()
        generate_clamex_entry = _load_generate_entry()
        generate_clamex_entry.start()
    except Exception:
        app = adsk.core.Application.get()
        ui = app.userInterface
        ui.messageBox(f'Clamex Toolpaths failed to start:\n{traceback.format_exc()}')


def stop(context):
    ui = None
    try:
        entry_module = sys.modules.get('commands.generate_clamex.entry')
        if entry_module:
            entry_module.stop()
        _purge_addin_modules()
    except Exception:
        app = adsk.core.Application.get()
        ui = app.userInterface
        ui.messageBox(f'Clamex Toolpaths failed to stop:\n{traceback.format_exc()}')
