"""Persist last-used setup and tool choices between command runs."""

import json
import os

SETTINGS_FILENAME = 'clamex_settings.json'


def settings_prefix(mode):
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


def save_settings(
    addin_dir,
    setup_name=None,
    tool_description=None,
    side_settings=None,
    flat_settings=None,
    op_prefix=None,
    flip_feed=None,
    flip_z=None,
    tool_thickness_offset=None,
    drill_holes=None,
    drill_tool_description=None,
    drill_clearance_mm=None,
    positive_direction=None,
    depth_positive_direction=None,
    tool_half_thickness_offset=None,
):
    data = load_settings(addin_dir)
    if setup_name is not None:
        data['setup_name'] = setup_name
    if tool_description is not None:
        data['tool_description'] = tool_description

    if side_settings is None and any(
        value is not None
        for value in (
            op_prefix,
            flip_feed,
            flip_z,
            tool_thickness_offset,
            drill_holes,
            drill_tool_description,
            drill_clearance_mm,
        )
    ):
        side_settings = {
            'op_prefix': op_prefix,
            'flip_feed': flip_feed,
            'flip_z': flip_z,
            'tool_thickness_offset': tool_thickness_offset,
            'drill_holes': drill_holes,
            'drill_tool_description': drill_tool_description,
            'drill_clearance_mm': drill_clearance_mm,
        }

    for prefix, bucket in ((settings_prefix('side'), side_settings), (settings_prefix('flat'), flat_settings)):
        if not bucket:
            continue
        for key, value in bucket.items():
            if value is not None:
                data[f'{prefix}{key}'] = value

    path = _settings_file(addin_dir)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2)
