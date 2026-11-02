"""
Custom-graphics preview for joints in the Design workspace.

Draws transient polylines (no timeline features, no sketches): the joint line,
each connector's Edge cut arc and Face cavity outline, drill axes, and faint
markers for joints already stored in the design.
"""

import adsk.core
import adsk.fusion

from lib import joint_math as jm
from lib import joints as jt
from lib.toolpath_def import cut_depth_mm, flat_point_chain, hole_offset_mm

GRAPHICS_ID = 'LamelloJointPreview'

COLOR_JOINT_LINE = (40, 170, 70)
COLOR_EDGE_CUT = (235, 120, 20)
COLOR_FACE_CUT = (30, 120, 220)
COLOR_DRILL = (210, 40, 40)
COLOR_EXISTING = (150, 150, 150)

_groups = []


def clear(design=None):
    """Remove every preview graphics group this module created."""
    for group in list(_groups):
        try:
            if group.isValid:
                group.deleteMe()
        except Exception:
            pass
    _groups.clear()
    if design:
        try:
            groups = design.rootComponent.customGraphicsGroups
            for index in range(groups.count - 1, -1, -1):
                group = groups.item(index)
                if group.id == GRAPHICS_ID:
                    group.deleteMe()
        except Exception:
            pass


def _color_effect(rgb):
    return adsk.fusion.CustomGraphicsSolidColorEffect.create(
        adsk.core.Color.create(rgb[0], rgb[1], rgb[2], 255)
    )


def _add_polyline(group, points_mm, rgb, weight=2.0):
    if len(points_mm) < 2:
        return
    flat = []
    for p in points_mm:
        flat.extend((p[0] / 10.0, p[1] / 10.0, p[2] / 10.0))
    coords = adsk.fusion.CustomGraphicsCoordinates.create(flat)
    lines = group.addLines(coords, [], True)
    lines.color = _color_effect(rgb)
    try:
        lines.weight = weight
    except Exception:
        pass
    try:
        lines.depthPriority = 1
    except Exception:
        pass


def _new_group(design):
    group = design.rootComponent.customGraphicsGroups.add()
    try:
        group.id = GRAPHICS_ID
    except Exception:
        pass
    _groups.append(group)
    return group


def draw_draft(design, draft, world_points, connector_type, edge_cutter_diameter_mm):
    """Draw both halves of every connector for a joint being defined."""
    group = _new_group(design)
    frame = draft.frame
    u, n, t = frame['u'], frame['n'], frame['t']
    half_t = 0.5 * frame['thickness_mm']

    end = jm.add(frame['start'], jm.scale(u, frame['length_mm']))
    _add_polyline(group, [frame['start'], end], COLOR_JOINT_LINE, 3.0)

    depth = cut_depth_mm(connector_type)
    profile = flat_point_chain(connector_type)
    hole = hole_offset_mm(connector_type)
    for p in world_points:
        try:
            arc = jm.edge_cut_outline(p, u, n, edge_cutter_diameter_mm, depth)
            _add_polyline(group, arc, COLOR_EDGE_CUT, 3.0)
        except jm.JointGeometryError:
            pass
        _add_polyline(
            group,
            jm.face_cavity_outline(p, u, frame['mate_normal'], profile),
            COLOR_FACE_CUT,
            3.0,
        )
        # Marker across the edge panel thickness at the connector centre.
        _add_polyline(group, [jm.add(p, jm.scale(t, -half_t)), jm.add(p, jm.scale(t, half_t))],
                      COLOR_JOINT_LINE, 2.0)
        # Drill axis through the thickness at the key-hole position.
        h = jm.add(p, jm.scale(n, -hole))
        _add_polyline(group, [jm.add(h, jm.scale(t, -half_t)), jm.add(h, jm.scale(t, half_t))],
                      COLOR_DRILL, 2.0)
    _refresh()


def draw_existing(design, skip_joint_id=None):
    """Faint markers for joints already stored on assembled (non-arranged) parts."""
    group = None
    for occurrence in design.rootComponent.allOccurrences:
        if jt.is_arranged_occurrence(occurrence):
            continue
        for connector in jt.occurrence_connectors(occurrence):
            record = connector['record']
            if connector['role'] != jt.ROLE_EDGE or record.get('id') == skip_joint_id:
                continue
            if group is None:
                group = _new_group(design)
            p = jt.point_mm(connector['point'])
            half_t = 0.5 * float(record.get('thickness_mm') or 10.0)
            t = connector['axis']
            n = connector['feed']
            _add_polyline(group, [jm.add(p, jm.scale(t, -half_t)), jm.add(p, jm.scale(t, half_t))],
                          COLOR_EXISTING, 3.0)
            _add_polyline(group, [p, jm.add(p, jm.scale(n, -15.0))], COLOR_EXISTING, 3.0)
    _refresh()


def _refresh():
    try:
        viewport = adsk.core.Application.get().activeViewport
        if viewport:
            viewport.refresh()
    except Exception:
        pass
