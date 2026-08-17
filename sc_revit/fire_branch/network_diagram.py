from __future__ import annotations

import html
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from sc_revit.fire_branch.model_plan import build_fire_branch_topology_plan


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

_EVIDENCE_LABELS = {
    "explicit_color": "文字＋線色",
    "explicit_nearby": "鄰近文字",
    "line_color_reference": "線段顏色",
    "layer_reference": "圖層參考",
    "drawing_default": "圖面預設",
    "conflicting_label": "文字衝突",
    "conflicting_color": "線色衝突",
    "diameter_increase_conflict": "反向增徑待確認",
    "unresolved": "待確認",
}

_REDUCER_SYMBOL_RADIUS_PX = 15.0
_TERMINAL_NODE_RADIUS_PX = 4.2
_MIN_FITTING_GAP_PX = 3.0


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
        "lead_color": previous["color"],
        "lead_stroke_width": previous["stroke_width"],
        "lead_diameter_mm": from_diameter,
        "source_segment_id": str(current["segment_id"]),
        "from_diameter_mm": from_diameter,
        "to_diameter_mm": to_diameter,
        "label": f"DN{from_diameter:g} → DN{to_diameter:g}",
        "placement": placement,
    }


def build_fire_branch_network_layout(
    analysis: dict[str, Any],
    *,
    main_diameter_mm: float | None = None,
) -> dict[str, Any]:
    """Build a schematic that preserves the active Revit view orientation."""

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
            ordered[0].get("cad_geometry_start")
            or ordered[0].get("start")
            or {},
            orientation,
        )
        end = _project_to_view(
            ordered[-1].get("cad_geometry_end")
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
        lengths = _row_display_lengths(row_segments)
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
    laid_out_segments: list[dict[str, Any]] = []
    laid_out_reducers: list[dict[str, Any]] = []
    laid_out_junctions: list[dict[str, Any]] = []
    segment_by_id: dict[str, dict[str, Any]] = {}
    row_lanes: list[dict[str, Any]] = []

    for row_index, row_segments in sorted(rows.items()):
        row_segments.sort(key=lambda item: int(item.get("sequence") or 0))
        station_index = row_position.get(row_index, row_index)
        station = station_start + station_index * station_spacing
        metrics = row_metrics[row_index]
        side = int(metrics["side"])
        if main_orientation == "vertical":
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
        cursor = main_cross
        for segment_position, raw in enumerate(row_segments):
            length_mm = _segment_length_mm(raw)
            length_px = float(metrics["lengths"][segment_position])
            next_cursor = cursor + side * length_px
            diameter = _float_or_none(raw.get("diameter_mm"))
            evidence = str(raw.get("evidence") or "unresolved")
            segment_id = str(raw.get("segment_id") or f"row-{row_index}-{len(laid_out_segments)}")
            center = (cursor + next_cursor) / 2
            if main_orientation == "vertical":
                x1, y1, x2, y2 = cursor, station, next_cursor, station
                label_x, label_y = center, station - 30.0
            else:
                x1, y1, x2, y2 = station, cursor, station, next_cursor
                label_x, label_y = station + 82.0, center
            item = {
                "segment_id": segment_id,
                "row_index": row_index,
                "sequence": int(raw.get("sequence") or 0),
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "color": cad_color_to_hex(raw.get("color")),
                "source_color": str(raw.get("color") or ""),
                "diameter_mm": diameter,
                "diameter_label": format_diameter_label(diameter),
                "length_label": format_length_label(length_mm),
                "evidence": evidence,
                "evidence_label": _EVIDENCE_LABELS.get(evidence, evidence or "待確認"),
                "review_required": diameter is None or "conflict" in evidence,
                "length_mm": length_mm,
                "stroke_width": _pipe_stroke_width(diameter),
                "label_x": label_x,
                "label_y": label_y,
                "terminal_x": x2,
                "terminal_y": y2,
                "branch_axis": branch_axis,
                "is_sprinkler_terminal": bool(raw.get("is_sprinkler_terminal")),
                "sprinkler_id": raw.get("sprinkler_id"),
                "source": raw,
            }
            laid_out_segments.append(item)
            segment_by_id[segment_id] = item
            cursor = next_cursor

    topology_plan = analysis.get("topology_plan") or build_fire_branch_topology_plan(
        analysis
    )
    for raw in topology_plan.get("reducers") or []:
        if str(raw.get("placement") or "along_branch") != "along_branch":
            continue
        previous_id = str(raw.get("after_segment_id") or "")
        current_id = str(raw.get("before_segment_id") or "")
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
            laid_out_reducers.append(reducer)

    for raw in topology_plan.get("junctions") or []:
        branch_ids = [str(item) for item in (raw.get("branch_segment_ids") or [])]
        branch = next(
            (segment_by_id.get(item) for item in branch_ids if segment_by_id.get(item)),
            None,
        )
        if branch is None:
            continue
        main_diameter = raw.get("main_diameter_mm")
        common_diameter = raw.get("common_branch_diameter_mm")
        kind = str(raw.get("kind") or "unresolved_tee")
        label = "待確認"
        if main_diameter is not None and common_diameter is not None:
            label = (
                f"DN{float(main_diameter):g} × DN{float(main_diameter):g}"
                f" × DN{float(common_diameter):g}"
            )
            if len(branch_ids) == 2:
                label += f" × DN{float(common_diameter):g}"
        laid_out_junctions.append(
            {
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

    for raw in topology_plan.get("reducers") or []:
        if str(raw.get("placement") or "") != "after_cross":
            continue
        current = segment_by_id.get(str(raw.get("branch_segment_id") or ""))
        if current is None:
            continue
        reducer = _build_reducer_layout(
            previous={
                **current,
                "color": current["color"],
                "stroke_width": _pipe_stroke_width(float(raw["from_diameter_mm"])),
            },
            current=current,
            row_index=int(raw.get("row_index") or 0),
            from_diameter=float(raw["from_diameter_mm"]),
            to_diameter=float(raw["to_diameter_mm"]),
            placement="after_cross",
        )
        if reducer is not None:
            laid_out_reducers.append(reducer)

    main_label = "主管"
    if main_diameter_mm:
        main_label += "｜" + format_diameter_label(float(main_diameter_mm))
    if main_orientation == "vertical":
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
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" data-orientation-source="{orientation_source}">',
        f"<title>{html.escape(title)}</title>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<rect x="0" y="0" width="100%" height="92" fill="#ffffff"/>',
        '<line x1="22" y1="91" x2="100%" y2="91" stroke="#d7d7d7" stroke-width="1"/>',
        f'<text x="28" y="37" font-family="Microsoft JhengHei, sans-serif" font-size="23" font-weight="700" fill="#202020">{html.escape(title)}</text>',
        '<text x="28" y="64" font-family="Microsoft JhengHei, sans-serif" font-size="13" fill="#666666">方向依目前 Revit 視圖｜虛線表示待確認</text>',
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
    parts.extend(
        [
            f'<line x1="{main["x1"]:.1f}" y1="{main["y1"]:.1f}" x2="{main["x2"]:.1f}" y2="{main["y2"]:.1f}" stroke="#d7d7d7" stroke-width="{main_width + 4:.1f}" stroke-linecap="round"/>',
            f'<line x1="{main["x1"]:.1f}" y1="{main["y1"]:.1f}" x2="{main["x2"]:.1f}" y2="{main["y2"]:.1f}" stroke="#34495e" stroke-width="{main_width:.1f}" stroke-linecap="round"/>',
            f'<rect x="{main["label_x"] - 10:.1f}" y="{main["label_y"] - 19:.1f}" width="160" height="28" rx="4" fill="#ffffff" stroke="#cccccc"/>',
            f'<text x="{main["label_x"]:.1f}" y="{main["label_y"]:.1f}" font-family="Microsoft JhengHei, sans-serif" font-size="14" font-weight="700" fill="#333333">{html.escape(main["label"])}</text>',
        ]
    )
    for segment in layout["segments"]:
        dash = ' stroke-dasharray="10 7"' if segment["review_required"] else ""
        label_fill = "#fff8dc" if segment["review_required"] else "#ffffff"
        label_border = "#d6a700" if segment["review_required"] else "#cfcfcf"
        label_x = float(segment["label_x"])
        label_y = float(segment["label_y"])
        pipe_width = float(segment["stroke_width"])
        parts.extend(
            [
                f'<g id="segment-{html.escape(segment["segment_id"], quote=True)}" data-row="{segment["row_index"]}" data-sequence="{segment["sequence"]}" data-diameter-mm="{segment["diameter_mm"] if segment["diameter_mm"] is not None else ""}">',
                f'<line x1="{segment["x1"]:.1f}" y1="{segment["y1"]:.1f}" x2="{segment["x2"]:.1f}" y2="{segment["y2"]:.1f}" stroke="#d0d0d0" stroke-width="{pipe_width + 4:.1f}" stroke-linecap="round"{dash}/>',
                f'<line x1="{segment["x1"]:.1f}" y1="{segment["y1"]:.1f}" x2="{segment["x2"]:.1f}" y2="{segment["y2"]:.1f}" stroke="{segment["color"]}" stroke-width="{pipe_width:.1f}" stroke-linecap="round"{dash}/>',
                f'<circle cx="{segment["x1"]:.1f}" cy="{segment["y1"]:.1f}" r="4.2" fill="#ffffff" stroke="#555555" stroke-width="1.5"/>',
                f'<rect x="{label_x - 73:.1f}" y="{label_y - 24:.1f}" width="146" height="44" rx="4" fill="{label_fill}" stroke="{label_border}"/>',
                f'<text x="{label_x:.1f}" y="{label_y - 5:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="14" font-weight="700" fill="#1f1f1f">{html.escape(segment["diameter_label"])}</text>',
                f'<text x="{label_x:.1f}" y="{label_y + 12:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="10.5" fill="#666666">{html.escape(segment["length_label"])}｜{html.escape(segment["evidence_label"])}</text>',
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
                f'<line class="reducer-lead" x1="{lead_x1:.1f}" y1="{lead_y1:.1f}" x2="{lead_x2:.1f}" y2="{lead_y2:.1f}" stroke="{reducer["lead_color"]}" stroke-width="{lead_width:.1f}" stroke-linecap="round" data-diameter-mm="{reducer["lead_diameter_mm"] if reducer["lead_diameter_mm"] is not None else ""}"/>',
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="15" fill="#fff3e0" stroke="#e57400" stroke-width="2"/>',
                f'<polygon points="{x - 10:.1f},{y - 10:.1f} {x + 10:.1f},{y - 6:.1f} {x + 10:.1f},{y + 6:.1f} {x - 10:.1f},{y + 10:.1f}" fill="#ffffff" stroke="#b95700" stroke-width="2"/>',
                f'<rect x="{x - 54:.1f}" y="{y + 33:.1f}" width="108" height="24" rx="3" fill="#ffffff" stroke="#d2d2d2"/>',
                f'<text x="{x:.1f}" y="{y + 50:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="11" font-weight="700" fill="#333333">{html.escape(reducer["label"])}</text>',
            ]
        )
    for segment in layout["segments"]:
        if segment.get("is_sprinkler_terminal"):
            parts.append(_svg_terminal_marker(segment))
    for junction in layout["junctions"]:
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
        elif kind == "reducing_tee":
            title = "異徑三通"
        else:
            title = "三通"
        vertical_start = y - 8 if "cross" in kind else y
        parts.extend(
            [
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="12" fill="{fill}" stroke="{stroke}" stroke-width="2.5"/>',
                f'<path d="M {x - 7:.1f} {y:.1f} H {x + 7:.1f} M {x:.1f} {vertical_start:.1f} V {y + 8:.1f}" fill="none" stroke="{stroke}" stroke-width="3" stroke-linecap="round"/>',
                f'<rect x="{x + 16:.1f}" y="{y - 27:.1f}" width="126" height="42" rx="4" fill="#ffffff" stroke="{stroke}"/>',
                f'<text x="{x + 79:.1f}" y="{y - 10:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="11" font-weight="700" fill="#333333">{title}</text>',
                f'<text x="{x + 79:.1f}" y="{y + 7:.1f}" text-anchor="middle" font-family="Microsoft JhengHei, sans-serif" font-size="10.5" fill="#555555">{html.escape(junction["label"])}</text>',
            ]
        )
    parts.extend(
        [
            "</g>",
            f'<line x1="22" y1="{height - footer_height}" x2="{width - 22}" y2="{height - footer_height}" stroke="#dddddd"/>',
            f'<text x="28" y="{height - 16}" font-family="Microsoft JhengHei, sans-serif" font-size="11.5" fill="#777777">管線顏色沿用 CAD｜管徑與長度標示於管段上方｜虛線與淡黃色框需人工確認</text>',
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


def _row_display_lengths(segments: list[dict[str, Any]]) -> list[float]:
    lengths_mm = [_segment_length_mm(item) for item in segments]
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


def _segment_length_mm(segment: dict[str, Any]) -> float:
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
