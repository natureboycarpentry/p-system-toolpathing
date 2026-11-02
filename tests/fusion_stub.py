"""Minimal adsk.core / adsk.fusion stand-ins for offline tests of lib/joints.py.

Only the members joints.py touches are implemented. Units are Fusion cm.
"""

import math
import sys
import types


class Point3D:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z

    @staticmethod
    def create(x=0.0, y=0.0, z=0.0):
        return Point3D(x, y, z)

    def transformBy(self, m):
        x, y, z = self.x, self.y, self.z
        r = m.rows
        self.x = r[0][0] * x + r[0][1] * y + r[0][2] * z + r[0][3]
        self.y = r[1][0] * x + r[1][1] * y + r[1][2] * z + r[1][3]
        self.z = r[2][0] * x + r[2][1] * y + r[2][2] * z + r[2][3]
        return True


class Vector3D:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z

    @staticmethod
    def create(x=0.0, y=0.0, z=0.0):
        return Vector3D(x, y, z)

    @property
    def length(self):
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)


class Matrix3D:
    def __init__(self, rows=None):
        self.rows = rows or [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]

    @staticmethod
    def create():
        return Matrix3D()

    def copy(self):
        return Matrix3D([row[:] for row in self.rows])

    def invert(self):
        # Rigid transforms only: R^T, -R^T t.
        r = self.rows
        rt = [[r[j][i] for j in range(3)] for i in range(3)]
        t = [r[0][3], r[1][3], r[2][3]]
        nt = [-sum(rt[i][k] * t[k] for k in range(3)) for i in range(3)]
        self.rows = [rt[0] + [nt[0]], rt[1] + [nt[1]], rt[2] + [nt[2]], [0, 0, 0, 1]]
        return True


def rigid(rotation_rows, translation_cm):
    rows = [list(rotation_rows[i]) + [translation_cm[i]] for i in range(3)]
    rows.append([0, 0, 0, 1])
    return Matrix3D(rows)


class Line3D:
    def __init__(self, start, end):
        self.startPoint, self.endPoint = start, end

    @staticmethod
    def cast(obj):
        return obj if isinstance(obj, Line3D) else None


class SurfaceTypes:
    PlaneSurfaceType = 0


class PointContainment:
    PointInsidePointContainment = 0
    PointOutsidePointContainment = 2


class Attribute:
    def __init__(self, owner, group, name, value):
        self.owner, self.groupName, self.name, self.value = owner, group, name, value

    def deleteMe(self):
        self.owner._items.remove(self)


class Attributes:
    def __init__(self):
        self._items = []

    @property
    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i]

    def itemByName(self, group, name):
        for a in self._items:
            if a.groupName == group and a.name == name:
                return a
        return None

    def add(self, group, name, value):
        a = Attribute(self, group, name, value)
        self._items.append(a)
        return a


class Component:
    def __init__(self, name):
        self.name = name
        self.attributes = Attributes()
        self.entityToken = 'tok-' + name


class Occurrence:
    def __init__(self, component, transform, path):
        self.component = component
        self.transform2 = transform
        self.fullPathName = path
        self.name = path.split('+')[-1]


class _Plane:
    surfaceType = SurfaceTypes.PlaneSurfaceType


class _Evaluator:
    def __init__(self, normal):
        self._normal = normal

    def getNormalAtPoint(self, _point):
        return True, Vector3D(*self._normal)


class _Body:
    name = 'Body1'

    def pointContainment(self, _point):
        return PointContainment.PointOutsidePointContainment


class _Vertex:
    def __init__(self, p):
        self.geometry = p


class _Edge:
    def __init__(self, a, b):
        self.geometry = Line3D(a, b)


class Face:
    """Planar quad face in world cm, belonging to *occurrence*."""

    def __init__(self, occurrence, corners_cm, outward_normal):
        pts = [Point3D(*c) for c in corners_cm]
        self.assemblyContext = occurrence
        self.geometry = _Plane()
        self.pointOnFace = pts[0]
        self.evaluator = _Evaluator(outward_normal)
        self.body = _Body()
        self.vertices = [_Vertex(p) for p in pts]
        self.edges = [_Edge(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
        a, b, c = corners_cm[0], corners_cm[1], corners_cm[3]
        ab = [b[i] - a[i] for i in range(3)]
        ac = [c[i] - a[i] for i in range(3)]
        self.area = math.sqrt(
            (ab[1] * ac[2] - ab[2] * ac[1]) ** 2
            + (ab[2] * ac[0] - ab[0] * ac[2]) ** 2
            + (ab[0] * ac[1] - ab[1] * ac[0]) ** 2
        )


class Design:
    def __init__(self, components):
        self._components = components

    def findAttributes(self, group, name):
        found = []
        for comp in self._components:
            for a in comp.attributes._items:
                if a.groupName == group and (not name or a.name == name):
                    found.append(a)
        return found


def install():
    adsk = types.ModuleType('adsk')
    core = types.ModuleType('adsk.core')
    fusion = types.ModuleType('adsk.fusion')
    core.Point3D, core.Vector3D, core.Matrix3D, core.Line3D = Point3D, Vector3D, Matrix3D, Line3D
    core.SurfaceTypes = SurfaceTypes
    fusion.PointContainment = PointContainment
    adsk.core, adsk.fusion = core, fusion
    sys.modules['adsk'] = adsk
    sys.modules['adsk.core'] = core
    sys.modules['adsk.fusion'] = fusion
