"""Pure, read-only topology profiling for Revit fire-branch snapshots.

This module deliberately does not choose fittings, move elements, or create a
model plan. It only describes the graph that has already been captured.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from itertools import combinations
from typing import Any


_AXES = ("x", "y", "z")


def _point_values(point: Mapping[str, Any] | Sequence[float]) -> tuple[float, float, float]:
    if isinstance(point, Mapping):
        return (
            float(point.get("x", 0.0)),
            float(point.get("y", 0.0)),
            float(point.get("z", 0.0)),
        )
    if len(point) != 3:
        raise ValueError("路徑點必須包含 x、y、z 三個座標")
    return float(point[0]), float(point[1]), float(point[2])


def _axis(delta: tuple[float, float, float], tolerance: float) -> str:
    magnitudes = [abs(value) for value in delta]
    length = max(magnitudes)
    if length <= tolerance:
        return "duplicate"
    non_dominant = sum(value for value in magnitudes if value != length)
    if non_dominant > max(tolerance, length * 1e-3):
        return "oblique"
    return _AXES[magnitudes.index(length)]


def _classify_axes(axes: Sequence[str]) -> tuple[str, int]:
    turns = sum(previous != current for previous, current in zip(axes, axes[1:]))
    if not axes:
        return "empty", turns
    if "oblique" in axes:
        return "unknown", turns
    if turns == 0:
        return "linear", turns
    if turns == 1:
        return "L", turns
    if turns == 2 and len(axes) == 3 and axes[0] == axes[-1]:
        return "U", turns
    if turns == 4 and len(axes) == 5 and axes[0] == axes[-1]:
        return "double_L", turns
    return "compound_bend", turns


def classify_axis_polyline(
    points: Iterable[Mapping[str, Any] | Sequence[float]],
    *,
    tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Classify an ordered axis-aligned route without mutating its points."""

    raw_points = [_point_values(point) for point in points]
    compact: list[tuple[float, float, float]] = []
    for point in raw_points:
        if not compact or any(abs(a - b) > tolerance for a, b in zip(compact[-1], point)):
            compact.append(point)
    if len(compact) < 2:
        return {"shape_class": "empty", "segment_count": 0, "turn_count": 0, "axes": []}

    axes: list[str] = []
    for start, end in zip(compact, compact[1:]):
        delta = tuple(b - a for a, b in zip(start, end))
        segment_axis = _axis(delta, tolerance)
        if segment_axis != "duplicate":
            axes.append(segment_axis)

    shape_class, turns = _classify_axes(axes)

    return {
        "shape_class": shape_class,
        "segment_count": len(axes),
        "turn_count": turns,
        "axes": axes,
        "start": {"x": compact[0][0], "y": compact[0][1], "z": compact[0][2]},
        "end": {"x": compact[-1][0], "y": compact[-1][1], "z": compact[-1][2]},
    }


