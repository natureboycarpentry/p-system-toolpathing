"""
Create and update Clamex path sketch geometry in a dedicated component.

Owns the root-level Clamex Toolpaths component and creates/replaces feed, flat,
drill, marker, and preview sketches used by preview and CAM generation.
"""

import adsk.cam
import adsk.core
import adsk.fusion

from lib import trace_log

CLAMEX_COMPONENT_NAME = 'Clamex Toolpaths'
# Attribute marking the component this add-in owns, so a renamed or duplicated
# 'Clamex Toolpaths (n)' never splits sketches and operations across components.
CLAMEX_TAG_GROUP = 'LamelloPSystemCNC'
CLAMEX_TAG_NAME = 'clamexToolpaths'
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

    trace_log.step(f'sketch: {sketch_name}')
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


def _is_tagged_clamex(component):
    try:
        return bool(component.attributes.itemByName(CLAMEX_TAG_GROUP, CLAMEX_TAG_NAME))
    except Exception:
        return False


def _tag_clamex(component):
    try:
        if not _is_tagged_clamex(component):
            component.attributes.add(CLAMEX_TAG_GROUP, CLAMEX_TAG_NAME, '1')
    except Exception:
        pass


def _is_clamex_name(name):
    """'Clamex Toolpaths' or a Fusion de-duplicated variant like 'Clamex Toolpaths (4)'."""
    return name == CLAMEX_COMPONENT_NAME or name.startswith(CLAMEX_COMPONENT_NAME + ' (')


def get_or_create_clamex_component(design):
    """Return (component, root occurrence) of the add-in's Clamex Toolpaths component.

    Lookup order: the component tagged by this add-in, then the exact name,
    then a de-duplicated name ('Clamex Toolpaths (4)'); the match is tagged so
    later runs keep using it. Created at the assembly root if none exists.
    """
    root = design.rootComponent
    exact = variant = None
    for occ in root.occurrences:
        component = occ.component
        if _is_tagged_clamex(component):
            return component, occ
        if component.name == CLAMEX_COMPONENT_NAME and not exact:
            exact = occ
        elif _is_clamex_name(component.name) and not variant:
            variant = occ
    found = exact or variant
    if found:
        _tag_clamex(found.component)
        return found.component, found

    transform = adsk.core.Matrix3D.create()
    occ = root.occurrences.addNewComponent(transform)
    occ.component.name = CLAMEX_COMPONENT_NAME
    _tag_clamex(occ.component)
    return occ.component, occ


def clamex_root_occurrence(design, component):
    """Root occurrence of *component* (the Clamex component the sketches live in)."""
    for occ in design.rootComponent.occurrences:
        if occ.component == component:
            return occ
    raise RuntimeError(f'Component "{component.name}" is not at the top of the assembly.')


def _design_relative_path(full_path, top_level_names):
    """Drop wrapper segments Manufacture adds in front of the design's own paths.

    A setup's models can live in a CAM copy that inserts the design as a
    reference, e.g. 'CAM Component:1+PJWardrobe v1:1+Arrange3:1+...'. Cut the
    path back to its first segment that is a top-level occurrence of the design.
    """
    segments = full_path.split('+')
    for index, segment in enumerate(segments):
        if segment in top_level_names:
            return '+'.join(segments[index:])
    return full_path


def _setup_model_paths(design, setup):
    """(include_all, set of occurrence fullPathNames) covered by the setup's models.

    An empty model list or the root component counts as "everything".
    """
    root = design.rootComponent
    paths = set()
    try:
        models = setup.models
    except Exception:
        models = None
    if not models or models.count == 0:
        return True, paths
    include_all = False
    top_level = {occ.name for occ in root.occurrences}
    for index in range(models.count):
        model = models.item(index)
        occurrence = adsk.fusion.Occurrence.cast(model)
        if occurrence:
            paths.add(_design_relative_path(occurrence.fullPathName, top_level))
            continue
        body = adsk.fusion.BRepBody.cast(model)
        if body:
            if body.assemblyContext:
                paths.add(_design_relative_path(body.assemblyContext.fullPathName, top_level))
            continue
        component = adsk.fusion.Component.cast(model)
        if component and component == root:
            include_all = True
    return include_all, paths


