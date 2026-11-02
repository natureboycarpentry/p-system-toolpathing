"""Round-trip test for lib/joints.py against a minimal Fusion stand-in.

A shelf's end face sits against a vertical side panel in the assembly. The
joint is saved in component-local coordinates, then read back through
different 'Arrange' transforms (side laid flat, shelf rotated 90 degrees).
"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'LamelloPSystemCNC'))

import fusion_stub as fs  # noqa: E402

fs.install()

from lib import joint_math as jm  # noqa: E402
from lib import joints as jt  # noqa: E402

IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
# Side panel modelled flat (thickness along local Z); assembled standing up:
# local X -> world +Z, local Y -> world +Y, local Z -> world -X.
STAND_UP = [[0, 0, -1], [0, 1, 0], [1, 0, 0]]
ROT_Z_90 = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]


def close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


class JointRoundTrip(unittest.TestCase):
    def setUp(self):
        self.shelf = fs.Component('Shelf')
        self.side = fs.Component('Left')
        self.design = fs.Design([self.shelf, self.side])

        self.shelf_asm = fs.Occurrence(self.shelf, fs.rigid(IDENTITY, (1.5, 0, 50)), 'Shelf:1')
        self.side_asm = fs.Occurrence(self.side, fs.rigid(STAND_UP, (63.3, 0, 0)), 'Left:1')

        # World cm: shelf end face at x=61.5, z 50..51.8; side inner face at x=61.5.
        self.shelf_end = fs.Face(
            self.shelf_asm,
            [(61.5, 0, 50), (61.5, 30, 50), (61.5, 30, 51.8), (61.5, 0, 51.8)],
            (1, 0, 0),
        )
        self.side_face = fs.Face(
            self.side_asm,
            [(61.5, 0, 0), (61.5, 0, 100), (61.5, 30, 100), (61.5, 30, 0)],
            (-1, 0, 0),
        )

    def save(self, **kw):
        draft = jt.analyze_face_pair(self.side_face, self.shelf_end)  # order shouldn't matter
        args = dict(connector_type='P14', end_offset_mm=100.0, count=2)
        args.update(kw)
        return draft, jt.save_joint(self.design, draft, **args)

    def test_roles_and_world_points(self):
        draft, (_jid, points, warning) = self.save()
        self.assertEqual(draft.edge_component.name, 'Shelf')
        self.assertEqual(draft.face_component.name, 'Left')
        self.assertIsNone(warning)
        self.assertTrue(close(points[0], (615, 100, 509)))
        self.assertTrue(close(points[1], (615, 200, 509)))

    def test_assembled_occurrences_reproduce_points(self):
        self.save()
        for occ in (self.shelf_asm, self.side_asm):
            pts = [jt.point_mm(c['point']) for c in jt.occurrence_connectors(occ)]
            self.assertTrue(close(pts[0], (615, 100, 509), 1e-6), (occ.name, pts))

    def test_arranged_side_lies_face_up(self):
        self.save()
        side_arranged = fs.Occurrence(
            self.side, fs.rigid(IDENTITY, (500, 0, 0)), 'Arrange1:1+Envelope1(Qty: 1):1+Left:2'
        )
        connectors = list(jt.occurrence_connectors(side_arranged))
        self.assertEqual({c['role'] for c in connectors}, {jt.ROLE_FACE})
        self.assertTrue(close(jt.point_mm(connectors[0]['point']), (5509, 100, 18)))
        self.assertEqual(jm.orientation_against(connectors[0]['axis'], (0, 0, 1)), jm.ORIENT_UP)
        self.assertTrue(close(connectors[0]['feed'], (0, 1, 0)))
        self.assertTrue(jt.is_arranged_occurrence(side_arranged))
        self.assertFalse(jt.is_arranged_occurrence(self.side_asm))

    def test_arranged_shelf_rotated(self):
        self.save()
        shelf_arranged = fs.Occurrence(
            self.shelf, fs.rigid(ROT_Z_90, (200, 0, 0)), 'Arrange1:1+Envelope2(Qty: 1):1+Shelf:2'
        )
        connectors = list(jt.occurrence_connectors(shelf_arranged))
        self.assertEqual(len(connectors), 2)
        c = connectors[0]
        self.assertEqual(c['role'], jt.ROLE_EDGE)
        self.assertTrue(close(jt.point_mm(c['point']), (1900, 600, 9)))
        # Cut-in direction rotates with the part; thickness axis stays vertical.
        self.assertTrue(close(c['feed'], (0, 1, 0)))
        self.assertNotEqual(jm.orientation_against(c['axis'], (0, 0, 1)), jm.ORIENT_TILTED)

    def test_flipped_side_reports_down(self):
        self.save()
        flip_x = [[1, 0, 0], [0, -1, 0], [0, 0, -1]]
        side_down = fs.Occurrence(self.side, fs.rigid(flip_x, (500, 0, 2)), 'Arrange1:1+E:1+Left:3')
        c = next(jt.occurrence_connectors(side_down))
        self.assertEqual(jm.orientation_against(c['axis'], (0, 0, 1)), jm.ORIENT_DOWN)

    def test_resave_replaces_and_delete_removes(self):
        _draft, (jid, _p, _w) = self.save()
        _draft, (jid2, _p, _w) = self.save(count=3)
        self.assertEqual(jid, jid2)
        self.assertEqual(self.shelf.attributes.count, 1)
        record = json.loads(self.shelf.attributes.item(0).value)
        self.assertEqual(len(record['connectors']), 3)
        self.assertEqual(jt.delete_joint(self.design, jid), 2)
        self.assertEqual(self.shelf.attributes.count + self.side.attributes.count, 0)

    def test_swap_roles(self):
        draft = jt.analyze_face_pair(self.side_face, self.shelf_end, swap=True)
        self.assertEqual(draft.edge_component.name, 'Left')

    def test_same_component_rejected(self):
        other = fs.Occurrence(self.shelf, fs.rigid(IDENTITY, (0, 0, 0)), 'Shelf:9')
        face = fs.Face(other, [(61.5, 0, 0), (61.5, 0, 100), (61.5, 30, 100), (61.5, 30, 0)], (-1, 0, 0))
        with self.assertRaises(jm.JointGeometryError):
            jt.analyze_face_pair(face, self.shelf_end)


if __name__ == '__main__':
    unittest.main()
