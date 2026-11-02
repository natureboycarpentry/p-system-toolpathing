"""
Joint definitions stored on components (Fusion side).

A joint is defined on the assembled model by two touching planar faces. Each
half is saved as a JSON attribute on its own component, in component-local
millimetres, so it follows every occurrence of that component, including the
copies Design-workspace Arrange creates. At CAM time occurrence.transform2
maps the stored connectors into world space.

Attribute: group GROUP, name 'joint:<id>', value JSON (see _record()).
"""

import json
import uuid

import adsk.core
import adsk.fusion

from lib import joint_math as jm

GROUP = 'LamelloPSystemCNC'
ATTR_PREFIX = 'joint:'
RECORD_VERSION = 1

ROLE_EDGE = 'edge'
ROLE_FACE = 'face'

# Edge-contact centres within this distance (component-local mm) are the same joint.
SAME_JOINT_TOLERANCE_MM = 1.0


# --- conversions (Fusion cm <-> joint_math mm tuples) ----------------------

def point_mm(point):
    return (point.x * 10.0, point.y * 10.0, point.z * 10.0)


def vector_tuple(vector):
    return (vector.x, vector.y, vector.z)


def point3d(mm):
    return adsk.core.Point3D.create(mm[0] / 10.0, mm[1] / 10.0, mm[2] / 10.0)


def vector3d(v):
    return adsk.core.Vector3D.create(v[0], v[1], v[2])


def _transform_point_mm(matrix, mm):
    p = point3d(mm)
    p.transformBy(matrix)
    return point_mm(p)


def _transform_dir(matrix, v):
    """Rotate a direction by *matrix* (translation ignored), returned normalized."""
    o = adsk.core.Point3D.create(0, 0, 0)
    t = adsk.core.Point3D.create(v[0], v[1], v[2])
    o.transformBy(matrix)
    t.transformBy(matrix)
    return jm.normalize((t.x - o.x, t.y - o.y, t.z - o.z))


def _inverse(matrix):
    inv = matrix.copy()
    inv.invert()
    return inv


# --- face analysis ----------------------------------------------------------

def face_outward_normal(face):
    """Unit outward normal (tuple) of a planar face, verified against the body."""
    point = face.pointOnFace
    ok, normal = face.evaluator.getNormalAtPoint(point)
    if not ok or normal.length <= 1e-9:
        raise jm.JointGeometryError('Could not read the face normal.')
    n = jm.normalize(vector_tuple(normal))
    try:
        probe = adsk.core.Point3D.create(
            point.x + n[0] * 0.05, point.y + n[1] * 0.05, point.z + n[2] * 0.05
        )
        if face.body.pointContainment(probe) == adsk.fusion.PointContainment.PointInsidePointContainment:
            n = jm.scale(n, -1.0)
    except Exception:
        pass
    return n


def _face_vertices_mm(face):
    return [point_mm(vertex.geometry) for vertex in face.vertices]


def _longest_line_dir(face):
    best = None
    for edge in face.edges:
        line = adsk.core.Line3D.cast(edge.geometry)
        if not line:
            continue
        d = jm.sub(point_mm(line.endPoint), point_mm(line.startPoint))
        size = jm.length(d)
        if best is None or size > best[0]:
            best = (size, d)
    if not best:
        raise jm.JointGeometryError('The edge face needs at least one straight edge.')
    return best[1]


def _is_planar(face):
    try:
        return face.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType
    except Exception:
        return False


class JointDraft:
    """Two analysed faces ready to become a joint (all geometry in world mm)."""

    def __init__(self, edge_face, mate_face, frame):
        self.edge_face = edge_face
        self.mate_face = mate_face
        self.edge_occurrence = edge_face.assemblyContext
        self.face_occurrence = mate_face.assemblyContext
        self.frame = frame

    @property
    def edge_component(self):
        return self.edge_occurrence.component

    @property
    def face_component(self):
        return self.face_occurrence.component

    def label(self):
        return f'{self.edge_component.name} → {self.face_component.name}'


