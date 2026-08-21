from __future__ import annotations

import html
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from sc_revit.fire_branch.topology_plan import create_topology_plan
from sc_revit.fire_branch.main_geometry import (
    normalize_main_geometry,
    project_point_to_main_geometry,
)


_ACI_DISPLAY_COLORS = {
    1: "#e53935",
    2: "#d9a900",
    3: "#00b050",
    4: "#00a8b5",
    5: "#2878d0",
    6: "#bf00bf",
    7: "#222222",
}

_DIAMETER_INCH_LABELS = {
    20.0: '3/4"',
    25.0: '1"',
    32.0: '1 1/4"',
    40.0: '1 1/2"',
    50.0: '2"',
    65.0: '2 1/2"',
    80.0: '3"',
    100.0: '4"',
    125.0: '5"',
    150.0: '6"',
    200.0: '8"',
    250.0: '10"',
}

# SVG 色彩以管徑為主，讓不同管徑即使 CAD 原始線色相同也能快速分辨。
# CAD 原始色仍會以 source_color 保留在 SVG data attribute 中作為證據。
_DIAMETER_DISPLAY_COLORS = {
    20.0: "#4c78a8",
    25.0: "#00a8b5",
    32.0: "#ff7f00",
    40.0: "#e53935",
    50.0: "#8e44ad",
    65.0: "#2e7d32",
    80.0: "#1565c0",
    100.0: "#455a64",
    125.0: "#795548",
    150.0: "#6d4c41",
    200.0: "#37474f",
    250.0: "#263238",
}

_EVIDENCE_LABELS = {
    "explicit_color": "文字＋線色",
    "explicit_nearby": "鄰近文字",
    "line_color_reference": "線段顏色",
    "layer_reference": "圖層參考",
    "drawing_default": "CAD備註預設",
    "conflicting_label": "文字衝突",
    "conflicting_color": "線色衝突",
    "diameter_increase_conflict": "反向增徑待確認",
    "unresolved": "待確認",
    "uniform_user_setting": "統一設定",
    "user_revision": "使用者修正",
}

_REDUCER_SYMBOL_RADIUS_PX = 15.0
_TERMINAL_NODE_RADIUS_PX = 4.2
_MIN_FITTING_GAP_PX = 3.0
_MAX_VISUAL_BRANCH_GAP_PX = 18.0


def _analysis_cad_path_verified(analysis: dict[str, Any]) -> bool:
    """Tell the renderer whether CAD geometry is a trusted route source.

    CAD geometry is trusted only when the producer explicitly proves the route
    match.  A missing contract usually means a stale DLL or stale preview and
    must never inherit CAD geometry or colour silently.
    """

    if "cad_path_verified" in analysis:
        return bool(analysis.get("cad_path_verified"))
    check = analysis.get("cad_path_check")
    if isinstance(check, dict):
        return (
            str(check.get("status") or "").strip().casefold() == "matched"
            and bool(check.get("coordinate_verified"))
        )
    return False


def _build_reducer_layout(
    *,
    previous: dict[str, Any],
    current: dict[str, Any],
    row_index: int,
    from_diameter: float,
    to_diameter: float,
    placement: str,
) -> dict[str, Any] | None:
    delta_x = float(current["x2"]) - float(current["x1"])
    delta_y = float(current["y2"]) - float(current["y1"])
    downstream_length = math.hypot(delta_x, delta_y)
    if downstream_length <= 0.001:
        return None
    minimum_clearance = (
        _REDUCER_SYMBOL_RADIUS_PX
        + _TERMINAL_NODE_RADIUS_PX
        + _MIN_FITTING_GAP_PX
    )
    lead_length = min(minimum_clearance, downstream_length * 0.40)
    lead_ratio = lead_length / downstream_length
    reducer_x = float(current["x1"]) + delta_x * lead_ratio
    reducer_y = float(current["y1"]) + delta_y * lead_ratio
    return {
        "row_index": row_index,
        "x": reducer_x,
        "y": reducer_y,
        "lead_start": (float(current["x1"]), float(current["y1"])),
        "lead_end": (reducer_x, reducer_y),
        "lead_length_px": lead_length,
        "spacing_basis": "symbol_clearance_only",
        "lead_color": previous.get("display_color", previous["color"]),
        "lead_stroke_width": previous["stroke_width"],
        "lead_diameter_mm": from_diameter,
        "source_segment_id": str(current["segment_id"]),
        "from_diameter_mm": from_diameter,
        "to_diameter_mm": to_diameter,
        "label": f"DN{from_diameter:g} → DN{to_diameter:g}",
        "placement": placement,
    }


def _build_main_context_layout(
    raw_segments: Any,
    *,
    orientation: dict[str, Any],
    main_orientation: str,
    row_geometry: list[dict[str, Any]],
    station_start: float,
    station_spacing: float,
    station_count: int,
    main_cross: float,
    maximum_negative: float,
    maximum_positive: float,
) -> dict[str, Any]:
    """Map the actual selected main network into the schematic SVG space.

    Geometry is normalized before it is mapped: small endpoint gaps are
    snapped, true crossings are split into graph edges, and branch anchors are
    projected to the nearest actual edge.  No artificial straight guide line
    replaces the selected main route.
    """

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_segments or []):
        if not isinstance(raw, dict):
            continue
        start = _project_to_view(raw.get("start") or {}, orientation)
        end = _project_to_view(raw.get("end") or {}, orientation)
        if math.hypot(end[0] - start[0], end[1] - start[1]) <= 1e-6:
            continue
        projected_connections: list[dict[str, Any]] = []
        for raw_connection in raw.get("connections") or []:
            if not isinstance(raw_connection, dict):
                continue
            connection = dict(raw_connection)
            raw_point = raw_connection.get("point")
            if isinstance(raw_point, dict):
                point_x, point_y = _project_to_view(raw_point, orientation)
                connection["point"] = {"x": point_x, "y": point_y}
            projected_connections.append(connection)
        normalized.append(
            {
                "segment_id": str(raw.get("segment_id") or f"main-context-{index}"),
                "source_element_id": raw.get("source_element_id"),
                "diameter_mm": raw.get("diameter_mm"),
                "connections": projected_connections,
                "start": start,
                "end": end,
            }
        )

    graph = normalize_main_geometry(normalized)
    graph["anchors"] = {}
    if not graph["segments"]:
        return {
            "shape": "linear",
            "segments": [],
            "anchors": {},
            "graph": graph,
        }

    primary_index = 1 if main_orientation == "vertical" else 0
    cross_index = 0 if main_orientation == "vertical" else 1
    row_starts = [item["start"] for item in row_geometry if item.get("start")]
    row_primary_values = [point[primary_index] for point in row_starts]
    context_primary_values = [
        value
        for segment in graph["segments"]
        for value in (segment["start"][primary_index], segment["end"][primary_index])
    ]
    primary_values = row_primary_values or context_primary_values
    primary_min = min(primary_values)
    primary_max = max(primary_values)
    primary_range = primary_max - primary_min
    screen_primary_min = station_start
    screen_primary_max = station_start + max(0, station_count - 1) * station_spacing
    if primary_range <= 1e-6 and max(context_primary_values) - min(context_primary_values) > 1e-6:
        primary_min = min(context_primary_values)
        primary_max = max(context_primary_values)
        primary_range = primary_max - primary_min
        primary_screen_extent = max(120.0, station_spacing)
        screen_primary_min = station_start - primary_screen_extent / 2.0
        screen_primary_max = station_start + primary_screen_extent / 2.0

    cross_values = [point[cross_index] for point in row_starts]
    if not cross_values:
        cross_values = [
            value
            for segment in graph["segments"]
            for value in (segment["start"][cross_index], segment["end"][cross_index])
        ]
    cross_center = sum(cross_values) / len(cross_values)
    context_cross_values = [
        value
        for segment in graph["segments"]
        for value in (segment["start"][cross_index], segment["end"][cross_index])
    ]
    context_cross_range = max(context_cross_values) - min(context_cross_values)
    available_cross_extent = max(maximum_negative, maximum_positive)
    desired_cross_extent = max(80.0, min(360.0, available_cross_extent * 0.75))
    cross_scale = (
        desired_cross_extent / context_cross_range
        if context_cross_range > 1e-6
        else 1.0
    )

    def map_point(point: tuple[float, float]) -> tuple[float, float]:
        if primary_range > 1e-6:
            primary = screen_primary_min + (
                (point[primary_index] - primary_min)
                / primary_range
                * (screen_primary_max - screen_primary_min)
            )
        else:
            primary = (screen_primary_min + screen_primary_max) / 2.0
        cross = main_cross + (point[cross_index] - cross_center) * cross_scale
        return (cross, primary) if main_orientation == "vertical" else (primary, cross)

    laid_out = []
    for segment in graph["segments"]:
        start = map_point(segment["start"])
        end = map_point(segment["end"])
        laid_out.append(
            {
                "segment_id": segment["segment_id"],
                "source_segment_id": segment.get("source_segment_id"),
                "source_element_id": segment.get("source_element_id"),
                "component_id": segment.get("component_id"),
                "node_start": segment.get("node_start"),
                "node_end": segment.get("node_end"),
                "x1": start[0],
                "y1": start[1],
                "x2": end[0],
                "y2": end[1],
            }
        )

    anchors: dict[int, tuple[float, float]] = {}
    for item in row_geometry:
        if item.get("start") is None or item.get("row_index") is None:
            continue
        projection = project_point_to_main_geometry(item["start"], graph)
        if projection is None:
            continue
        graph["anchors"][int(item["row_index"])] = {
            **projection,
            "point": projection["point"],
        }
        anchors[int(item["row_index"])] = map_point(projection["point"])
    return {
        "shape": graph["shape"],
        "segments": laid_out,
        "anchors": anchors,
        "graph": graph,
    }


