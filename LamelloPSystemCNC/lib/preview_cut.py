"""
Forum-style cut preview: tool solids + Combine Cut into setup stock.

During executePreview, TemporaryBRep tool bodies are inserted via a single
BaseFeature, then Combine-Cut into setup.models. The preview transaction
rewinds all Design edits on the next preview cycle or Cancel.

CustomGraphics show-through on the hidden tool body is attempted as an
overlay; the cut pocket itself is the primary visual.
"""

import adsk.core
import adsk.fusion

from lib.cam_ops import (
    find_setup_by_name,
    setup_wcs_z_axis,
    tool_diameter_mm,
    tool_flute_length_mm,
)
from lib.path_geometry import CLAMEX_COMPONENT_NAME
from lib.placement_sets import MODE_FLAT, MODE_SIDE
from lib.tool_body import (
    build_drill_tool_body,
    build_flat_tool_body,
    build_side_tool_body,
    transform_temp_body,
)
from lib.toolpath_def import (
    DEFAULT_DRILL_CLEARANCE_MM,
    SLOT_LENGTH_MM,
    cross_offset_mm,
    feed_point_chain,
    flat_point_chain,
)
from lib.transform import (
    drill_hole_world_point,
    placement_anchor_point,
    reference_axis_direction,
    resolve_placement_axes,
    transform_feed_chain,
    transform_flat_chain,
)
from lib.units import mm_to_cm, negate_vector, offset_point

_DEFAULT_Z = adsk.core.Vector3D.create(0, 0, 1)


def _feed_only_world_points(anchor, feed_entity, flip_feed, connector_type):
    anchor_origin = placement_anchor_point(anchor)
    feed_axis = reference_axis_direction(feed_entity)
    if flip_feed:
        feed_axis = negate_vector(feed_axis)
    offset_cm = mm_to_cm(cross_offset_mm(connector_type))
    cross = offset_point(anchor_origin, feed_axis, offset_cm)
    far_end = offset_point(cross, feed_axis, mm_to_cm(SLOT_LENGTH_MM))
    return [far_end, cross, anchor_origin, cross, far_end]


def _side_world_points_for_anchor(anchor, set_data, setup_z_axis, half_thickness_offset_mm=None):
    if not set_data.get('reference_axis'):
        return None
    connector_type = set_data.get('connector_type')
    z_axis = setup_z_axis or _DEFAULT_Z
    try:
        return transform_feed_chain(
            anchor,
            feed_point_chain(),
            set_data['reference_axis'],
            z_axis,
            set_data.get('flip_feed', False),
            set_data.get('flip_z', False),
            set_data.get('tool_thickness_offset', True),
            cross_offset_mm(connector_type),
            half_thickness_offset_mm,
        )
    except Exception:
        return _feed_only_world_points(
            anchor,
            set_data['reference_axis'],
            set_data.get('flip_feed', False),
            connector_type,
        )


def _flat_world_points_for_anchor(anchor, set_data, setup_z_axis):
    if not set_data.get('reference_axis'):
        return None
    z_axis = setup_z_axis or _DEFAULT_Z
    return transform_flat_chain(
        anchor,
        flat_point_chain(set_data.get('connector_type')),
        set_data['reference_axis'],
        z_axis,
        set_data.get('flip_feed', False),
        set_data.get('flip_z', False),
    )

_TOOL_BODY_NAME = '__Preview Tool__'
_GRAPHICS_GROUP_NAME = '__Preview Tool Graphics__'


def _log(app, message):
    try:
        app.log(f'Clamex cut preview: {message}')
    except Exception:
        pass


def _design_from_app(app):
    return adsk.fusion.Design.cast(
        app.activeDocument.products.itemByProductType('DesignProductType')
    )


def _body_volume(body):
    try:
        return float(body.volume)
    except Exception:
        return None