def analyze_face_pair(face_a, face_b, swap=False):
    """Build a JointDraft from two selected faces.

    The smaller face is treated as the edge face (end of the panel that gets the
    Edge slot) unless *swap* is set.
    """
    for face in (face_a, face_b):
        if not face or not _is_planar(face):
            raise jm.JointGeometryError('Both selections must be planar faces.')
        if not face.assemblyContext:
            raise jm.JointGeometryError(
                f'"{face.body.name}" is not inside a component. Each panel must be its own '
                'component so joints can follow it through Arrange.'
            )

    edge_face, mate_face = (face_a, face_b) if face_a.area <= face_b.area else (face_b, face_a)
    if swap:
        edge_face, mate_face = mate_face, edge_face

    if edge_face.assemblyContext.component == mate_face.assemblyContext.component:
        raise jm.JointGeometryError('Both faces belong to the same component. Pick two panels.')

    frame = jm.joint_frame(
        edge_normal=face_outward_normal(edge_face),
        edge_vertices=_face_vertices_mm(edge_face),
        edge_line_dir=_longest_line_dir(edge_face),
        mate_normal=face_outward_normal(mate_face),
        mate_vertices=_face_vertices_mm(mate_face),
    )
    return JointDraft(edge_face, mate_face, frame)


# --- records ----------------------------------------------------------------

def _record(joint_id, role, partner, connector_type, end_offset_mm, count, frame,
            points_local, feed_local, axis_local, contact_local):
    return {
        'v': RECORD_VERSION,
        'id': joint_id,
        'role': role,
        'partner': partner,
        'connector_type': connector_type,
        'end_offset_mm': end_offset_mm,
        'count': count,
        'length_mm': frame['length_mm'],
        'thickness_mm': frame['thickness_mm'],
        'feed': list(feed_local),
        'axis': list(axis_local),
        'contact': list(contact_local),
        'connectors': [{'p': list(p)} for p in points_local],
    }


def layout_world_points(draft, end_offset_mm, count):
    """Connector world points (mm) for the draft plus an optional warning."""
    positions, warning = jm.connector_positions(draft.frame['length_mm'], end_offset_mm, count)
    return jm.connector_points(draft.frame, positions), warning


def _edge_contact_local(draft):
    inv = _inverse(draft.edge_occurrence.transform2)
    mid = jm.add(draft.frame['start'], jm.scale(draft.frame['u'], 0.5 * draft.frame['length_mm']))
    return _transform_point_mm(inv, mid)


def build_records(draft, joint_id, connector_type, end_offset_mm, count):
    """Return (edge_record, face_record, world_points, warning)."""
    frame = draft.frame
    world_points, warning = layout_world_points(draft, end_offset_mm, count)

    edge_inv = _inverse(draft.edge_occurrence.transform2)
    face_inv = _inverse(draft.face_occurrence.transform2)

    edge_record = _record(
        joint_id, ROLE_EDGE, draft.face_component.name, connector_type, end_offset_mm, count, frame,
        [_transform_point_mm(edge_inv, p) for p in world_points],
        _transform_dir(edge_inv, frame['n']),
        _transform_dir(edge_inv, frame['t']),
        _edge_contact_local(draft),
    )
    face_record = _record(
        joint_id, ROLE_FACE, draft.edge_component.name, connector_type, end_offset_mm, count, frame,
        [_transform_point_mm(face_inv, p) for p in world_points],
        _transform_dir(face_inv, frame['u']),
        _transform_dir(face_inv, frame['mate_normal']),
        _transform_point_mm(face_inv, world_points[0]),
    )
    return edge_record, face_record, world_points, warning


def read_component_joints(component):
    """All joint records stored on a component (any role)."""
    records = []
    try:
        attrs = component.attributes
        for index in range(attrs.count):
            attr = attrs.item(index)
            if attr.groupName != GROUP or not attr.name.startswith(ATTR_PREFIX):
                continue
            try:
                record = json.loads(attr.value)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get('connectors'):
                records.append(record)
    except Exception:
        pass
    return records


