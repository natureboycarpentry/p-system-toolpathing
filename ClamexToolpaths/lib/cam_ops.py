"""Create Trace CAM operations, assign geometry, and generate toolpaths."""

import adsk.cam
import adsk.core


def operation_display_name(jo_name, prefix='Clamex'):
    return f'{prefix} – {jo_name}'


def _cad_contour_parameter(parameters):
    """Locate the CadContours2dParameterValue on a trace operation input or operation."""
    for index in range(parameters.count):
        param = parameters.item(index)
        try:
            value = param.value
            if value and value.classType() == adsk.cam.CadContours2dParameterValue.classType():
                return value
        except Exception:
            continue

    for name in ('curves', 'contours', 'machiningBoundarySel'):
        param = parameters.itemByName(name)
        if param:
            try:
                return param.value
            except Exception:
                continue
    return None


def _set_trace_defaults(op_input):
    """Apply sensible Trace defaults when parameters are available."""
    defaults = [
        ('toolCenterOnBoundary', True),
        ('doMultipleDepths', False),
    ]
    for name, value in defaults:
        param = op_input.parameters.itemByName(name)
        if not param:
            continue
        try:
            param.value.value = value
        except Exception:
            pass

    # Prefer following the 3D sketch path so local Z wiggle is honoured.
    for name in ('traceMode', 'toolpathType', 'geometryType'):
        param = op_input.parameters.itemByName(name)
        if not param:
            continue
        try:
            param.value.value = '3d'
        except Exception:
            try:
                param.value.value = 'follow3d'
            except Exception:
                pass


def _assign_open_chain(contour_param, geometry_entities):
    chains = contour_param.getCurveSelections()
    chains.clear()
    chain = chains.createNewChainSelection()
    chain.isOpen = True
    chain.inputGeometry = list(geometry_entities)
    contour_param.applyCurveSelections(chains)


def remove_existing_operation(setup, display_name):
    """Delete a prior Clamex operation with the same display name (idempotent regenerate)."""
    for index in range(setup.operations.count - 1, -1, -1):
        op = setup.operations.item(index)
        if op.name == display_name:
            op.deleteMe()


def _set_parameter_expression(parameters, name, expression):
    param = parameters.itemByName(name)
    if not param:
        return False
    try:
        param.expression = expression
        return True
    except Exception:
        pass
    try:
        param.value.value = expression
        return True
    except Exception:
        return False


def _set_drill_hole_mode(parameters):
    """Switch drill geometry to sketch/world point selection."""
    param = parameters.itemByName('holeMode')
    if not param:
        return False
    for expression in ("'selection-points'", "'selection_points'"):
        try:
            param.expression = expression
            return True
        except Exception:
            pass
    try:
        param.value.value = 'selection-points'
        return True
    except Exception:
        return False


def _assign_drill_points(parameters, point_entities):
    """Assign sketch points to a drill operation (call after holeMode is set)."""
    entity_list = list(point_entities)
    collection = adsk.core.ObjectCollection.create()
    for entity in entity_list:
        collection.add(entity)

    for param_name in ('holePoints', 'selection-points', 'points', 'holeCenters'):
        param = parameters.itemByName(param_name)
        if not param:
            continue
        try:
            cad_value = param.value
            if cad_value and hasattr(cad_value, '_set_value'):
                try:
                    cad_value._set_value(collection)
                    return True
                except Exception:
                    pass
            if cad_value and hasattr(cad_value, 'value'):
                try:
                    cad_value.value = entity_list
                    return True
                except Exception:
                    pass
        except Exception:
            continue

    for index in range(parameters.count):
        param = parameters.item(index)
        try:
            param_id = param.id if hasattr(param, 'id') else ''
            if 'point' not in param_id.lower():
                continue
            cad_value = param.value
            if cad_value and hasattr(cad_value, '_set_value'):
                try:
                    cad_value._set_value(collection)
                    return True
                except Exception:
                    pass
            if cad_value and hasattr(cad_value, 'value'):
                try:
                    cad_value.value = entity_list
                    return True
                except Exception:
                    pass
        except Exception:
            continue
    return False


def _drill_parameter_names(parameters):
    names = []
    for index in range(parameters.count):
        param = parameters.item(index)
        try:
            names.append(param.id)
        except Exception:
            pass
    return names