def _occurrence_for_body(design, body):
    """
    Find an occurrence whose native body matches *body*, or None for root bodies.

    Setup model proxies may be occurrence bodies; Combine must happen in the
    owning component with tool solids in that component's local space.
    """
    if not body:
        return None
    parent = body.parentComponent
    if not parent:
        return None
    if parent == design.rootComponent:
        return None

    # Prefer the occurrence that owns this exact body instance.
    try:
        for occ in design.rootComponent.allOccurrences:
            if occ.component != parent:
                continue
            try:
                for index in range(occ.bRepBodies.count):
                    if occ.bRepBodies.item(index) == body:
                        return occ
            except Exception:
                pass
            # Native body identity (proxy vs native).
            try:
                native = body.nativeObject if hasattr(body, 'nativeObject') and body.nativeObject else body
                for index in range(occ.component.bRepBodies.count):
                    if occ.component.bRepBodies.item(index) == native:
                        return occ
            except Exception:
                pass
    except Exception:
        pass

    # Fall back to first occurrence of the component.
    try:
        for occ in design.rootComponent.allOccurrences:
            if occ.component == parent:
                return occ
    except Exception:
        pass
    return None


def _native_body(body):
    try:
        native = body.nativeObject
        if native:
            return native
    except Exception:
        pass
    return body


def _world_to_component_matrix(occurrence):
    """Matrix that maps world coordinates into the occurrence's component space."""
    if not occurrence:
        return None
    try:
        world_from_comp = occurrence.transform
        inverse = world_from_comp.copy()
        if not inverse.invert():
            return None
        return inverse
    except Exception:
        return None


def _collect_setup_targets(design, setup):
    """
    Return list of (native_body, occurrence_or_None) for setup.models.

    Skips Clamex Toolpaths. Falls back to root bodies if models are empty.
    """
    targets = []
    seen = set()

    def _add(body, occ):
        native = _native_body(body)
        if not native:
            return
        try:
            key = native.entityToken
        except Exception:
            key = id(native)
        if key in seen:
            return
        try:
            if native.parentComponent and native.parentComponent.name == CLAMEX_COMPONENT_NAME:
                return
        except Exception:
            pass
        seen.add(key)
        targets.append((native, occ))

    if setup:
        try:
            models = setup.models
            for index in range(models.count):
                entity = models.item(index)
                body = adsk.fusion.BRepBody.cast(entity)
                if body:
                    _add(body, _occurrence_for_body(design, body))
                    continue
                occ = adsk.fusion.Occurrence.cast(entity)
                if occ:
                    for bi in range(occ.bRepBodies.count):
                        _add(occ.bRepBodies.item(bi), occ)
        except Exception:
            pass

    if targets:
        return targets

    # Fallback: all root-component bodies except Clamex Toolpaths.
    root = design.rootComponent
    for index in range(root.bRepBodies.count):
        _add(root.bRepBodies.item(index), None)
    for occ in root.occurrences:
        if occ.component.name == CLAMEX_COMPONENT_NAME:
            continue
        for bi in range(occ.bRepBodies.count):
            _add(occ.bRepBodies.item(bi), occ)
    return targets


def _insert_temp_bodies(component, temp_bodies):
    """
    Insert TemporaryBRep bodies into *component* via one BaseFeature.

    Returns the list of created BRepBody objects. Caller must not nest
    BaseFeature edits.
    """
    if not temp_bodies:
        return []

    base_features = component.features.baseFeatures
    base_feat = base_features.add()
    created = []
    try:
        base_feat.startEdit()
        for temp in temp_bodies:
            if not temp:
                continue
            body = component.bRepBodies.add(temp, base_feat)
            if body:
                try:
                    body.name = _TOOL_BODY_NAME
                except Exception:
                    pass
                created.append(body)
        base_feat.finishEdit()
    except Exception:
        try:
            if base_feat.isValid and base_feat.isActive:
                base_feat.finishEdit()
        except Exception:
            pass
        raise
    return created


def _combine_cut(component, target_body, tool_bodies):
    """Combine Cut tool_bodies from target_body; keep tool bodies."""
    if not tool_bodies:
        return False
    tools = adsk.core.ObjectCollection.create()
    for body in tool_bodies:
        tools.add(body)

    combine_features = component.features.combineFeatures
    combine_input = combine_features.createInput(target_body, tools)
    combine_input.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    combine_input.isKeepToolBodies = True
    combine_features.add(combine_input)
    return True


