"""Bundle sample Lamello tools into the document tool library.

Tools ship as Fusion-exported JSON under resources/example_tools/tools.json.
Only the active document library is modified — never Hub or local libraries.
"""

from __future__ import annotations

import json
import os

import adsk.cam
import adsk.core

from lib.cam_ops import list_document_tools
from lib.errors import UserFacingError

EXAMPLE_TOOLS_REL = os.path.join('resources', 'example_tools', 'tools.json')

# Preferred dropdown picks after a fresh install (match tools.json descriptions).
SAMPLE_SIDE_DESCRIPTION = 'Lamello Cutter'
SAMPLE_FLAT_DESCRIPTION = 'Lamello Vertical Cutter'
SAMPLE_DRILL_DESCRIPTION = '6mm Lamello Drill'

SAMPLE_PREFERRED_BY_SECTION = {
    'side': SAMPLE_SIDE_DESCRIPTION,
    'flat': SAMPLE_FLAT_DESCRIPTION,
    'drill': SAMPLE_DRILL_DESCRIPTION,
}


def example_tools_path(addin_dir):
    """Absolute path to the bundled sample tools JSON."""
    return os.path.join(addin_dir, EXAMPLE_TOOLS_REL)


def load_example_tool_dicts(addin_dir):
    """Return the list of tool dicts from the bundled library JSON."""
    path = example_tools_path(addin_dir)
    if not os.path.isfile(path):
        raise UserFacingError(
            f'Sample tools file is missing:\n{path}\n'
            'Reinstall the add-in, then try again.'
        )
    try:
        with open(path, encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise UserFacingError(
            f'Sample tools file could not be read:\n{path}\n{exc}'
        ) from exc

    tools = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(tools, list) or not tools:
        raise UserFacingError(
            f'Sample tools file has no tools:\n{path}'
        )
    return tools


def _existing_descriptions(cam):
    return {desc for desc, _tool in list_document_tools(cam)}


def add_example_tools(cam, addin_dir):
    """Add bundled sample tools to the document library.

    Skips tools whose description already exists. Returns (added, skipped).
    """
    if not cam:
        raise UserFacingError(
            'Please switch to the Manufacture workspace with an active CAM document, '
            'then try again.'
        )

    tool_dicts = load_example_tool_dicts(addin_dir)
    existing = _existing_descriptions(cam)
    library = cam.documentToolLibrary
    added = 0
    skipped = 0

    for tool_dict in tool_dicts:
        description = (tool_dict.get('description') or '').strip()
        if not description:
            raise UserFacingError(
                'A sample tool is missing a description and cannot be installed.'
            )
        if description in existing:
            skipped += 1
            continue

        try:
            tool = adsk.cam.Tool.createFromJson(json.dumps(tool_dict))
        except Exception as exc:
            raise UserFacingError(
                f'Could not create sample tool "{description}":\n{exc}'
            ) from exc
        if not tool:
            raise UserFacingError(
                f'Could not create sample tool "{description}".'
            )

        try:
            library.add(tool)
        except Exception as exc:
            raise UserFacingError(
                f'Could not add sample tool "{description}" to the document '
                f'tool library:\n{exc}'
            ) from exc

        existing.add(description)
        added += 1

    return added, skipped


def prompt_add_example_tools_if_empty(cam, addin_dir):
    """If the document library is empty, offer to install sample tools.

    Returns the (possibly updated) tool list from list_document_tools.
    Raises UserFacingError when the user declines or install fails to populate.
    """
    tools = list_document_tools(cam)
    if tools:
        return tools

    ui = adsk.core.Application.get().userInterface
    result = ui.messageBox(
        'No tools found in the document tool library.\n\n'
        'Add the bundled Lamello sample tools '
        '(side cutter, vertical cutter, and drill)?',
        'Lamello P-System',
        adsk.core.MessageBoxButtonTypes.YesNoButtonType,
        adsk.core.MessageBoxIconTypes.QuestionIconType,
    )
    if result != adsk.core.DialogResults.DialogYes:
        raise UserFacingError(
            'No tools found in the document tool library. Add milling tools to '
            'the document library, or re-run and choose Yes to install the '
            'sample tools (also available via Add sample tools on the Setup tab).'
        )

    add_example_tools(cam, addin_dir)
    tools = list_document_tools(cam)
    if not tools:
        raise UserFacingError(
            'Sample tools were not added to the document tool library. '
            'Add milling tools manually, then re-run the add-in.'
        )
    return tools


def format_add_result_message(added, skipped):
    """Short status text after an Add sample tools click."""
    if added and skipped:
        return (
            f'Added {added} sample tool(s) to the document library. '
            f'{skipped} already present (skipped).'
        )
    if added:
        return f'Added {added} sample tool(s) to the document library.'
    if skipped:
        return 'All sample tools are already in the document library.'
    return 'No sample tools were added.'