def summarize_fire_branch_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize a captured graph for review; never changes Revit data."""

    graph = snapshot.get("main_graph")
    if not isinstance(graph, Mapping):
        raise ValueError("快照缺少 main_graph")
    elements = [item for item in graph.get("elements", []) if isinstance(item, Mapping)]
    edges = [item for item in graph.get("edges", []) if isinstance(item, Mapping)]
    connections = [item for item in graph.get("connections", []) if isinstance(item, Mapping)]
    element_ids = {int(item["element_id"]) for item in elements if "element_id" in item}
    adjacency: dict[int, set[int]] = defaultdict(set)
    for connection in connections:
        try:
            first = int(connection["from_element_id"])
            second = int(connection["to_element_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if first in element_ids and second in element_ids and first != second:
            adjacency[first].add(second)
            adjacency[second].add(first)

    components: list[list[int]] = []
    visited: set[int] = set()
    for element_id in sorted(element_ids):
        if element_id in visited:
            continue
        component: list[int] = []
        queue = deque([element_id])
        visited.add(element_id)
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbour in adjacency[current]:
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append(neighbour)
        components.append(component)

    kind_counts = Counter(str(item.get("kind") or "unknown") for item in elements)
    pipe_elements = [item for item in elements if item.get("kind") == "pipe"]
    pipe_axis_counts: Counter[str] = Counter()
    pipe_lengths: list[float] = []
    for pipe in pipe_elements:
        geometry = pipe.get("geometry")
        if not isinstance(geometry, Mapping):
            continue
        start = geometry.get("start")
        end = geometry.get("end")
        if isinstance(start, Mapping) and isinstance(end, Mapping):
            delta = tuple(
                float(end.get(axis, 0.0)) - float(start.get(axis, 0.0)) for axis in _AXES
            )
            pipe_axis_counts[_axis(delta, 1e-6)] += 1
        try:
            pipe_lengths.append(float(geometry.get("length_mm", 0.0)))
        except (TypeError, ValueError):
            pass

    element_degree_counts = Counter(len(adjacency[element_id]) for element_id in element_ids)
    junction_count = sum(count for degree, count in element_degree_counts.items() if degree >= 3)
    diameter_profiles = _build_diameter_profiles(elements, connections)
    if len(components) != 1:
        shape_class = "disconnected_components"
        shape_reason = "Connector 圖分成多個元素群組"
    elif junction_count:
        shape_class = "compound_network"
        shape_reason = "元素圖含三通或四通節點，不能直接標成單一 L/U 路徑"
    else:
        shape_class = "single_route_candidate"
        shape_reason = "目前沒有元素級分支，才適合進一步做 L/U/雙 L 路徑分類"

    length_summary: dict[str, float] = {}
    if pipe_lengths:
        length_summary = {
            "min_mm": round(min(pipe_lengths), 3),
            "max_mm": round(max(pipe_lengths), 3),
            "average_mm": round(sum(pipe_lengths) / len(pipe_lengths), 3),
        }

    return {
        "schema_version": "fire_branch_topology_profile.v1",
        "snapshot_id": snapshot.get("snapshot_id"),
        "source_schema_version": snapshot.get("schema_version"),
        "scope": "main_graph_only",
        "element_count": len(elements),
        "pipe_count": len(pipe_elements),
        "edge_count": len(edges),
        "connection_count": len(connections),
        "stopped_connection_count": len(graph.get("stopped_connections", [])),
        "component_count": len(components),
        "component_sizes": sorted((len(component) for component in components), reverse=True),
        "kind_counts": dict(sorted(kind_counts.items())),
        "pipe_axis_counts": dict(sorted(pipe_axis_counts.items())),
        "element_degree_counts": {
            str(degree): count for degree, count in sorted(element_degree_counts.items())
        },
        "junction_element_count": junction_count,
        "diameter_profiles": diameter_profiles,
        "shape_class": shape_class,
        "shape_reason": shape_reason,
        "pipe_length_summary": length_summary,
    }


def _build_diameter_profiles(
    elements: list[Mapping[str, Any]],
    connections: list[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Describe same-diameter continuity without choosing a main route."""

    by_id = {
        int(item["element_id"]): item
        for item in elements
        if item.get("element_id") is not None
    }
    element_adjacency: dict[int, set[int]] = defaultdict(set)
    for connection in connections:
        try:
            first = int(connection["from_element_id"])
            second = int(connection["to_element_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if first in by_id and second in by_id and first != second:
            element_adjacency[first].add(second)
            element_adjacency[second].add(first)

    pipes = {
        element_id: item
        for element_id, item in by_id.items()
        if item.get("kind") == "pipe" and item.get("diameter_mm") is not None
    }
    pipe_adjacency: dict[int, set[int]] = defaultdict(set)
    same_diameter_junctions: Counter[str] = Counter()
    for fitting_id, fitting in by_id.items():
        if fitting.get("kind") == "pipe":
            continue
        neighbours = [element_id for element_id in element_adjacency[fitting_id] if element_id in pipes]
        for first, second in combinations(neighbours, 2):
            first_diameter = float(pipes[first]["diameter_mm"])
            second_diameter = float(pipes[second]["diameter_mm"])
            if first_diameter != second_diameter:
                continue
            pipe_adjacency[first].add(second)
            pipe_adjacency[second].add(first)
        by_diameter = Counter(str(float(pipes[item]["diameter_mm"])) for item in neighbours)
        for diameter, count in by_diameter.items():
            if count >= 3:
                same_diameter_junctions[diameter] += 1

    result: dict[str, dict[str, Any]] = {}
    for diameter in sorted({float(item["diameter_mm"]) for item in pipes.values()}, reverse=True):
        members = {
            element_id for element_id, item in pipes.items() if float(item["diameter_mm"]) == diameter
        }
        components: list[list[int]] = []
        visited: set[int] = set()
        for element_id in sorted(members):
            if element_id in visited:
                continue
            component: list[int] = []
            queue = deque([element_id])
            visited.add(element_id)
            while queue:
                current = queue.popleft()
                component.append(current)
                for neighbour in pipe_adjacency[current]:
                    if neighbour in members and neighbour not in visited:
                        visited.add(neighbour)
                        queue.append(neighbour)
            components.append(component)

        axis_counts: Counter[str] = Counter()
        total_length = 0.0
        for element_id in members:
            geometry = pipes[element_id].get("geometry")
            if not isinstance(geometry, Mapping):
                continue
            start = geometry.get("start")
            end = geometry.get("end")
            if isinstance(start, Mapping) and isinstance(end, Mapping):
                delta = tuple(
                    float(end.get(axis, 0.0)) - float(start.get(axis, 0.0))
                    for axis in _AXES
                )
                axis_counts[_axis(delta, 1e-6)] += 1
            try:
                total_length += float(geometry.get("length_mm", 0.0))
            except (TypeError, ValueError):
                pass

        route_candidates = _extract_route_candidates(members, pipe_adjacency, pipes)

        diameter_key = f"DN{diameter:g}"
        result[diameter_key] = {
            "diameter_mm": diameter,
            "pipe_count": len(members),
            "same_diameter_component_count": len(components),
            "same_diameter_component_sizes": sorted(
                (len(component) for component in components), reverse=True
            ),
            "same_diameter_junction_count": same_diameter_junctions[str(float(diameter))],
            "axis_counts": dict(sorted(axis_counts.items())),
            "total_length_mm": round(total_length, 3),
            "route_candidate_count": len(route_candidates),
            "route_candidates": route_candidates,
        }
    return result


def _extract_route_candidates(
    members: set[int],
    pipe_adjacency: Mapping[int, set[int]],
    pipes: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Extract maximal same-diameter pipe paths between graph boundaries."""

    local_adjacency = {
        element_id: {neighbour for neighbour in pipe_adjacency[element_id] if neighbour in members}
        for element_id in members
    }
    boundaries = {element_id for element_id in members if len(local_adjacency[element_id]) != 2}
    visited_edges: set[frozenset[int]] = set()
    candidates: list[dict[str, Any]] = []

    def add_path(path: list[int]) -> None:
        if not path:
            return
        axes: list[str] = []
        length_mm = 0.0
        for element_id in path:
            geometry = pipes[element_id].get("geometry")
            if not isinstance(geometry, Mapping):
                continue
            start = geometry.get("start")
            end = geometry.get("end")
            if isinstance(start, Mapping) and isinstance(end, Mapping):
                delta = tuple(
                    float(end.get(axis, 0.0)) - float(start.get(axis, 0.0))
                    for axis in _AXES
                )
                segment_axis = _axis(delta, 1e-6)
                if segment_axis != "duplicate":
                    axes.append(segment_axis)
            try:
                length_mm += float(geometry.get("length_mm", 0.0))
            except (TypeError, ValueError):
                pass
        shape_class, turns = _classify_axes(axes)
        candidates.append(
            {
                "pipe_ids": path,
                "segment_count": len(path),
                "turn_count": turns,
                "axes": axes,
                "shape_class": shape_class,
                "length_mm": round(length_mm, 3),
                "boundary_start": path[0],
                "boundary_end": path[-1],
            }
        )

    for start in sorted(boundaries):
        for neighbour in sorted(local_adjacency[start]):
            edge = frozenset((start, neighbour))
            if edge in visited_edges:
                continue
            visited_edges.add(edge)
            path = [start, neighbour]
            previous, current = start, neighbour
            while current not in boundaries:
                options = sorted(local_adjacency[current] - {previous})
                if not options:
                    break
                next_pipe = options[0]
                if next_pipe == start or next_pipe in path:
                    break
                next_edge = frozenset((current, next_pipe))
                if next_edge in visited_edges:
                    break
                visited_edges.add(next_edge)
                path.append(next_pipe)
                previous, current = current, next_pipe
            add_path(path)

    # A same-diameter cycle has no boundary. Preserve it as one review item.
    for start in sorted(members):
        for neighbour in sorted(local_adjacency[start]):
            edge = frozenset((start, neighbour))
            if edge in visited_edges:
                continue
            visited_edges.add(edge)
            path = [start, neighbour]
            previous, current = start, neighbour
            while True:
                options = sorted(local_adjacency[current] - {previous})
                if not options:
                    break
                next_pipe = options[0]
                if next_pipe == start or next_pipe in path:
                    break
                next_edge = frozenset((current, next_pipe))
                if next_edge in visited_edges:
                    break
                visited_edges.add(next_edge)
                path.append(next_pipe)
                previous, current = current, next_pipe
            add_path(path)
            break

    return candidates