def _hide_tool_bodies(tool_bodies):
    for body in tool_bodies:
        try:
            body.isLightBulbOn = False
        except Exception:
            pass


def _add_tool_graphics(design, tool_bodies):
    """Forum-style show-through CustomGraphics overlay for hidden tool bodies."""
    if not tool_bodies:
        return 0
    root = design.rootComponent
    group = root.customGraphicsGroups.add()
    try:
        group.id = _GRAPHICS_GROUP_NAME
    except Exception:
        pass

    fill = adsk.fusion.CustomGraphicsShowThroughColorEffect.create(
        adsk.core.Color.create(255, 0, 0, 57),
        0.35,
    )
    edge_color = adsk.fusion.CustomGraphicsShowThroughColorEffect.create(
        adsk.core.Color.create(0, 0, 0, 255),
        0.5,
    )

    drawn = 0
    for body in tool_bodies:
        try:
            graphics = group.addBRepBody(body)
            graphics.isSelectable = False
            graphics.color = fill
            drawn += 1
        except Exception:
            continue
        try:
            for edge in body.edges:
                curve_gfx = group.addCurve(edge.geometry)
                curve_gfx.color = edge_color
                try:
                    curve_gfx.weight = 1.125
                except Exception:
                    pass
        except Exception:
            pass
    return drawn


def _axes_for_set(anchor, set_data, setup_z_axis):
    feed = set_data.get('reference_axis')
    if not feed or not setup_z_axis:
        return None
    return resolve_placement_axes(
        anchor,
        feed,
        setup_z_axis,
        set_data.get('flip_feed', False),
        set_data.get('flip_z', False),
    )


def _build_temp_tools_for_values(app, values, cam, setup_z_axis):
    """
    Build TemporaryBRep tool solids in world space for all preview placements.

    Returns a list of temporary BRepBody objects (not yet in the document).
    """
    mode = values.get('mode', MODE_SIDE)
    placement_sets = values.get('placement_sets') or []
    side_tool = values.get('side_tool')
    flat_tool = values.get('flat_tool')
    drill_tool = values.get('drill_tool')

    side_dia = tool_diameter_mm(side_tool) if side_tool else None
    side_thick = tool_flute_length_mm(side_tool) if side_tool else None
    if side_thick is None:
        half = values.get('tool_half_thickness_offset_mm')
        if half is not None:
            side_thick = abs(float(half)) * 2.0

    flat_dia = tool_diameter_mm(flat_tool) if flat_tool else None
    flat_flute = tool_flute_length_mm(flat_tool) if flat_tool else None
    drill_dia = tool_diameter_mm(drill_tool) if drill_tool else None

    temps = []
    for set_data in placement_sets:
        for anchor in set_data.get('anchor_points') or []:
            axes = _axes_for_set(anchor, set_data, setup_z_axis)
            if not axes:
                continue
            _origin, feed_axis, depth_axis = axes

            try:
                if mode == MODE_FLAT:
                    world_points = _flat_world_points_for_anchor(
                        anchor, set_data, setup_z_axis
                    )
                    if not world_points:
                        continue
                    body = build_flat_tool_body(
                        world_points, depth_axis, flat_dia, flat_flute
                    )
                    if body:
                        temps.append(body)
                    continue

                world_points = _side_world_points_for_anchor(
                    anchor,
                    set_data,
                    setup_z_axis,
                    values.get('tool_half_thickness_offset_mm'),
                )
                if world_points:
                    body = build_side_tool_body(
                        world_points,
                        feed_axis,
                        depth_axis,
                        side_dia,
                        side_thick,
                    )
                    if body:
                        temps.append(body)

                if (
                    set_data.get('drill_holes')
                    and set_data.get('reference_axis') is not None
                    and setup_z_axis
                ):
                    hole = drill_hole_world_point(
                        anchor,
                        set_data['reference_axis'],
                        setup_z_axis,
                        set_data.get('flip_feed', False),
                        set_data.get('flip_z', False),
                        set_data.get('connector_type'),
                    )
                    clearance = set_data.get(
                        'drill_clearance_mm', DEFAULT_DRILL_CLEARANCE_MM
                    )
                    drill_body = build_drill_tool_body(
                        hole, depth_axis, drill_dia, clearance
                    )
                    if drill_body:
                        temps.append(drill_body)
            except Exception as exc:
                _log(app, f'build tool failed: {exc}')
                continue
    return temps