def find_existing_joint_id(draft):
    """Id of a stored joint between the same two components at the same contact."""
    contact = _edge_contact_local(draft)
    partner = draft.face_component.name
    for record in read_component_joints(draft.edge_component):
        if record.get('role') != ROLE_EDGE or record.get('partner') != partner:
            continue
        stored = record.get('contact')
        if stored and jm.distance(tuple(stored), contact) <= SAME_JOINT_TOLERANCE_MM:
            return record.get('id')
    return None


def _set_attr(component, name, value):
    existing = component.attributes.itemByName(GROUP, name)
    if existing:
        existing.deleteMe()
    component.attributes.add(GROUP, name, value)


def delete_joint(design, joint_id):
    """Remove both halves of a joint. Returns the number of attributes removed."""
    removed = 0
    for attr in list(design.findAttributes(GROUP, ATTR_PREFIX + joint_id)):
        try:
            attr.deleteMe()
            removed += 1
        except Exception:
            pass
    return removed


def save_joint(design, draft, connector_type, end_offset_mm, count):
    """Create or replace the joint for *draft*. Returns (joint_id, world_points, warning)."""
    joint_id = find_existing_joint_id(draft)
    if joint_id:
        delete_joint(design, joint_id)
    else:
        joint_id = uuid.uuid4().hex[:12]

    edge_record, face_record, world_points, warning = build_records(
        draft, joint_id, connector_type, end_offset_mm, count
    )
    name = ATTR_PREFIX + joint_id
    _set_attr(draft.edge_component, name, json.dumps(edge_record))
    _set_attr(draft.face_component, name, json.dumps(face_record))
    return joint_id, world_points, warning


# --- inventory (Manage Joints) ----------------------------------------------

def collect_joints(design):
    """Every stored joint in the design, both halves paired by id.

    Returns a list of dicts sorted by label: id, label, connector_type, count,
    edge / face ((component, record) or None) and broken (a half is missing,
    e.g. its part was deleted or re-made).
    """
    by_id = {}
    for component in design.allComponents:
        for record in read_component_joints(component):
            joint_id = record.get('id')
            role = record.get('role')
            if not joint_id or role not in (ROLE_EDGE, ROLE_FACE):
                continue
            entry = by_id.setdefault(joint_id, {'id': joint_id, ROLE_EDGE: None, ROLE_FACE: None})
            entry[role] = (component, record)

    joints = []
    for entry in by_id.values():
        edge, face = entry[ROLE_EDGE], entry[ROLE_FACE]
        record = (edge or face)[1]
        edge_name = edge[0].name if edge else face[1].get('partner') or '?'
        face_name = face[0].name if face else edge[1].get('partner') or '?'
        entry.update(
            label=f'{edge_name} → {face_name}',
            connector_type=record.get('connector_type') or '',
            count=len(record.get('connectors') or []),
            broken=edge is None or face is None,
        )
        joints.append(entry)
    joints.sort(key=lambda j: (j['label'], j['id']))
    return joints


# --- world placements for an occurrence --------------------------------------

def occurrence_connectors(occurrence):
    """Stored connectors of an occurrence's component, mapped to world space.

    Yields dicts: role, record, index, point (Point3D cm), feed / axis (unit
    tuples). Edge: feed = cut-in (out of the edge face), axis = thickness
    direction. Face: feed = joint line, axis = mate face outward normal.
    """
    matrix = occurrence.transform2
    for record in read_component_joints(occurrence.component):
        try:
            feed = _transform_dir(matrix, record['feed'])
            axis = _transform_dir(matrix, record['axis'])
        except (KeyError, jm.JointGeometryError):
            continue
        for index, connector in enumerate(record['connectors']):
            yield {
                'role': record.get('role'),
                'record': record,
                'index': index,
                'point': point3d(_transform_point_mm(matrix, connector['p'])),
                'feed': feed,
                'axis': axis,
            }


def is_arranged_occurrence(occurrence):
    """True for copies Design-workspace Arrange nests under 'ArrangeN' occurrences."""
    try:
        segments = occurrence.fullPathName.split('+')[:-1]
    except Exception:
        return False
    return any(segment.startswith('Arrange') for segment in segments)
