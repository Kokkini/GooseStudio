import unittest

import numpy as np
import trimesh

from myhelpers.long_edge_repair import repair_long_edge_outliers


def make_bad_cylinder(ring_size=64):
    angles = np.arange(ring_size, dtype=np.float64) * 2.0 * np.pi / ring_size
    top = np.column_stack((np.cos(angles), np.sin(angles), np.full(ring_size, 0.5)))
    bottom = np.column_stack((np.cos(angles), np.sin(angles), np.full(ring_size, -0.5)))
    vertices = np.vstack((top, bottom, [[0.0, 0.0, 10.0], [0.0, 0.0, -10.0]]))
    top_center = 2 * ring_size
    bottom_center = top_center + 1

    faces = []
    for index in range(ring_size):
        following = (index + 1) % ring_size
        faces.extend(
            (
                [top_center, index, following],
                [bottom_center, ring_size + following, ring_size + index],
                [index, ring_size + index, ring_size + following],
                [index, ring_size + following, following],
            )
        )

    return trimesh.Trimesh(
        vertices=vertices,
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
    )


class LongEdgeRepairTest(unittest.TestCase):
    def test_replaces_long_edge_hub_rings_and_keeps_closed_winding(self):
        mesh = make_bad_cylinder()
        repaired, stats = repair_long_edge_outliers(mesh, max_removed_face_fraction=0.75)

        self.assertEqual(stats["outlier_edges"], 128)
        self.assertEqual(stats["outlier_faces"], 128)
        self.assertEqual(stats["removed_faces"], 128)
        self.assertEqual(stats["added_faces"], 124)
        self.assertEqual(len(mesh.faces), 256)
        self.assertEqual(len(repaired.faces), 252)
        self.assertTrue(repaired.is_watertight)
        self.assertTrue(repaired.is_winding_consistent)

    def test_multiplier_can_leave_a_regular_mesh_unchanged(self):
        mesh = make_bad_cylinder()
        repaired, stats = repair_long_edge_outliers(mesh, median_multiplier=100.0)

        self.assertEqual(stats["outlier_edges"], 0)
        self.assertEqual(stats["removed_faces"], 0)
        self.assertTrue(np.array_equal(repaired.faces, mesh.faces))


if __name__ == "__main__":
    unittest.main()
