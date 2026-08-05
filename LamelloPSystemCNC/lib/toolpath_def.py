"""
Master Clamex connector-local toolpath definition (millimetres).

Side and flat cavity geometry is defined in connector-local coordinates before
transform.py maps it into world space using anchor and feed-axis selections.
"""

from enum import Enum


class MoveType(Enum):
    RAPID = 'rapid'
    FEED = 'feed'


DEFAULT_CONNECTOR_TYPE = 'P14'

# Side cut depth into the face (mm). The "14" / "10" in P14 / P10.
CONNECTOR_CUT_DEPTH_MM = {
    'P14': 14.0,
    'P10': 10.0,
}

CONNECTOR_HOLE_OFFSET_MM = {
    'P14': 7.5,
    'P10': 5.5,
}

DEFAULT_DRILL_CLEARANCE_MM = 10.0


def cut_depth_mm(connector_type=None):
    """Return side cut depth (mm) for the connector type (P14→14, P10→10)."""
    key = connector_type or DEFAULT_CONNECTOR_TYPE
    return CONNECTOR_CUT_DEPTH_MM.get(key, CONNECTOR_CUT_DEPTH_MM[DEFAULT_CONNECTOR_TYPE])


def cross_offset_mm(connector_type, tool_diameter_mm):
    """Return cross-point offset: (tool_diameter / 2) − cut_depth.

    Example: Ø100.4, P14 → 50.2 − 14 = 36.2 mm.
    Requires a positive tool diameter from the Fusion tool library.
    """
    try:
        diameter = float(tool_diameter_mm)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            'tool_diameter_mm is required to derive cross-point offset'
        ) from exc
    if diameter <= 0:
        raise ValueError('tool_diameter_mm must be positive')
    return (diameter * 0.5) - cut_depth_mm(connector_type)


def hole_offset_mm(connector_type=None):
    """Return tightening-hole XY offset opposite feed for the connector type."""
    key = connector_type or DEFAULT_CONNECTOR_TYPE
    return CONNECTOR_HOLE_OFFSET_MM.get(key, CONNECTOR_HOLE_OFFSET_MM[DEFAULT_CONNECTOR_TYPE])


def default_op_prefix(connector_type=None):
    """Default CAM operation name prefix for a connector type (Edge tab)."""
    key = connector_type or DEFAULT_CONNECTOR_TYPE
    return f'{key} - Edge'


def default_flat_op_prefix(connector_type=None):
    """Default CAM operation name prefix for Face (top-face cavity) ops."""
    key = connector_type or DEFAULT_CONNECTOR_TYPE
    return f'{key} - Face'


FLAT_REFERENCE_HALF_EXTENT_MM = 36.434
FLAT_REFERENCE_MAX_DEPTH_MM = 14.0

CONNECTOR_FLAT_HALF_EXTENT_MM = {
    'P14': 36.434,
    'P10': 31.5,
}


# Top-face cavity profile digitized from p14Topface G-code (feed mm, depth mm).
# Depth is negative into the part; anchor sits at feed=0 on the surface (depth=0).
FLAT_MASTER_PATH_MM = [
    (-36.434, 0.0),
    (-35.374, -0.946),
    (-34.287, -1.865),
    (-33.172, -2.754),
    (-32.032, -3.615),
    (-30.865, -4.446),
    (-29.675, -5.247),
    (-28.461, -6.016),
    (-27.223, -6.753),
    (-25.965, -7.457),
    (-24.685, -8.128),
    (-23.385, -8.766),
    (-22.067, -9.369),
    (-20.73, -9.937),
    (-19.377, -10.47),
    (-18.008, -10.967),
    (-16.625, -11.427),
    (-15.228, -11.851),
    (-13.818, -12.237),
    (-12.397, -12.586),
    (-10.966, -12.897),
    (-9.526, -13.17),
    (-8.078, -13.405),
    (-6.623, -13.601),
    (-5.163, -13.758),
    (-3.698, -13.876),
    (-2.231, -13.955),
    (-0.762, -13.995),
    (0.709, -13.995),
    (2.178, -13.957),
    (3.646, -13.879),
    (5.11, -13.763),
    (6.571, -13.607),
    (8.026, -13.412),
    (9.475, -13.179),
    (10.916, -12.907),
    (12.347, -12.597),
    (13.769, -12.25),
    (15.18, -11.864),
    (16.578, -11.442),
    (17.963, -10.982),
    (19.333, -10.486),
    (20.687, -9.955),
    (22.025, -9.387),
    (23.345, -8.785),
    (24.646, -8.148),
    (25.927, -7.478),
    (27.187, -6.774),
    (28.425, -6.037),
    (29.641, -5.269),
    (30.833, -4.469),
    (32.001, -3.638),
    (33.143, -2.777),
    (34.259, -1.887),
    (35.347, -0.969),
    (36.409, -0.023),
    (36.434, 0.0),
]


def flat_half_extent_mm(connector_type=None):
    """Return half the flat cavity extent along feed for the connector type."""
    key = connector_type or DEFAULT_CONNECTOR_TYPE
    return CONNECTOR_FLAT_HALF_EXTENT_MM.get(key, CONNECTOR_FLAT_HALF_EXTENT_MM[DEFAULT_CONNECTOR_TYPE])


