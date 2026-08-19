"""Normalize selected main-pipe geometry into a deterministic 2D graph.

The main route is not assumed to be one straight line.  Revit may return a
connected run as several pipe pieces, and CAD may cross or split those pieces
at a junction.  This module keeps the source segments, snaps small endpoint
gaps, splits true intersections, and exposes the same graph to SVG and later
model planning.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any


Point = tuple[float, float]


def normalize_main_geometry(
    raw_segments: list[dict[str, Any]] | None,
    *,
    tolerance: float = 5.0 / 304.8,
) -> dict[str, Any]:
    """Return a snapped, intersection-split graph for the supplied segments.

    Coordinates are deliberately left in the caller's units.  The tolerance
    is used only for endpoint snapping and numeric intersection checks; no
    synthetic centre line is created.
    """

    prepared: list[dict[str, Any]] = []
    connection_points: dict[str, list[Point]] = {}
    for index, raw in enumerate(raw_segments or []):
        if not isinstance(raw, dict):
            continue
        start = _point(raw.get("start"))
        end = _point(raw.get("end"))
        if _distance(start, end) <= max(tolerance * 0.1, 1e-9):
            continue
        connection_records = []
        for connection in raw.get("connections") or []:
            if not isinstance(connection, dict):
                continue
            key = str(connection.get("key") or "").strip()
            point = _point(connection.get("point"))
            endpoint = str(connection.get("endpoint") or "").strip().casefold()
            if not key or endpoint not in {"start", "end"}:
                continue
            connection_points.setdefault(key, []).append(point)
            connection_records.append(
                {"key": key, "endpoint": endpoint, "point": point}
            )
        prepared.append(
            {
                "source_index": index,
                "source_segment_id": str(
                    raw.get("segment_id") or f"main-context-{index}"
                ),
                "source": raw,
                "start": start,
                "end": end,
                "connections": connection_records,
            }
        )

    if not prepared:
        return {
            "segments": [],
            "nodes": [],
            "components": [],
            "shape": "linear",
            "raw_segment_count": 0,
            "edge_count": 0,
            "node_count": 0,
            "component_count": 0,
            "intersection_count": 0,
            "anchors": {},
        }

    split_parameters: list[list[float]] = [[0.0, 1.0] for _ in prepared]
    intersection_count = 0
    for first_index, first in enumerate(prepared):
        for second_index in range(first_index + 1, len(prepared)):
            second = prepared[second_index]
            pairs = _intersection_parameters(
                first["start"],
                first["end"],
                second["start"],
                second["end"],
                tolerance,
            )
            if not pairs:
                continue
            intersection_count += 1
            for first_parameter, second_parameter in pairs:
                split_parameters[first_index].append(first_parameter)
                split_parameters[second_index].append(second_parameter)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    canonical_connections = {
        key: _canonical_connection_point(key, points, prepared)
        for key, points in connection_points.items()
        if points
    }
    for item_index, item in enumerate(prepared):
        parameters = _unique_parameters(split_parameters[item_index])
        for part_index, (left, right) in enumerate(
            zip(parameters, parameters[1:]), start=1
        ):
            start = _lerp(item["start"], item["end"], left)
            end = _lerp(item["start"], item["end"], right)
            start_keys = [
                record["key"]
                for record in item["connections"]
                if record["endpoint"] == "start"
            ]
            end_keys = [
                record["key"]
                for record in item["connections"]
                if record["endpoint"] == "end"
            ]
            if left <= 1e-9 and start_keys:
                start = canonical_connections.get(start_keys[0], start)
            if right >= 1.0 - 1e-9 and end_keys:
                end = canonical_connections.get(end_keys[0], end)
            if _distance(start, end) <= max(tolerance * 0.1, 1e-9):
                continue
            start_node = _find_or_add_node(nodes, start, tolerance)
            end_node = _find_or_add_node(nodes, end, tolerance)
            if start_node == end_node:
                continue
            source_id = item["source_segment_id"]
            edge_id = (
                source_id
                if len(parameters) == 2
                else f"{source_id}#{part_index}"
            )
            edges.append(
                {
                    "segment_id": edge_id,
                    "source_segment_id": source_id,
                    "source_element_id": item["source"].get("source_element_id"),
                    "start": start,
                    "end": end,
                    "source_start": _lerp(item["start"], item["end"], left),
                    "source_end": _lerp(item["start"], item["end"], right),
                    "connection_keys": sorted(set(start_keys + end_keys)),
                    "node_start": start_node,
                    "node_end": end_node,
                    "source": item["source"],
                }
            )

    adjacency: list[list[int]] = [[] for _ in nodes]
    for edge_index, edge in enumerate(edges):
        adjacency[edge["node_start"]].append(edge_index)
        adjacency[edge["node_end"]].append(edge_index)

    components: list[dict[str, Any]] = []
    edge_component: dict[int, int] = {}
    node_component: dict[int, int] = {}
    for node_index in range(len(nodes)):
        if node_index in node_component:
            continue
        queue = deque([node_index])
        node_component[node_index] = len(components)
        component_nodes: list[int] = []
        component_edges: set[int] = set()
        while queue:
            current = queue.popleft()
            component_nodes.append(current)
            for edge_index in adjacency[current]:
                component_edges.add(edge_index)
                edge = edges[edge_index]
                other = (
                    edge["node_end"]
                    if edge["node_start"] == current
                    else edge["node_start"]
                )
                if other not in node_component:
                    node_component[other] = len(components)
                    queue.append(other)
        component_index = len(components)
        for edge_index in component_edges:
            edge_component[edge_index] = component_index
        components.append(
            {
                "component_id": component_index,
                "node_ids": sorted(component_nodes),
                "edge_ids": sorted(component_edges),
            }
        )

    for node_index, node in enumerate(nodes):
        node["node_id"] = node_index
        node["degree"] = len(adjacency[node_index])
        node["component_id"] = node_component.get(node_index)
    for edge_index, edge in enumerate(edges):
        edge["component_id"] = edge_component.get(edge_index)
        edge["axis"] = _axis(edge["start"], edge["end"])

    shape = _classify_graph_shape(edges, nodes, adjacency, components)
    return {
        "segments": edges,
        "nodes": nodes,
        "components": components,
        "shape": shape,
        "raw_segment_count": len(prepared),
        "edge_count": len(edges),
        "node_count": len(nodes),
        "component_count": len(components),
        "intersection_count": intersection_count,
        "anchors": {},
    }


def project_point_to_main_geometry(
    point: Point,
    graph: dict[str, Any],
) -> dict[str, Any] | None:
    """Project a branch anchor to the nearest actual main graph edge."""

    best: tuple[float, str, dict[str, Any], Point] | None = None
    for edge in graph.get("segments") or []:
        start = _point(edge.get("start"))
        end = _point(edge.get("end"))
        projected, distance = _project_to_segment(point, start, end)
        candidate = (distance, str(edge.get("segment_id") or ""), edge, projected)
        if best is None or (candidate[0], candidate[1]) < (best[0], best[1]):
            best = candidate
    if best is None:
        return None
    distance, _, edge, projected = best
    return {
        "point": projected,
        "distance": distance,
        "segment_id": edge.get("segment_id"),
        "source_segment_id": edge.get("source_segment_id"),
        "component_id": edge.get("component_id"),
        "node_start": edge.get("node_start"),
        "node_end": edge.get("node_end"),
    }


def _classify_graph_shape(
    edges: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    adjacency: list[list[int]],
    components: list[dict[str, Any]],
) -> str:
    if not edges:
        return "linear"
    if any(len(neighbours) > 2 for neighbours in adjacency):
        return "network"
    if all(edge.get("axis") == edges[0].get("axis") for edge in edges):
        return "linear"
    if len(components) != 1:
        return "compound_bend"
    endpoints = [index for index, neighbours in enumerate(adjacency) if len(neighbours) == 1]
    if len(endpoints) != 2:
        return "compound_bend"
    path_axes: list[str] = []
    current = endpoints[0]
    previous_edge = -1
    visited_edges: set[int] = set()
    while len(visited_edges) < len(edges):
        next_edges = [edge_index for edge_index in adjacency[current] if edge_index != previous_edge]
        next_edges = [edge_index for edge_index in next_edges if edge_index not in visited_edges]
        if not next_edges:
            break
        edge_index = next_edges[0]
        visited_edges.add(edge_index)
        edge = edges[edge_index]
        path_axes.append(str(edge.get("axis") or ""))
        current = edge["node_end"] if edge["node_start"] == current else edge["node_start"]
        previous_edge = edge_index
    turns = sum(1 for first, second in zip(path_axes, path_axes[1:]) if first != second)
    if turns == 1:
        return "L"
    if turns == 2 and len(path_axes) >= 3 and path_axes[0] == path_axes[-1]:
        return "U"
    return "compound_bend"


def _intersection_parameters(
    first_start: Point,
    first_end: Point,
    second_start: Point,
    second_end: Point,
    tolerance: float,
) -> list[tuple[float, float]]:
    first_vector = _subtract(first_end, first_start)
    second_vector = _subtract(second_end, second_start)
    denominator = _cross(first_vector, second_vector)
    offset = _subtract(second_start, first_start)
    epsilon = max(tolerance * 0.25, 1e-9)
    if abs(denominator) > epsilon:
        first_parameter = _cross(offset, second_vector) / denominator
        second_parameter = _cross(offset, first_vector) / denominator
        if _in_unit_interval(first_parameter, tolerance) and _in_unit_interval(second_parameter, tolerance):
            return [(max(0.0, min(1.0, first_parameter)), max(0.0, min(1.0, second_parameter)))]
        return []
    if abs(_cross(offset, first_vector)) > epsilon:
        return []
    first_length_squared = _dot(first_vector, first_vector)
    second_length_squared = _dot(second_vector, second_vector)
    if first_length_squared <= epsilon or second_length_squared <= epsilon:
        return []
    candidates: list[tuple[float, float]] = []
    for first_parameter in (0.0, 1.0):
        point = _lerp(first_start, first_end, first_parameter)
        second_parameter = _dot(_subtract(point, second_start), second_vector) / second_length_squared
        if _in_unit_interval(second_parameter, tolerance):
            candidates.append((first_parameter, max(0.0, min(1.0, second_parameter))))
    for second_parameter in (0.0, 1.0):
        point = _lerp(second_start, second_end, second_parameter)
        first_parameter = _dot(_subtract(point, first_start), first_vector) / first_length_squared
        if _in_unit_interval(first_parameter, tolerance):
            candidates.append((max(0.0, min(1.0, first_parameter)), second_parameter))
    return _unique_pairs(candidates)


def _canonical_connection_point(
    key: str,
    connector_points: list[Point],
    prepared: list[dict[str, Any]],
) -> Point:
    """Resolve a fitting connection onto the source pipe centre lines.

    Revit fitting connectors sit on the fitting faces, so averaging their
    origins moves an elbow joint away from both pipe centre-line endpoints.
    The connector records prove connectivity; the intersecting source lines
    define the shared topology coordinate.
    """

    average = (
        sum(point[0] for point in connector_points) / len(connector_points),
        sum(point[1] for point in connector_points) / len(connector_points),
    )
    connected = [
        item
        for item in prepared
        if any(record.get("key") == key for record in item.get("connections") or [])
    ]
    candidates: list[tuple[float, float, Point]] = []
    for first_index, first in enumerate(connected):
        first_vector = _subtract(first["end"], first["start"])
        first_length = math.hypot(*first_vector)
        if first_length <= 1e-9:
            continue
        for second in connected[first_index + 1 :]:
            second_vector = _subtract(second["end"], second["start"])
            second_length = math.hypot(*second_vector)
            if second_length <= 1e-9:
                continue
            denominator = _cross(first_vector, second_vector)
            normalized_cross = abs(denominator) / (first_length * second_length)
            if normalized_cross <= 0.25:
                continue
            first_parameter = _cross(
                _subtract(second["start"], first["start"]),
                second_vector,
            ) / denominator
            intersection = _lerp(first["start"], first["end"], first_parameter)
            candidates.append(
                (_distance(intersection, average), -normalized_cross, intersection)
            )
    if not candidates:
        return average
    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def _find_or_add_node(nodes: list[dict[str, Any]], point: Point, tolerance: float) -> int:
    for index, node in enumerate(nodes):
        if _distance(_point(node), point) <= tolerance:
            old = _point(node)
            node["x"] = (old[0] + point[0]) / 2.0
            node["y"] = (old[1] + point[1]) / 2.0
            return index
    nodes.append({"x": point[0], "y": point[1]})
    return len(nodes) - 1


def _point(value: Any) -> Point:
    if isinstance(value, tuple) or isinstance(value, list):
        return float(value[0]), float(value[1])
    raw = value if isinstance(value, dict) else {}
    return float(raw.get("x") or 0), float(raw.get("y") or 0)


def _subtract(first: Point, second: Point) -> Point:
    return first[0] - second[0], first[1] - second[1]


def _dot(first: Point, second: Point) -> float:
    return first[0] * second[0] + first[1] * second[1]


def _cross(first: Point, second: Point) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _distance(first: Point, second: Point) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _lerp(first: Point, second: Point, ratio: float) -> Point:
    return first[0] + (second[0] - first[0]) * ratio, first[1] + (second[1] - first[1]) * ratio


def _project_to_segment(point: Point, start: Point, end: Point) -> tuple[Point, float]:
    vector = _subtract(end, start)
    length_squared = _dot(vector, vector)
    if length_squared <= 1e-12:
        return start, _distance(point, start)
    ratio = max(0.0, min(1.0, _dot(_subtract(point, start), vector) / length_squared))
    projected = _lerp(start, end, ratio)
    return projected, _distance(point, projected)


def _axis(start: Point, end: Point) -> str:
    return "x" if abs(end[0] - start[0]) >= abs(end[1] - start[1]) else "y"


def _in_unit_interval(value: float, tolerance: float) -> bool:
    margin = max(tolerance, 1e-9)
    return -margin <= value <= 1.0 + margin


def _unique_parameters(values: list[float]) -> list[float]:
    result: list[float] = []
    for value in sorted(max(0.0, min(1.0, float(item))) for item in values):
        if not result or abs(value - result[-1]) > 1e-9:
            result.append(value)
    if not result or result[0] != 0.0:
        result.insert(0, 0.0)
    if result[-1] != 1.0:
        result.append(1.0)
    return result


def _unique_pairs(values: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for pair in values:
        if not any(abs(pair[0] - item[0]) <= 1e-9 and abs(pair[1] - item[1]) <= 1e-9 for item in result):
            result.append(pair)
    return result
