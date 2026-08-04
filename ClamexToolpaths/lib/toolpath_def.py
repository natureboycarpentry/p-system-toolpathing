"""Master Clamex connector-local toolpath definition (millimetres)."""

from enum import Enum


class MoveType(Enum):
    RAPID = 'rapid'
    FEED = 'feed'


# Distance from anchor point to the T cross-point along the feed axis (P14 default).
CROSS_OFFSET_MM = 36.2

DEFAULT_CONNECTOR_TYPE = 'P14'

CONNECTOR_CROSS_OFFSET_MM = {
    'P14': 36.2,
    'P10': 40.2,
}

CONNECTOR_HOLE_OFFSET_MM = {
    'P14': 7.5,
    'P10': 5.5,
}

DEFAULT_DRILL_CLEARANCE_MM = 10.0


def cross_offset_mm(connector_type=None):
    """Return cross-point offset for the given connector type."""
    key = connector_type or DEFAULT_CONNECTOR_TYPE
    return CONNECTOR_CROSS_OFFSET_MM.get(key, CONNECTOR_CROSS_OFFSET_MM[DEFAULT_CONNECTOR_TYPE])


def hole_offset_mm(connector_type=None):
    """Return tightening-hole XY offset opposite feed for the connector type."""
    key = connector_type or DEFAULT_CONNECTOR_TYPE
    return CONNECTOR_HOLE_OFFSET_MM.get(key, CONNECTOR_HOLE_OFFSET_MM[DEFAULT_CONNECTOR_TYPE])


def default_op_prefix(connector_type=None):
    """Default CAM operation name prefix for a connector type (side tab)."""
    key = connector_type or DEFAULT_CONNECTOR_TYPE
    return f'{key} - Side'


def default_flat_op_prefix(connector_type=None):
    """Default CAM operation name prefix for flat top-face cavities."""
    key = connector_type or DEFAULT_CONNECTOR_TYPE
    return f'{key} - Flat'


FLAT_REFERENCE_HALF_EXTENT_MM = 36.434
FLAT_REFERENCE_MAX_DEPTH_MM = 14.0

CONNECTOR_FLAT_HALF_EXTENT_MM = {
    'P14': 36.434,
    'P10': 31.5,
}

CONNECTOR_FLAT_MAX_DEPTH_MM = {
    'P14': 14.0,
    'P10': 10.0,
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
    key = connector_type or DEFAULT_CONNECTOR_TYPE
    return CONNECTOR_FLAT_HALF_EXTENT_MM.get(key, CONNECTOR_FLAT_HALF_EXTENT_MM[DEFAULT_CONNECTOR_TYPE])


def flat_max_depth_mm(connector_type=None):
    key = connector_type or DEFAULT_CONNECTOR_TYPE
    return CONNECTOR_FLAT_MAX_DEPTH_MM.get(key, CONNECTOR_FLAT_MAX_DEPTH_MM[DEFAULT_CONNECTOR_TYPE])


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

# Legacy connector pocket depth (mm). Feed geometry is defined at depth=0 (anchor plane);
# this constant documents the original connector-local cut depth for reference.
CONNECTOR_POCKET_DEPTH_MM = 12.5

# Offset applied to depth (Z0) when half tool thickness compensation is enabled.
TOOL_HALF_THICKNESS_OFFSET_MM = -3.5

# Master path in cross-local coordinates: feed along +feed, depth relative to anchor (0 = anchor plane).
# The T cross / wiggle centre sits at feed=0, depth=0; the far end is at feed=SLOT_LENGTH_MM.
MASTER_PATH_MM = [
    (MoveType.RAPID, SLOT_LENGTH_MM, 0.0, 0.0),
    (MoveType.FEED, SLOT_LENGTH_MM, 0.0, 0.0),
    (MoveType.FEED, 0.0, 0.0, 0.0),
    (MoveType.FEED, 0.0, 0.0, 1.4),
    (MoveType.FEED, 0.0, 0.0, -1.4),
    (MoveType.FEED, 0.0, 0.0, -0.05),
    (MoveType.FEED, SLOT_LENGTH_MM, 0.0, 0.0),
    (MoveType.RAPID, SLOT_LENGTH_MM, 0.0, 0.0),
]


def feed_point_chain():
    """Ordered local (feed, 0, depth) tuples for FEED moves only."""
    return [(x, y, z) for move_type, x, y, z in MASTER_PATH_MM if move_type == MoveType.FEED]
