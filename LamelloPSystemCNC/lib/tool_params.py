"""
Editable tool feed/speed parameters for the Setup tab.

Each section (side / flat / drill) pairs a tool dropdown with a group of
expression fields for the selected tool. Reads prefer the tool's default
preset and fall back to the tool itself; edits are written back through the
document tool library so every operation using the tool picks them up.

Displayed values are evaluated numbers with units (never raw CAM formulas
like tool_feedPlunge). Edits are written as unit-bearing expressions.

Important: most tool-library CAMParameter.value values are already in the
parameter's UI unit (rpm, mm/min). Length chip-load values use Fusion
database length (cm). Surface speed is special: Fusion stores it as mm/min
(π × D_mm × rpm) even though the Fusion UI shows m/min or ft/min. Do not
run rpm/feed rates through UnitsManager.formatInternalValue — that
mis-scales them badly.
"""

import re

import adsk.cam
import adsk.core
import adsk.fusion

from lib.cam_ops import default_tool_preset, find_tool_by_description
from lib.ui_helpers import read_dropdown, select_dropdown

SECTION_SIDE = 'side'
SECTION_FLAT = 'flat'
SECTION_DRILL = 'drill'

# (parameter name, label, tooltip, editable)
PARAM_SPECS = (
    (
        'tool_spindleSpeed',
        'Spindle speed',
        'Spindle RPM for the selected tool. Edits are saved to the document tool library.',
        True,
    ),
    (
        'tool_surfaceSpeed',
        'Surface speed',
        'Cutting surface speed derived from spindle speed and tool diameter (read-only).',
        False,
    ),
    (
        'tool_feedCutting',
        'Cutting feedrate',
        'Primary cutting feed for the selected tool. Edits are saved to the document tool library.',
        True,
    ),
    (
        'tool_feedPlunge',
        'Plunge feedrate',
        'Feed used when plunging into material.',
        True,
    ),
    (
        'tool_feedRamp',
        'Ramp feedrate',
        'Feed used when ramping into material.',
        True,
    ),
    (
        'tool_feedPerTooth',
        'Feed per tooth',
        'Chip load per tooth; may drive or reflect the cutting feed depending on tool data.',
        True,
    ),
)

_METRIC_UNITS = {
    'tool_spindleSpeed': 'rpm',
    'tool_surfaceSpeed': 'm/min',
    'tool_feedCutting': 'mm/min',
    'tool_feedPlunge': 'mm/min',
    'tool_feedRamp': 'mm/min',
    'tool_feedPerTooth': 'mm',
}

_IMPERIAL_UNITS = {
    'tool_spindleSpeed': 'rpm',
    'tool_surfaceSpeed': 'ft/min',
    'tool_feedCutting': 'in/min',
    'tool_feedPlunge': 'in/min',
    'tool_feedRamp': 'in/min',
    'tool_feedPerTooth': 'in',
}

# Length params: CAM value is in database cm and needs conversion.
_LENGTH_PARAMS = frozenset({'tool_feedPerTooth'})

# Surface speed: CAM value is mm/min; display as m/min or ft/min.
_SURFACE_SPEED_PARAM = 'tool_surfaceSpeed'

_UNIT_SUFFIX_RE = re.compile(
    r'\s*(rpm|m\s*/\s*min|ft\s*/\s*min|mm\s*/\s*min|in\s*/\s*min|mm|in)\s*$',
    re.IGNORECASE,
)
_SIMPLE_NUMBER_RE = re.compile(r'^[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?$')


def _units_manager():
    """Return a UnitsManager from the design product when available."""
    app = adsk.core.Application.get()
    try:
        product = app.activeDocument.products.itemByProductType('DesignProductType')
        design = adsk.fusion.Design.cast(product)
        if design:
            return design.unitsManager
    except Exception:
        pass
    try:
        return app.activeProduct.unitsManager
    except Exception:
        return None


def _is_imperial(units_mgr):
    if not units_mgr:
        return False
    try:
        length_unit = (units_mgr.defaultLengthUnits or '').lower()
    except Exception:
        return False
    return length_unit in ('in', 'inch', 'ft', 'foot', 'yd', 'yard')


def _compact_units(units_mgr=None):
    if units_mgr is None:
        units_mgr = _units_manager()
    return _IMPERIAL_UNITS if _is_imperial(units_mgr) else _METRIC_UNITS


def _tool_param(tool, name):
    """Return the named CAMParameter from the tool's default preset or the tool itself."""
    preset = default_tool_preset(tool)
    for owner in (preset, tool):
        if not owner:
            continue
        try:
            param = owner.parameters.itemByName(name)
        except Exception:
            param = None
        if param:
            return param
    return None


