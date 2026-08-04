"""Live command preview: tool-body Combine Cut with sketch fallback."""

import adsk.core
import adsk.fusion

from lib.cam_ops import find_setup_by_name, setup_wcs_z_axis
from lib.path_geometry import (
    CLAMEX_COMPONENT_NAME,
    PREVIEW_PLACEMENT_PREFIX,
    create_feed_path_sketch,
    create_flat_path_sketch,
    create_marker_sketch,
    delete_preview_sketches,
    get_or_create_clamex_component,
)
from lib.placement_sets import MODE_FLAT, MODE_SIDE
from lib.preview_cut import draw_cut_preview
from lib.toolpath_def import SLOT_LENGTH_MM, cross_offset_mm, feed_point_chain, flat_point_chain
from lib.transform import (
    drill_hole_world_point,
    placement_anchor_point,
    reference_axis_direction,
    transform_feed_chain,
    transform_flat_chain,
)
from lib.units import mm_to_cm, negate_vector, offset_point

_DEFAULT_Z_HINT = adsk.core.Vector3D.create(0, 0, 1)
_DEFAULT_X_HINT = adsk.core.Vector3D.create(1, 0, 0)


def _feed_only_world_points(anchor, feed_entity, flip_feed, connector_type):
    """
    Simplified side preview when full transform_feed_chain fails.

    Used when depth-axis resolution is incomplete during live preview; draws a
    coarse feed-axis polyline instead of the full T-slot wiggle.
    """
    anchor_origin = placement_anchor_point(anchor)
    feed_axis = reference_axis_direction(feed_entity)
    if flip_feed:
        feed_axis = negate_vector(feed_axis)

    offset_cm = mm_to_cm(cross_offset_mm(connector_type))
    cross = offset_point(anchor_origin, feed_axis, offset_cm)
    far_end = offset_point(cross, feed_axis, mm_to_cm(SLOT_LENGTH_MM))
    return [far_end, cross, anchor_origin, cross, far_end]


def _draw_anchor_marker(component, preview_name, anchor_origin, setup_z_axis, size_cm=0.25):
    """Draw a fallback cross marker when a full path cannot be resolved."""
    z_hint = setup_z_axis or _DEFAULT_Z_HINT
    create_marker_sketch(
        component,
        preview_name,
        anchor_origin,
        _DEFAULT_X_HINT,
        z_hint,
        size_cm,
    )


def _side_world_points_for_anchor(anchor, set_data, setup_z_axis, half_thickness_offset_mm=None):
    has_feed = set_data.get('reference_axis') is not None
    connector_type = set_data.get('connector_type')
    offset_mm = cross_offset_mm(connector_type)
    z_axis = setup_z_axis or _DEFAULT_Z_HINT

    if has_feed:
        try:
            return transform_feed_chain(
                anchor,
                feed_point_chain(),
                set_data['reference_axis'],
                z_axis,
                set_data.get('flip_feed', False),
                set_data.get('flip_z', False),
                set_data.get('tool_thickness_offset', True),
                offset_mm,
                half_thickness_offset_mm,
            )
        except Exception:
            return _feed_only_world_points(
                anchor,
                set_data['reference_axis'],
                set_data.get('flip_feed', False),
                connector_type,
            )

    return None


def _flat_world_points_for_anchor(anchor, set_data, setup_z_axis):
    if not set_data.get('reference_axis'):
        return None
    z_axis = setup_z_axis or _DEFAULT_Z_HINT
    return transform_flat_chain(
        anchor,
        flat_point_chain(set_data.get('connector_type')),
        set_data['reference_axis'],
        z_axis,
        set_data.get('flip_feed', False),
        set_data.get('flip_z', False),
    )


def clear_toolpath_preview(app):
    """Remove existing preview sketches without creating the toolpaths component."""
    design = adsk.fusion.Design.cast(
        app.activeDocument.products.itemByProductType('DesignProductType')
    )
    if not design:
        return
    for occ in design.rootComponent.occurrences:
        if occ.component.name == CLAMEX_COMPONENT_NAME:
            delete_preview_sketches(occ.component)
            return


def draw_toolpath_preview(app, values, cam):
    """
    Preview placements for the active milling tab.

    Prefers forum-style tool-body Combine Cut into setup stock. Falls back to
    centerline 3D sketches when cut preview cannot run (missing tools/axes/stock).
    """
    placement_sets = values.get('placement_sets') if values else None
    if not placement_sets:
        return 0

    mode = values.get('mode', MODE_SIDE)
    setup_z_axis = None
    setup_name = values.get('setup_name')
    if setup_name and cam:
        setup = find_setup_by_name(cam, setup_name)
        if setup:
            try:
                setup_z_axis = setup_wcs_z_axis(setup)
            except Exception:
                setup_z_axis = None

    design = adsk.fusion.Design.cast(
        app.activeDocument.products.itemByProductType('DesignProductType')
    )
    if design:
        # Clear prior centerline sketches; cut preview replaces them when it works.
        for occ in design.rootComponent.occurrences:
            if occ.component.name == CLAMEX_COMPONENT_NAME:
                delete_preview_sketches(occ.component)
                break

    # Tool-body cut preview first (executePreview transaction rolls it back).
    try:
        cut_count = draw_cut_preview(app, values, cam)
        if cut_count:
            return cut_count
    except Exception as exc:
        try:
            app.log(f'Clamex cut preview failed, sketch fallback:\n{exc}')
        except Exception:
            pass

    if not design:
        return 0

    component, occurrence = get_or_create_clamex_component(design)
    if occurrence:
        occurrence.isLightBulbOn = True

    delete_preview_sketches(component)

    drawn = 0
    preview_index = 0
    for set_data in placement_sets:
        anchors = set_data.get('anchor_points') or []
        for anchor in anchors:
            preview_index += 1
            preview_name = PREVIEW_PLACEMENT_PREFIX
            if preview_index > 1:
                preview_name = f'{PREVIEW_PLACEMENT_PREFIX} {preview_index}'

            try:
                if mode == MODE_FLAT:
                    world_points = _flat_world_points_for_anchor(anchor, set_data, setup_z_axis)
                    if world_points:
                        create_flat_path_sketch(component, preview_name, world_points)
                    else:
                        _draw_anchor_marker(
                            component,
                            preview_name,
                            placement_anchor_point(anchor),
                            setup_z_axis,
                        )
                    drawn += 1
                    continue

                world_points = _side_world_points_for_anchor(
                    anchor,
                    set_data,
                    setup_z_axis,
                    values.get('tool_half_thickness_offset_mm'),
                )
                if world_points:
                    create_feed_path_sketch(component, preview_name, world_points)
                else:
                    _draw_anchor_marker(
                        component,
                        preview_name,
                        placement_anchor_point(anchor),
                        setup_z_axis,
                    )
                drawn += 1

                if (
                    set_data.get('drill_holes')
                    and set_data.get('reference_axis') is not None
                    and setup_z_axis
                ):
                    hole_point = drill_hole_world_point(
                        anchor,
                        set_data['reference_axis'],
                        setup_z_axis,
                        set_data.get('flip_feed', False),
                        set_data.get('flip_z', False),
                        set_data.get('connector_type'),
                    )
                    drill_preview_name = f'{preview_name} drill'
                    _draw_anchor_marker(
                        component,
                        drill_preview_name,
                        hole_point,
                        setup_z_axis,
                        size_cm=0.2,
                    )
                    drawn += 1
            except Exception:
                continue

    return drawn
