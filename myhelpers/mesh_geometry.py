"""Small, dependency-light mesh geometry helpers used by MyHelpers nodes."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Sequence

import numpy as np
import trimesh as trimesh_lib


_EPSILON = 1e-12


def _face_edges(faces: np.ndarray) -> np.ndarray:
    """Return the three undirected edge endpoints for every triangular face."""

    return np.concatenate(
        (
            faces[:, [0, 1]],
            faces[:, [1, 2]],
            faces[:, [2, 0]],
        ),
        axis=0,
    )


def _incident_faces_by_vertex(
    faces: np.ndarray,
    vertices_to_check: Iterable[int],
) -> dict[int, np.ndarray]:
    """Build incident-face lists for only the supplied candidate vertices."""

    candidates = np.asarray(list(vertices_to_check), dtype=np.int64)
    if candidates.size == 0:
        return {}

    flat_vertices = faces.reshape(-1)
    face_ids = np.repeat(np.arange(faces.shape[0], dtype=np.int64), 3)
    order = np.argsort(flat_vertices, kind="stable")
    sorted_vertices = flat_vertices[order]
    sorted_face_ids = face_ids[order]

    result: dict[int, np.ndarray] = {}
    for vertex in candidates:
        start = int(np.searchsorted(sorted_vertices, vertex, side="left"))
        end = int(np.searchsorted(sorted_vertices, vertex, side="right"))
        if end > start:
            result[int(vertex)] = np.unique(sorted_face_ids[start:end])
    return result


def _edge_incidence_counts(faces: np.ndarray) -> np.ndarray:
    if faces.shape[0] == 0:
        return np.empty(0, dtype=np.int64)
    _, counts = np.unique(
        np.sort(_face_edges(faces), axis=1),
        axis=0,
        return_counts=True,
    )
    return counts


def _is_closed_manifold(vertices: np.ndarray, faces: np.ndarray) -> bool:
    """Require two-sided edge incidence and consistent winding."""

    counts = _edge_incidence_counts(faces)
    if counts.size == 0 or not np.all(counts == 2):
        return False
    candidate = trimesh_lib.Trimesh(vertices=vertices, faces=faces, process=False)
    return bool(candidate.is_winding_consistent)


def _normal_from_faces(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    if faces.shape[0] == 0:
        return np.zeros(3, dtype=np.float64)
    triangles = vertices[faces]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    normal = normals.sum(axis=0)
    length = float(np.linalg.norm(normal))
    if length <= _EPSILON:
        return np.zeros(3, dtype=np.float64)
    return normal / length


def _boundary_loops(faces: np.ndarray, removed_face_mask: np.ndarray) -> list[list[int]]:
    """Return interface loops between removed and retained faces."""

    all_edges = _face_edges(faces)
    canonical_edges = np.sort(all_edges, axis=1)
    unique_edges, inverse, edge_counts = np.unique(
        canonical_edges,
        axis=0,
        return_inverse=True,
        return_counts=True,
    )
    # _face_edges concatenates edge 0 for every face, then edge 1, then edge
    # 2, so the face mask must be tiled in that same order.
    repeated_removed = np.tile(removed_face_mask.astype(np.int8), 3)
    removed_counts = np.bincount(
        inverse,
        weights=repeated_removed,
        minlength=unique_edges.shape[0],
    )
    interface_mask = (edge_counts == 2) & (removed_counts == 1)
    interface_edges = unique_edges[interface_mask]
    if interface_edges.shape[0] == 0:
        return []

    adjacency: dict[int, list[int]] = defaultdict(list)
    for first, second in interface_edges:
        first = int(first)
        second = int(second)
        adjacency[first].append(second)
        adjacency[second].append(first)

    # A cap can be constructed safely only from closed simple loops.
    if any(len(neighbors) != 2 for neighbors in adjacency.values()):
        return []

    remaining_edges = {
        tuple(sorted((int(first), int(second))))
        for first, second in interface_edges
    }
    loops: list[list[int]] = []
    while remaining_edges:
        first_edge = next(iter(remaining_edges))
        start, current = first_edge
        loop = [start]
        previous = -1

        while True:
            loop.append(current)
            remaining_edges.discard(
                tuple(sorted((previous if previous >= 0 else start, current)))
            )
            neighbors = adjacency[current]
            next_vertex = neighbors[0] if neighbors[0] != previous else neighbors[1]
            previous, current = current, next_vertex
            if current == start:
                break
            if len(loop) > len(adjacency) + 1:
                return []

        remaining_edges.discard(tuple(sorted(first_edge)))
        if len(loop) >= 3:
            loops.append(loop)

    return loops


def _center_fan_caps(
    vertices: np.ndarray,
    loops: Sequence[Sequence[int]],
    retained_edge_directions: dict[tuple[int, int], tuple[int, int]],
) -> tuple[np.ndarray, np.ndarray] | None:
    """Create planar center caps without reusing retained internal edges."""

    centers: list[np.ndarray] = []
    cap_faces: list[list[int]] = []
    center_start = vertices.shape[0]
    for loop in loops:
        loop_indices = [int(index) for index in loop]
        points = vertices[np.asarray(loop_indices, dtype=np.int64)]
        center = points.mean(axis=0)
        if not np.isfinite(center).all():
            return None
        center_index = center_start + len(centers)
        centers.append(center)

        for index, first in enumerate(loop_indices):
            second = loop_indices[(index + 1) % len(loop_indices)]
            retained = retained_edge_directions.get(tuple(sorted((first, second))))
            if retained == (first, second):
                face = [second, first, center_index]
            elif retained == (second, first):
                face = [first, second, center_index]
            else:
                return None
            triangle = vertices[np.asarray(face[:2])] - center
            if np.linalg.norm(np.cross(triangle[0], triangle[1])) <= _EPSILON:
                return None
            cap_faces.append(face)

    if not centers or not cap_faces:
        return None
    return np.asarray(centers, dtype=np.float64), np.asarray(cap_faces, dtype=np.int64)


def _signed_area(points: np.ndarray) -> float:
    return float(
        0.5
        * np.sum(
            points[:, 0] * np.roll(points[:, 1], -1)
            - points[:, 1] * np.roll(points[:, 0], -1)
        )
    )


def _cross_2d(first: np.ndarray, second: np.ndarray, third: np.ndarray) -> float:
    ab = second - first
    ac = third - first
    return float(ab[0] * ac[1] - ab[1] * ac[0])


def _directed_edge_in_face(face: Sequence[int], first: int, second: int) -> int:
    """Return +1/-1 for the direction of an edge in a wound triangle."""

    for index in range(3):
        start = int(face[index])
        end = int(face[(index + 1) % 3])
        if start == first and end == second:
            return 1
        if start == second and end == first:
            return -1
    return 0


def _point_in_ccw_triangle(
    points: np.ndarray,
    first: np.ndarray,
    second: np.ndarray,
    third: np.ndarray,
    tolerance: float,
) -> bool:
    """Vectorized point-in-triangle test for an array of 2D points."""

    if points.shape[0] == 0:
        return False
    c1 = (second[0] - first[0]) * (points[:, 1] - first[1]) - (second[1] - first[1]) * (points[:, 0] - first[0])
    c2 = (third[0] - second[0]) * (points[:, 1] - second[1]) - (third[1] - second[1]) * (points[:, 0] - second[0])
    c3 = (first[0] - third[0]) * (points[:, 1] - third[1]) - (first[1] - third[1]) * (points[:, 0] - third[0])
    inside = (c1 >= -tolerance) & (c2 >= -tolerance) & (c3 >= -tolerance)
    return bool(np.any(inside))


def _triangulate_polygon(
    loop: Sequence[int],
    vertices: np.ndarray,
    normal: np.ndarray,
) -> np.ndarray | None:
    """Triangulate a simple 3D loop in its best-fit plane using ear clipping."""

    boundary_indices = [int(index) for index in loop]
    points = vertices[np.asarray(boundary_indices, dtype=np.int64)].astype(np.float64, copy=False)
    if points.shape[0] < 3:
        return None

    center = points.mean(axis=0)
    centered = points - center
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    fitted_normal = vh[-1]
    plane_normal = np.asarray(normal, dtype=np.float64)
    plane_length = float(np.linalg.norm(plane_normal))
    if plane_length <= _EPSILON or abs(float(np.dot(plane_normal, fitted_normal))) < 0.5:
        plane_normal = fitted_normal
        plane_length = float(np.linalg.norm(plane_normal))
    if plane_length <= _EPSILON:
        return None
    plane_normal /= plane_length

    tangent = vh[0] - plane_normal * np.dot(vh[0], plane_normal)
    tangent_length = float(np.linalg.norm(tangent))
    if tangent_length <= _EPSILON:
        tangent = vh[1] - plane_normal * np.dot(vh[1], plane_normal)
        tangent_length = float(np.linalg.norm(tangent))
    if tangent_length <= _EPSILON:
        return None
    tangent /= tangent_length
    bitangent = np.cross(plane_normal, tangent)
    bitangent /= max(float(np.linalg.norm(bitangent)), _EPSILON)
    points_2d = np.column_stack((centered @ tangent, centered @ bitangent))

    scale = max(float(np.max(np.linalg.norm(centered, axis=1))), 1.0)
    collinear_tolerance = 1e-10 * scale * scale

    if _signed_area(points_2d) < 0:
        boundary_indices.reverse()
        points_2d = points_2d[::-1].copy()

    # Remove collinear boundary vertices while remembering the original loop;
    # the omitted vertices are put back by splitting the affected cap edge.
    loop_indices = boundary_indices.copy()
    simplified_points = points_2d.copy()
    changed = True
    while changed and len(loop_indices) > 3:
        changed = False
        for index in range(len(loop_indices)):
            previous = (index - 1) % len(loop_indices)
            following = (index + 1) % len(loop_indices)
            if np.linalg.norm(simplified_points[index] - simplified_points[previous]) <= 1e-10 * scale:
                return None
            if abs(_cross_2d(simplified_points[previous], simplified_points[index], simplified_points[following])) <= collinear_tolerance:
                del loop_indices[index]
                simplified_points = np.delete(simplified_points, index, axis=0)
                changed = True
                break

    if len(loop_indices) < 3 or abs(_signed_area(simplified_points)) <= collinear_tolerance:
        return None

    remaining = list(range(len(loop_indices)))
    triangles: list[list[int]] = []
    max_iterations = len(remaining) * len(remaining)
    iterations = 0
    ear_tolerance = 1e-10 * scale * scale

    while len(remaining) > 3 and iterations < max_iterations:
        clipped = False
        iterations += 1
        for position, current in enumerate(remaining):
            previous = remaining[(position - 1) % len(remaining)]
            following = remaining[(position + 1) % len(remaining)]
            a = simplified_points[previous]
            b = simplified_points[current]
            c = simplified_points[following]
            if _cross_2d(a, b, c) <= ear_tolerance:
                continue

            others = [index for index in remaining if index not in (previous, current, following)]
            if others and _point_in_ccw_triangle(
                simplified_points[np.asarray(others, dtype=np.int64)],
                a,
                b,
                c,
                ear_tolerance,
            ):
                continue

            triangles.append([loop_indices[previous], loop_indices[current], loop_indices[following]])
            del remaining[position]
            clipped = True
            break

        if not clipped:
            return None

    if len(remaining) != 3:
        return None
    triangles.append([loop_indices[index] for index in remaining])

    # Reinsert any original boundary vertices omitted as collinear points.
    boundary_position = {vertex: index for index, vertex in enumerate(boundary_indices)}
    cap_faces = [list(face) for face in triangles]
    for edge_index, first in enumerate(loop_indices):
        second = loop_indices[(edge_index + 1) % len(loop_indices)]
        first_position = boundary_position.get(first)
        second_position = boundary_position.get(second)
        if first_position is None or second_position is None:
            return None

        chain = [first]
        position = first_position
        while position != second_position:
            position = (position + 1) % len(boundary_indices)
            chain.append(boundary_indices[position])
            if len(chain) > len(boundary_indices) + 1:
                return None
        if len(chain) <= 2:
            continue

        edge_key = frozenset((first, second))
        cap_index = next(
            (
                index
                for index, face in enumerate(cap_faces)
                if edge_key.issubset(face)
            ),
            None,
        )
        if cap_index is None:
            return None
        original_face = cap_faces[cap_index]
        opposite = next(vertex for vertex in original_face if vertex not in edge_key)
        forward = any(
            original_face[index] == first
            and original_face[(index + 1) % 3] == second
            for index in range(3)
        )
        replacement = []
        for first_segment, second_segment in zip(chain, chain[1:]):
            if forward:
                replacement.append([first_segment, second_segment, opposite])
            else:
                replacement.append([second_segment, first_segment, opposite])
        cap_faces[cap_index : cap_index + 1] = replacement

    return np.asarray(cap_faces, dtype=np.int64)


def _as_trimesh(mesh: object) -> trimesh_lib.Trimesh:
    if isinstance(mesh, trimesh_lib.Trimesh):
        return mesh
    if isinstance(mesh, trimesh_lib.Scene):
        geometries = [
            geometry
            for geometry in mesh.geometry.values()
            if isinstance(geometry, trimesh_lib.Trimesh)
        ]
        if not geometries:
            raise TypeError("The TRIMESH input scene has no mesh geometry")
        return trimesh_lib.util.concatenate(geometries)
    raise TypeError(f"Expected a trimesh.Trimesh or Scene, got {type(mesh).__name__}")
