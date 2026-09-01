#!/usr/bin/env python3
"""Install the long-edge repair overlay into a standalone ComfyUI checkout.

The standalone ComfyUI workflow saved by the UI is a graph document with
``nodes`` and ``links`` arrays, while Goose Studio submits API-format
dictionaries. This installer patches either representation and keeps a
sibling backup of the workflow before writing it.

The node is added to the existing ``ComfyUI-MyHelpers`` package. No separate
workflow-specific custom-node package is created.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
NODE_SOURCE = ROOT / "myhelpers"
MYHELPERS_PACKAGE = "ComfyUI-MyHelpers"
REPAIR_CLASS = "RepairLongEdgeOutliers"
REPAIR_INPUTS = {
    "enabled": True,
    "median_multiplier": 5.0,
    "max_removed_face_fraction": 0.25,
    "fill_holes": True,
}


def _patch_myhelpers_init(path: Path) -> None:
    """Register the node without replacing existing MyHelpers nodes."""

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


def _find_node(nodes: list[dict[str, Any]], node_type: str) -> dict[str, Any]:
    for node in nodes:
        if node.get("type") == node_type:
            return node
    raise ValueError(f"Could not find a {node_type} node in the workflow")


def _find_api_node(workflow: dict[str, Any], class_type: str) -> tuple[str, dict[str, Any]]:
    for node_id, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") == class_type:
            return str(node_id), node
    raise ValueError(f"Could not find a {class_type} node in the API workflow")


def _next_numeric_id(values: list[Any], fallback: str) -> str:
    numeric = []
    for value in values:
        try:
            numeric.append(int(value))
        except (TypeError, ValueError):
            continue
    return str(max(numeric, default=0) + 1) if numeric else fallback


def _api_repair_node(post_id: str) -> dict[str, Any]:
    return {
        "inputs": {
            "trimesh": [post_id, 0],
            **REPAIR_INPUTS,
        },
        "class_type": REPAIR_CLASS,
        "_meta": {"title": "Repair Long Edge Outliers"},
    }


def patch_api_workflow(workflow: dict[str, Any]) -> str:
    """Insert or reconnect the repair node in a ComfyUI API workflow."""

    post_id, _post = _find_api_node(workflow, "Hy3D21PostprocessMesh")
    uv_id, uv = _find_api_node(workflow, "Hy3D21MeshUVWrap")
    try:
        repair_id, repair = _find_api_node(workflow, REPAIR_CLASS)
    except ValueError:
        repair_id = _next_numeric_id(list(workflow), "60")
        repair = _api_repair_node(post_id)
        workflow[repair_id] = repair

    repair["inputs"] = {"trimesh": [post_id, 0], **REPAIR_INPUTS}
    repair["_meta"] = {"title": "Repair Long Edge Outliers"}
    uv.setdefault("inputs", {})["trimesh"] = [repair_id, 0]
    return repair_id


def _remove_ui_link(workflow: dict[str, Any], link_id: int) -> None:
    workflow["links"] = [link for link in workflow.get("links", []) if link[0] != link_id]
    for node in workflow.get("nodes", []):
        for node_input in node.get("inputs", []):
            if node_input.get("link") == link_id:
                node_input["link"] = None
        for output in node.get("outputs", []):
            links = output.get("links")
            if isinstance(links, list):
                output["links"] = [value for value in links if value != link_id]


def _ui_repair_node(
    node_id: int,
    post: dict[str, Any],
    repair_order: int,
    incoming: int,
    outgoing: list[int],
) -> dict[str, Any]:
    post_pos = post.get("pos", [0, 0])
    inputs = [
        {"localized_name": "trimesh", "name": "trimesh", "type": "TRIMESH", "link": incoming},
    ]
    widget_types = (
        ("enabled", "BOOLEAN"),
        ("median_multiplier", "FLOAT"),
        ("max_removed_face_fraction", "FLOAT"),
        ("fill_holes", "BOOLEAN"),
    )
    inputs.extend(
        {
            "localized_name": name,
            "name": name,
            "type": value_type,
            "widget": {"name": name},
            "link": None,
        }
        for name, value_type in widget_types
    )
    return {
        "id": node_id,
        "type": REPAIR_CLASS,
        "pos": [float(post_pos[0]), float(post_pos[1]) + 230.0],
        "size": [360.0, 220.0],
        "flags": {},
        "order": repair_order,
        "mode": 0,
        "inputs": inputs,
        "outputs": [
            {
                "localized_name": "trimesh",
                "name": "trimesh",
                "type": "TRIMESH",
                "links": outgoing,
            }
        ],
        "properties": {
            "Node name for S&R": REPAIR_CLASS,
            "widget_ue_connectable": {},
        },
        "widgets_values": list(REPAIR_INPUTS.values()),
    }


def _mesh_input_destinations(
    workflow: dict[str, Any],
    post_id: int,
    repair_id: int | None,
    uv_id: int,
) -> list[tuple[int, int, str]]:
    """Collect mesh consumers, retaining branches already connected to post."""

    destinations: list[tuple[int, int, str]] = []
    for link in workflow.get("links", []):
        if len(link) < 6 or link[1] != post_id or link[2] != 0:
            continue
        if repair_id is not None and link[3] == repair_id:
            continue
        destination = (int(link[3]), int(link[4]), str(link[5]))
        if destination not in destinations:
            destinations.append(destination)

    uv_destination = (uv_id, 0, "TRIMESH")
    if uv_destination not in destinations:
        destinations.append(uv_destination)
    return destinations


def patch_ui_workflow(workflow: dict[str, Any]) -> int:
    """Insert or reconnect the repair node in a ComfyUI UI workflow."""

    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("UI workflow has no nodes array")
    post = _find_node(nodes, "Hy3D21PostprocessMesh")
    uv = _find_node(nodes, "Hy3D21MeshUVWrap")
    exporters = [node for node in nodes if node.get("type") == "Hy3D21ExportMesh"]
    existing = next((node for node in nodes if node.get("type") == REPAIR_CLASS), None)

    node_id = int(existing["id"]) if existing is not None else int(
        _next_numeric_id([node.get("id") for node in nodes], "60")
    )
    existing_order = int(existing.get("order", 0)) if existing is not None else 0
    destinations = _mesh_input_destinations(
        workflow,
        int(post["id"]),
        node_id if existing is not None else None,
        int(uv["id"]),
    )
    for exporter in exporters:
        destination = (int(exporter["id"]), 0, "TRIMESH")
        if destination not in destinations:
            destinations.append(destination)

    links_to_remove = []
    for link in workflow.get("links", []):
        origin_id, target_id = link[1], link[3]
        if (
            origin_id == post["id"]
            or (existing is not None and (origin_id == node_id or target_id == node_id))
            or any(target_id == destination[0] and link[4] == destination[1] for destination in destinations)
        ):
            links_to_remove.append(link[0])
    for link_id in links_to_remove:
        _remove_ui_link(workflow, link_id)

    last_link_id = max(
        int(workflow.get("last_link_id", 0)),
        max((int(link[0]) for link in workflow.get("links", [])), default=0),
    )
    incoming = last_link_id + 1
    outgoing = list(range(incoming + 1, incoming + 1 + len(destinations)))
    workflow.setdefault("links", []).append(
        [incoming, int(post["id"]), 0, node_id, 0, "TRIMESH"]
    )
    for link_id, (destination_id, destination_slot, destination_type) in zip(outgoing, destinations):
        workflow["links"].append(
            [link_id, node_id, 0, destination_id, destination_slot, destination_type]
        )

    post_output = next(
        (output for output in post.get("outputs", []) if output.get("name") == "trimesh"),
        None,
    )
    if post_output is None:
        raise ValueError("Postprocess node has no trimesh output")
    post_output.setdefault("links", []).append(incoming)

    destination_nodes = {int(node["id"]): node for node in nodes}
    for link_id, (destination_id, destination_slot, _destination_type) in zip(outgoing, destinations):
        destination_node = destination_nodes.get(destination_id)
        if destination_node is None:
            raise ValueError(f"Could not find mesh destination node {destination_id}")
        matching_inputs = [
            node_input
            for node_input in destination_node.get("inputs", [])
            if node_input.get("name") == "trimesh" and destination_slot == 0
        ]
        if not matching_inputs:
            raise ValueError(f"Node {destination_id} has no trimesh input")
        matching_inputs[0]["link"] = link_id

    if existing is None:
        post_order = int(post.get("order", 0))
        for node in nodes:
            if int(node.get("order", 0)) > post_order:
                node["order"] = int(node["order"]) + 1
        nodes.append(_ui_repair_node(node_id, post, post_order + 1, incoming, outgoing))
    else:
        existing.clear()
        existing.update(_ui_repair_node(node_id, post, existing_order, incoming, outgoing))

    workflow["last_node_id"] = max(int(workflow.get("last_node_id", 0)), node_id)
    workflow["last_link_id"] = max(int(workflow.get("last_link_id", 0)), *(outgoing or [incoming]))
    return node_id


def patch_workflow(path: Path, *, make_backup: bool = True) -> tuple[str, Path | None]:
    """Patch a workflow file and return its format plus backup path."""

    original = path.read_text(encoding="utf-8")
    workflow = json.loads(original)
    if isinstance(workflow, dict) and isinstance(workflow.get("nodes"), list):
        patch_ui_workflow(workflow)
        workflow_format = "ui"
    elif isinstance(workflow, dict):
        patch_api_workflow(workflow)
        workflow_format = "api"
    else:
        raise ValueError("Workflow JSON must contain an object")

    backup_path = None
    if make_backup:
        backup_path = path.with_suffix(path.suffix + ".bak")
        index = 1
        while backup_path.exists():
            backup_path = path.with_suffix(path.suffix + f".bak.{index}")
            index += 1
        shutil.copy2(path, backup_path)

    path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return workflow_format, backup_path


def install_node(comfyui_root: Path) -> Path:
    destination = comfyui_root / "custom_nodes" / MYHELPERS_PACKAGE
    if not destination.is_dir():
        raise FileNotFoundError(
            f"The existing MyHelpers package was not found: {destination}"
        )
    for file_name in ("mesh_geometry.py", "long_edge_repair.py"):
        source = NODE_SOURCE / file_name
        if not source.is_file():
            raise FileNotFoundError(f"MyHelpers overlay file is missing: {source}")
        shutil.copy2(source, destination / file_name)
    init_path = destination / "__init__.py"
    if not init_path.is_file():
        raise FileNotFoundError(f"MyHelpers package has no __init__.py: {init_path}")
    _patch_myhelpers_init(init_path)
    return destination


def _default_workflow(comfyui_root: Path) -> Path:
    preferred = comfyui_root / "user" / "default" / "workflows" / "image_to_3D_HY2.1.json"
    if preferred.is_file():
        return preferred
    matches = sorted(comfyui_root.glob("user/*/workflows/image_to_3D_HY2.1.json"))
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError(
        "Could not locate image_to_3D_HY2.1.json; pass its path with --workflow"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--comfyui-root",
        required=True,
        type=Path,
        help="Standalone ComfyUI installation directory",
    )
    parser.add_argument(
        "--workflow",
        type=Path,
        help="Workflow JSON; defaults to user/default/workflows/image_to_3D_HY2.1.json",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a .bak copy before changing the workflow",
    )
    args = parser.parse_args()

    comfyui_root = args.comfyui_root.resolve()
    if not comfyui_root.is_dir():
        raise SystemExit(f"ComfyUI root does not exist: {comfyui_root}")
    workflow = (args.workflow or _default_workflow(comfyui_root)).resolve()
    if not workflow.is_file():
        raise SystemExit(f"Workflow does not exist: {workflow}")

    destination = install_node(comfyui_root)
    workflow_format, backup = patch_workflow(workflow, make_backup=not args.no_backup)
    print(f"Installed {REPAIR_CLASS} in {destination}")
    print(f"Patched {workflow_format} workflow: {workflow}")
    if backup is not None:
        print(f"Backup: {backup}")


if __name__ == "__main__":
    main()