def flat_max_depth_mm(connector_type=None):
    """Return the maximum flat cavity depth at centre (same as side cut depth)."""
    return cut_depth_mm(connector_type)


def flat_point_chain(connector_type=None):
    """Return scaled (feed_mm, depth_mm) points for the flat cavity profile."""
    half_extent = flat_half_extent_mm(connector_type)
    max_depth = flat_max_depth_mm(connector_type)
    feed_scale = half_extent / FLAT_REFERENCE_HALF_EXTENT_MM
    depth_scale = max_depth / FLAT_REFERENCE_MAX_DEPTH_MM
    return [
        (feed_mm * feed_scale, depth_mm * depth_scale)
        for feed_mm, depth_mm in FLAT_MASTER_PATH_MM
    ]

# Slot length from cross-point to far end along +feed.
SLOT_LENGTH_MM = 48.0

# Cutter Z reference: which part of the side-cutter flute is the programmed depth.
CUTTER_Z_FLUTE_TOP = 'Flute Top'
CUTTER_Z_FLUTE_CENTRE = 'Flute Centre'
CUTTER_Z_FLUTE_BOTTOM = 'Flute Bottom'
DEFAULT_CUTTER_Z_REFERENCE = CUTTER_Z_FLUTE_CENTRE
CUTTER_Z_REFERENCE_OPTIONS = (
    CUTTER_Z_FLUTE_TOP,
    CUTTER_Z_FLUTE_CENTRE,
    CUTTER_Z_FLUTE_BOTTOM,
)


def half_flute_mm(flute_length_mm):
    """Return absolute half flute length in mm, or None if missing/invalid."""
    try:
        flute = float(flute_length_mm)
    except (TypeError, ValueError):
        return None
    if flute <= 0:
        return None
    return 0.5 * flute


def cutter_z_depth_offset_mm(reference, flute_length_mm=None, half_flute=None):
    """Return depth offset (mm) for a cutter Z reference: +½, 0, or −½ flute.

    Flute Top → +half, Flute Centre → 0, Flute Bottom → −half.
    Pass flute_length_mm or a precomputed half_flute magnitude.
    Flute Top/Bottom require a readable flute length; Centre does not.
    """
    if half_flute is not None:
        try:
            half = abs(float(half_flute))
        except (TypeError, ValueError):
            half = None
    else:
        half = half_flute_mm(flute_length_mm)

    if reference == CUTTER_Z_FLUTE_TOP:
        if half is None:
            raise ValueError(
                f'Cutter Z "{CUTTER_Z_FLUTE_TOP}" requires a readable side-tool flute length.'
            )
        return half
    if reference == CUTTER_Z_FLUTE_BOTTOM:
        if half is None:
            raise ValueError(
                f'Cutter Z "{CUTTER_Z_FLUTE_BOTTOM}" requires a readable side-tool flute length.'
            )
        return -half
    return 0.0


def migrate_cutter_z_reference(value):
    """Normalize a saved or legacy value to a cutter Z reference label.

    Legacy bool tool_thickness_offset: True → Flute Bottom (−½), False → Flute Centre (0).
    """
    if value is True:
        return CUTTER_Z_FLUTE_BOTTOM
    if value is False:
        return CUTTER_Z_FLUTE_CENTRE
    if isinstance(value, str) and value in CUTTER_Z_REFERENCE_OPTIONS:
        return value
    return DEFAULT_CUTTER_Z_REFERENCE

# T-slot wiggle at the cross: ±WIGGLE_DEPTH_MM then settle slightly below centre.
WIGGLE_DEPTH_MM = 1.4
WIGGLE_SETTLE_MM = -0.05

# Side master path in cross-local coordinates: feed along +feed, depth relative to anchor
# (0 = anchor plane). The T cross / wiggle centre sits at feed=0, depth=0; the far end is
# at feed=SLOT_LENGTH_MM. Depth=0 is the anchor plane, not a legacy pocket depth offset.
MASTER_PATH_MM = [
    (MoveType.RAPID, SLOT_LENGTH_MM, 0.0, 0.0),
    (MoveType.FEED, SLOT_LENGTH_MM, 0.0, 0.0),
    (MoveType.FEED, 0.0, 0.0, 0.0),
    (MoveType.FEED, 0.0, 0.0, WIGGLE_DEPTH_MM),
    (MoveType.FEED, 0.0, 0.0, -WIGGLE_DEPTH_MM),
    (MoveType.FEED, 0.0, 0.0, WIGGLE_SETTLE_MM),
    (MoveType.FEED, SLOT_LENGTH_MM, 0.0, 0.0),
    (MoveType.RAPID, SLOT_LENGTH_MM, 0.0, 0.0),
]


def feed_point_chain():
    """Ordered local (feed, 0, depth) tuples for FEED moves only."""
    return [(x, y, z) for move_type, x, y, z in MASTER_PATH_MM if move_type == MoveType.FEED]
