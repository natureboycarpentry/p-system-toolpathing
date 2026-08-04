"""
Transform master path points using a placement anchor and reference axes.

Resolves anchor/feed/WCS axes from Fusion selections and maps connector-local
millimetre paths into world-space Point3D chains for sketch creation.
"""

import adsk.core
import adsk.fusion

from lib.toolpath_def import (
    DEFAULT_CUTTER_Z_REFERENCE,
    cutter_z_depth_offset_mm,
    hole_offset_mm,
)
from lib.units import MM_TO_CM, negate_vector


def _depth_offset_mm(cutter_z_reference, half_flute_mm):
    """Resolve the Z0 depth offset from cutter Z reference and half flute (mm)."""
    return cutter_z_depth_offset_mm(
        cutter_z_reference or DEFAULT_CUTTER_Z_REFERENCE,
        half_flute=half_flute_mm,
    )


def _unit_vector(vector):
    copy = vector.copy()
    copy.normalize()
    return copy


def _negate_copy(vector):
    return negate_vector(vector)


def joint_origin_frame(joint_origin):
    """
    Return (origin, xAxis, yAxis, zAxis) for a JointOrigin in assembly space.

    The selection entity should already be an assembly-context proxy when the
    Joint Origin lives inside a sub-component.
    """
    matrix = joint_origin.transform
    return matrix.getAsCoordinateSystem()


def _direction_from_points(start, end, reverse=False):
    direction = adsk.core.Vector3D.create(
        end.x - start.x,
        end.y - start.y,
        end.z - start.z,
    )
    if direction.length <= 1e-6:
        raise RuntimeError('Reference line has zero length.')
    if reverse:
        direction.scaleBy(-1.0)
    return _unit_vector(direction)


def _direction_from_line3d(line, reverse=False):
    return _direction_from_points(line.startPoint, line.endPoint, reverse=reverse)


def _direction_from_linear_edge(edge):
    line = adsk.core.Line3D.cast(edge.geometry)
    if line:
        return _direction_from_line3d(line, reverse=edge.isParamReversed)

    evaluator = edge.evaluator
    success, start_param, end_param = evaluator.getParameterExtents()
    if not success:
        raise RuntimeError('Reference edge must be linear.')
    mid_param = (start_param + end_param) * 0.5
    success, tangent = evaluator.getTangent(mid_param)
    if not success or tangent.length <= 1e-6:
        raise RuntimeError('Reference edge must be linear.')
    if edge.isParamReversed:
        tangent = _negate_copy(tangent)
    return _unit_vector(tangent)


def _direction_from_sketch_line(sketch_line):
    # SketchLine.geometry is sketch-local; worldGeometry is root/assembly space
    # and must be used so feed matches the visible selection on rotated planes.
    line = adsk.core.Line3D.cast(sketch_line.worldGeometry)
    if line:
        return _direction_from_line3d(line)

    start = sketch_line.startSketchPoint.worldGeometry
    end = sketch_line.endSketchPoint.worldGeometry
    return _direction_from_points(start, end)


def _direction_from_infinite_geometry(geometry):
    infinite = adsk.core.InfiniteLine3D.cast(geometry)
    if infinite:
        return _unit_vector(infinite.direction)

    line = adsk.core.Line3D.cast(geometry)
    if line:
        return _direction_from_line3d(line)

    return None


def reference_axis_direction(entity):
    """
    Return a unit direction vector from a user-selected linear reference.

    Supports linear edges, sketch lines, construction lines, and construction axes.
    """
    if not entity:
        raise RuntimeError('Select a reference axis.')

    edge = adsk.fusion.BRepEdge.cast(entity)
    if edge:
        return _direction_from_linear_edge(edge)

    sketch_line = adsk.fusion.SketchLine.cast(entity)
    if sketch_line:
        return _direction_from_sketch_line(sketch_line)

    for cast_type in (
        adsk.fusion.ConstructionLine,
        adsk.fusion.ConstructionAxis,
    ):
        construction = cast_type.cast(entity)
        if not construction:
            continue
        direction = _direction_from_infinite_geometry(construction.geometry)
        if direction:
            return direction

    raise RuntimeError(
        'Select a linear edge, sketch line, construction line, or construction axis '
        'as the reference axis.'
    )


def placement_anchor_point(entity):
    """
    Return the anchor position in assembly/world space for a supported point entity.

    Supports Joint Origins, sketch points, B-Rep vertices, and construction points.
    """
    if not entity:
        raise RuntimeError('Select an anchor point.')

    if 'JointOrigin' in entity.objectType:
        origin, _, _, _ = joint_origin_frame(entity)
        return origin

    sketch_point = adsk.fusion.SketchPoint.cast(entity)
    if sketch_point:
        return sketch_point.worldGeometry

    vertex = adsk.fusion.BRepVertex.cast(entity)
    if vertex:
        return vertex.geometry

    construction_point = adsk.fusion.ConstructionPoint.cast(entity)
    if construction_point:
        return construction_point.geometry

    raise RuntimeError(
        'Select a Joint Origin, sketch point, vertex, or construction point as the anchor.'
    )


def _coord_suffix_mm(point):
    """Short coordinate suffix for stable, unique placement naming (Fusion uses cm)."""
    return f' ({point.x * 10:.1f}, {point.y * 10:.1f}, {point.z * 10:.1f})'


