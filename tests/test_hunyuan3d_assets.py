import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "download_hunyuan3d_assets", ROOT / "scripts" / "download_hunyuan3d_assets.py"
)
assert SPEC and SPEC.loader
ASSETS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASSETS)


class Hunyuan3DAssetsTest(unittest.TestCase):
    def test_download_matches_hunyuan_snapshot_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "snapshot"
            paint = snapshot / ASSETS.PAINT_SUBDIRECTORY
            for relative in (
                "model_index.json",
                "scheduler/scheduler_config.json",
                "text_encoder/config.json",
                "tokenizer/tokenizer_config.json",
                "unet/config.json",
                "unet/diffusion_pytorch_model.bin",
                "vae/config.json",
                "vae/diffusion_pytorch_model.bin",
            ):
                path = paint / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")

            snapshot_download = mock.Mock(return_value=str(snapshot))
            fake_huggingface_hub = types.SimpleNamespace(snapshot_download=snapshot_download)
            with mock.patch.dict(sys.modules, {"huggingface_hub": fake_huggingface_hub}):
                result = ASSETS.download_hunyuan3d_paint_assets(
                    cache_dir=Path(temporary) / "hub-cache",
                    revision="test-revision",
                )

            self.assertEqual(paint, result)
            self.assertEqual(ASSETS.HUNYUAN_REPOSITORY, snapshot_download.call_args.kwargs["repo_id"])
            self.assertEqual(list(ASSETS.PAINT_ALLOW_PATTERNS), snapshot_download.call_args.kwargs["allow_patterns"])
            self.assertEqual("test-revision", snapshot_download.call_args.kwargs["revision"])
            self.assertEqual(
                str(Path(temporary) / "hub-cache"),
                snapshot_download.call_args.kwargs["cache_dir"],
            )

    def test_download_includes_dinov2_processor_and_weights(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "dinov2"
            for relative in ("config.json", "preprocessor_config.json", "model.safetensors"):
                path = snapshot / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")

            snapshot_download = mock.Mock(return_value=str(snapshot))
            fake_huggingface_hub = types.SimpleNamespace(snapshot_download=snapshot_download)
            with mock.patch.dict(sys.modules, {"huggingface_hub": fake_huggingface_hub}):
                result = ASSETS.download_hunyuan3d_dinov2_assets(
                    cache_dir=Path(temporary) / "hub-cache",
                    revision="test-dinov2-revision",
                )

            self.assertEqual(snapshot, result)
            self.assertEqual(ASSETS.DINO_REPOSITORY, snapshot_download.call_args.kwargs["repo_id"])
            self.assertEqual(
                list(ASSETS.DINO_ALLOW_PATTERNS),
                snapshot_download.call_args.kwargs["allow_patterns"],
            )
            self.assertEqual("test-dinov2-revision", snapshot_download.call_args.kwargs["revision"])


if __name__ == "__main__":
    unittest.main()