def _format_number(value):
    """Format a float without scientific notation."""
    value = float(value)
    abs_value = abs(value)
    if abs_value >= 100:
        text = f'{value:.0f}'
    elif abs_value >= 10:
        text = f'{value:.2f}'
    elif abs_value >= 1:
        text = f'{value:.3f}'
    else:
        text = f'{value:.6f}'
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text


def _literal_from_expression(param):
    """If expression is a plain number (optional unit), return that float; else None."""
    try:
        expression = (param.expression or '').strip()
    except Exception:
        return None
    if not expression:
        return None
    cleaned = _UNIT_SUFFIX_RE.sub('', expression).strip().replace(',', '')
    if not _SIMPLE_NUMBER_RE.match(cleaned):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _convert_surface_speed(raw_mm_per_min, compact, units_mgr):
    """Convert Fusion's mm/min surface-speed value to the display unit."""
    if units_mgr and compact:
        try:
            return float(units_mgr.convert(raw_mm_per_min, 'mm/min', compact))
        except Exception:
            pass
    if compact == 'm/min':
        return raw_mm_per_min / 1000.0
    if compact == 'ft/min':
        return raw_mm_per_min / 304.8
    return raw_mm_per_min


def _evaluated_display_number(param, param_name, compact, units_mgr):
    """Return the number to show for this param in `compact` units."""
    # Always use the evaluated API value for surface speed — literals may be
    # stored in mm/min without a unit suffix, and the field is read-only.
    if param_name == _SURFACE_SPEED_PARAM:
        try:
            raw = float(param.value.value)
        except Exception:
            return None
        return _convert_surface_speed(raw, compact, units_mgr)

    literal = _literal_from_expression(param)
    if literal is not None:
        return literal

    try:
        raw = float(param.value.value)
    except Exception:
        return None

    # Length chip-load values are stored in database cm.
    if param_name in _LENGTH_PARAMS:
        if units_mgr:
            try:
                return float(units_mgr.convert(raw, 'cm', compact))
            except Exception:
                pass
        if compact == 'mm':
            return raw * 10.0
        if compact == 'in':
            return raw / 2.54
        return raw

    # rpm / feed rates: already in the UI unit.
    return raw


def _format_param_display(param, param_name, units_mgr=None, compact_units=None):
    """Return an evaluated display string with units, never a CAM formula."""
    if units_mgr is None:
        units_mgr = _units_manager()
    if compact_units is None:
        compact_units = _compact_units(units_mgr)

    compact = compact_units.get(param_name, '')
    number = _evaluated_display_number(param, param_name, compact, units_mgr)
    if number is None:
        return ''
    text = _format_number(number)
    return f'{text} {compact}'.strip() if compact else text


