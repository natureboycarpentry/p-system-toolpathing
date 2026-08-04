"""
TemporaryBRep tool solids for cut preview.

Builds disc/cylinder samples from selected CAM tool dimensions and placement
centerlines. Solids are created in world centimetres for later BaseFeature
insert + Combine Cut. Missing library dims skip the solid (no invented sizes).
"""

import adsk.core
import adsk.fusion

from lib.toolpath_def import feed_point_chain
from lib.units import mm_to_cm, offset_point

# Preview-only drill length into stock when into_mm is not supplied.
_DEFAULT_DRILL_INTO_MM = 5.0


def create_cylinder(center, axis, radius_cm, half_length_cm):
    """Axis-aligned TemporaryBRep cylinder centered on *center*."""
    if radius_cm <= 1e-8 or half_length_cm <= 1e-8:
        return None
    unit = axis.copy()
    unit.normalize()
    p1 = offset_point(center, unit, -half_length_cm)
    p2 = offset_point(center, unit, half_length_cm)
    tmp = adsk.fusion.TemporaryBRepManager.get()
    return tmp.createCylinderOrCone(p1, radius_cm, p2, radius_cm)


def transform_temp_body(body, matrix):
    """Apply a Matrix3D transform to a TemporaryBRep body in place."""
    if not body or not matrix:
        return body
    tmp = adsk.fusion.TemporaryBRepManager.get()
    tmp.transform(body, matrix)
    return body


def side_disc_at_point(center, feed_axis, depth_axis, diameter_mm, thickness_mm):
    """
    Side T-slot disc: short cylinder whose axis is depth (setup WCS +Z).

    Flat faces are parallel to the board top (feed×cross plane); thickness
    is flute length along depth. feed_axis is unused (call-site compat).

    Trace follows the flute tip on the path, so the disc centre is raised by
    half thickness along depth so the tip face lands on the path point.
    """
    del feed_axis  # orientation uses depth only
    radius_cm = mm_to_cm(diameter_mm) * 0.5
    half_thick_cm = mm_to_cm(thickness_mm) * 0.5
    # Tip follows path; raise centre so the tip face sits on the path.
    tip_center = offset_point(center, depth_axis, half_thick_cm)
    return create_cylinder(tip_center, depth_axis, radius_cm, half_thick_cm)


def flat_cutter_at_point(center, depth_axis, diameter_mm, flute_mm):
    """Flat cutter approximation: cylinder along depth centered on the path."""
    radius_cm = mm_to_cm(diameter_mm) * 0.5
    half_flute_cm = mm_to_cm(flute_mm) * 0.5
    return create_cylinder(center, depth_axis, radius_cm, half_flute_cm)


def drill_cylinder_at_point(center, depth_axis, diameter_mm, clearance_mm, into_mm=None):
    """
    Drill preview cylinder along depth.

    Extends *clearance_mm* above the hole point and *into_mm* into the part
    (along −depth, matching path convention where +depth is WCS +Z out of stock).
    """
    into = _DEFAULT_DRILL_INTO_MM if into_mm is None else into_mm
    radius_cm = mm_to_cm(diameter_mm) * 0.5
    unit = depth_axis.copy()
    unit.normalize()
    # Path uses −depth into part; above hole is +depth.
    p_above = offset_point(center, unit, mm_to_cm(clearance_mm))
    p_into = offset_point(center, unit, -mm_to_cm(into))
    tmp = adsk.fusion.TemporaryBRepManager.get()
    return tmp.createCylinderOrCone(p_above, radius_cm, p_into, radius_cm)


def resolve_side_dims(diameter_mm, thickness_mm):
    """Return (dia, thick) or (None, None) when library dims are missing."""
    if not diameter_mm or diameter_mm <= 0 or not thickness_mm or thickness_mm <= 0:
        return None, None
    return diameter_mm, thickness_mm


def resolve_flat_dims(diameter_mm, flute_mm):
    """Return (dia, flute) or (None, None) when library dims are missing."""
    if not diameter_mm or diameter_mm <= 0 or not flute_mm or flute_mm <= 0:
        return None, None
    return diameter_mm, flute_mm


def resolve_drill_dims(diameter_mm):
    """Return diameter or None when the library dim is missing."""
    if not diameter_mm or diameter_mm <= 0:
        return None
    return diameter_mm


def build_side_tool_body(world_points, feed_axis, depth_axis, diameter_mm, thickness_mm):
    """Single side disc at the T-slot cross (feed=0), not the far end of the slot."""
    if not world_points:
        return None
    dia, thick = resolve_side_dims(diameter_mm, thickness_mm)
    if dia is None:
        return None

    # Prefer the FEED-chain index of (feed=0, depth=0) — the T cross centre.
    local = feed_point_chain()
    t_index = 0
    for i, (feed_mm, _y, depth_mm) in enumerate(local):
        if abs(feed_mm) < 1e-6 and abs(depth_mm) < 1e-6:
            t_index = i
            break
    if t_index >= len(world_points):
        t_index = 1 if len(world_points) > 1 else 0

    return side_disc_at_point(
        world_points[t_index], feed_axis, depth_axis, dia, thick
    )


def build_flat_tool_body(world_points, depth_axis, diameter_mm, flute_mm):
    """Single flat cutter at the end of the centerline."""
    if not world_points:
        return None
    dia, flute = resolve_flat_dims(diameter_mm, flute_mm)
    if dia is None:
        return None
    return flat_cutter_at_point(world_points[-1], depth_axis, dia, flute)


def build_drill_tool_body(hole_point, depth_axis, diameter_mm, clearance_mm):
    """Single drill cylinder at the tightening-hole point."""
    dia = resolve_drill_dims(diameter_mm)
    if dia is None:
        return None
    return drill_cylinder_at_point(hole_point, depth_axis, dia, clearance_mm)