def placement_display_name(entity):
    """Stable display name for idempotent sketch/op naming."""
    if 'JointOrigin' in entity.objectType:
        try:
            return entity.name
        except Exception:
            return 'Joint Origin'

    try:
        point = placement_anchor_point(entity)
    except Exception:
        point = None

    sketch_point = adsk.fusion.SketchPoint.cast(entity)
    if sketch_point:
        try:
            base = sketch_point.parentSketch.name
        except Exception:
            base = 'Sketch Point'
        return base + (_coord_suffix_mm(point) if point else '')

    vertex = adsk.fusion.BRepVertex.cast(entity)
    if vertex:
        try:
            base = f'{vertex.body.name} – Vertex'
        except Exception:
            base = 'Vertex'
        return base + (_coord_suffix_mm(point) if point else '')

    construction_point = adsk.fusion.ConstructionPoint.cast(entity)
    if construction_point:
        try:
            base = construction_point.name or 'Construction Point'
        except Exception:
            base = 'Construction Point'
        return base + (_coord_suffix_mm(point) if point else '')

    return 'Placement'


def resolve_placement_axes(anchor_entity, feed_entity, setup_z_axis, flip_feed, flip_z):
    """
    Resolve feed/depth axes with depth Z0 at the anchor point.

    Depth always follows the setup WCS +Z axis; flip_z reverses it.
    """
    anchor_origin = placement_anchor_point(anchor_entity)
    feed_axis = reference_axis_direction(feed_entity)
    depth_axis = setup_z_axis.copy()
    depth_axis.normalize()

    if flip_feed:
        feed_axis = _negate_copy(feed_axis)
    if flip_z:
        depth_axis = _negate_copy(depth_axis)

    return anchor_origin, feed_axis, depth_axis


def transform_feed_chain(
    anchor_entity,
    local_points,
    feed_entity,
    setup_z_axis,
    flip_feed,
    flip_z,
    cross_offset_mm,
    cutter_z_reference=DEFAULT_CUTTER_Z_REFERENCE,
    half_flute_mm=None,
):
    """Transform cross-local (feed, 0, depth) points to world Point3D objects.

    cross_offset_mm is the derived anchor→cross distance along feed
    ((tool_diameter/2) − cut_depth). cutter_z_reference shifts depth by
    +½ / 0 / −½ side-cutter flute length (Flute Top / Centre / Bottom).
    """
    if cross_offset_mm is None:
        raise ValueError('cross_offset_mm is required')

    anchor_origin, feed_axis, depth_axis = resolve_placement_axes(
        anchor_entity,
        feed_entity,
        setup_z_axis,
        flip_feed,
        flip_z,
    )

    cross_offset_cm = cross_offset_mm * MM_TO_CM
    depth_z0_offset_mm = _depth_offset_mm(cutter_z_reference, half_flute_mm)
    world_points = []
    for feed_mm, _cross, depth_mm in local_points:
        feed_cm = cross_offset_cm + (feed_mm * MM_TO_CM)
        depth_cm = (depth_mm + depth_z0_offset_mm) * MM_TO_CM
        world_points.append(
            adsk.core.Point3D.create(
                anchor_origin.x + feed_cm * feed_axis.x + (-depth_cm) * depth_axis.x,
                anchor_origin.y + feed_cm * feed_axis.y + (-depth_cm) * depth_axis.y,
                anchor_origin.z + feed_cm * feed_axis.z + (-depth_cm) * depth_axis.z,
            )
        )
    return world_points


def transform_flat_chain(
    anchor_entity,
    local_points,
    feed_entity,
    setup_z_axis,
    flip_feed,
    flip_z=False,
):
    """Transform flat (feed, depth) points to world Point3D objects."""
    anchor_origin, feed_axis, depth_axis = resolve_placement_axes(
        anchor_entity,
        feed_entity,
        setup_z_axis,
        flip_feed,
        flip_z,
    )

    world_points = []
    for feed_mm, depth_mm in local_points:
        feed_cm = feed_mm * MM_TO_CM
        depth_cm = depth_mm * MM_TO_CM
        world_points.append(
            adsk.core.Point3D.create(
                anchor_origin.x + feed_cm * feed_axis.x + (-depth_cm) * depth_axis.x,
                anchor_origin.y + feed_cm * feed_axis.y + (-depth_cm) * depth_axis.y,
                anchor_origin.z + feed_cm * feed_axis.z + (-depth_cm) * depth_axis.z,
            )
        )
    return world_points


def drill_hole_world_point(
    anchor_entity,
    feed_entity,
    setup_z_axis,
    flip_feed,
    flip_z,
    connector_type=None,
):
    """Return the tightening-hole centre at anchor − feed × connector hole offset."""
    anchor_origin, feed_axis, _depth_axis = resolve_placement_axes(
        anchor_entity,
        feed_entity,
        setup_z_axis,
        flip_feed,
        flip_z,
    )
    offset_cm = hole_offset_mm(connector_type) * MM_TO_CM
    return adsk.core.Point3D.create(
        anchor_origin.x - offset_cm * feed_axis.x,
        anchor_origin.y - offset_cm * feed_axis.y,
        anchor_origin.z - offset_cm * feed_axis.z,
    )
