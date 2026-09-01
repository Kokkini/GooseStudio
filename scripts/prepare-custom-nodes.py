#!/usr/bin/env python3
"""Stage the approved custom-node snapshot for the runtime image build."""

import shutil
import os
from pathlib import Path

SOURCE = Path(os.getenv("GOOSE_STUDIO_CUSTOM_NODES", "/mnt/f/Users/localuser/ComfyUI/custom_nodes"))
ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "image_custom_nodes"
MYHELPERS_PACKAGE = "ComfyUI-MyHelpers"
MYHELPERS_OVERLAY = ROOT / "myhelpers"

NODES = [
    "comfyui-videohelpersuite",
    "comfyui-easy-use",
    "comfyui-kjnodes",
    "rgthree-comfy",
    "seed-vc-mw",
    "seedvr2_videoupscaler",
    "comfyui_essentials",
    "ComfyUI-MyHelpers",
    "ComfyUI-MyWanAnimatePreprocess",
    "ComfyUI-WanAnimatePreprocess",
    "ComfyUI-Remove-Island-On-Mask",
    "comfyui-segment-anything-2",
    "ComfyUI-Hunyuan3d-2-1",
]

IGNORE = shutil.ignore_patterns(
    ".git",
    ".git-credentials",
    ".env",
    ".env.*",
    "credentials.json",
    "auth.json",
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "__pycache__",
    ".pytest_cache",
    "tests",
    "testframework",
    "example_workflows",
    "build",
    "dist",
    "*.so",
    "*.pyd",
    "*.pyc",
)


def main() -> None:
    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True)
    missing = []
    for node in NODES:
        source = SOURCE / node
        if not source.is_dir():
            missing.append(node)
            continue
        shutil.copytree(source, STAGING / node, ignore=IGNORE)
    if missing:
        raise SystemExit(f"Missing custom nodes: {', '.join(missing)}")
    _stage_myhelpers_overlay()
    print(STAGING)


def _patch_myhelpers_init(path: Path) -> None:
    """Register the approved overlay without replacing existing MyHelpers nodes."""

    text = path.read_text(encoding="utf-8")
    import_line = "from .long_edge_repair import RepairLongEdgeOutliers"
    if import_line not in text:
        marker = "\nNODE_CLASS_MAPPINGS = {"
        if marker not in text:
            raise RuntimeError(f"Could not find NODE_CLASS_MAPPINGS in {path}")
        text = text.replace(marker, f"\n{import_line}{marker}", 1)

    mapping_line = '    "RepairLongEdgeOutliers": RepairLongEdgeOutliers,'
    if mapping_line not in text:
        marker = "NODE_CLASS_MAPPINGS = {\n"
        if marker not in text:
            raise RuntimeError(f"Could not find NODE_CLASS_MAPPINGS in {path}")
        text = text.replace(marker, f"{marker}{mapping_line}\n", 1)

    display_line = '    "RepairLongEdgeOutliers": "Repair Long Edge Outliers",'
    if display_line not in text:
        marker = "NODE_DISPLAY_NAME_MAPPINGS = {\n"
        if marker not in text:
            raise RuntimeError(f"Could not find NODE_DISPLAY_NAME_MAPPINGS in {path}")
        text = text.replace(marker, f"{marker}{display_line}\n", 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def _stage_myhelpers_overlay() -> None:
    """Overlay the tested node into the existing ComfyUI-MyHelpers package."""

    package = STAGING / MYHELPERS_PACKAGE
    if not package.is_dir():
        raise SystemExit(f"Staged custom node is missing: {package}")

    for file_name in ("mesh_geometry.py", "long_edge_repair.py"):
        source = MYHELPERS_OVERLAY / file_name
        if not source.is_file():
            raise SystemExit(f"MyHelpers overlay file is missing: {source}")
        shutil.copy2(source, package / file_name)

    init_path = package / "__init__.py"
    if not init_path.is_file():
        raise SystemExit(f"MyHelpers package has no __init__.py: {init_path}")
    _patch_myhelpers_init(init_path)


if __name__ == "__main__":
    main()