def setup_model_components(design, setup):
    """Components a setup references through bodies that carry no assembly path.

    Setups linked to a Design-workspace Arrange report their models as native
    bodies (assemblyContext None), so the occurrence can only be recovered from
    the body's component.
    """
    root = design.rootComponent
    components = []
    try:
        models = setup.models
        count = models.count if models else 0
    except Exception:
        return components
    for index in range(count):
        body = adsk.fusion.BRepBody.cast(models.item(index))
        if not body or body.assemblyContext:
            continue
        component = body.parentComponent
        if component and component != root and not any(c == component for c in components):
            components.append(component)
    return components


def setup_includes_occurrence(design, setup, occurrence):
    include_all, paths = _setup_model_paths(design, setup)
    top_level = {occ.name for occ in design.rootComponent.occurrences}
    return include_all or _design_relative_path(occurrence.fullPathName, top_level) in paths


def _setup_wrapper_occurrence(design, setup):
    """Occurrence that holds the design inside the setup's CAM assembly, or None.

    Newer documents keep setup models in a CAM-side assembly
    ('CAM Component:1+<design>:1+...'). Entities handed to that setup (models,
    Trace/Drill geometry) must be proxies through this occurrence; passing raw
    design entities crashes Fusion.
    """
    try:
        cam = adsk.cam.CAM.cast(adsk.core.Application.get().activeProduct)
        wrapper = cam.designRootOccurrence if cam else None
        if wrapper:
            return wrapper
    except Exception:
        pass

    top_level = {occ.name for occ in design.rootComponent.occurrences}
    try:
        models = setup.models
        count = models.count if models else 0
    except Exception:
        return None
    for index in range(count):
        model = models.item(index)
        context = adsk.fusion.Occurrence.cast(model)
        if not context:
            body = adsk.fusion.BRepBody.cast(model)
            context = body.assemblyContext if body else None
        if not context:
            continue
        segments = context.fullPathName.split('+')
        cut = next((i for i, seg in enumerate(segments) if seg in top_level), None)
        if not cut:
            continue
        wrapper_path = '+'.join(segments[:cut])
        while context and context.fullPathName != wrapper_path:
            context = context.assemblyContext
        if context:
            return context
    return None


def cam_side_occurrence(design_occurrence, wrapper):
    """Twin of a top-level design occurrence inside the CAM assembly, as a proxy.

    The CAM assembly holds its own copy of the design under *wrapper*; CAM
    crashes on design entities merely proxied through it, so geometry must come
    from the copy. Raises RuntimeError when the copy has not picked the
    occurrence up (yet).
    """
    copy_root = wrapper.component
    same = copy_root == design_occurrence.component.parentDesign.rootComponent
    trace_log.step(f'twin: wrapper component is design root: {same}')
    if same:
        return design_occurrence.createForAssemblyContext(wrapper)
    twin = copy_root.occurrences.itemByName(design_occurrence.name)
    if not twin:
        raise RuntimeError(
            f'The setup\'s CAM model does not contain "{design_occurrence.name}" yet. '
            'Save the document (or update the Models reference) and run Generate again.'
        )
    return twin.createForAssemblyContext(wrapper)


def _models_contain(setup, occurrence):
    try:
        models = setup.models
        for index in range(models.count):
            model = adsk.fusion.Occurrence.cast(models.item(index))
            if model and model.fullPathName == occurrence.fullPathName:
                return True
    except Exception:
        pass
    return False