def _parse_user_value(text):
    """Strip a unit suffix and return a float, or None if unparseable."""
    text = (text or '').strip()
    if not text:
        return None
    text = _UNIT_SUFFIX_RE.sub('', text).strip().replace(',', '')
    if not _SIMPLE_NUMBER_RE.match(text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _push_tool_to_library(cam, tool):
    """Persist edited tool parameters so operations using the tool pick them up."""
    library = cam.documentToolLibrary
    try:
        library.update(tool, True)
        return
    except Exception:
        pass
    try:
        library.update(tool)
    except Exception:
        pass


class ToolParamsController:
    """Owns the three tool dropdown + parameter-group sections on the Setup tab."""

    def __init__(self):
        self._syncing = False
        self._sections = {}

    @staticmethod
    def dropdown_id(section):
        return f'{section}ToolSelect'

    @staticmethod
    def group_id(section):
        return f'{section}ToolParamsGroup'

    @staticmethod
    def field_id(section, param_name):
        return f'{section}ToolParam_{param_name}'

    def build_section(self, parent_inputs, section, dropdown_label, group_label,
                      tools, default_description, tooltip=''):
        """Create the tool dropdown and its parameter group. Populate fields afterwards
        with refresh_fields()."""
        dropdown = parent_inputs.addDropDownCommandInput(
            self.dropdown_id(section),
            dropdown_label,
            adsk.core.DropDownStyles.TextListDropDownStyle,
        )
        if tooltip:
            dropdown.tooltip = tooltip
        for description, _tool in tools:
            dropdown.listItems.add(description, False, '')
        select_dropdown(dropdown, default_description)

        # Keep labels short — units live in the value string to avoid truncation.
        group = parent_inputs.addGroupCommandInput(self.group_id(section), group_label)
        group.isExpanded = False
        for param_name, label, param_tooltip, editable in PARAM_SPECS:
            field = group.children.addStringValueInput(
                self.field_id(section, param_name),
                label,
                '',
            )
            field.tooltip = param_tooltip
            if not editable:
                field.isReadOnly = True

        self._sections[section] = {
            'dropdown': self.dropdown_id(section),
            'group': self.group_id(section),
        }
        return dropdown, group

    def selected_description(self, inputs, section):
        dropdown = adsk.core.DropDownCommandInput.cast(
            inputs.itemById(self.dropdown_id(section))
        )
        return read_dropdown(dropdown)

    def refresh_fields(self, inputs, cam, section):
        """Reload the parameter fields from the currently selected tool."""
        tool = find_tool_by_description(cam, self.selected_description(inputs, section))
        units_mgr = _units_manager()
        compact = _compact_units(units_mgr)
        self._syncing = True
        try:
            for param_name, _label, _tooltip, _editable in PARAM_SPECS:
                field = adsk.core.StringValueCommandInput.cast(
                    inputs.itemById(self.field_id(section, param_name))
                )
                if not field:
                    continue
                param = _tool_param(tool, param_name) if tool else None
                if param:
                    field.value = _format_param_display(param, param_name, units_mgr, compact)
                    field.isVisible = True
                else:
                    field.value = ''
                    field.isVisible = False
        finally:
            self._syncing = False

    def refresh_all(self, inputs, cam):
        for section in self._sections:
            self.refresh_fields(inputs, cam, section)

    def refresh_tool_lists(self, inputs, tools, preferred_by_section=None):
        """Rebuild Edge/Face/Drill dropdown items from the document library.

        Keeps the current selection when it still exists. Otherwise prefers
        preferred_by_section[section] when present in the new list, else the
        first item.
        """
        preferred_by_section = preferred_by_section or {}
        self._syncing = True
        try:
            for section in self._sections:
                dropdown = adsk.core.DropDownCommandInput.cast(
                    inputs.itemById(self.dropdown_id(section))
                )
                if not dropdown:
                    continue
                previous = read_dropdown(dropdown)
                dropdown.listItems.clear()
                for description, _tool in tools:
                    dropdown.listItems.add(description, False, '')
                preferred = preferred_by_section.get(section)
                descriptions = {desc for desc, _tool in tools}
                if previous and previous in descriptions:
                    select_dropdown(dropdown, previous)
                elif preferred and preferred in descriptions:
                    select_dropdown(dropdown, preferred)
                else:
                    select_dropdown(dropdown, None)
        finally:
            self._syncing = False

    def _apply_field_edit(self, changed_input, inputs, cam, section, param_name):
        tool = find_tool_by_description(cam, self.selected_description(inputs, section))
        if not tool:
            return
        param = _tool_param(tool, param_name)
        if not param:
            return

        compact = _compact_units().get(param_name, '')
        number = _parse_user_value(changed_input.value)
        if number is None:
            self.refresh_fields(inputs, cam, section)
            return

        applied = False
        expression = f'{number} {compact}'.strip() if compact else str(number)
        try:
            param.expression = expression
            applied = True
        except Exception:
            pass

        if not applied:
            try:
                # Length params need database cm; others take the UI-unit number.
                if param_name in _LENGTH_PARAMS:
                    units_mgr = _units_manager()
                    if units_mgr and compact:
                        param.value.value = units_mgr.convert(number, compact, 'cm')
                    elif compact == 'mm':
                        param.value.value = number / 10.0
                    else:
                        param.value.value = number
                else:
                    param.value.value = number
                applied = True
            except Exception:
                pass

        if applied:
            _push_tool_to_library(cam, tool)
        self.refresh_fields(inputs, cam, section)

    def handle_input_changed(self, changed_input, inputs, cam):
        """Route dropdown/field changes. Returns True when this controller handled the input."""
        if self._syncing:
            return True

        input_id = changed_input.id
        for section in self._sections:
            if input_id == self.dropdown_id(section):
                self.refresh_fields(inputs, cam, section)
                return True
            prefix = f'{section}ToolParam_'
            if input_id.startswith(prefix):
                self._apply_field_edit(
                    changed_input, inputs, cam, section, input_id[len(prefix):]
                )
                return True
        return False

    def owns_input(self, input_id):
        for section in self._sections:
            if input_id == self.dropdown_id(section) or input_id.startswith(f'{section}ToolParam_'):
                return True
        return False
