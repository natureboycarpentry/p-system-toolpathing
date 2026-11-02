"""
Pure-Python joint geometry (no Fusion imports, unit-testable offline).

Vectors and points are 3-tuples in millimetres. A joint is two planar faces
that touch face to face: the *edge face* (end of the panel that gets the Edge
T-slot) and the *mate face* (face of the panel that gets the Face cavity).

Frame conventions for a joint:
- n  outward normal of the edge face (points from the edge panel into the mate
     panel). Edge feed follows n: the side cutter approaches from outside, with
     its centre (R - cut depth) beyond the edge face.
- u  joint line direction (along the longest straight edge of the edge face).
- t  across the edge panel's thickness (n x u).
- Connectors sit on the contact plane, centred in the edge panel's thickness.
"""

import math

DEFAULT_END_OFFSET_MM = 100.0
DEFAULT_CONNECTOR_COUNT = 2
MAX_CONNECTOR_COUNT = 20

# Faces closer than this along the normal count as touching.
CONTACT_TOLERANCE_MM = 0.5
# |cos| thresholds.
FACING_TOLERANCE = 0.999   # edge and mate normals must be anti-parallel
ALIGNED_TOLERANCE = 0.99   # "parallel to setup Z" for orientation checks

# Nominal edge-cutter diameter for Design-workspace preview only, used when no
# CAM tool diameter is readable. Generation always uses the library tool.
NOMINAL_EDGE_CUTTER_DIAMETER_MM = 100.4

ORIENT_UP = 'up'
ORIENT_DOWN = 'down'
ORIENT_TILTED = 'tilted'


class JointGeometryError(ValueError):
    """The selected faces cannot form a joint (message is user-facing)."""


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def length(a):
    return math.sqrt(dot(a, a))


def distance(a, b):
    return length(sub(a, b))


def normalize(a):
    size = length(a)
    if size <= 1e-12:
        raise JointGeometryError('Zero-length direction.')
    return scale(a, 1.0 / size)


def connector_positions(joint_length_mm, end_offset_mm, count):
    """Positions along [0, joint_length] for *count* connectors.

    The first and last connector sit *end_offset_mm* from each end; the rest are
    evenly spaced between. Returns (positions, warning_or_None).
    """
    if joint_length_mm <= 1e-6:
        raise JointGeometryError('The joint has zero length.')
    count = max(1, int(count))
    end_offset_mm = max(0.0, float(end_offset_mm))
    centre = joint_length_mm * 0.5
    if count == 1:
        return [centre], None

    start = end_offset_mm
    end = joint_length_mm - end_offset_mm
    if end - start < 1e-6:
        return [centre], (
            f'Joint is only {joint_length_mm:.0f} mm long, too short for '
            f'{end_offset_mm:.0f} mm end offsets, so one centred connector is used.'
        )
    step = (end - start) / (count - 1)
    return [start + index * step for index in range(count)], None


def joint_frame(edge_normal, edge_vertices, edge_line_dir, mate_normal, mate_vertices):
    """Compute the joint frame from two touching planar faces (world mm).

    edge_normal / mate_normal: outward unit normals of each face.
    edge_vertices / mate_vertices: face vertex positions.
    edge_line_dir: direction of the longest straight edge of the edge face.

    Returns a dict with u, t, n, mate_normal, start (s=0 point on the
    mid-thickness line), length_mm, thickness_mm and warnings.
    """
    if not edge_vertices or not mate_vertices:
        raise JointGeometryError('Both faces need corners (straight-edged panels).')

    n = normalize(edge_normal)
    m = normalize(mate_normal)
    if dot(n, m) > -FACING_TOLERANCE:
        raise JointGeometryError(
            'The two faces are not facing each other. Pick the end face of one panel '
            'and the face of the other panel it sits against.'
        )

    u = sub(edge_line_dir, scale(n, dot(edge_line_dir, n)))
    u = normalize(u)
    t = normalize(cross(n, u))

    origin = edge_vertices[0]
    gap = abs(dot(sub(mate_vertices[0], origin), n))
    if gap > CONTACT_TOLERANCE_MM:
        raise JointGeometryError(f'The faces are {gap:.1f} mm apart. They must touch.')

    edge_s = [dot(sub(v, origin), u) for v in edge_vertices]
    edge_t = [dot(sub(v, origin), t) for v in edge_vertices]
    mate_s = [dot(sub(v, origin), u) for v in mate_vertices]
    mate_t = [dot(sub(v, origin), t) for v in mate_vertices]

    s0 = max(min(edge_s), min(mate_s))
    s1 = min(max(edge_s), max(mate_s))
    if s1 - s0 <= 1e-3:
        raise JointGeometryError('The faces do not overlap along the joint.')

    t0, t1 = min(edge_t), max(edge_t)
    warnings = []
    if t0 < min(mate_t) - CONTACT_TOLERANCE_MM or t1 > max(mate_t) + CONTACT_TOLERANCE_MM:
        warnings.append('The edge panel overhangs the mating face across its thickness.')

    t_mid = 0.5 * (t0 + t1)
    start = add(add(origin, scale(u, s0)), scale(t, t_mid))
    return {
        'u': u,
        't': t,
        'n': n,
        'mate_normal': m,
        'start': start,
        'length_mm': s1 - s0,
        'thickness_mm': t1 - t0,
        'warnings': warnings,
    }


def connector_points(frame, positions):
    """World points (mm) of connectors at *positions* along the joint line."""
    return [add(frame['start'], scale(frame['u'], s)) for s in positions]


def orientation_against(vector, z_axis):
    """Classify a direction against setup +Z: up / down / tilted."""
    d = dot(normalize(vector), normalize(z_axis))
    if d > ALIGNED_TOLERANCE:
        return ORIENT_UP
    if d < -ALIGNED_TOLERANCE:
        return ORIENT_DOWN
    return ORIENT_TILTED


def face_cavity_outline(point, u, mate_normal, profile):
    """Face-cavity outline in the mate panel from profile (feed_mm, depth_mm <= 0).

    mate_normal points out of the mate panel, so negative depth goes into it.
    """
    return [add(add(point, scale(u, f)), scale(mate_normal, d)) for f, d in profile]


def edge_cut_outline(point, u, n, cutter_diameter_mm, cut_depth_mm, segments=24):
    """Arc the side-cutter disc leaves in the edge panel (plane spanned by u, n).

    The disc centre sits (R - depth) outside the edge face along n, so the arc
    reaches *cut_depth_mm* into the edge panel at the connector point.
    """
    radius = 0.5 * cutter_diameter_mm
    if radius <= cut_depth_mm:
        raise JointGeometryError('Edge cutter is too small for the connector cut depth.')
    centre = add(point, scale(n, radius - cut_depth_mm))
    half_angle = math.acos((radius - cut_depth_mm) / radius)
    outline = []
    for k in range(segments + 1):
        a = -half_angle + 2.0 * half_angle * k / segments
        direction = add(scale(n, -math.cos(a)), scale(u, math.sin(a)))
        outline.append(add(centre, scale(direction, radius)))
    return outline
