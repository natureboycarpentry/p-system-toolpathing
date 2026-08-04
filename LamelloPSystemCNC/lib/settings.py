"""Persist last-used setup and tool choices between command runs."""

import json
import os

SETTINGS_FILENAME = 'clamex_settings.json'


def settings_prefix(mode):
    """Return the persisted-settings key prefix for a tab mode ('side' or 'flat')."""
    return f'{mode}_'


def _settings_file(addin_dir):
    return os.path.join(addin_dir, SETTINGS_FILENAME)


def load_settings(addin_dir):
    path = _settings_file(addin_dir)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(addin_dir, setup_name=None, side_settings=None, flat_settings=None,
                  global_settings=None):
    """
    Merge and persist command settings.

    side_settings / flat_settings are dicts whose keys are written as
    side_<key> / flat_<key> in clamex_settings.json. global_settings keys are
    written unprefixed.
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

    path = _settings_file(addin_dir)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2)