def _set_drill_depths(parameters, clearance_mm):
    """Configure retract above anchor and bottom at the selected point."""
    clearance_expr = f'{clearance_mm} mm'
    zero_expr = '0 mm'

    for name, expr in (
        ('topHeight_offset', clearance_expr),
        ('topHeight_value', clearance_expr),
        ('retractHeight', clearance_expr),
        ('retractHeight_offset', clearance_expr),
        ('bottomHeight_offset', zero_expr),
        ('bottomHeight_value', zero_expr),
        ('holeDepth', zero_expr),
    ):
        _set_parameter_expression(parameters, name, expr)

    for name, expr in (
        ('topHeight_mode', "'fromSelectedPoint'"),
        ('bottomHeight_mode', "'toSelectedPoint'"),
        ('fromMode', "'selectedPoint'"),
        ('toMode', "'selectedPoint'"),
    ):
        _set_parameter_expression(parameters, name, expr)


def create_drill_operation(
    setup,
    cam,
    display_name,
    tool,
    point_entities,
    clearance_mm,
    tool_preset=None,
):
    """
    Create a Drilling operation at sketch point(s) with retract clearance above anchor.

    Returns the created Operation.
    """
    remove_existing_operation(setup, display_name)

    op_input = setup.operations.createInput('drill')
    op_input.displayName = display_name
    op_input.tool = tool
    if tool_preset:
        try:
            op_input.toolPreset = tool_preset
        except Exception:
            pass

    # holePoints only exists after add(); holeMode must be set before assigning points.
    op = setup.operations.add(op_input)
    live_params = op.parameters

    if not _set_drill_hole_mode(live_params):
        raise RuntimeError('Drill operation has no holeMode parameter.')

    if not _assign_drill_points(live_params, point_entities):
        available = ', '.join(_drill_parameter_names(live_params)[:30])
        raise RuntimeError(
            'Drill operation has no point-selection parameter.'
            f' Available parameters: {available}'
        )

    _set_drill_depths(live_params, clearance_mm)

    cam.generateToolpath(op)
    return op


def create_trace_operation(setup, cam, display_name, tool, geometry_entities, tool_preset=None):
    """
    Create a Trace operation, assign tool + sketch geometry, and generate the toolpath.

    Returns the created Operation.
    """
    remove_existing_operation(setup, display_name)

    op_input = setup.operations.createInput('trace')
    op_input.displayName = display_name
    op_input.tool = tool
    if tool_preset:
        try:
            op_input.toolPreset = tool_preset
        except Exception:
            pass

    _set_trace_defaults(op_input)

    contour_param = _cad_contour_parameter(op_input.parameters)
    if not contour_param:
        raise RuntimeError('Trace operation has no contour/curve parameter.')

    _assign_open_chain(contour_param, geometry_entities)
    op = setup.operations.add(op_input)

    # Re-apply geometry on the live operation in case add() resets selections.
    live_contour = _cad_contour_parameter(op.parameters)
    if live_contour:
        _assign_open_chain(live_contour, geometry_entities)

    cam.generateToolpath(op)
    return op


def list_milling_setups(cam):
    """Return all milling setups in the document."""
    setups = []
    for index in range(cam.setups.count):
        setup = cam.setups.item(index)
        try:
            if setup.classType() == adsk.cam.Setup.classType():
                setups.append(setup)
        except Exception:
            setups.append(setup)
    return setups


def find_setup_by_name(cam, setup_name):
    for setup in list_milling_setups(cam):
        if setup.name == setup_name:
            return setup
    return None


def setup_wcs_z_axis(setup):
    """Return the setup WCS +Z axis as a unit vector in model space."""
    if not setup:
        raise RuntimeError('Select a Setup.')
    _origin, _x_axis, _y_axis, z_axis = setup.workCoordinateSystem.getAsCoordinateSystem()
    copy = z_axis.copy()
    copy.normalize()
    return copy


def tool_description(tool):
    param = tool.parameters.itemByName('tool_description')
    if param:
        try:
            return param.value.value
        except Exception:
            pass
    return 'Tool'


def list_document_tools(cam):
    """Return (description, Tool) pairs from the document tool library."""
    tools = []
    library = cam.documentToolLibrary
    for index in range(library.count):
        # documentToolLibrary.item() returns a Tool directly (not a wrapper).
        tool = library.item(index)
        tools.append((tool_description(tool), tool))
    return tools


def find_tool_by_description(cam, description):
    for desc, tool in list_document_tools(cam):
        if desc == description:
            return tool
    return None


def default_tool_preset(tool):
    try:
        presets = tool.presets
        if presets.count > 0:
            return presets.item(0)
    except Exception:
        pass
    return None
