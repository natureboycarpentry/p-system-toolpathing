"""Unit conversion and vector helpers for Fusion geometry (internal units are cm)."""

import adsk.core

MM_TO_CM = 0.1


def mm_to_cm(mm):
    """Convert millimetres to Fusion centimetres."""
    return mm * MM_TO_CM


def negate_vector(vector):
    """Return a copy of vector scaled by -1."""
    copy = vector.copy()
    copy.scaleBy(-1.0)
    return copy


def offset_point(origin, axis, distance):
    """Return origin + axis * distance as a new Point3D."""
    return adsk.core.Point3D.create(
        origin.x + axis.x * distance,
        origin.y + axis.y * distance,
        origin.z + axis.z * distance,
    )
