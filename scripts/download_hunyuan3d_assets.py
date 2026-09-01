"""Pre-download the Hunyuan3D-2.1 paint pipeline and DINOv2 encoder.

The ComfyUI node downloads the paint snapshot lazily on the first textured
mesh request, then loads ``facebook/dinov2-giant`` for image features. Keep
both downloads in the Hugging Face Hub cache rather than using ``local_dir``:
the node expects the normal ``snapshot_download`` cache layout.

For Modal, pass the same persistent directory as ``cache_dir`` here and set
``HF_HUB_CACHE`` to that directory before starting ComfyUI in the worker.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Final


HUNYUAN_REPOSITORY: Final = "tencent/Hunyuan3D-2.1"
PAINT_SUBDIRECTORY: Final = "hunyuan3d-paintpbr-v2-1"
PAINT_ALLOW_PATTERNS: Final = (f"{PAINT_SUBDIRECTORY}/*",)
DINO_REPOSITORY: Final = "facebook/dinov2-giant"
DINO_ALLOW_PATTERNS: Final = (
    "config.json",
    "preprocessor_config.json",
    "model*.safetensors",
    "model*.safetensors.index.json",
    "pytorch_model*.bin",
    "pytorch_model*.bin.index.json",
)


def _validate_paint_snapshot(snapshot_root: Path) -> Path:
    """Ensure the filtered snapshot contains the files the paint pipeline needs."""

    paint_root = snapshot_root / PAINT_SUBDIRECTORY
    required_files = (
        "model_index.json",
        "scheduler/scheduler_config.json",
        "text_encoder/config.json",
        "tokenizer/tokenizer_config.json",
        "unet/config.json",
        "vae/config.json",
    )
    missing = [relative for relative in required_files if not (paint_root / relative).is_file()]
    if not any(
        (paint_root / relative).is_file()
        for relative in ("unet/diffusion_pytorch_model.bin", "unet/diffusion_pytorch_model.safetensors")
    ):
        missing.append("unet model weights (*.bin or *.safetensors)")
    if not any(
        (paint_root / relative).is_file()
        for relative in ("vae/diffusion_pytorch_model.bin", "vae/diffusion_pytorch_model.safetensors")
    ):
        missing.append("vae model weights (*.bin or *.safetensors)")
    if missing:
        raise RuntimeError(
            f"Hunyuan3D paint snapshot is incomplete at {paint_root}: missing {', '.join(missing)}"
        )
    return paint_root


def _validate_dinov2_snapshot(snapshot_root: Path) -> Path:
    """Ensure the DINOv2 snapshot contains its processor, config, and weights."""

    required_files = ("config.json", "preprocessor_config.json")
    missing = [relative for relative in required_files if not (snapshot_root / relative).is_file()]
    has_weights = any(snapshot_root.glob("*.safetensors")) or any(snapshot_root.glob("*.bin"))
    if not has_weights:
        missing.append("model weights (*.safetensors or *.bin)")
    if missing:
        raise RuntimeError(
            f"DINOv2 snapshot is incomplete at {snapshot_root}: missing {', '.join(missing)}"
        )
    return snapshot_root


def _download_snapshot(
    *,
    repository: str,
    allow_patterns: tuple[str, ...],
    cache_dir: str | Path | None,
    revision: str | None,
    label: str,
) -> Path:
    """Download one filtered Hub snapshot using the node-compatible cache layout."""

    from huggingface_hub import snapshot_download

    selected_revision = revision or None
    options = {
        "repo_id": repository,
        "allow_patterns": list(allow_patterns),
        "token": os.getenv("HF_TOKEN") or None,
    }
    if selected_revision:
        options["revision"] = selected_revision
    if cache_dir is not None:
        cache_path = Path(cache_dir)
        cache_path.mkdir(parents=True, exist_ok=True)
        options["cache_dir"] = str(cache_path)

    print(f"[hunyuan3d] Downloading {label} from {repository}", flush=True)
    return Path(snapshot_download(**options))


def download_hunyuan3d_paint_assets(
    *,
    cache_dir: str | Path | None = None,
    revision: str | None = None,
) -> Path:
    """Download and validate the Hunyuan3D PBR paint snapshot.

    ``cache_dir`` is the Hugging Face Hub cache root, not a ComfyUI model
    directory. Leaving it unset reproduces the custom node's normal behavior.
    ``HF_TOKEN`` and ``HUNYUAN3D_REVISION`` are read from the environment;
    credentials are never accepted on the command line or printed.
    """

    snapshot_root = _download_snapshot(
        repository=HUNYUAN_REPOSITORY,
        allow_patterns=PAINT_ALLOW_PATTERNS,
        cache_dir=cache_dir,
        revision=revision or os.getenv("HUNYUAN3D_REVISION"),
        label=PAINT_SUBDIRECTORY,
    )
    paint_root = _validate_paint_snapshot(snapshot_root)
    file_count = sum(1 for path in paint_root.rglob("*") if path.is_file())
    print(f"[hunyuan3d] Ready: {paint_root} ({file_count} files)", flush=True)
    return paint_root


def download_hunyuan3d_dinov2_assets(
    *,
    cache_dir: str | Path | None = None,
    revision: str | None = None,
) -> Path:
    """Download and validate the DINOv2 encoder used by the paint pipeline."""

    snapshot_root = _download_snapshot(
        repository=DINO_REPOSITORY,
        allow_patterns=DINO_ALLOW_PATTERNS,
        cache_dir=cache_dir,
        revision=revision or os.getenv("DINOV2_REVISION"),
        label="DINOv2 giant encoder",
    )
    dino_root = _validate_dinov2_snapshot(snapshot_root)
    file_count = sum(1 for path in dino_root.rglob("*") if path.is_file())
    print(f"[hunyuan3d] Ready: {dino_root} ({file_count} files)", flush=True)
    return dino_root


def download_hunyuan3d_assets(
    *,
    cache_dir: str | Path | None = None,
    hunyuan_revision: str | None = None,
    dinov2_revision: str | None = None,
) -> dict[str, Path]:
    """Download all Hugging Face snapshots used by the configured paint workflow."""

    return {
        "paint": download_hunyuan3d_paint_assets(
            cache_dir=cache_dir,
            revision=hunyuan_revision,
        ),
        "dinov2": download_hunyuan3d_dinov2_assets(
            cache_dir=cache_dir,
            revision=dinov2_revision,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Hugging Face Hub cache directory; use the same path as the worker's HF_HUB_CACHE",
    )
    parser.add_argument(
        "--revision",
        help="Optional Hunyuan branch, tag, or commit; defaults to HUNYUAN3D_REVISION or the repository default",
    )
    parser.add_argument(
        "--dinov2-revision",
        help="Optional DINOv2 branch, tag, or commit; defaults to DINOV2_REVISION or the repository default",
    )
    args = parser.parse_args()
    download_hunyuan3d_assets(
        cache_dir=args.cache_dir,
        hunyuan_revision=args.revision,
        dinov2_revision=args.dinov2_revision,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
