from __future__ import annotations

import hashlib
import json
import math
import copy
from typing import Any

from sc_revit.fire_branch.main_geometry import normalize_main_geometry


_JUNCTION_TOLERANCE_FEET = 5.0 / 304.8


def build_fire_branch_execution_plan(
    *,
    diameter_analysis: dict[str, Any],
    main_pipe_ids: list[str | int],
    sprinkler_ids: list[str | int],
    preview_snapshot_id: str,
    pipe_type_id: str | int,
    system_type_id: str | int,
    level_id: str | int,
    topology_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the immutable topology contract shared by preview and Revit."""

    if not str(preview_snapshot_id or "").strip():
        raise ValueError("缺少預覽批次，請重新分析")
    if topology_plan is None:
        from sc_revit.fire_branch.topology_plan import create_topology_plan

        topology_plan = create_topology_plan(
            diameter_analysis,
            source_mode=str(diameter_analysis.get("source_mode") or "cad"),
            preview_snapshot_id=str(preview_snapshot_id),
        )
    else:
        topology_plan = copy.deepcopy(topology_plan)
    validation = topology_plan.get("validation") or {}
    if str(validation.get("status") or "") == "invalid":
        raise ValueError("目前拓樸計畫無效，請修正後重新執行建立前檢查")

    segments = [
        {
            "segment_id": str(item.get("segment_id") or ""),
            "plan_entity_id": str(item.get("plan_entity_id") or ""),
            "row_index": int(item.get("row_index") or 0),
            "sequence": int(item.get("sequence") or 0),
            "start": item.get("start") or {},
            "end": item.get("end") or {},
            "diameter_mm": float(item["diameter_mm"]),
            "sprinkler_id": item.get("sprinkler_id"),
            "is_sprinkler_terminal": bool(item.get("is_sprinkler_terminal")),
        }
        for item in (topology_plan.get("segments") or [])
        if item.get("diameter_mm") is not None
    ]
    if not segments:
        raise ValueError("目前預覽沒有可用的管徑分段")
    if int(diameter_analysis.get("unresolved_segment_count") or 0) != 0:
        raise ValueError("目前預覽仍有尚未確認的管徑分段")

    if any(item.get("review_required") for item in topology_plan["junctions"]):
        raise ValueError("目前預覽仍有尚未確認的接頭拓樸")

    plan = {
        "schema_version": "fire_branch_execution_plan.v5",
        "source_mode": str(topology_plan.get("source_mode") or "cad"),
        "topology_plan_revision": int(topology_plan.get("revision") or 1),
        "topology_plan_hash": str(topology_plan.get("plan_hash") or ""),
        "main_pipe_ids": sorted(int(item) for item in main_pipe_ids),
        "sprinkler_ids": sorted(int(item) for item in sprinkler_ids),
        "preview_snapshot_id": str(preview_snapshot_id),
        "pipe_type_id": int(pipe_type_id),
        "system_type_id": int(system_type_id),
        "level_id": int(level_id),
        "diameter_plan": segments,
        "topology_plan": topology_plan,
    }
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    plan["plan_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return plan


def build_fire_branch_topology_plan(
    diameter_analysis: dict[str, Any],
) -> dict[str, Any]:
    """Resolve tees, crosses and reducer placement once for every consumer."""

    segment_by_id = {
        str(item.get("segment_id") or ""): item
        for item in (diameter_analysis.get("segments") or [])
    }
    raw_junctions = list(diameter_analysis.get("junctions") or [])
    consumed: set[int] = set()
    junctions: list[dict[str, Any]] = []
    reducers = [
        {
            **item,
            "placement": "along_branch",
        }
        for item in (diameter_analysis.get("reducers") or [])
        if str(item.get("placement") or "along_branch") == "along_branch"
        and str(item.get("before_segment_id") or "").strip()
        and str(item.get("after_segment_id") or "").strip()
    ]
    main_graph = normalize_main_geometry(
        diameter_analysis.get("main_context_segments") or []
    )

    for index, raw in enumerate(raw_junctions):
        if index in consumed:
            continue
        opposite_index = _find_opposite_junction(
            index,
            raw_junctions,
            segment_by_id,
            consumed,
        )
        main_diameter = _float_or_none(raw.get("main_diameter_mm"))
        branch_diameter = _float_or_none(raw.get("branch_diameter_mm"))
        if opposite_index is None:
            junctions.append(
                {
                    "kind": str(raw.get("kind") or "unresolved_tee"),
                    "row_indexes": [int(raw.get("row_index") or 0)],
                    "branch_segment_ids": [str(raw.get("branch_segment_id") or "")],
                    "main_segment_id": str(raw.get("main_segment_id") or ""),
                    "point": raw.get("point") or {},
                    "main_diameter_mm": main_diameter,
                    "common_branch_diameter_mm": branch_diameter,
                    "source_branch_diameters_mm": [branch_diameter],
                    "branch_outlet_diameters_mm": [branch_diameter],
                    "branch_outlet_diameters_by_segment_id": {
                        str(raw.get("branch_segment_id") or ""): branch_diameter
                    },
                    "review_required": bool(raw.get("review_required")),
                }
            )
            continue

        opposite = raw_junctions[opposite_index]
        consumed.add(opposite_index)
        opposite_main = _float_or_none(opposite.get("main_diameter_mm"))
        opposite_branch = _float_or_none(opposite.get("branch_diameter_mm"))
        rows_and_diameters = sorted(
            [
                (int(raw.get("row_index") or 0), branch_diameter, raw),
                (int(opposite.get("row_index") or 0), opposite_branch, opposite),
            ],
            key=lambda item: item[0],
        )
        resolved = (
            main_diameter is not None
            and opposite_main is not None
            and branch_diameter is not None
            and opposite_branch is not None
            and math.isclose(main_diameter, opposite_main)
        )
        common = max(branch_diameter, opposite_branch) if resolved else None
        junction_point = _average_point(raw.get("point"), opposite.get("point"))
        main_run_directions = _main_run_directions_at_point(main_graph, junction_point)
        main_run_count = len(main_run_directions)
        main_is_straight_through = _has_opposite_directions(main_run_directions)
        has_main_geometry = bool(main_graph.get("segments"))
        if has_main_geometry and main_run_count == 1:
            kind = (
                "endpoint_tee"
                if resolved
                and math.isclose(main_diameter, branch_diameter)
                and math.isclose(main_diameter, opposite_branch)
                else "reducing_endpoint_tee" if resolved else "unresolved_endpoint_tee"
            )
        elif not has_main_geometry or main_is_straight_through:
            kind = (
                "cross"
                if resolved
                and math.isclose(main_diameter, branch_diameter)
                and math.isclose(main_diameter, opposite_branch)
                else "reducing_cross" if resolved else "unresolved_cross"
            )
        else:
            kind = "unresolved_main_junction"
        branch_outlet_diameters = [item[1] for item in rows_and_diameters]
        if kind in {"reducing_cross", "reducing_endpoint_tee"} and common is not None:
            branch_outlet_diameters = [common for _ in rows_and_diameters]
            reducer_placement = (
                "after_cross" if kind == "reducing_cross" else "after_endpoint_tee"
            )
            for row_index, source_diameter, source_junction in rows_and_diameters:
                if source_diameter is None or math.isclose(float(source_diameter), common):
                    continue
                reducers.append(
                    {
                        "row_index": row_index,
                        "branch_segment_id": str(
                            source_junction.get("branch_segment_id") or ""
                        ),
                        "placement": reducer_placement,
                        "point": source_junction.get("point") or junction_point,
                        "from_diameter_mm": float(common),
                        "to_diameter_mm": float(source_diameter),
                    }
                )
        junctions.append(
            {
                "kind": kind,
                "row_indexes": [item[0] for item in rows_and_diameters],
                "branch_segment_ids": [
                    str(item[2].get("branch_segment_id") or "")
                    for item in rows_and_diameters
                ],
                "main_segment_id": str(raw.get("main_segment_id") or ""),
                "point": junction_point,
                "main_diameter_mm": main_diameter if resolved else None,
                "common_branch_diameter_mm": common,
                "source_branch_diameters_mm": [item[1] for item in rows_and_diameters],
                "branch_outlet_diameters_mm": branch_outlet_diameters,
                "branch_outlet_diameters_by_segment_id": {
                    str(item[2].get("branch_segment_id") or ""): diameter
                    for item, diameter in zip(rows_and_diameters, branch_outlet_diameters)
                },
                "main_run_count": main_run_count if has_main_geometry else None,
                "review_required": bool(
                    not resolved
                    or raw.get("review_required")
                    or opposite.get("review_required")
                    or kind == "unresolved_main_junction"
                ),
            }
        )
    return {
        "schema_version": "fire_branch_topology_plan.v4",
        "junctions": junctions,
        "reducers": reducers,
    }


def _main_run_directions_at_point(
    graph: dict[str, Any],
    point: dict[str, Any],
) -> list[tuple[float, float]]:
    """Return the distinct main-pipe rays that physically leave a junction."""

    target = (
        float((point or {}).get("x") or 0),
        float((point or {}).get("y") or 0),
    )
    directions: list[tuple[float, float]] = []
    for edge in graph.get("segments") or []:
        start = tuple(float(value) for value in (edge.get("start") or (0, 0))[:2])
        end = tuple(float(value) for value in (edge.get("end") or (0, 0))[:2])
        vector = (end[0] - start[0], end[1] - start[1])
        length_squared = vector[0] * vector[0] + vector[1] * vector[1]
        if length_squared <= 1e-18:
            continue
        parameter = (
            (target[0] - start[0]) * vector[0]
            + (target[1] - start[1]) * vector[1]
        ) / length_squared
        clamped = min(1.0, max(0.0, parameter))
        projected = (
            start[0] + vector[0] * clamped,
            start[1] + vector[1] * clamped,
        )
        if math.hypot(target[0] - projected[0], target[1] - projected[1]) > _JUNCTION_TOLERANCE_FEET:
            continue
        for endpoint in (start, end):
            ray = (endpoint[0] - target[0], endpoint[1] - target[1])
            length = math.hypot(ray[0], ray[1])
            if length <= _JUNCTION_TOLERANCE_FEET:
                continue
            normalized = (ray[0] / length, ray[1] / length)
            if not any(
                normalized[0] * existing[0] + normalized[1] * existing[1] > 0.999
                for existing in directions
            ):
                directions.append(normalized)
    return directions


def _has_opposite_directions(directions: list[tuple[float, float]]) -> bool:
    return any(
        first[0] * second[0] + first[1] * second[1] < -0.999
        for index, first in enumerate(directions)
        for second in directions[index + 1 :]
    )


def _find_opposite_junction(
    index: int,
    junctions: list[dict[str, Any]],
    segment_by_id: dict[str, dict[str, Any]],
    consumed: set[int],
) -> int | None:
    current = junctions[index]
    current_segment = segment_by_id.get(str(current.get("branch_segment_id") or ""))
    if current_segment is None:
        return None
    current_direction = _outward_direction(current_segment, current.get("point") or {})
    for candidate_index in range(index + 1, len(junctions)):
        if candidate_index in consumed:
            continue
        candidate = junctions[candidate_index]
        if str(current.get("main_segment_id") or "") != str(candidate.get("main_segment_id") or ""):
            continue
        if _point_distance(current.get("point"), candidate.get("point")) > _JUNCTION_TOLERANCE_FEET:
            continue
        candidate_segment = segment_by_id.get(str(candidate.get("branch_segment_id") or ""))
        if candidate_segment is None:
            continue
        candidate_direction = _outward_direction(candidate_segment, candidate.get("point") or {})
        if current_direction[0] * candidate_direction[0] + current_direction[1] * candidate_direction[1] < 0:
            return candidate_index
    return None


def _outward_direction(
    segment: dict[str, Any],
    point: dict[str, Any],
) -> tuple[float, float]:
    start = segment.get("start") or {}
    end = segment.get("end") or {}
    near, far = (start, end) if _point_distance(start, point) <= _point_distance(end, point) else (end, start)
    return (
        float(far.get("x") or 0) - float(near.get("x") or 0),
        float(far.get("y") or 0) - float(near.get("y") or 0),
    )


def _point_distance(first: Any, second: Any) -> float:
    first = first or {}
    second = second or {}
    return math.hypot(
        float(first.get("x") or 0) - float(second.get("x") or 0),
        float(first.get("y") or 0) - float(second.get("y") or 0),
    )


def _average_point(first: Any, second: Any) -> dict[str, float]:
    first = first or {}
    second = second or {}
    return {
        axis: (float(first.get(axis) or 0) + float(second.get(axis) or 0)) / 2.0
        for axis in ("x", "y", "z")
    }


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def select_single_sprinkler(
    sprinklers: list[dict[str, Any]],
    selected_ids: list[str | int],
) -> dict[str, Any]:
    if len(selected_ids) != 1:
        raise ValueError("請在灑水頭表格選取一顆灑水頭進行測試")
    selected_id = str(selected_ids[0])
    selected = next(
        (item for item in sprinklers if str(item.get("element_id")) == selected_id),
        None,
    )
    if selected is None:
        raise ValueError("選取的灑水頭已不在目前資料中，請重新讀取")
    return selected


def build_single_sprinkler_model_plan(
    *,
    main_pipe_id: str | int,
    sprinkler: dict[str, Any],
    preview_snapshot_id: str,
    diameter_analysis: dict[str, Any],
    pipe_type_id: str | int,
    system_type_id: str | int,
    level_id: str | int,
) -> dict[str, Any]:
    """Build the immutable contract used by preview, sandbox, and commit."""

    if not str(preview_snapshot_id or "").strip():
        raise ValueError("缺少預覽批次，請重新分析")
    sprinkler_id = sprinkler.get("element_id")
    point = sprinkler.get("point") or {}
    if sprinkler_id in (None, ""):
        raise ValueError("選取的灑水頭缺少 ElementId")

    segments = list(diameter_analysis.get("segments") or [])
    rows: dict[int, list[dict[str, Any]]] = {}
    for segment in segments:
        rows.setdefault(int(segment.get("row_index") or 0), []).append(segment)
    if not rows:
        raise ValueError("目前預覽沒有可用的管徑分段")

    px = float(point.get("x") or 0)
    py = float(point.get("y") or 0)
    ranked_rows = sorted(
        (
            min(_point_to_segment_2d(px, py, item) for item in row_segments),
            row_index,
        )
        for row_index, row_segments in rows.items()
    )
    source_row_index = ranked_rows[0][1]
    row_segments = sorted(
        rows[source_row_index],
        key=lambda item: int(item.get("sequence") or 0),
    )
    if any(
        item.get("diameter_mm") is None or bool(item.get("review_required"))
        for item in row_segments
    ):
        raise ValueError("選取灑水頭所屬支管仍有尚未確認的管徑")

    diameter_plan = [
        {
            "plan_entity_id": str(item.get("plan_entity_id") or ""),
            "segment_id": str(item.get("segment_id") or ""),
            "row_index": source_row_index,
            "sequence": int(item.get("sequence") or 0),
            "start": item.get("start") or {},
            "end": item.get("end") or {},
            "diameter_mm": float(item["diameter_mm"]),
            "sprinkler_id": item.get("sprinkler_id"),
            "is_sprinkler_terminal": bool(item.get("is_sprinkler_terminal")),
        }
        for item in row_segments
    ]
    plan = {
        "schema_version": "fire_branch_model_plan.v1",
        "sandbox_scope": "single_sprinkler",
        "main_pipe_id": int(main_pipe_id),
        "sprinkler_id": int(sprinkler_id),
        "source_row_index": source_row_index,
        "preview_snapshot_id": str(preview_snapshot_id),
        "pipe_type_id": int(pipe_type_id),
        "system_type_id": int(system_type_id),
        "level_id": int(level_id),
        "require_diameter_plan": True,
        "diameter_plan": diameter_plan,
    }
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    plan["plan_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return plan


def _point_to_segment_2d(px: float, py: float, segment: dict[str, Any]) -> float:
    start = segment.get("start") or {}
    end = segment.get("end") or {}
    x1 = float(start.get("x") or 0)
    y1 = float(start.get("y") or 0)
    x2 = float(end.get("x") or 0)
    y2 = float(end.get("y") or 0)
    dx = x2 - x1
    dy = y2 - y1
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        return math.hypot(px - x1, py - y1)
    ratio = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_squared))
    return math.hypot(px - (x1 + ratio * dx), py - (y1 + ratio * dy))
