import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "voxelize_glb.py"
SPEC = importlib.util.spec_from_file_location("goose_studio_voxelize_glb", SCRIPT)
VOXELIZER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VOXELIZER)


class VoxelizeGlbTest(unittest.TestCase):
    def test_converts_colored_glb_to_vox_at_requested_longest_side_resolution(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "colored-box.glb"
            output = directory / "colored-box.vox"
            mesh = trimesh.creation.box(extents=(2.0, 1.0, 0.5))
            mesh.visual.vertex_colors = np.tile(
                np.asarray([32, 160, 224, 255], dtype=np.uint8),
                (len(mesh.vertices), 1),
            )
            mesh.export(source)

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    str(source),
                    "--output",
                    str(output),
                    "--format",
                    "vox",
                    "--res",
                    "16",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertTrue(output.is_file())
            self.assertEqual(output.read_bytes()[:4], b"VOX ")

    def test_supports_clockwise_rotation_and_color_resolution(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "colored-box.glb"
            output = directory / "rotated-box.vox"
            report = directory / "rotated-box.json"
            mesh = trimesh.creation.box(extents=(2.0, 1.0, 0.5))
            mesh.visual.vertex_colors = np.tile(
                np.asarray([32, 160, 224, 255], dtype=np.uint8),
                (len(mesh.vertices), 1),
            )
            mesh.export(source)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    str(source),
                    "--output",
                    str(output),
                    "--format",
                    "vox",
                    "--res",
                    "16",
                    "--rotate-clockwise",
                    "90",
                    "--col-res",
                    "4",
                    "--report",
                    str(report),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            metadata = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(output.is_file())
            self.assertEqual(output.read_bytes()[:4], b"VOX ")
            self.assertEqual(metadata["rotation_clockwise_degrees"], 90.0)
            self.assertEqual(metadata["rotation_axis"], "y")
            self.assertEqual(metadata["rotation_pivot"], [0.0, 0.0, 0.0])
            self.assertEqual(metadata["color_resolution"], 4)
            self.assertIn("Applied clockwise Y-axis rotation: 90 degrees", result.stdout)
            self.assertIn("RGBA color levels per channel: 4", result.stdout)

    def test_quantize_color_uses_endpoint_inclusive_levels(self):
        self.assertEqual(
            VOXELIZER.quantize_color((0.1, 0.5, 1.0, 0.0), color_resolution=4),
            (0.0, 2.0 / 3.0, 1.0, 0.0),
        )

    def test_rejects_color_resolution_below_two(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--source",
                "missing.glb",
                "--output",
                "output.vox",
                "--col-res",
                "1",
            ],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--col-res must be between 2 and 256", result.stderr)

if __name__ == "__main__":
    unittest.main()
