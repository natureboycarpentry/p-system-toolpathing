"""
Create and update Clamex path sketch geometry in a dedicated component.

Owns the root-level Clamex Toolpaths component and creates/replaces feed, flat,
drill, marker, and preview sketches used by preview and CAM generation.
"""

import adsk.core
import adsk.fusion

CLAMEX_COMPONENT_NAME = 'Clamex Toolpaths'
SKETCH_PREFIX = 'Clamex Path – '
FLAT_SKETCH_PREFIX = 'Clamex Flat Path – '
DRILL_SKETCH_PREFIX = 'Clamex Drill – '
PREVIEW_PLACEMENT_PREFIX = '__Preview__'


def sketch_name_for_placement(placement_name):
    return f'{SKETCH_PREFIX}{placement_name}'


def drill_sketch_name_for_placement(placement_name):
    return f'{DRILL_SKETCH_PREFIX}{placement_name}'


def flat_sketch_name_for_placement(placement_name):
    return f'{FLAT_SKETCH_PREFIX}{placement_name}'


def _create_polyline_sketch(component, sketch_name, world_points, path_label):
    """Create or replace a named 3D sketch containing an open polyline."""
    if len(world_points) < 2:
        raise ValueError(
            f'Need at least two points for {path_label} "{sketch_name}", got {len(world_points)}'
        )

    _delete_sketch_by_name(component, sketch_name)

    sketch = component.sketches.add(component.xYConstructionPlane)
    sketch.name = sketch_name
    if hasattr(sketch, 'is3D'):
        sketch.is3D = True

    lines = sketch.sketchCurves.sketchLines
    sketch_lines = []
    for index in range(len(world_points) - 1):
        line = lines.addByTwoPoints(world_points[index], world_points[index + 1])
        sketch_lines.append(line)

    return sketch, sketch_lines


def create_flat_path_sketch(component, placement_name, world_points):
    """Create a named 3D sketch for a flat top-face cavity path."""
    return _create_polyline_sketch(
        component,
        flat_sketch_name_for_placement(placement_name),
        world_points,
        'flat path',
    )


def get_or_create_clamex_component(design):
    """Return the Clamex Toolpaths component, creating it at the assembly root if needed."""
    root = design.rootComponent
    for occ in root.occurrences:
        if occ.component.name == CLAMEX_COMPONENT_NAME:
            return occ.component, occ

    transform = adsk.core.Matrix3D.create()
    occ = root.occurrences.addNewComponent(transform)
    occ.component.name = CLAMEX_COMPONENT_NAME
    return occ.component, occ


def _delete_sketch_by_name(component, sketch_name):
    sketch = component.sketches.itemByName(sketch_name)
    if sketch:
        sketch.deleteMe()


def delete_preview_sketches(component):
    """Remove all transient preview sketches from the Clamex component."""
    prefixes = (
        sketch_name_for_placement(PREVIEW_PLACEMENT_PREFIX),
        flat_sketch_name_for_placement(PREVIEW_PLACEMENT_PREFIX),
    )
    for index in range(component.sketches.count - 1, -1, -1):
        sketch = component.sketches.item(index)
        if any(sketch.name.startswith(prefix) for prefix in prefixes):
            sketch.deleteMe()


def create_marker_sketch(component, placement_name, center, axis_a, axis_b, size_cm):
    """Create a small 3D cross marker sketch at center."""
    sketch_name = sketch_name_for_placement(placement_name)
    _delete_sketch_by_name(component, sketch_name)

    half = size_cm * 0.5
    axis_b_copy = axis_b.copy()
    axis_b_copy.normalize()
    axis_a_copy = axis_a.copy()
    axis_a_copy.normalize()

    p1 = adsk.core.Point3D.create(
        center.x - axis_a_copy.x * half,
        center.y - axis_a_copy.y * half,
        center.z - axis_a_copy.z * half,
    )
    p2 = adsk.core.Point3D.create(
        center.x + axis_a_copy.x * half,
        center.y + axis_a_copy.y * half,
        center.z + axis_a_copy.z * half,
    )
    p3 = adsk.core.Point3D.create(
        center.x - axis_b_copy.x * half,
        center.y - axis_b_copy.y * half,
        center.z - axis_b_copy.z * half,
    )
    p4 = adsk.core.Point3D.create(
        center.x + axis_b_copy.x * half,
        center.y + axis_b_copy.y * half,
        center.z + axis_b_copy.z * half,
    )

    sketch = component.sketches.add(component.xYConstructionPlane)
    sketch.name = sketch_name
    if hasattr(sketch, 'is3D'):
        sketch.is3D = True

    lines = sketch.sketchCurves.sketchLines
    lines.addByTwoPoints(p1, p2)
    lines.addByTwoPoints(p3, p4)
    return sketch


def create_feed_path_sketch(component, placement_name, world_points):
    """
    Create a named 3D sketch containing an open polyline through world_points.

    Any existing sketch with the same name in the component is replaced first.
    Returns (sketch, list of SketchLine entities).
    """
    return _create_polyline_sketch(
        component,
        sketch_name_for_placement(placement_name),
        world_points,
        'feed path',
    )


def create_drill_point_sketch(component, placement_name, world_point):
    """
    Create a named 3D sketch containing a single point for a drill operation.

    Returns (sketch, SketchPoint).
    """
    sketch_name = drill_sketch_name_for_placement(placement_name)
    _delete_sketch_by_name(component, sketch_name)

    sketch = component.sketches.add(component.xYConstructionPlane)
    sketch.name = sketch_name
    if hasattr(sketch, 'is3D'):
        sketch.is3D = True

    point = sketch.sketchPoints.add(world_point)
    return sketch, point


def geometry_for_assembly(sketch_lines, clamex_occurrence):
    """
    Return sketch line entities with assembly context when the Clamex component
    is nested under the root occurrence.
    """
    if not clamex_occurrence:
        return list(sketch_lines)

    return [line.createForAssemblyContext(clamex_occurrence) for line in sketch_lines]


def point_for_assembly(sketch_point, clamex_occurrence):
    """Return a sketch point entity with assembly context when nested."""
    if not clamex_occurrence:
        return sketch_point
    return sketch_point.createForAssemblyContext(clamex_occurrence)