def _cut_targets_with_temps(app, design, targets, world_temps):
    """
    Insert tool solids per target component and Combine Cut.

    Groups targets by component so each gets one BaseFeature insert.
    Returns (cut_ok_count, inserted_tool_bodies).
    """
    if not world_temps or not targets:
        return 0, []

    # Group targets by component.
    by_component = {}
    for native_body, occ in targets:
        component = native_body.parentComponent
        if not component:
            continue
        key = component.name
        # Use component object identity via token when possible.
        try:
            key = component.entityToken
        except Exception:
            key = id(component)
        by_component.setdefault(key, {
            'component': component,
            'occurrence': occ,
            'bodies': [],
        })
        by_component[key]['bodies'].append(native_body)
        # Prefer a non-None occurrence if we later find one.
        if occ and not by_component[key]['occurrence']:
            by_component[key]['occurrence'] = occ

    all_tools = []
    cut_ok = 0

    for group in by_component.values():
        component = group['component']
        occ = group['occurrence']
        matrix = _world_to_component_matrix(occ)

        local_temps = []
        tmp_mgr = adsk.fusion.TemporaryBRepManager.get()
        for world_body in world_temps:
            try:
                local = tmp_mgr.copy(world_body)
            except Exception as exc:
                _log(app, f'temp body copy failed: {exc}')
                continue
            if matrix:
                transform_temp_body(local, matrix)
            local_temps.append(local)
        if not local_temps:
            continue

        try:
            inserted = _insert_temp_bodies(component, local_temps)
        except Exception as exc:
            _log(app, f'BaseFeature insert failed: {exc}')
            continue

        if not inserted:
            continue

        _hide_tool_bodies(inserted)
        all_tools.extend(inserted)

        for target in group['bodies']:
            vol_before = _body_volume(target)
            try:
                _combine_cut(component, target, inserted)
            except Exception as exc:
                _log(app, f'Combine Cut failed: {exc}')
                continue
            vol_after = _body_volume(target)
            if (
                vol_before is not None
                and vol_after is not None
                and abs(vol_before - vol_after) < 1e-8
            ):
                _log(app, 'Combine Cut left volume unchanged (no intersection?)')
                continue
            cut_ok += 1

    return cut_ok, all_tools


def draw_cut_preview(app, values, cam):
    """
    Attempt forum-style tool-body Combine Cut preview.

    Returns number of successful cuts (0 means caller should keep sketch fallback).
    """
    if not values or not values.get('placement_sets'):
        return 0

    design = _design_from_app(app)
    if not design:
        _log(app, 'no Design product')
        return 0

    setup = None
    setup_z_axis = None
    setup_name = values.get('setup_name')
    if setup_name and cam:
        setup = find_setup_by_name(cam, setup_name)
        if setup:
            try:
                setup_z_axis = setup_wcs_z_axis(setup)
            except Exception:
                setup_z_axis = None

    if not setup_z_axis:
        _log(app, 'no setup WCS Z — cannot orient tool bodies')
        return 0

    world_temps = _build_temp_tools_for_values(app, values, cam, setup_z_axis)
    if not world_temps:
        _log(app, 'no tool solids built')
        return 0

    targets = _collect_setup_targets(design, setup)
    if not targets:
        _log(app, 'no stock targets')
        return 0

    cut_ok, tool_bodies = _cut_targets_with_temps(app, design, targets, world_temps)
    if cut_ok:
        try:
            gfx = _add_tool_graphics(design, tool_bodies)
            if gfx:
                _log(app, f'added CustomGraphics for {gfx} tool body(ies)')
        except Exception as exc:
            _log(app, f'CustomGraphics overlay skipped: {exc}')
        _log(app, f'Combine Cut ok on {cut_ok} target(s)')
    else:
        _log(app, 'no successful Combine Cuts')

    return cut_ok
