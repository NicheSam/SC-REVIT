"""Read-only CAD route graph normalization.

CAD drawings often split one physical route into several lines or polylines.
This module deliberately does not compare CAD and Revit segment lengths. It
normalizes already-transformed CAD fragments into a graph so downstream code
can compare anchors, direction and connectivity while preserving the original
fragment evidence.

Coordinates are unit-agnostic. Callers must pass tolerances in the same model
coordinate unit as the input points; no engineering tolerance is hidden here.
The Revit side must supply points after the ImportInstance geometry has been
converted to model coordinates exactly once. A root GeometryInstance already
contains its placement transform, so applying GetTotalTransform again would
shift the graph and invalidate otherwise matching CAD evidence.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Any, Mapping, Sequence


Point = tuple[float, float, float]


def compare_cad_route_candidates(
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Select one CAD route without hiding the alternatives.

    Route selection is intentionally lexicographic: reaching the requested
    sprinkler and staying on one continuous CAD path outrank a shorter or
    visually convenient route.  The complete candidate table is returned so
    the SVG/review UI can explain why a candidate was selected or rejected.
    """

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(candidates or []):
        if not isinstance(raw, Mapping):
            continue
        candidate_id = str(
            raw.get("candidate_id") or raw.get("id") or f"candidate-{index}"
        ).strip()
        if not candidate_id:
            candidate_id = f"candidate-{index}"
        if candidate_id in seen:
            candidate_id = f"{candidate_id}:{index}"
        seen.add(candidate_id)
        metrics = {
            "sprinkler_reached": bool(
                raw.get("sprinkler_reached")
                or raw.get("complete_to_sprinkler")
                or raw.get("sprinkler_end_matched")
            ),
            "continuous_coverage_ratio": _candidate_ratio(
                raw, "continuous_coverage_ratio"
            ),
            "coverage_ratio": _candidate_ratio(raw, "coverage_ratio"),
            "diameter_evidence_ratio": _candidate_ratio(
                raw, "diameter_evidence_ratio"
            ),
            "topology_consistency_ratio": _candidate_ratio(
                raw, "topology_consistency_ratio"
            ),
            "non_route_intersections": _candidate_number(
                raw, "non_route_intersections", "non_route_penalty"
            ),
            "turn_count": _candidate_number(raw, "turn_count"),
            "length": _candidate_number(raw, "length", "length_mm"),
            "anchor_distance": _candidate_number(raw, "anchor_distance"),
        }
        normalized.append(
            {
                "candidate_id": candidate_id,
                "metrics": metrics,
                "edge_ids": sorted(str(item) for item in (raw.get("edge_ids") or [])),
                "source_fragment_ids": sorted(
                    str(item) for item in (raw.get("source_fragment_ids") or [])
                ),
            }
        )

    normalized.sort(key=lambda item: item["candidate_id"])
    if not normalized:
        return {
            "schema_version": "fire_branch_route_candidate_decision.v1",
            "status": "needs_review",
            "selected_candidate_id": None,
            "criteria": ["到達目標灑水頭", "CAD 連續路徑", "證據完整度"],
            "candidates": {},
            "rejected_candidate_ids": [],
        }

    def rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
        metrics = item["metrics"]
        return (
            -int(metrics["sprinkler_reached"]),
            -metrics["continuous_coverage_ratio"],
            -metrics["coverage_ratio"],
            -metrics["diameter_evidence_ratio"],
            -metrics["topology_consistency_ratio"],
            metrics["non_route_intersections"],
            metrics["turn_count"],
            metrics["length"],
            metrics["anchor_distance"],
            item["candidate_id"],
        )

    ordered = sorted(normalized, key=rank_key)
    selected = ordered[0]
    result_candidates: dict[str, dict[str, Any]] = {}
    for rank, item in enumerate(ordered, start=1):
        metrics = item["metrics"]
        reached = metrics["sprinkler_reached"]
        reasons = [
            "到達目標灑水頭" if reached else "未到達目標灑水頭",
            f"CAD 連續覆蓋 {metrics['continuous_coverage_ratio']:.3f}",
            f"管徑證據 {metrics['diameter_evidence_ratio']:.3f}",
        ]
        rejected_reasons: list[str] = []
        if item is not selected:
            if not reached and selected["metrics"]["sprinkler_reached"]:
                rejected_reasons.append("未到達目標灑水頭")
            if metrics["continuous_coverage_ratio"] < selected["metrics"]["continuous_coverage_ratio"]:
                rejected_reasons.append("CAD 連續覆蓋較低")
            if not rejected_reasons:
                rejected_reasons.append("排序條件低於已選候選")
        result_candidates[item["candidate_id"]] = {
            **item,
            "selected": item is selected,
            "rank": rank,
            "reasons": reasons,
            "rejected_reasons": rejected_reasons,
        }
    return {
        "schema_version": "fire_branch_route_candidate_decision.v1",
        "status": "selected",
        "selected_candidate_id": selected["candidate_id"],
        "criteria": [
            "先到達目標灑水頭",
            "再看 CAD 連續覆蓋",
            "再看管徑與拓樸證據",
            "最後以轉折、長度及識別碼穩定排序",
        ],
        "candidates": result_candidates,
        "rejected_candidate_ids": [
            item["candidate_id"] for item in ordered[1:]
        ],
    }


