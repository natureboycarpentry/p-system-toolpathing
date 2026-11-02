"""Offline tests for lib/joint_math.py (no Fusion).

Run from the repo root:  python3 -m unittest discover -s tests
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'LamelloPSystemCNC'))

from lib import joint_math as jm  # noqa: E402


def close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# Shelf (edge panel) 18 thick (Z), 300 deep (Y): its +X end face at x=600 sits
# against the left face of a side panel at x=600.
SHELF_END = [(600, 0, 0), (600, 300, 0), (600, 300, 18), (600, 0, 18)]
SIDE_FACE = [(600, -10, -200), (600, 310, -200), (600, 310, 800), (600, -10, 800)]


class ConnectorPositionTests(unittest.TestCase):
    def test_two_connectors_at_end_offsets(self):
        pos, warn = jm.connector_positions(300, 100, 2)
        self.assertEqual(pos, [100, 200])
        self.assertIsNone(warn)

    def test_four_connectors_evenly_spaced(self):
        pos, _ = jm.connector_positions(800, 100, 4)
        self.assertEqual(pos, [100, 300, 500, 700])

    def test_single_connector_centred(self):
        pos, _ = jm.connector_positions(300, 100, 1)
        self.assertEqual(pos, [150])

    def test_too_short_falls_back_to_one(self):
        pos, warn = jm.connector_positions(150, 100, 2)
        self.assertEqual(pos, [75])
        self.assertIn('too short', warn)

    def test_negative_offset_clamped(self):
        pos, _ = jm.connector_positions(300, -5, 2)
        self.assertEqual(pos, [0, 300])


class JointFrameTests(unittest.TestCase):
    def frame(self, mate=SIDE_FACE):
        return jm.joint_frame(
            edge_normal=(1, 0, 0),
            edge_vertices=SHELF_END,
            edge_line_dir=(0, 300, 0),
            mate_normal=(-1, 0, 0),
            mate_vertices=mate,
        )

    def test_frame_axes_and_size(self):
        f = self.frame()
        self.assertTrue(close(f['u'], (0, 1, 0)))
        self.assertTrue(close(f['n'], (1, 0, 0)))
        self.assertTrue(close(f['t'], (0, 0, 1)))
        self.assertAlmostEqual(f['length_mm'], 300)
        self.assertAlmostEqual(f['thickness_mm'], 18)
        self.assertEqual(f['warnings'], [])

    def test_connectors_mid_thickness_on_contact_plane(self):
        f = self.frame()
        pos, _ = jm.connector_positions(f['length_mm'], 100, 2)
        pts = jm.connector_points(f, pos)
        self.assertTrue(close(pts[0], (600, 100, 9)))
        self.assertTrue(close(pts[1], (600, 200, 9)))

    def test_overlap_clips_to_shorter_mate(self):
        short_mate = [(600, 50, -200), (600, 250, -200), (600, 250, 800), (600, 50, 800)]
        f = self.frame(short_mate)
        self.assertAlmostEqual(f['length_mm'], 200)
        self.assertTrue(close(f['start'], (600, 50, 9)))

    def test_rejects_gap(self):
        moved = [(605, y, z) for _x, y, z in SIDE_FACE]
        with self.assertRaises(jm.JointGeometryError):
            self.frame(moved)

    def test_rejects_same_direction_normals(self):
        with self.assertRaises(jm.JointGeometryError):
            jm.joint_frame((1, 0, 0), SHELF_END, (0, 1, 0), (1, 0, 0), SIDE_FACE)

    def test_overhang_warning(self):
        thin_mate = [(600, -10, 5), (600, 310, 5), (600, 310, 800), (600, -10, 800)]
        f = self.frame(thin_mate)
        self.assertTrue(f['warnings'])

    def test_line_dir_not_quite_in_plane_is_projected(self):
        f = jm.joint_frame((1, 0, 0), SHELF_END, (0.01, 300, 0), (-1, 0, 0), SIDE_FACE)
        self.assertTrue(close(f['u'], (0, 1, 0)))


class OutlineTests(unittest.TestCase):
    def test_edge_cut_reaches_depth_into_edge_panel(self):
        p = (600, 100, 9)
        arc = jm.edge_cut_outline(p, (0, 1, 0), (1, 0, 0), 100.4, 14, segments=24)
        self.assertTrue(close(arc[12], (586, 100, 9)))  # 14 mm back into the shelf
        chord = math.sqrt(50.2 ** 2 - 36.2 ** 2)
        self.assertTrue(close(arc[0], (600, 100 - chord, 9)))
        self.assertTrue(close(arc[-1], (600, 100 + chord, 9)))

    def test_face_cavity_goes_into_mate(self):
        p = (600, 100, 9)
        outline = jm.face_cavity_outline(p, (0, 1, 0), (-1, 0, 0), [(-36, 0), (0, -14), (36, 0)])
        self.assertTrue(close(outline[1], (614, 100, 9)))  # 14 mm into the side panel

    def test_orientation(self):
        self.assertEqual(jm.orientation_against((0, 0, 2), (0, 0, 1)), jm.ORIENT_UP)
        self.assertEqual(jm.orientation_against((0, 0, -1), (0, 0, 1)), jm.ORIENT_DOWN)
        self.assertEqual(jm.orientation_against((1, 0, 0), (0, 0, 1)), jm.ORIENT_TILTED)


if __name__ == '__main__':
    unittest.main()