def _build_topology_canvas_layout(
    raw_segments: list[dict[str, Any]],
    *,
    orientation: dict[str, Any],
    main_context_layout: dict[str, Any],
    cad_verified: bool,
    canvas_contract: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Map trusted topology geometry into one stable, editable canvas space.

    The returned transform is shared by main pipes and branch pipes.  It never
    assigns pipe coordinates from row order, so bent mains and mixed branch
    directions cannot collapse into the same schematic lane.
    """

    graph = main_context_layout.get("graph") or {}
    graph_segments = list(graph.get("segments") or [])
    if not cad_verified or not graph_segments or not raw_segments:
        return None

    branch_sources: dict[str, dict[str, tuple[float, float]]] = {}
    points: list[tuple[float, float]] = []
    for segment in graph_segments:
        points.extend((segment["start"], segment["end"]))
    for index, raw in enumerate(raw_segments):
        start_raw = raw.get("cad_geometry_start") or raw.get("start")
        end_raw = raw.get("cad_geometry_end") or raw.get("end")
        if not isinstance(start_raw, dict) or not isinstance(end_raw, dict):
            return None
        start = _project_to_view(start_raw, orientation)
        end = _project_to_view(end_raw, orientation)
        if math.hypot(end[0] - start[0], end[1] - start[1]) <= 1e-9:
            return None
        segment_id = str(raw.get("segment_id") or f"canvas-segment-{index}")
        branch_sources[segment_id] = {"start": start, "end": end}
        points.extend((start, end))

    minimum_x = min(point[0] for point in points)
    maximum_x = max(point[0] for point in points)
    minimum_y = min(point[1] for point in points)
    maximum_y = max(point[1] for point in points)
    current_source_bounds = {
        "minimum_x": minimum_x,
        "maximum_x": maximum_x,
        "minimum_y": minimum_y,
        "maximum_y": maximum_y,
    }
    stable_contract = _valid_canvas_contract(canvas_contract)
    if stable_contract is not None:
        width = stable_contract["width"]
        height = stable_contract["height"]
        scale = stable_contract["scale"]
        offset_x = stable_contract["offset_x"]
        offset_y = stable_contract["offset_y"]
        source_bounds = dict(stable_contract["source_bounds"])
        contract_reused = True
    else:
        span_x = max(maximum_x - minimum_x, 1e-6)
        span_y = max(maximum_y - minimum_y, 1e-6)
        margin_x = 150.0
        margin_y = 90.0
        maximum_content_width = 1500.0
        maximum_content_height = 1600.0
        preferred_scale = 22.0
        scale = min(
            preferred_scale,
            maximum_content_width / span_x,
            maximum_content_height / span_y,
        )
        content_width = span_x * scale
        content_height = span_y * scale
        width = max(760.0, content_width + margin_x * 2.0)
        height = max(520.0, content_height + margin_y * 2.0)
        offset_x = (width - content_width) / 2.0 - minimum_x * scale
        offset_y = (height - content_height) / 2.0 - minimum_y * scale
        source_bounds = current_source_bounds
        contract_reused = False

    def map_point(point: tuple[float, float]) -> tuple[float, float]:
        return point[0] * scale + offset_x, point[1] * scale + offset_y

    main_segments = []
    for segment in graph_segments:
        start = map_point(segment["start"])
        end = map_point(segment["end"])
        main_segments.append(
            {
                "segment_id": segment["segment_id"],
                "source_segment_id": segment.get("source_segment_id"),
                "source_element_id": segment.get("source_element_id"),
                "component_id": segment.get("component_id"),
                "node_start": segment.get("node_start"),
                "node_end": segment.get("node_end"),
                "x1": start[0],
                "y1": start[1],
                "x2": end[0],
                "y2": end[1],
            }
        )

    branch_segments = {
        segment_id: {
            "start": map_point(source["start"]),
            "end": map_point(source["end"]),
        }
        for segment_id, source in branch_sources.items()
    }
    _close_visual_branch_gaps(branch_segments, raw_segments)
    anchors = {
        int(row_index): map_point(anchor["point"])
        for row_index, anchor in (graph.get("anchors") or {}).items()
        if isinstance(anchor, dict) and anchor.get("point") is not None
    }
    return {
        "coordinate_space": "topology_canvas",
        "width": width,
        "height": height,
        "main_segments": main_segments,
        "branch_segments": branch_segments,
        "anchors": anchors,
        "transform": {
            "scale": scale,
            "offset_x": offset_x,
            "offset_y": offset_y,
            "width": width,
            "height": height,
            "source_bounds": source_bounds,
            "current_source_bounds": current_source_bounds,
            "contract_reused": contract_reused,
        },
    }


def _valid_canvas_contract(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(contract, dict):
        return None
    try:
        width = float(contract.get("width"))
        height = float(contract.get("height"))
        scale = float(contract.get("scale"))
        offset_x = float(contract.get("offset_x"))
        offset_y = float(contract.get("offset_y"))
    except (TypeError, ValueError):
        return None
    source_bounds = contract.get("source_bounds")
    if not isinstance(source_bounds, dict):
        return None
    if (
        not math.isfinite(width)
        or not math.isfinite(height)
        or not math.isfinite(scale)
        or not math.isfinite(offset_x)
        or not math.isfinite(offset_y)
        or width <= 0
        or height <= 0
        or scale <= 0
    ):
        return None
    return {
        "width": width,
        "height": height,
        "scale": scale,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "source_bounds": copy_canvas_bounds(source_bounds),
    }


def copy_canvas_bounds(bounds: dict[str, Any]) -> dict[str, float]:
    return {
        "minimum_x": float(bounds.get("minimum_x") or 0.0),
        "maximum_x": float(bounds.get("maximum_x") or 0.0),
        "minimum_y": float(bounds.get("minimum_y") or 0.0),
        "maximum_y": float(bounds.get("maximum_y") or 0.0),
    }


def _close_visual_branch_gaps(
    branch_segments: dict[str, dict[str, tuple[float, float]]],
    raw_segments: list[dict[str, Any]],
) -> None:
    rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for raw in raw_segments:
        segment_id = str(raw.get("segment_id") or "").strip()
        if segment_id in branch_segments:
            rows[int(raw.get("row_index") or 0)].append(raw)
    for row_segments in rows.values():
        ordered = sorted(row_segments, key=lambda item: int(item.get("sequence") or 0))
        for before_raw, after_raw in zip(ordered, ordered[1:]):
            before = branch_segments.get(str(before_raw.get("segment_id") or ""))
            after = branch_segments.get(str(after_raw.get("segment_id") or ""))
            if before is None or after is None:
                continue
            before_end = before["end"]
            after_start = after["start"]
            gap = math.hypot(
                before_end[0] - after_start[0],
                before_end[1] - after_start[1],
            )
            if gap <= 0.001 or gap > _MAX_VISUAL_BRANCH_GAP_PX:
                continue
            before_vector = (
                before["end"][0] - before["start"][0],
                before["end"][1] - before["start"][1],
            )
            after_vector = (
                after["end"][0] - after["start"][0],
                after["end"][1] - after["start"][1],
            )
            if not _vectors_aligned(before_vector, after_vector):
                continue
            midpoint = (
                (before_end[0] + after_start[0]) / 2.0,
                (before_end[1] + after_start[1]) / 2.0,
            )
            before["end"] = midpoint
            after["start"] = midpoint


def _vectors_aligned(
    first: tuple[float, float],
    second: tuple[float, float],
) -> bool:
    first_length = math.hypot(first[0], first[1])
    second_length = math.hypot(second[0], second[1])
    if first_length <= 0.001 or second_length <= 0.001:
        return False
    dot = (
        first[0] * second[0]
        + first[1] * second[1]
    ) / (first_length * second_length)
    return dot > 0.995


def _classify_main_context_shape(segments: list[dict[str, Any]]) -> str:
    """Classify the visible main context without changing its geometry."""

    if not segments:
        return "linear"
    axes = [_segment_axis_name(item["start"], item["end"]) for item in segments]
    if all(axis == axes[0] for axis in axes):
        return "linear"
    if len(segments) == 2 and _main_segments_share_endpoint(segments[0], segments[1]):
        return "L"
    return "compound_bend"


def _segment_axis_name(start: tuple[float, float], end: tuple[float, float]) -> str:
    dx = abs(end[0] - start[0])
    dy = abs(end[1] - start[1])
    return "x" if dx >= dy else "y"


def _main_segments_share_endpoint(
    first: dict[str, Any],
    second: dict[str, Any],
    tolerance: float = 5.0 / 304.8,
) -> bool:
    points_first = (first["start"], first["end"])
    points_second = (second["start"], second["end"])
    return any(
        math.hypot(point_a[0] - point_b[0], point_a[1] - point_b[1]) <= tolerance
        for point_a in points_first
        for point_b in points_second
    )


def build_fire_branch_network_layout(
    analysis: dict[str, Any],
    *,
    main_diameter_mm: float | None = None,
) -> dict[str, Any]:
    """Build a schematic that preserves the active Revit view orientation."""

    cad_verified = _analysis_cad_path_verified(analysis)

    raw_segments = sorted(
        list(analysis.get("segments") or []),
        key=lambda item: (
            int(item.get("row_index") or 0),
            int(item.get("sequence") or 0),
        ),
    )
    rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for segment in raw_segments:
        rows[int(segment.get("row_index") or 0)].append(segment)

    orientation = _normalize_view_orientation(analysis.get("view_orientation"))
    row_geometry: list[dict[str, Any]] = []
    horizontal_score = 0.0
    vertical_score = 0.0
    for row_index, segments in rows.items():
        ordered = sorted(segments, key=lambda item: int(item.get("sequence") or 0))
        start = _project_to_view(
            (
                ordered[0].get("cad_geometry_start")
                if cad_verified
                else None
            )
            or ordered[0].get("start")
            or {},
            orientation,
        )
        end = _project_to_view(
            (
                ordered[-1].get("cad_geometry_end")
                if cad_verified
                else None
            )
            or ordered[-1].get("end")
            or {},
            orientation,
        )
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        horizontal_score += abs(dx)
        vertical_score += abs(dy)
        row_geometry.append(
            {
                "row_index": row_index,
                "start": start,
                "end": end,
                "dx": dx,
                "dy": dy,
            }
        )

    branch_axis = "x" if horizontal_score >= vertical_score else "y"
    main_orientation = "vertical" if branch_axis == "x" else "horizontal"
    ordered_rows = sorted(
        row_geometry,
        key=lambda item: item["start"][1]
        if main_orientation == "vertical"
        else item["start"][0],
    )
    station_tolerance = 5.0 / 304.8
    station_groups: list[list[dict[str, Any]]] = []
    for item in ordered_rows:
        coordinate = (
            item["start"][1]
            if main_orientation == "vertical"
            else item["start"][0]
        )
        if not station_groups:
            station_groups.append([item])
            continue
        previous_coordinates = [
            member["start"][1]
            if main_orientation == "vertical"
            else member["start"][0]
            for member in station_groups[-1]
        ]
        if abs(coordinate - sum(previous_coordinates) / len(previous_coordinates)) <= station_tolerance:
            station_groups[-1].append(item)
        else:
            station_groups.append([item])
    row_position = {
        int(item["row_index"]): position
        for position, group in enumerate(station_groups)
        for item in group
    }
    row_geometry_by_index = {
        int(item["row_index"]): item for item in row_geometry
    }
    row_metrics: dict[int, dict[str, Any]] = {}
    maximum_negative = 260.0
    maximum_positive = 260.0
    for row_index, row_segments in rows.items():
        row_segments.sort(key=lambda item: int(item.get("sequence") or 0))
        geometry = row_geometry_by_index[row_index]
        delta = geometry["dx"] if branch_axis == "x" else geometry["dy"]
        side = _direction_sign(delta, row_index)
        lengths = _row_display_lengths(row_segments, cad_verified=cad_verified)
        extent = sum(lengths)
        row_metrics[row_index] = {"side": side, "lengths": lengths, "extent": extent}
        if side < 0:
            maximum_negative = max(maximum_negative, extent)
        else:
            maximum_positive = max(maximum_positive, extent)

    label_gutter = 120.0
    edge_margin = 90.0
    station_count = max(1, len(station_groups))
    if main_orientation == "vertical":
        main_cross = label_gutter + edge_margin + maximum_negative
        width = main_cross + maximum_positive + edge_margin
        station_start = 96.0
        station_spacing = 142.0
        height = max(
            520.0,
            station_start + (station_count - 1) * station_spacing + 112.0,
        )
    else:
        main_cross = label_gutter + edge_margin + maximum_negative
        height = main_cross + maximum_positive + edge_margin
        station_start = 106.0
        station_spacing = 220.0
        width = max(
            760.0,
            station_start + (station_count - 1) * station_spacing + 132.0,
        )
    main_context_layout = _build_main_context_layout(
        analysis.get("main_context_segments"),
        orientation=orientation,
        main_orientation=main_orientation,
        row_geometry=row_geometry,
        station_start=station_start,
        station_spacing=station_spacing,
        station_count=station_count,
        main_cross=main_cross,
        maximum_negative=maximum_negative,
        maximum_positive=maximum_positive,
    )
    topology_canvas = _build_topology_canvas_layout(
        raw_segments,
        orientation=orientation,
        main_context_layout=main_context_layout,
        cad_verified=cad_verified,
        canvas_contract=analysis.get("network_canvas_contract"),
    )
    coordinate_space = "schematic_lanes"
    if topology_canvas is not None:
        coordinate_space = "topology_canvas"
        width = float(topology_canvas["width"])
        height = float(topology_canvas["height"])
        main_context_layout["segments"] = topology_canvas["main_segments"]
        main_context_layout["anchors"] = topology_canvas["anchors"]
    laid_out_segments: list[dict[str, Any]] = []
    laid_out_reducers: list[dict[str, Any]] = []
    laid_out_junctions: list[dict[str, Any]] = []
    segment_by_id: dict[str, dict[str, Any]] = {}
    row_lanes: list[dict[str, Any]] = []
    topology_plan = analysis.get("topology_plan") or create_topology_plan(analysis)
    topology_segments_by_id = {
        str(item.get("segment_id") or ""): item
        for item in (topology_plan.get("segments") or [])
        if str(item.get("segment_id") or "")
    }

    for row_index, row_segments in sorted(rows.items()):
        row_segments.sort(key=lambda item: int(item.get("sequence") or 0))
        station_index = row_position.get(row_index, row_index)
        station = station_start + station_index * station_spacing
        metrics = row_metrics[row_index]
        side = int(metrics["side"])
        if topology_canvas is not None:
            lane = None
        elif main_orientation == "vertical":
            lane = {
                "x": 18.0,
                "y": station - 58.0,
                "width": width - 36.0,
                "height": 116.0,
                "label_x": 34.0,
                "label_y": station + 5.0,
            }
        else:
            lane = {
                "x": station - 100.0,
                "y": 18.0,
                "width": 200.0,
                "height": height - 36.0,
                "label_x": station,
                "label_y": 42.0,
            }
        if lane is not None:
            lane.update(
                {
                    "row_index": row_index,
                    "position": station_index,
                    "station": station,
                    "side": side,
                    "label": f"第 {row_index + 1} 排",
                    "segment_count": len(row_segments),
                }
            )
            row_lanes.append(lane)
        anchor = main_context_layout["anchors"].get(row_index)
        if topology_canvas is not None:
            cursor = 0.0
        elif anchor is not None:
            if main_orientation == "vertical":
                station = anchor[1]
                lane["y"] = station - 58.0
                lane["label_y"] = station + 5.0
                cursor = anchor[0]
            else:
                station = anchor[0]
                lane["x"] = station - 100.0
                lane["label_x"] = station
                cursor = anchor[1]
        else:
            cursor = main_cross
        for segment_position, raw in enumerate(row_segments):
            length_mm = _segment_length_mm(raw, cad_verified=cad_verified)
            length_px = float(metrics["lengths"][segment_position])
            diameter = _float_or_none(raw.get("diameter_mm"))
            evidence = str(raw.get("evidence") or "unresolved")
            segment_id = str(raw.get("segment_id") or f"row-{row_index}-{len(laid_out_segments)}")
            canvas_segment = (
                topology_canvas["branch_segments"].get(segment_id)
                if topology_canvas is not None
                else None
            )
            if canvas_segment is not None:
                x1, y1 = canvas_segment["start"]
                x2, y2 = canvas_segment["end"]
                delta_x = x2 - x1
                delta_y = y2 - y1
                segment_axis = "x" if abs(delta_x) >= abs(delta_y) else "y"
                center_x = (x1 + x2) / 2.0
                center_y = (y1 + y2) / 2.0
                if segment_axis == "x":
                    label_x, label_y = center_x, center_y - 30.0
                else:
                    label_x, label_y = center_x + 82.0, center_y
            else:
                next_cursor = cursor + side * length_px
                center = (cursor + next_cursor) / 2
                if main_orientation == "vertical":
                    x1, y1, x2, y2 = cursor, station, next_cursor, station
                    label_x, label_y = center, station - 30.0
                    segment_axis = branch_axis
                else:
                    x1, y1, x2, y2 = station, cursor, station, next_cursor
                    label_x, label_y = station + 82.0, center
                    segment_axis = branch_axis
            raw_source_color = str(raw.get("color") or "")
            source_color = (
                cad_color_to_hex(raw.get("color"))
                if cad_verified
                else "#8a8a8a"
            )
            evidence_label = (
                _EVIDENCE_LABELS.get(evidence, evidence or "待確認")
                if cad_verified
                else "CAD路徑未驗證"
            )
            item = {
                "segment_id": segment_id,
                "plan_entity_id": str(
                    raw.get("plan_entity_id")
                    or topology_segments_by_id.get(segment_id, {}).get("plan_entity_id")
                    or f"segment:{segment_id}"
                ),
                "row_index": row_index,
                "sequence": int(raw.get("sequence") or 0),
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "color": source_color,
                "display_color": (
                    diameter_to_display_color(diameter, source_color)
                    if cad_verified
                    else "#8a8a8a"
                ),
                "source_color": source_color,
                "cad_source_color": raw_source_color,
                "diameter_mm": diameter,
                "diameter_label": format_diameter_label(diameter),
                "length_label": format_length_label(length_mm),
                "evidence": evidence,
                "evidence_label": evidence_label,
                "review_required": (
                    not cad_verified
                    or diameter is None
                    or "conflict" in evidence
                ),
                "length_mm": length_mm,
                "stroke_width": _pipe_stroke_width(diameter),
                "label_x": label_x,
                "label_y": label_y,
                "terminal_x": x2,
                "terminal_y": y2,
                "branch_axis": segment_axis,
                "is_sprinkler_terminal": bool(raw.get("is_sprinkler_terminal")),
                "sprinkler_id": raw.get("sprinkler_id"),
                "source": raw,
            }
            laid_out_segments.append(item)
            segment_by_id[segment_id] = item
            if canvas_segment is None:
                cursor = next_cursor

    for reducer_index, raw in enumerate(topology_plan.get("reducers") or []):
        if str(raw.get("placement") or "along_branch") != "along_branch":
            continue
        previous_id = str(raw.get("before_segment_id") or "")
        current_id = str(raw.get("after_segment_id") or "")
        previous = segment_by_id.get(previous_id)
        current = segment_by_id.get(current_id)
        if previous is None or current is None:
            continue
        from_diameter = float(raw.get("from_diameter_mm") or 0)
        to_diameter = float(raw.get("to_diameter_mm") or 0)
        reducer = _build_reducer_layout(
            previous=previous,
            current=current,
            row_index=int(raw.get("row_index") or 0),
            from_diameter=from_diameter,
            to_diameter=to_diameter,
            placement="along_branch",
        )
        if reducer is not None:
            reducer["plan_index"] = reducer_index
            reducer["plan_entity_id"] = str(
                raw.get("plan_entity_id")
                or f"reducer:{raw.get('before_segment_id') or ''}:{raw.get('after_segment_id') or raw.get('branch_segment_id') or ''}"
            )
            laid_out_reducers.append(reducer)

    for junction_index, raw in enumerate(topology_plan.get("junctions") or []):
        branch_ids = [str(item) for item in (raw.get("branch_segment_ids") or [])]
        branch = next(
            (segment_by_id.get(item) for item in branch_ids if segment_by_id.get(item)),
            None,
        )
        if branch is None:
            continue
        main_diameter = raw.get("main_diameter_mm")
        common_diameter = raw.get("common_branch_diameter_mm")
        outlet_diameters = [
            item
            for item in (raw.get("branch_outlet_diameters_mm") or [])
            if item is not None
        ]
        kind = str(raw.get("kind") or "unresolved_tee")
        label = "待確認"
        if main_diameter is not None and common_diameter is not None:
            if "endpoint_tee" in kind:
                tee_outlets = outlet_diameters or [common_diameter]
                if len(tee_outlets) >= 2:
                    first = tee_outlets[0]
                    second = tee_outlets[1]
                else:
                    first = common_diameter
                    second = common_diameter
                label = (
                    f"DN{float(first):g} × DN{float(second):g}"
                    f" × DN{float(main_diameter):g}"
                )
            else:
                cross_outlets = outlet_diameters or [common_diameter]
                label = (
                    f"DN{float(main_diameter):g} × DN{float(main_diameter):g}"
                    f" × DN{float(cross_outlets[0]):g}"
                )
                if len(branch_ids) == 2 and "endpoint_tee" not in kind:
                    second = cross_outlets[1] if len(cross_outlets) > 1 else common_diameter
                    label += f" × DN{float(second):g}"
        laid_out_junctions.append(
            {
                "plan_index": junction_index,
                "plan_entity_id": str(
                    raw.get("plan_entity_id")
                    or f"junction:{raw.get('main_segment_id') or 'main'}:{':'.join(sorted(branch_ids))}"
                ),
                "row_index": int((raw.get("row_indexes") or [0])[0]),
                "x": branch["x1"],
                "y": branch["y1"],
                "kind": kind,
                "label": label,
                "review_required": bool(raw.get("review_required")),
                "main_segment_id": str(raw.get("main_segment_id") or ""),
                "main_diameter_mm": main_diameter,
                "branch_diameter_mm": common_diameter,
                "opposite_branch_diameter_mm": common_diameter,
                "branch_segment_id": branch_ids[0],
                "source_branch_diameters_mm": raw.get("source_branch_diameters_mm") or [],
            }
        )

    for reducer_index, raw in enumerate(topology_plan.get("reducers") or []):
        if str(raw.get("placement") or "") not in {
            "after_cross",
            "after_endpoint_tee",
        }:
            continue
        current = segment_by_id.get(str(raw.get("branch_segment_id") or ""))
        if current is None:
            continue
        from_diameter = float(raw.get("from_diameter_mm") or 0)
        to_diameter = float(raw.get("to_diameter_mm") or 0)
        current_diameter = current.get("diameter_mm")
        if (
            current_diameter is None
            or from_diameter <= 0
            or to_diameter <= 0
            or not math.isclose(float(current_diameter), to_diameter)
        ):
            continue
        reducer = _build_reducer_layout(
            previous={
                **current,
                "color": current["color"],
                "display_color": diameter_to_display_color(
                    from_diameter,
                    current.get("source_color") or current["color"],
                ),
                "stroke_width": _pipe_stroke_width(from_diameter),
            },
            current=current,
            row_index=int(raw.get("row_index") or 0),
            from_diameter=from_diameter,
            to_diameter=to_diameter,
            placement=str(raw.get("placement") or "after_cross"),
        )
        if reducer is not None:
            reducer["plan_index"] = reducer_index
            reducer["plan_entity_id"] = str(
                raw.get("plan_entity_id")
                or f"reducer:{raw.get('branch_segment_id') or ''}:after-cross"
            )
            laid_out_reducers.append(reducer)

    main_label = "主管"
    if main_diameter_mm:
        main_label += "｜" + format_diameter_label(float(main_diameter_mm))
    if topology_canvas is not None and main_context_layout["segments"]:
        first_main = main_context_layout["segments"][0]
        main = {
            "x1": first_main["x1"],
            "y1": first_main["y1"],
            "x2": first_main["x2"],
            "y2": first_main["y2"],
            "label_x": min(item["x1"] for item in main_context_layout["segments"]),
            "label_y": min(item["y1"] for item in main_context_layout["segments"]) - 22.0,
        }
    elif main_orientation == "vertical":
        main = {
            "x1": main_cross,
            "y1": station_start - 58.0,
            "x2": main_cross,
            "y2": station_start
            + max(0, len(station_groups) - 1) * station_spacing
            + 58.0,
            "label_x": main_cross + 26.0,
            "label_y": station_start - 73.0,
        }
    else:
        main = {
            "x1": station_start - 58.0,
            "y1": main_cross,
            "x2": station_start
            + max(0, len(station_groups) - 1) * station_spacing
            + 58.0,
            "y2": main_cross,
            "label_x": station_start - 48.0,
            "label_y": main_cross - 22.0,
        }
    main.update(
        {
            "orientation": main_orientation,
            "diameter_mm": main_diameter_mm,
            "stroke_width": _pipe_stroke_width(main_diameter_mm),
            "label": main_label,
        }
    )
    return {
        "width": width,
        "height": height,
        "main": main,
        "main_shape": main_context_layout["shape"],
        "main_segments": main_context_layout["segments"],
        "main_graph": main_context_layout.get("graph") or {
            "segments": [],
            "nodes": [],
            "components": [],
            "anchors": {},
            "shape": "linear",
            "edge_count": 0,
            "node_count": 0,
            "component_count": 0,
        },
        "coordinate_space": coordinate_space,
        "canvas_transform": (
            topology_canvas.get("transform") if topology_canvas is not None else None
        ),
        "canvas_contract": (
            {
                "width": float(topology_canvas["width"]),
                "height": float(topology_canvas["height"]),
                "scale": float(topology_canvas["transform"]["scale"]),
                "offset_x": float(topology_canvas["transform"]["offset_x"]),
                "offset_y": float(topology_canvas["transform"]["offset_y"]),
                "source_bounds": copy_canvas_bounds(
                    topology_canvas["transform"].get("source_bounds") or {}
                ),
            }
            if topology_canvas is not None
            else None
        ),
        "orientation": {
            **orientation,
            "branch_axis": branch_axis,
            "main_orientation": main_orientation,
        },
        "row_lanes": sorted(row_lanes, key=lambda item: item["position"]),
        "segments": laid_out_segments,
        "reducers": laid_out_reducers,
        "junctions": laid_out_junctions,
        "row_count": len(rows),
        "station_count": len(station_groups),
        "cad_verified": cad_verified,
        "cad_status": str(
            (analysis.get("cad_path_check") or {}).get("status") or ""
        ),
    }


def render_fire_branch_network_svg(
    analysis: dict[str, Any],
    *,
    title: str = "消防支管路網",
    main_diameter_mm: float | None = None,
) -> str:
    layout = build_fire_branch_network_layout(
        analysis,
        main_diameter_mm=main_diameter_mm,
    )
    width = int(layout["width"])
    drawing_height = int(layout["height"])
    header_height = 92
    footer_height = 42
    height = drawing_height + header_height + footer_height
    main = layout["main"]
    orientation = layout["orientation"]
    main_width = _pipe_stroke_width(_float_or_none(main.get("diameter_mm")))
    orientation_source = html.escape(str(orientation.get("source") or ""), quote=True)
    cad_verified = bool(layout.get("cad_verified"))
    cad_status = html.escape(str(layout.get("cad_status") or ""), quote=True)
    compass_x = width * 0.5
    compass_y = 47.0
    north = orientation["north_screen"]
    east = orientation["east_screen"]
    north_x = compass_x + float(north["x"]) * 22.0
    north_y = compass_y + float(north["y"]) * 22.0
    east_x = compass_x + float(east["x"]) * 22.0
    east_y = compass_y + float(east["y"]) * 22.0
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" data-coordinate-space="{html.escape(str(layout.get("coordinate_space") or "schematic_lanes"), quote=True)}" data-orientation-source="{orientation_source}" data-main-shape="{html.escape(str(layout.get("main_shape") or "linear"), quote=True)}" data-cad-verified="{str(cad_verified).lower()}" data-cad-status="{cad_status}">',
        f"<title>{html.escape(title)}</title>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<rect x="0" y="0" width="100%" height="92" fill="#ffffff"/>',
        '<line x1="22" y1="91" x2="100%" y2="91" stroke="#d7d7d7" stroke-width="1"/>',
        f'<text x="28" y="37" font-family="Microsoft JhengHei, sans-serif" font-size="23" font-weight="700" fill="#202020">{html.escape(title)}</text>',
        (
            '<text x="28" y="64" font-family="Microsoft JhengHei, sans-serif" '
            'font-size="13" fill="#a15c00">CAD 路徑未驗證｜本圖僅供示意，不可用於建模</text>'
            if not cad_verified
            else '<text x="28" y="64" font-family="Microsoft JhengHei, sans-serif" font-size="13" fill="#666666">方向依目前 Revit 視圖｜虛線表示待確認</text>'
        ),
        f'<circle cx="{compass_x:.1f}" cy="{compass_y:.1f}" r="3" fill="#555555"/>',
        f'<line x1="{compass_x:.1f}" y1="{compass_y:.1f}" x2="{north_x:.1f}" y2="{north_y:.1f}" stroke="#334e68" stroke-width="2"/>',
        f'<text x="{compass_x + float(north["x"]) * 32.0:.1f}" y="{compass_y + float(north["y"]) * 32.0 + 4:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="12" font-weight="700" fill="#334e68">北</text>',
        f'<text x="{compass_x - float(north["x"]) * 32.0:.1f}" y="{compass_y - float(north["y"]) * 32.0 + 4:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="12" font-weight="700" fill="#66788a">南</text>',
        f'<line x1="{compass_x:.1f}" y1="{compass_y:.1f}" x2="{east_x:.1f}" y2="{east_y:.1f}" stroke="#8a5a00" stroke-width="2"/>',
        f'<text x="{compass_x + float(east["x"]) * 32.0:.1f}" y="{compass_y + float(east["y"]) * 32.0 + 4:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="12" font-weight="700" fill="#8a5a00">東</text>',
        f'<text x="{compass_x - float(east["x"]) * 32.0:.1f}" y="{compass_y - float(east["y"]) * 32.0 + 4:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="12" font-weight="700" fill="#8a7350">西</text>',
        f'<text x="{width - 28}" y="38" text-anchor="end" font-family="Microsoft JhengHei, sans-serif" font-size="14" fill="#444444">{len(layout["segments"])} 管段　{len(layout["junctions"])} 三通　{len(layout["reducers"])} 異徑　{sum(bool(item["review_required"]) for item in layout["segments"])} 待確認</text>',
        f'<text x="{width - 28}" y="64" text-anchor="end" font-family="Microsoft JhengHei, sans-serif" font-size="12" fill="#777777">雙擊管段可回到 Revit 定位</text>',
        f'<g transform="translate(0 {header_height})">',
    ]
    for lane in layout["row_lanes"]:
        fill = "#fafafa" if int(lane["position"]) % 2 == 0 else "#ffffff"
        parts.extend(
            [
                f'<rect x="{lane["x"]:.1f}" y="{lane["y"]:.1f}" width="{lane["width"]:.1f}" height="{lane["height"]:.1f}" rx="5" fill="{fill}" stroke="#ececec"/>',
                f'<text x="{lane["label_x"]:.1f}" y="{lane["label_y"]:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="14" font-weight="700" fill="#555555">{html.escape(lane["label"])}</text>',
                f'<text x="{lane["label_x"]:.1f}" y="{lane["label_y"] + 17:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="11" fill="#888888">{lane["segment_count"]} 段</text>',
            ]
        )
    if layout.get("main_segments"):
        for context_segment in layout["main_segments"]:
            parts.extend(
                [
                    f'<line class="main-context-segment" data-main-shape="{html.escape(str(layout.get("main_shape") or "linear"), quote=True)}" data-main-segment-id="{html.escape(str(context_segment["segment_id"]), quote=True)}" data-plan-entity-id="{html.escape(str(context_segment.get("plan_entity_id") or "main:" + str(context_segment["segment_id"])), quote=True)}" x1="{context_segment["x1"]:.1f}" y1="{context_segment["y1"]:.1f}" x2="{context_segment["x2"]:.1f}" y2="{context_segment["y2"]:.1f}" stroke="#d7d7d7" stroke-width="{main_width + 4:.1f}" stroke-linecap="round"/>',
                    f'<line class="main-context-segment" data-main-shape="{html.escape(str(layout.get("main_shape") or "linear"), quote=True)}" data-main-segment-id="{html.escape(str(context_segment["segment_id"]), quote=True)}" data-plan-entity-id="{html.escape(str(context_segment.get("plan_entity_id") or "main:" + str(context_segment["segment_id"])), quote=True)}" x1="{context_segment["x1"]:.1f}" y1="{context_segment["y1"]:.1f}" x2="{context_segment["x2"]:.1f}" y2="{context_segment["y2"]:.1f}" stroke="#34495e" stroke-width="{main_width:.1f}" stroke-linecap="round"/>',
                ]
            )
    else:
        parts.extend(
            [
                f'<line x1="{main["x1"]:.1f}" y1="{main["y1"]:.1f}" x2="{main["x2"]:.1f}" y2="{main["y2"]:.1f}" stroke="#d7d7d7" stroke-width="{main_width + 4:.1f}" stroke-linecap="round"/>',
                f'<line x1="{main["x1"]:.1f}" y1="{main["y1"]:.1f}" x2="{main["x2"]:.1f}" y2="{main["y2"]:.1f}" stroke="#34495e" stroke-width="{main_width:.1f}" stroke-linecap="round"/>',
            ]
        )
    parts.append(
        f'<text class="main-label" x="{main["label_x"]:.1f}" y="{main["label_y"]:.1f}" '
        'font-family="Microsoft JhengHei, sans-serif" font-size="14" font-weight="700" '
        'fill="#333333" paint-order="stroke" stroke="#ffffff" stroke-width="5" '
        f'stroke-linejoin="round">{html.escape(main["label"])}</text>'
    )
    for segment in layout["segments"]:
        dash = ' stroke-dasharray="10 7"' if segment["review_required"] else ""
        label_x = float(segment["label_x"])
        label_y = float(segment["label_y"])
        # Alternate the label side when adjacent segments share a lane.  This
        # keeps labels readable without reserving a fixed card that is wider
        # than the pipe segment itself.
        sequence = int(segment.get("sequence") or 0)
        if segment.get("branch_axis") == "x":
            label_y += -18.0 if sequence % 2 == 0 else 18.0
        else:
            label_x += -18.0 if sequence % 2 == 0 else 18.0
        pipe_width = float(segment["stroke_width"])
        label_color = "#a15c00" if segment["review_required"] else "#1f1f1f"
        detail_text = f'{segment["length_label"]}｜{segment["evidence_label"]}'
        parts.extend(
            [
                f'<g id="segment-{html.escape(segment["segment_id"], quote=True)}" data-plan-entity-id="{html.escape(segment["plan_entity_id"], quote=True)}" data-row="{segment["row_index"]}" data-sequence="{segment["sequence"]}" data-diameter-mm="{segment["diameter_mm"] if segment["diameter_mm"] is not None else ""}" data-source-color="{html.escape(segment["color"], quote=True)}" data-cad-source-color="{html.escape(segment.get("cad_source_color") or "", quote=True)}" data-evidence="{html.escape(segment["evidence"], quote=True)}">',
                f'<title>{html.escape(segment["diameter_label"])}｜{html.escape(detail_text)}</title>',
                f'<line x1="{segment["x1"]:.1f}" y1="{segment["y1"]:.1f}" x2="{segment["x2"]:.1f}" y2="{segment["y2"]:.1f}" stroke="#d0d0d0" stroke-width="{pipe_width + 4:.1f}" stroke-linecap="round"{dash}/>',
                f'<line x1="{segment["x1"]:.1f}" y1="{segment["y1"]:.1f}" x2="{segment["x2"]:.1f}" y2="{segment["y2"]:.1f}" stroke="{segment["display_color"]}" stroke-width="{pipe_width:.1f}" stroke-linecap="round"{dash}/>',
                f'<circle cx="{segment["x1"]:.1f}" cy="{segment["y1"]:.1f}" r="4.2" fill="#ffffff" stroke="#555555" stroke-width="1.5"/>',
                f'<text class="segment-label" x="{label_x:.1f}" y="{label_y - 4:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="11" font-weight="700" fill="{label_color}" paint-order="stroke" stroke="#ffffff" stroke-width="4" stroke-linejoin="round">{html.escape(segment["diameter_label"])}</text>',
                f'<text class="segment-detail" x="{label_x:.1f}" y="{label_y + 10:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="8.5" fill="#666666" paint-order="stroke" stroke="#ffffff" stroke-width="3" stroke-linejoin="round">{html.escape(detail_text)}</text>',
                "</g>",
            ]
        )
    for reducer in layout["reducers"]:
        x = reducer["x"]
        y = reducer["y"]
        lead_x1, lead_y1 = reducer["lead_start"]
        lead_x2, lead_y2 = reducer["lead_end"]
        lead_width = float(reducer["lead_stroke_width"])
        parts.extend(
            [
                f'<line x1="{lead_x1:.1f}" y1="{lead_y1:.1f}" x2="{lead_x2:.1f}" y2="{lead_y2:.1f}" stroke="#d0d0d0" stroke-width="{lead_width + 4:.1f}" stroke-linecap="round"/>',
                f'<line class="reducer-lead" data-plan-entity-id="{html.escape(reducer["plan_entity_id"], quote=True)}" x1="{lead_x1:.1f}" y1="{lead_y1:.1f}" x2="{lead_x2:.1f}" y2="{lead_y2:.1f}" stroke="{reducer["lead_color"]}" stroke-width="{lead_width:.1f}" stroke-linecap="round" data-diameter-mm="{reducer["lead_diameter_mm"] if reducer["lead_diameter_mm"] is not None else ""}"/>',
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="15" fill="#fff3e0" stroke="#e57400" stroke-width="2"/>',
                f'<polygon points="{x - 10:.1f},{y - 10:.1f} {x + 10:.1f},{y - 6:.1f} {x + 10:.1f},{y + 6:.1f} {x - 10:.1f},{y + 10:.1f}" fill="#ffffff" stroke="#b95700" stroke-width="2"/>',
                f'<title>{html.escape(reducer["label"])}</title>',
                f'<text class="reducer-label" x="{x:.1f}" y="{y + 30:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="9.5" font-weight="700" fill="#333333" paint-order="stroke" stroke="#ffffff" stroke-width="3" stroke-linejoin="round">{html.escape(reducer["label"])}</text>',
            ]
        )
    for segment in layout["segments"]:
        if segment.get("is_sprinkler_terminal"):
            parts.append(_svg_terminal_marker(segment))
    for junction_index, junction in enumerate(layout["junctions"]):
        x = junction["x"]
        y = junction["y"]
        review = bool(junction["review_required"])
        stroke = "#d97706" if review else "#176b54"
        fill = "#fff7df" if review else "#e9f7f1"
        kind = str(junction.get("kind") or "")
        if review:
            title = "待確認四通" if "cross" in kind else "待確認三通"
        elif kind == "reducing_cross":
            title = "異徑四通"
        elif kind == "cross":
            title = "四通"
        elif kind in {"reducing_tee", "reducing_endpoint_tee"}:
            title = "異徑三通"
        else:
            title = "三通"
        vertical_start = y - 8 if "cross" in kind else y
        compact_label = str(junction["label"])
        junction_label_x = x + 16.0
        junction_label_y = y - 15.0 if junction_index % 2 == 0 else y + 27.0
        junction_anchor = "start"
        if junction_index % 4 == 3:
            junction_label_x = x - 16.0
            junction_anchor = "end"
        parts.extend(
            [
                f'<circle data-plan-entity-id="{html.escape(junction["plan_entity_id"], quote=True)}" cx="{x:.1f}" cy="{y:.1f}" r="12" fill="{fill}" stroke="{stroke}" stroke-width="2.5"/>',
                f'<path d="M {x - 7:.1f} {y:.1f} H {x + 7:.1f} M {x:.1f} {vertical_start:.1f} V {y + 8:.1f}" fill="none" stroke="{stroke}" stroke-width="3" stroke-linecap="round"/>',
                f'<title>{html.escape(title)}｜{html.escape(compact_label)}</title>',
                f'<text class="junction-label" x="{junction_label_x:.1f}" y="{junction_label_y:.1f}" text-anchor="{junction_anchor}" font-family="Microsoft JhengHei, sans-serif" font-size="9" font-weight="700" fill="{stroke}" paint-order="stroke" stroke="#ffffff" stroke-width="3" stroke-linejoin="round">{html.escape(title)}｜{html.escape(compact_label)}</text>',
            ]
        )
    parts.extend(
        [
            "</g>",
            f'<line x1="22" y1="{height - footer_height}" x2="{width - 22}" y2="{height - footer_height}" stroke="#dddddd"/>',
            f'<text x="28" y="{height - 16}" font-family="Microsoft JhengHei, sans-serif" font-size="11.5" fill="#777777">管線色彩依管徑｜選取物件可查看完整證據與修正｜虛線表示待確認</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts) + "\n"


def write_fire_branch_network_svg(
    path: str | Path,
    analysis: dict[str, Any],
    *,
    title: str = "消防支管路網",
    main_diameter_mm: float | None = None,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_fire_branch_network_svg(
            analysis,
            title=title,
            main_diameter_mm=main_diameter_mm,
        ),
        encoding="utf-8",
    )
    return output


def _svg_terminal_marker(segment: dict[str, Any]) -> str:
    x = float(segment["x2"])
    y = float(segment["y2"])
    sprinkler_id = html.escape(str(segment.get("sprinkler_id") or ""))
    if segment.get("branch_axis") == "y":
        return (
            f'<g class="sprinkler-terminal" data-sprinkler-id="{sprinkler_id}">'
            f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x + 22:.1f}" y2="{y:.1f}" '
            'stroke="#555555" stroke-width="1.8"/>'
            f'<path d="M {x + 30:.1f} {y - 9:.1f} Q {x + 20:.1f} {y:.1f} '
            f'{x + 30:.1f} {y + 9:.1f}" fill="#ffffff" stroke="#444444" '
            'stroke-width="1.8"/></g>'
        )
    return (
        f'<g class="sprinkler-terminal" data-sprinkler-id="{sprinkler_id}">'
        f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y + 22:.1f}" '
        'stroke="#555555" stroke-width="1.8"/>'
        f'<path d="M {x - 9:.1f} {y + 30:.1f} Q {x:.1f} {y + 20:.1f} '
        f'{x + 9:.1f} {y + 30:.1f}" fill="#ffffff" stroke="#444444" '
        'stroke-width="1.8"/></g>'
    )


def cad_color_to_hex(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text.startswith("rgb:"):
        try:
            red, green, blue = (int(part) for part in text[4:].split(","))
            if all(0 <= item <= 255 for item in (red, green, blue)):
                return f"#{red:02x}{green:02x}{blue:02x}"
        except (TypeError, ValueError):
            pass
    if text.startswith("aci:"):
        text = text[4:]
    if text.isdigit():
        return _ACI_DISPLAY_COLORS.get(int(text), "#555555")
    named = {
        "red": "#e53935",
        "yellow": "#d9a900",
        "green": "#00b050",
        "cyan": "#00a8b5",
        "blue": "#2878d0",
        "magenta": "#bf00bf",
        "orange": "#ff7f00",
        "white": "#222222",
        "black": "#222222",
    }
    return named.get(text, "#555555")


def diameter_to_display_color(
    diameter_mm: float | None,
    source_color: str | None = None,
) -> str:
    """Return a stable SVG colour for a resolved diameter.

    Unknown diameters remain neutral instead of inheriting a misleading CAD
    colour.  The original CAD colour is kept separately for evidence/audit.
    """
    if diameter_mm is None:
        return "#8a8a8a"
    nominal = float(diameter_mm)
    for known, color in _DIAMETER_DISPLAY_COLORS.items():
        if abs(known - nominal) <= 0.01:
            return color
    return source_color or "#8a8a8a"


def format_diameter_label(value: float | None) -> str:
    if value is None:
        return "待確認"
    nominal = float(value)
    inch = _DIAMETER_INCH_LABELS.get(round(nominal, 3))
    dn = f"DN{nominal:g}"
    return f"{inch} / {dn}" if inch else dn


def format_length_label(value_mm: float) -> str:
    length = max(0.0, float(value_mm or 0))
    if length >= 1000.0:
        return f"{length / 1000.0:.2f} m"
    return f"{length:.0f} mm"


def _row_display_lengths(
    segments: list[dict[str, Any]],
    *,
    cad_verified: bool = False,
) -> list[float]:
    lengths_mm = [
        _segment_length_mm(item, cad_verified=cad_verified) for item in segments
    ]
    total_mm = sum(lengths_mm)
    if total_mm <= 1e-9:
        return [0.0 for _ in segments]
    display_extent = max(130.0, min(900.0, total_mm / 13.0))
    return [display_extent * length_mm / total_mm for length_mm in lengths_mm]


def _pipe_stroke_width(diameter_mm: float | None) -> float:
    if diameter_mm is None:
        return 4.0
    nominal = float(diameter_mm)
    for maximum, width in (
        (25.0, 4.0),
        (32.0, 6.0),
        (40.0, 8.0),
        (50.0, 10.0),
        (65.0, 12.0),
        (80.0, 14.0),
    ):
        if nominal <= maximum:
            return width
    return 16.0


def _direction_sign(delta: float, row_index: int) -> int:
    if abs(delta) <= 0.000001:
        return 1 if row_index % 2 == 0 else -1
    return 1 if delta > 0 else -1


def _normalize_view_orientation(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    right = _normalize_xyz(raw.get("right"), (1.0, 0.0, 0.0))
    up = _normalize_xyz(raw.get("up"), (0.0, 1.0, 0.0))
    source = str(raw.get("source") or "").strip() or "model_xy_fallback"
    east_screen = _normalize_xy((right[0], -up[0]), (1.0, 0.0))
    north_screen = _normalize_xy((right[1], -up[1]), (0.0, -1.0))
    return {
        "source": source,
        "view_id": raw.get("view_id"),
        "view_name": str(raw.get("view_name") or ""),
        "right": {"x": right[0], "y": right[1], "z": right[2]},
        "up": {"x": up[0], "y": up[1], "z": up[2]},
        "east_screen": {"x": east_screen[0], "y": east_screen[1]},
        "north_screen": {"x": north_screen[0], "y": north_screen[1]},
    }


def _normalize_xyz(value: Any, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    raw = value if isinstance(value, dict) else {}
    vector = (
        float(raw.get("x") or 0),
        float(raw.get("y") or 0),
        float(raw.get("z") or 0),
    )
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 0.000001:
        return fallback
    return tuple(component / length for component in vector)


def _normalize_xy(
    value: tuple[float, float],
    fallback: tuple[float, float],
) -> tuple[float, float]:
    length = math.hypot(value[0], value[1])
    if length <= 0.000001:
        return fallback
    return value[0] / length, value[1] / length


def _project_to_view(
    point: dict[str, Any],
    orientation: dict[str, Any],
) -> tuple[float, float]:
    model = (
        float(point.get("x") or 0),
        float(point.get("y") or 0),
        float(point.get("z") or 0),
    )
    right = orientation["right"]
    up = orientation["up"]
    screen_x = sum(model[index] * float(right[key]) for index, key in enumerate(("x", "y", "z")))
    screen_y = -sum(model[index] * float(up[key]) for index, key in enumerate(("x", "y", "z")))
    return screen_x, screen_y


def _segment_length_mm(
    segment: dict[str, Any],
    *,
    cad_verified: bool = False,
) -> float:
    if cad_verified:
        cad_start = segment.get("cad_geometry_start") or {}
        cad_end = segment.get("cad_geometry_end") or {}
        if cad_start and cad_end:
            dx = float(cad_end.get("x") or 0) - float(cad_start.get("x") or 0)
            dy = float(cad_end.get("y") or 0) - float(cad_start.get("y") or 0)
            cad_length = math.hypot(dx, dy) * 304.8
            if cad_length > 1e-9:
                return cad_length
    explicit = _float_or_none(segment.get("planned_length_mm"))
    if explicit and explicit > 0:
        return explicit
    start = segment.get("start") or {}
    end = segment.get("end") or {}
    dx = float(end.get("x") or 0) - float(start.get("x") or 0)
    dy = float(end.get("y") or 0) - float(start.get("y") or 0)
    return math.hypot(dx, dy) * 304.8


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _range(values) -> float:
    items = list(values)
    return max(items) - min(items) if items else 0.0


def _find_station(stations: list[float], value: float) -> int | None:
    tolerance = 50.0 / 304.8
    for index, station in enumerate(stations):
        if abs(station - value) <= tolerance:
            return index
    return None
