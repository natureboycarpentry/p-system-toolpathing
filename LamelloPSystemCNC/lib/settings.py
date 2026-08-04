"""Persist last-used setup and tool choices between command runs.

Settings live in a per-user AppData folder so App Store installs are not written
to. An older in-add-in-folder file is migrated once if present.
"""

import json
import os
import shutil
import sys

SETTINGS_FILENAME = 'clamex_settings.json'
_SETTINGS_DIR_NAME = 'LamelloPSystemCNC'


def settings_prefix(mode):
    """Return the persisted-settings key prefix for a tab mode ('side' or 'flat')."""
    return f'{mode}_'


def user_settings_dir():
    """Per-user directory for clamex_settings.json (outside the install folder)."""
    if sys.platform == 'darwin':
        return os.path.expanduser(
            os.path.join('~', 'Library', 'Application Support', _SETTINGS_DIR_NAME)
        )
    appdata = os.environ.get('APPDATA')
    if appdata:
        return os.path.join(appdata, _SETTINGS_DIR_NAME)
    return os.path.join(os.path.expanduser('~'), _SETTINGS_DIR_NAME)


def _settings_file():
    return os.path.join(user_settings_dir(), SETTINGS_FILENAME)


def _legacy_settings_file(addin_dir):
    if not addin_dir:
        return None
    return os.path.join(addin_dir, SETTINGS_FILENAME)


def _migrate_legacy_settings(addin_dir):
    """Copy old add-in-folder settings once into the user settings dir."""
    legacy = _legacy_settings_file(addin_dir)
    destination = _settings_file()
    if not legacy or not os.path.isfile(legacy) or os.path.isfile(destination):
        return
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(legacy, destination)
    except OSError:
        pass


def load_settings(addin_dir=None):
    """
    Load persisted settings from the user AppData folder.

    If addin_dir is provided and a legacy in-folder settings file exists, it is
    migrated once into the user folder before reading.
    """
    _migrate_legacy_settings(addin_dir)
    path = _settings_file()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(addin_dir=None, setup_name=None, side_settings=None, flat_settings=None,
                  global_settings=None):
    """
    Merge and persist command settings.

    side_settings / flat_settings are dicts whose keys are written as
    side_<key> / flat_<key> in clamex_settings.json. global_settings keys are
    written unprefixed.

    addin_dir is only used to migrate a legacy in-folder settings file.
    """
    data = load_settings(addin_dir)
    if setup_name is not None:
        data['setup_name'] = setup_name

    for key, value in (global_settings or {}).items():
        if value is not None:
            data[key] = value

    for prefix, bucket in ((settings_prefix('side'), side_settings), (settings_prefix('flat'), flat_settings)):
        if not bucket:
            continue
        for key, value in bucket.items():
            if value is not None:
                data[f'{prefix}{key}'] = value

    path = _settings_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2)
