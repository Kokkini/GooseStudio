import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tools import unimate_worker

ROOT = Path(__file__).resolve().parents[1]


def _package(name):
    module = types.ModuleType(name)
    module.__path__ = []
    return module


class UniMateWorkerTests(unittest.TestCase):
    def test_generated_npy_uses_unimates_feature_animation_path(self):
        scratch_root = ROOT / "temp"
        scratch_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="unimate-worker-", dir=scratch_root
        ) as temp:
            root = Path(temp)
            asset = root / "deer.fbx"
            asset.write_bytes(b"rig")
            weights = root / "weights"
            (weights / "checkpoints").mkdir(parents=True)
            (weights / "config.json").write_text(
                json.dumps({"truebones": {}, "dataset": {}, "experiment": {}}),
                encoding="utf-8",
            )
            checkpoint = weights / "checkpoints" / "checkpoint_step_100000.pt"
            checkpoint.write_bytes(b"checkpoint")
            np.save(weights / "dataset_stats.npy", np.zeros((1,), dtype=np.float32))

            captured = {}

            def preprocess_asset(**kwargs):
                output_dir = Path(kwargs["output_dir"])
                output_dir.mkdir(parents=True, exist_ok=True)
                joint_count = 6
                cond = {
                    "parents": np.asarray([-1, 0, 1, 1, 0, 4]),
                    "tpos_first_frame": np.zeros((joint_count, 3), dtype=np.float32),
                    "tpos_local_rotations": np.tile(
                        np.asarray([1, 0, 0, 0], dtype=np.float32), (joint_count, 1)
                    ),
                }
                np.save(output_dir / "cond.npy", {asset.stem: cond})
                (output_dir / f"{asset.stem}_canonical.glb").write_bytes(b"canonical")
                return {asset.stem: cond}

            class InferenceArgs:
                def __init__(self, **kwargs):
                    self.__dict__.update(kwargs)

            def sample_motion(args):
                motion_dir = Path(args.output_dir) / "motions"
                motion_dir.mkdir(parents=True, exist_ok=True)
                np.save(motion_dir / "sample.npy", np.zeros((60, 6, 12), dtype=np.float32))

            def animate_character(**kwargs):
                captured.update(kwargs)
                output_dir = Path(kwargs["output_dir"])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "deer.glb").write_bytes(b"animated-glb")

            def save_blender_project(glb_path, blend_path):
                self.assertEqual(glb_path.read_bytes(), b"animated-glb")
                blend_path.write_bytes(b"blender-project")
                return blend_path

            fake_modules = {
                "data_process": _package("data_process"),
                "data_process.mesh_animation": _package("data_process.mesh_animation"),
                "data_process.mesh_animation.preprocess_char": types.ModuleType(
                    "data_process.mesh_animation.preprocess_char"
                ),
                "data_process.mesh_animation.animate_motion": types.ModuleType(
                    "data_process.mesh_animation.animate_motion"
                ),
                "unimate": _package("unimate"),
                "unimate.inference": _package("unimate.inference"),
                "unimate.inference.sample": types.ModuleType("unimate.inference.sample"),
            }
            fake_modules[
                "data_process.mesh_animation.preprocess_char"
            ].preprocess_asset = preprocess_asset
            fake_modules[
                "data_process.mesh_animation.animate_motion"
            ].animate_character = animate_character
            fake_modules["unimate.inference.sample"].InferenceArgs = InferenceArgs
            fake_modules["unimate.inference.sample"].main = sample_motion

            with (
                mock.patch.dict(sys.modules, fake_modules),
                mock.patch.object(unimate_worker, "UNIMATE_ROOT", root),
                mock.patch.object(unimate_worker, "MODEL_ROOT", weights),
                mock.patch.object(unimate_worker, "MODEL_CONFIG", weights / "config.json"),
                mock.patch.object(unimate_worker, "CHECKPOINT", checkpoint),
                mock.patch.object(unimate_worker, "_repo_imports"),
                mock.patch.object(unimate_worker, "save_blender_project", side_effect=save_blender_project),
            ):
                output_path = root / "result" / "animated_model.glb"
                result = unimate_worker.run_unimate(
                    asset_path=asset,
                    clip_path=None,
                    prompt="The deer walks.",
                    face_r=None,
                    face_l=None,
                    job_root=root / "job",
                    output_path=output_path,
                    progress=lambda _: None,
                )

            self.assertEqual(result, output_path)
            self.assertEqual(result.read_bytes(), b"animated-glb")
            self.assertEqual(result.with_suffix(".blend").read_bytes(), b"blender-project")
            self.assertEqual(captured["char_path"], str(asset))
            self.assertTrue(captured["anim_path"].endswith("sample.npy"))
            self.assertEqual(captured["cond_path"], str(root / "job" / "preprocessed" / "cond.npy"))
            self.assertEqual(captured["dataset_type"], "truebones")
            self.assertEqual(captured["anim_mode"], "fk")
            self.assertEqual(captured["extra_bones_strategy"], "merge")


if __name__ == "__main__":
    unittest.main()
