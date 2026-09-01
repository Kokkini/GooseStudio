"""Repair isolated long-edge outliers in regular Hunyuan3D meshes."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import trimesh as trimesh_lib

from .mesh_geometry import (
    _as_trimesh,
    _boundary_loops,
    _center_fan_caps,
    _directed_edge_in_face,
    _incident_faces_by_vertex,
    _is_closed_manifold,
    _normal_from_faces,
    _triangulate_polygon,
)


_EPSILON = 1e-12
_MIN_HUB_FACES = 16
_MIN_HUB_OUTLIER_FRACTION = 0.5


def _oriented_polygon_cap(
    loop: Sequence[int],
    cap: np.ndarray | None,
    retained_edge_directions: dict[tuple[int, int], tuple[int, int]],
) -> np.ndarray | None:
    """Orient and validate a polygon cap against its retained neighbors."""

    if cap is None or cap.shape[0] == 0 or len(loop) < 3:
        return None

    first = int(loop[0])
    second = int(loop[1])
    retained_direction = retained_edge_directions.get(tuple(sorted((first, second))))
    if retained_direction is None:
        return None

    retained_sign = 1 if retained_direction == (first, second) else -1
    cap_sign = next(
        (
            _directed_edge_in_face(face, first, second)
            for face in cap
            if _directed_edge_in_face(face, first, second)
        ),
        0,
    )
    if cap_sign == 0:
        return None
    if cap_sign == retained_sign:
        cap = cap[:, [0, 2, 1]]

    for index in range(len(loop)):
        first = int(loop[index])
        second = int(loop[(index + 1) % len(loop)])
        retained_direction = retained_edge_directions.get(tuple(sorted((first, second))))
        cap_sign = next(
            (
                _directed_edge_in_face(face, first, second)
                for face in cap
                if _directed_edge_in_face(face, first, second)
            ),
            0,
        )
        retained_sign = (
            1
            if retained_direction == (first, second)
            else -1
            if retained_direction == (second, first)
            else 0
        )
        if retained_sign == 0 or cap_sign == 0 or cap_sign == retained_sign:
            return None

    return cap


def _retained_edge_directions(
    faces: np.ndarray,
    removed_face_mask: np.ndarray,
    loops: Sequence[Sequence[int]],
) -> dict[tuple[int, int], tuple[int, int]]:
    boundary_edges = {
        tuple(sorted((int(loop[index]), int(loop[(index + 1) % len(loop)]))))
        for loop in loops
        for index in range(len(loop))
    }
    directions: dict[tuple[int, int], tuple[int, int]] = {}
    for face in faces[~removed_face_mask]:
        for index in range(3):
            first = int(face[index])
            second = int(face[(index + 1) % 3])
            key = tuple(sorted((first, second)))
            if key in boundary_edges and key not in directions:
                directions[key] = (first, second)
    return directions


def _finalize_mesh(vertices: np.ndarray, faces: np.ndarray) -> trimesh_lib.Trimesh:
    repaired = trimesh_lib.Trimesh(vertices=vertices, faces=faces, process=False)
    repaired.remove_unreferenced_vertices()
    return repaired


def _complete_outlier_hub_rings(
    faces: np.ndarray,
    removed_face_mask: np.ndarray,
    edges: np.ndarray,
    outlier_edge_ids: np.ndarray,
) -> np.ndarray:
    """Include the complete face ring around a concentrated outlier hub."""

    if outlier_edge_ids.size == 0:
        return removed_face_mask
    outlier_vertices = np.unique(edges[outlier_edge_ids].reshape(-1))
    incident_by_vertex = _incident_faces_by_vertex(faces, outlier_vertices)
    completed = removed_face_mask.copy()
    for incident in incident_by_vertex.values():
        outlier_face_count = int(np.count_nonzero(removed_face_mask[incident]))
        if (
            outlier_face_count >= _MIN_HUB_FACES
            and float(outlier_face_count) / float(incident.shape[0]) >= _MIN_HUB_OUTLIER_FRACTION
        ):
            completed[incident] = True
    return completed


def repair_long_edge_outliers(
    mesh: object,
    *,
    median_multiplier: float = 5.0,
    max_removed_face_fraction: float = 0.25,
    fill_holes: bool = True,
) -> tuple[trimesh_lib.Trimesh, dict[str, float | int]]:
    """Remove faces containing edges far outside the mesh edge distribution."""

    source = _as_trimesh(mesh)
    vertices = np.asarray(source.vertices, dtype=np.float64)
    faces = np.asarray(source.faces, dtype=np.int64)
    empty_stats = {
        "median_edge_length": 0.0,
        "threshold": 0.0,
        "outlier_edges": 0,
        "outlier_faces": 0,
        "removed_faces": 0,
        "added_faces": 0,
    }

    if vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError("The TRIMESH input must contain triangular vertices and faces")
    if faces.shape[0] == 0 or not _is_closed_manifold(vertices, faces):
        return source.copy(), empty_stats

    median_multiplier = max(float(median_multiplier), 1.0)
    max_removed_face_fraction = min(max(float(max_removed_face_fraction), 0.01), 0.9)
    edge_lengths = np.asarray(source.edges_unique_length, dtype=np.float64)
    valid_lengths = np.isfinite(edge_lengths) & (edge_lengths > _EPSILON)
    if not np.any(valid_lengths):
        return source.copy(), empty_stats

    median_edge_length = float(np.median(edge_lengths[valid_lengths]))
    threshold = median_edge_length * median_multiplier
    outlier_edge_ids = np.flatnonzero(valid_lengths & (edge_lengths > threshold))
    stats = {
        "median_edge_length": median_edge_length,
        "threshold": threshold,
        "outlier_edges": int(outlier_edge_ids.size),
        "outlier_faces": 0,
        "removed_faces": 0,
        "added_faces": 0,
    }
    if outlier_edge_ids.size == 0:
        return source.copy(), stats

    edge_ids_by_face = np.asarray(source.edges_unique_inverse, dtype=np.int64)
    if edge_ids_by_face.size != faces.shape[0] * 3:
        return source.copy(), stats
    edge_ids_by_face = edge_ids_by_face.reshape(faces.shape[0], 3)
    removed_face_mask = np.any(np.isin(edge_ids_by_face, outlier_edge_ids), axis=1)
    stats["outlier_faces"] = int(np.count_nonzero(removed_face_mask))
    removed_face_mask = _complete_outlier_hub_rings(
        faces,
        removed_face_mask,
        np.asarray(source.edges_unique, dtype=np.int64),
        outlier_edge_ids,
    )
    removed_count = int(np.count_nonzero(removed_face_mask))
    if removed_count == 0 or removed_count > int(faces.shape[0] * max_removed_face_fraction):
        return source.copy(), stats

    loops = _boundary_loops(faces, removed_face_mask)
    if not loops:
        return source.copy(), stats

    retained_faces = faces[~removed_face_mask]
    directions = _retained_edge_directions(faces, removed_face_mask, loops)
    repair_normal = _normal_from_faces(vertices, faces[removed_face_mask])
    cap_faces: list[np.ndarray] = []
    if fill_holes:
        for loop in loops:
            cap = _oriented_polygon_cap(
                loop,
                _triangulate_polygon(loop, vertices, repair_normal),
                directions,
            )
            if cap is None:
                cap_faces = []
                break
            cap_faces.append(cap)

    if not fill_holes:
        repaired = _finalize_mesh(vertices.copy(), retained_faces)
        stats["removed_faces"] = removed_count
        return repaired, stats

    if cap_faces:
        output_faces = np.concatenate([retained_faces, *cap_faces], axis=0)
        repaired = _finalize_mesh(vertices.copy(), output_faces)
        if _is_closed_manifold(
            np.asarray(repaired.vertices, dtype=np.float64),
            np.asarray(repaired.faces, dtype=np.int64),
        ):
            stats["removed_faces"] = removed_count
            stats["added_faces"] = int(sum(cap.shape[0] for cap in cap_faces))
            return repaired, stats

    # If an ear-clipped diagonal already exists in a retained component, use
    # new in-plane center vertices. This keeps every new internal edge unique.
    fallback = _center_fan_caps(vertices, loops, directions)
    if fallback is None:
        return source.copy(), stats
    center_vertices, fallback_faces = fallback
    output_vertices = np.concatenate((vertices, center_vertices), axis=0)
    output_faces = np.concatenate((retained_faces, fallback_faces), axis=0)
    if not _is_closed_manifold(output_vertices, output_faces):
        return source.copy(), stats

    repaired = _finalize_mesh(output_vertices, output_faces)
    stats["removed_faces"] = removed_count
    stats["added_faces"] = int(fallback_faces.shape[0])
    return repaired, stats


class RepairLongEdgeOutliers:
    """Remove face patches containing edges far above the mesh median."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "trimesh": ("TRIMESH",),
                "enabled": ("BOOLEAN", {"default": True}),
                "median_multiplier": (
                    "FLOAT",
                    {
                        "default": 5.0,
                        "min": 1.0,
                        "max": 1000.0,
                        "step": 0.1,
                        "tooltip": "Remove faces containing edges longer than this multiple of the positive median edge length.",
                    },
                ),
                "max_removed_face_fraction": (
                    "FLOAT",
                    {
                        "default": 0.25,
                        "min": 0.01,
                        "max": 0.9,
                        "step": 0.01,
                        "tooltip": "Safety limit for the fraction of faces that may be replaced.",
                    },
                ),
                "fill_holes": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("TRIMESH",)
    RETURN_NAMES = ("trimesh",)
    FUNCTION = "process"
    CATEGORY = "MyHelpers/Mesh"
    DESCRIPTION = (
        "Repairs regular meshes by removing faces with extreme edge-length "
        "outliers and safely capping the resulting holes."
    )

    def process(
        self,
        trimesh,
        enabled,
        median_multiplier,
        max_removed_face_fraction,
        fill_holes,
    ):
        if not enabled:
            print("[RepairLongEdgeOutliers] Disabled; passing the mesh through unchanged")
            return (_as_trimesh(trimesh).copy(),)

        repaired, stats = repair_long_edge_outliers(
            trimesh,
            median_multiplier=median_multiplier,
            max_removed_face_fraction=max_removed_face_fraction,
            fill_holes=fill_holes,
        )
        if stats["removed_faces"]:
            print(
                "[RepairLongEdgeOutliers] median=%.6g threshold=%.6g; "
                "%d outlier edge(s), removed %d face(s), added %d cap face(s)"
                % (
                    stats["median_edge_length"],
                    stats["threshold"],
                    stats["outlier_edges"],
                    stats["removed_faces"],
                    stats["added_faces"],
                )
            )
        else:
            print(
                "[RepairLongEdgeOutliers] median=%.6g threshold=%.6g; "
                "no safely repairable outlier patch detected"
                % (stats["median_edge_length"], stats["threshold"])
            )
        return (repaired,)