def ensure_clamex_in_setup(design, setup, component=None):
    """Create the Clamex Toolpaths component if needed and add it to the setup's models.

    CAM only accepts sketch geometry from models in the setup. Existing model
    selections are kept. Returns (component, occurrence, ok) where ok is False
    when Fusion refused the change (the caller should tell the user). The
    occurrence is in the setup's context (a proxy when the setup lives in a
    CAM-side assembly), ready for geometry_for_assembly / point_for_assembly.
    Pass *component* to use the component the sketches were created in.
    """
    trace_log.step('ensure: get_or_create_clamex_component')
    if component:
        occurrence = clamex_root_occurrence(design, component)
    else:
        component, occurrence = get_or_create_clamex_component(design)
    trace_log.step(f'ensure: clamex occurrence {occurrence.fullPathName}')
    wrapper = _setup_wrapper_occurrence(design, setup)
    trace_log.step(f'ensure: wrapper {wrapper.fullPathName if wrapper else None}')
    if wrapper:
        occurrence = cam_side_occurrence(occurrence, wrapper)
        trace_log.step(f'ensure: CAM-side twin {occurrence.fullPathName}')
    if setup_includes_occurrence(design, setup, occurrence) or _models_contain(setup, occurrence):
        trace_log.step('ensure: already in setup')
        return component, occurrence, True
    try:
        models = setup.models
        collection = adsk.core.ObjectCollection.create()
        for index in range(models.count):
            collection.add(models.item(index))
        collection.add(occurrence)
        trace_log.step(f'ensure: setting setup.models ({collection.count} entities)')
        setup.models = collection
        trace_log.step('ensure: setup.models set')
    except Exception as exc:
        trace_log.step(f'ensure: setup.models refused: {exc}')
        return component, occurrence, False
    return component, occurrence, (
        setup_includes_occurrence(design, setup, occurrence) or _models_contain(setup, occurrence)
    )


ADD_TO_SETUP_HINT = (
    f'Could not add "{CLAMEX_COMPONENT_NAME}" to the setup automatically. Edit the setup, '
    f'and on the Setup tab ⌘/Ctrl-click "{CLAMEX_COMPONENT_NAME}" under Model, then regenerate.'
)


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


_TWIN_TOLERANCE_CM = 1e-4


def _same_point(p, q):
    return p.distanceTo(q) <= _TWIN_TOLERANCE_CM


def _twin_sketch(entity, clamex_occurrence):
    """Sketch in clamex_occurrence's component with the entity's sketch name, or None.

    None means no mapping is needed (the occurrence already references the
    entity's own component).
    """
    sketch = entity.parentSketch
    if clamex_occurrence.component == sketch.parentComponent:
        return None
    twin = clamex_occurrence.component.sketches.itemByName(sketch.name)
    if not twin:
        raise RuntimeError(
            f'The setup\'s CAM model does not contain sketch "{sketch.name}" yet. '
            'Save the document (or update the Models reference) and run Generate again.'
        )
    return twin


def geometry_for_assembly(sketch_lines, clamex_occurrence):
    """
    Return sketch line entities in the setup's context: proxied through the
    Clamex occurrence, and swapped for the CAM-side copy's lines when the
    setup lives in a CAM assembly (see cam_side_occurrence).
    """
    if not clamex_occurrence:
        return list(sketch_lines)

    result = []
    for line in sketch_lines:
        twin_sketch = _twin_sketch(line, clamex_occurrence)
        if twin_sketch:
            start = line.startSketchPoint.geometry
            end = line.endSketchPoint.geometry
            match = None
            candidates = twin_sketch.sketchCurves.sketchLines
            for index in range(candidates.count):
                other = candidates.item(index)
                a, b = other.startSketchPoint.geometry, other.endSketchPoint.geometry
                if (_same_point(a, start) and _same_point(b, end)) or (
                    _same_point(a, end) and _same_point(b, start)
                ):
                    match = other
                    break
            if not match:
                raise RuntimeError(f'No matching CAM-side line in sketch "{twin_sketch.name}".')
            line = match
        result.append(line.createForAssemblyContext(clamex_occurrence))
    trace_log.step(f'geometry: {len(result)} line(s) in setup context')
    return result


def point_for_assembly(sketch_point, clamex_occurrence):
    """Return a sketch point entity in the setup's context (see geometry_for_assembly)."""
    if not clamex_occurrence:
        return sketch_point
    twin_sketch = _twin_sketch(sketch_point, clamex_occurrence)
    if twin_sketch:
        target = sketch_point.geometry
        points = twin_sketch.sketchPoints
        origin = twin_sketch.originPoint
        match = None
        for index in range(points.count):
            other = points.item(index)
            if other != origin and _same_point(other.geometry, target):
                match = other
                break
        if not match:
            raise RuntimeError(f'No matching CAM-side point in sketch "{twin_sketch.name}".')
        sketch_point = match
    return sketch_point.createForAssemblyContext(clamex_occurrence)