def build_revit_route_candidate_decisions(
    assignments: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize Revit's per-sprinkler CAD assignment audit for the plan.

    The Revit handler remains authoritative for the selected candidate.  This
    adapter only gives the Python topology/SVG layers the same complete
    candidate table and an explicit consistency check; it never replaces the
    selected route or re-runs physical routing.
    """

    decisions: list[dict[str, Any]] = []
    for assignment in assignments or []:
        if not isinstance(assignment, Mapping):
            continue
        sprinkler_id = str(assignment.get("sprinkler_id") or "").strip()
        raw_candidates = assignment.get("candidates") or []
        normalized: list[dict[str, Any]] = []
        revit_selected_key = _revit_candidate_key(
            assignment.get("main_pipe_id"), assignment.get("source_import_id")
        )
        for index, raw in enumerate(raw_candidates):
            if not isinstance(raw, Mapping):
                continue
            main_pipe_id = raw.get("main_pipe_id")
            source_import_id = raw.get("source_import_id")
            candidate_id = (
                f"sprinkler:{sprinkler_id}:"
                f"main:{main_pipe_id}:source:{source_import_id}:candidate:{index}"
            )
            item = dict(raw)
            item.update(
                {
                    "candidate_id": candidate_id,
                    "sprinkler_reached": bool(
                        raw.get("sprinkler_end_matched")
                    ),
                    "anchor_distance": raw.get("mean_offset_mm"),
                    "length": raw.get("branch_length_mm"),
                    "edge_ids": [str(main_pipe_id)] if main_pipe_id is not None else [],
                    "source_fragment_ids": (
                        [str(source_import_id)]
                        if source_import_id is not None
                        else []
                    ),
                    "revit_candidate_key": _revit_candidate_key(
                        main_pipe_id, source_import_id
                    ),
                }
            )
            normalized.append(item)

        if normalized:
            comparison = compare_cad_route_candidates(normalized)
        else:
            comparison = compare_cad_route_candidates([])
        authoritative_id = next(
            (
                item["candidate_id"]
                for item in normalized
                if item.get("revit_candidate_key") == revit_selected_key
            ),
            None,
        )
        comparator_id = comparison.get("selected_candidate_id")
        consistent = (
            authoritative_id is not None
            and comparator_id == authoritative_id
        )
        status = str(assignment.get("status") or "").strip() or "unknown"
        if authoritative_id is None:
            comparison_status = "needs_review"
            selection_message = "Revit 沒有保留可核對的 CAD 候選。"
        elif consistent:
            comparison_status = "selected"
            selection_message = "Revit 選取結果與候選排序一致。"
        else:
            comparison_status = "needs_review"
            selection_message = (
                "Revit 選取結果與 Python 候選排序不同，保留 Revit 結果並要求核對。"
            )
        comparison.update(
            {
                "status": comparison_status,
                "sprinkler_id": sprinkler_id,
                "revit_assignment_status": status,
                "authority": "revit_cad_route_evidence",
                "revit_selected_candidate_id": authoritative_id,
                "selection_consistent": consistent,
                "selection_message": selection_message,
            }
        )
        decisions.append(comparison)
    return decisions


def _revit_candidate_key(main_pipe_id: Any, source_import_id: Any) -> str:
    return f"main:{main_pipe_id}|source:{source_import_id}"


def _candidate_ratio(raw: Mapping[str, Any], key: str) -> float:
    try:
        value = float(raw.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value)) if math.isfinite(value) else 0.0


def _candidate_number(raw: Mapping[str, Any], *keys: str) -> float:
    for key in keys:
        try:
            value = float(raw.get(key) or 0.0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return max(0.0, value)
    return 0.0


def build_cad_route_graph(
    segments: Sequence[Mapping[str, Any]],
    *,
    coordinate_tolerance: float,
    z_tolerance: float | None = None,
) -> dict[str, Any]:
    """Build a topology graph from fragmented 2D CAD line evidence.

    ``coordinate_tolerance`` is used only for endpoint/intersection clustering
    and numerical segment membership. A gap larger than this value remains a
    separate component. Every output edge keeps the source fragment ids,
    layers and colors so the graph can be audited back to CAD.
    """

    tolerance = _positive_tolerance(coordinate_tolerance, "coordinate_tolerance")
    z_limit = tolerance if z_tolerance is None else _positive_tolerance(
        z_tolerance, "z_tolerance"
    )
    normalized = _normalize_segments(segments)
    split_parameters = [[0.0, 1.0] for _ in normalized]
    for first_index, first in enumerate(normalized):
        for second_index in range(first_index + 1, len(normalized)):
            _collect_pair_split_parameters(
                first,
                normalized[second_index],
                split_parameters[first_index],
                split_parameters[second_index],
                tolerance,
                z_limit,
            )

    nodes: list[dict[str, Any]] = []
    buckets: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    raw_edges: list[dict[str, Any]] = []
    for segment, parameters in zip(normalized, split_parameters):
        ordered = _unique_parameters(parameters, tolerance, segment["length"])
        for start_parameter, end_parameter in zip(ordered, ordered[1:]):
            start = _lerp(segment["start"], segment["end"], start_parameter)
            end = _lerp(segment["start"], segment["end"], end_parameter)
            if _distance(start, end) <= tolerance:
                continue
            start_node = _find_or_create_node(
                nodes, buckets, start, segment, tolerance, z_limit
            )
            end_node = _find_or_create_node(
                nodes, buckets, end, segment, tolerance, z_limit
            )
            if start_node == end_node:
                continue
            raw_edges.append(
                {
                    "start_node": start_node,
                    "end_node": end_node,
                    "source_segment_ids": [segment["source_segment_id"]],
                    "layers": _metadata_values(segment, "layer"),
                    "colors": _metadata_values(segment, "color"),
                    "geometry_kinds": _metadata_values(segment, "geometry_kind"),
                }
            )

    edges = _aggregate_edges(raw_edges, nodes)
    _finalize_nodes(nodes, edges)
    components = _build_components(nodes, edges)
    component_by_edge: dict[str, str] = {}
    component_by_node: dict[str, str] = {}
    for component in components:
        component_id = str(component["component_id"])
        for edge_id in component["edge_ids"]:
            component_by_edge[str(edge_id)] = component_id
        for node_id in component["node_ids"]:
            component_by_node[str(node_id)] = component_id
    for edge in edges:
        edge["component_id"] = component_by_edge.get(str(edge["edge_id"]))
    for node in nodes:
        node["component_id"] = component_by_node.get(str(node["node_id"]))
    return {
        "schema_version": "fire_branch_cad_route_graph.v1",
        "coordinate_tolerance": tolerance,
        "z_tolerance": z_limit,
        "source_fragment_count": len(normalized),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "component_count": len(components),
        "nodes": nodes,
        "edges": edges,
        "components": components,
        "length_is_diagnostic_only": True,
    }


def _positive_tolerance(value: float, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必須是正數") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} 必須是正數")
    return result


def _normalize_segments(segments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(segments):
        if not isinstance(raw, Mapping):
            continue
        try:
            start = _point(raw.get("start"))
            end = _point(raw.get("end"))
        except (TypeError, ValueError):
            continue
        length = _distance(start, end)
        if length == 0:
            continue
        source_id = str(raw.get("segment_id") or raw.get("id") or f"fragment-{index}")
        result.append(
            {
                "source_segment_id": source_id,
                "start": start,
                "end": end,
                "length": length,
                "layer": raw.get("layer"),
                "color": raw.get("color") or raw.get("color_key"),
                "geometry_kind": raw.get("geometry_kind") or raw.get("kind"),
            }
        )
    return result


def _point(value: Any) -> Point:
    if isinstance(value, Mapping):
        values = (value.get("x"), value.get("y"), value.get("z", 0.0))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) not in (2, 3):
            raise ValueError("點位必須包含 2 或 3 個座標")
        values = (value[0], value[1], value[2] if len(value) == 3 else 0.0)
    else:
        raise ValueError("缺少點位")
    result = tuple(float(item) for item in values)
    if not all(math.isfinite(item) for item in result):
        raise ValueError("點位必須是有限數值")
    return result  # type: ignore[return-value]


def _point_dict(point: Point) -> dict[str, float]:
    return {"x": point[0], "y": point[1], "z": point[2]}


def _lerp(start: Point, end: Point, parameter: float) -> Point:
    return tuple(
        start[index] + (end[index] - start[index]) * parameter for index in range(3)
    )  # type: ignore[return-value]


def _distance(first: Point, second: Point) -> float:
    return math.sqrt(sum((first[index] - second[index]) ** 2 for index in range(3)))


def _distance_xy(first: Point, second: Point) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _cross_xy(first: Point, second: Point) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _subtract(first: Point, second: Point) -> Point:
    return tuple(first[index] - second[index] for index in range(3))  # type: ignore[return-value]


def _dot_xy(first: Point, second: Point) -> float:
    return first[0] * second[0] + first[1] * second[1]


def _cross_from(origin: Point, first: Point, second: Point) -> float:
    return _cross_xy(_subtract(first, origin), _subtract(second, origin))


def _parameter_on_segment(point: Point, start: Point, end: Point) -> float:
    direction = _subtract(end, start)
    denominator = _dot_xy(direction, direction)
    if denominator == 0:
        return 0.0
    return _dot_xy(_subtract(point, start), direction) / denominator


def _collect_pair_split_parameters(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    first_parameters: list[float],
    second_parameters: list[float],
    tolerance: float,
    z_tolerance: float,
) -> None:
    first_start = first["start"]
    first_end = first["end"]
    second_start = second["start"]
    second_end = second["end"]
    first_direction = _subtract(first_end, first_start)
    second_direction = _subtract(second_end, second_start)
    denominator = _cross_xy(first_direction, second_direction)
    scale = max(_distance_xy(first_start, first_end), _distance_xy(second_start, second_end))
    if abs(denominator) > tolerance * max(scale, tolerance):
        offset = _subtract(second_start, first_start)
        first_parameter = _cross_xy(offset, second_direction) / denominator
        second_parameter = _cross_xy(offset, first_direction) / denominator
        if _parameter_is_near_range(first_parameter, first["length"], tolerance) and _parameter_is_near_range(
            second_parameter, second["length"], tolerance
        ):
            first_point = _lerp(first_start, first_end, _clamp01(first_parameter))
            second_point = _lerp(second_start, second_end, _clamp01(second_parameter))
            if abs(first_point[2] - second_point[2]) <= z_tolerance:
                first_parameters.append(_clamp01(first_parameter))
                second_parameters.append(_clamp01(second_parameter))
        return

    # Parallel fragments only share a route when they are close to the same
    # supporting line. Add overlap endpoints so overlapping source objects do
    # not become duplicate un-split edges.
    if _distance_point_to_line_xy(second_start, first_start, first_end) > tolerance:
        return
    if _distance_point_to_line_xy(second_end, first_start, first_end) > tolerance:
        return
    for point in (second_start, second_end):
        parameter = _parameter_on_segment(point, first_start, first_end)
        if _parameter_is_near_range(parameter, first["length"], tolerance):
            first_parameters.append(_clamp01(parameter))
    for point in (first_start, first_end):
        parameter = _parameter_on_segment(point, second_start, second_end)
        if _parameter_is_near_range(parameter, second["length"], tolerance):
            second_parameters.append(_clamp01(parameter))


def _distance_point_to_line_xy(point: Point, start: Point, end: Point) -> float:
    length = _distance_xy(start, end)
    if length == 0:
        return _distance_xy(point, start)
    return abs(_cross_from(start, end, point)) / length


def _parameter_is_near_range(parameter: float, length: float, tolerance: float) -> bool:
    slack = tolerance / max(length, tolerance)
    return -slack <= parameter <= 1.0 + slack


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _unique_parameters(parameters: Sequence[float], tolerance: float, length: float) -> list[float]:
    values = sorted(_clamp01(float(value)) for value in parameters)
    result: list[float] = []
    parameter_tolerance = tolerance / max(length, tolerance)
    for value in values:
        if not result or value - result[-1] > parameter_tolerance:
            result.append(value)
    if not result or result[0] != 0.0:
        result.insert(0, 0.0)
    if result[-1] != 1.0:
        result.append(1.0)
    return result


def _find_or_create_node(
    nodes: list[dict[str, Any]],
    buckets: dict[tuple[int, int, int], list[int]],
    point: Point,
    segment: Mapping[str, Any],
    tolerance: float,
    z_tolerance: float,
) -> int:
    key = _cell_key(point, tolerance)
    candidates: list[int] = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                candidates.extend(buckets.get((key[0] + dx, key[1] + dy, key[2] + dz), []))
    best: tuple[float, int] | None = None
    for node_id in sorted(set(candidates)):
        existing = _point(nodes[node_id]["point"])
        distance = _distance(existing, point)
        if distance <= tolerance and abs(existing[2] - point[2]) <= z_tolerance:
            candidate = (distance, node_id)
            if best is None or candidate < best:
                best = candidate
    if best is not None:
        node = nodes[best[1]]
        node["max_snap_residual"] = max(node["max_snap_residual"], best[0])
        node["source_segment_ids"] = sorted(
            set(node["source_segment_ids"]) | {segment["source_segment_id"]}
        )
        return best[1]
    node_id = len(nodes)
    nodes.append(
        {
            "node_id": f"cad-node-{node_id}",
            "point": _point_dict(point),
            "source_segment_ids": [segment["source_segment_id"]],
            "max_snap_residual": 0.0,
            "degree": 0,
            "edge_ids": [],
        }
    )
    buckets[key].append(node_id)
    return node_id


def _cell_key(point: Point, tolerance: float) -> tuple[int, int, int]:
    return tuple(int(math.floor(value / tolerance)) for value in point)  # type: ignore[return-value]


def _metadata_values(segment: Mapping[str, Any], key: str) -> list[str]:
    value = segment.get(key)
    if value in (None, ""):
        return []
    return [str(value)]


def _aggregate_edges(
    raw_edges: Sequence[Mapping[str, Any]], nodes: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], dict[str, Any]] = {}
    for raw in raw_edges:
        start = int(raw["start_node"])
        end = int(raw["end_node"])
        key = (min(start, end), max(start, end))
        edge = grouped.get(key)
        if edge is None:
            edge = {
                "start_node": key[0],
                "end_node": key[1],
                "source_segment_ids": [],
                "layers": [],
                "colors": [],
                "geometry_kinds": [],
                "fragment_count": 0,
            }
            grouped[key] = edge
        edge["source_segment_ids"] = sorted(
            set(edge["source_segment_ids"]) | set(raw["source_segment_ids"])
        )
        for field in ("layers", "colors", "geometry_kinds"):
            edge[field] = sorted(set(edge[field]) | set(raw[field]))
        edge["fragment_count"] += 1
    result: list[dict[str, Any]] = []
    for edge_index, key in enumerate(sorted(grouped)):
        edge = grouped[key]
        start_point = _node_point(nodes[edge["start_node"]])
        end_point = _node_point(nodes[edge["end_node"]])
        edge.update(
            {
                "edge_id": f"cad-edge-{edge_index}",
                "start": _point_dict(start_point),
                "end": _point_dict(end_point),
                "length": _distance(start_point, end_point),
            }
        )
        result.append(edge)
    return result


def _node_point(node: Mapping[str, Any]) -> Point:
    return _point(node["point"])


def _finalize_nodes(nodes: list[dict[str, Any]], edges: Sequence[Mapping[str, Any]]) -> None:
    for edge in edges:
        start = int(edge["start_node"])
        end = int(edge["end_node"])
        for node_id in (start, end):
            nodes[node_id]["degree"] += 1
            nodes[node_id]["edge_ids"].append(edge["edge_id"])
    for node in nodes:
        node["edge_ids"] = sorted(node["edge_ids"])
        node["source_segment_ids"] = sorted(set(node["source_segment_ids"]))


def _build_components(
    nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    adjacency: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for edge in edges:
        start = int(edge["start_node"])
        end = int(edge["end_node"])
        adjacency[start].append((end, str(edge["edge_id"])))
        adjacency[end].append((start, str(edge["edge_id"])))
    visited: set[int] = set()
    components: list[dict[str, Any]] = []
    for node_id in range(len(nodes)):
        if node_id in visited or node_id not in adjacency:
            continue
        queue = deque([node_id])
        visited.add(node_id)
        component_nodes: list[int] = []
        component_edges: set[str] = set()
        while queue:
            current = queue.popleft()
            component_nodes.append(current)
            for neighbour, edge_id in adjacency[current]:
                component_edges.add(edge_id)
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append(neighbour)
        components.append(
            {
                "component_id": f"cad-component-{len(components)}",
                "node_ids": [f"cad-node-{item}" for item in sorted(component_nodes)],
                "edge_ids": sorted(component_edges),
                "node_count": len(component_nodes),
                "edge_count": len(component_edges),
            }
        )
    return components
