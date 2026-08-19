from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


_SOURCE_PATH = Path(__file__).resolve()


def _rule_source_paths() -> tuple[Path, ...]:
    return (_SOURCE_PATH, _SOURCE_PATH.with_name("diameter_analysis.py"))


def _rule_identity() -> tuple[str, str]:
    digest = hashlib.sha256()
    sources = _rule_source_paths()
    for source_path in sources:
        digest.update(source_path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(source_path.read_bytes())
    rule_hash = digest.hexdigest()[:12]
    updated = datetime.fromtimestamp(
        max(source_path.stat().st_mtime for source_path in sources)
    )
    return f"dev-{updated:%Y%m%d-%H%M%S}", rule_hash


def build_preview_summary(preview_payload: dict[str, Any]) -> dict[str, Any]:
    """Translate Revit preview evidence into a concise user-facing result."""

    cad_check = preview_payload.get("cad_path_check") or {}
    cad_status = str(cad_check.get("status") or "")
    coverage = max(0.0, min(1.0, float(cad_check.get("coverage_ratio") or 0)))
    skipped_count = len(preview_payload.get("skipped") or [])
    diameter_analysis = _build_diameter_analysis(
        cad_check,
        list(preview_payload.get("cad_coordinate_anchors") or []),
        str(preview_payload.get("cad_coordinate_anchor_error") or ""),
        dict(preview_payload.get("view_orientation") or {}),
    )
    diameter_ready = not diameter_analysis or diameter_analysis.get("status") == "ready"
    status = (
        "ready"
        if cad_status == "matched" and skipped_count == 0 and diameter_ready
        else "needs_attention"
    )

    cad_labels = {
        "matched": f"吻合 {coverage:.0%}",
        "mismatch": f"覆蓋率 {coverage:.0%}（路徑尚未吻合）",
        "ambiguous": "目前無法確定",
        "ambiguous_source": "找到多個可能來源",
        "cad_unavailable": "目前視圖沒有可用 CAD",
        "cad_no_paths": "沒有找到可用路徑",
        "invalid_transform": "CAD 對位資料無效",
    }
    lines = [
        f"找到支管：{int(preview_payload.get('row_count') or 0)} 排",
        f"預估管段：{int(preview_payload.get('estimated_pipe_count') or 0)} 段",
        f"灑水頭：{int(preview_payload.get('sprinkler_count') or 0)} 顆",
        f"CAD 路徑：{cad_labels.get(cad_status, '尚未完成核對')}",
    ]
    main_context_count = int(cad_check.get("main_context_segment_count") or 0)
    planned_count = int(cad_check.get("planned_segment_count") or 0)
    if main_context_count or planned_count:
        lines.append(
            "CAD 抽取範圍："
            f"主管 {main_context_count} 段＋支管 {planned_count} 段"
        )
    if cad_check.get("extraction_scope"):
        lines.append("CAD 抽取方式：" + str(cad_check.get("extraction_scope")))
    if skipped_count:
        lines.append(f"略過灑水頭：{skipped_count} 顆")
    if diameter_analysis:
        default_diameter = diameter_analysis.get("default_diameter_mm")
        default_note_count = int(diameter_analysis.get("default_note_count") or 0)
        default_note_summary = (
            f"CAD 備註預設：已偵測 {default_note_count} 筆｜未標註管徑 {float(default_diameter):g} mm"
            if default_note_count and default_diameter is not None
            else "CAD 備註預設：未偵測到"
        )
        lines.extend(
            [
                "DWG 單位：" + str(diameter_analysis.get("source_unit") or "未指定"),
                f"管徑標註：{int(diameter_analysis.get('label_count') or 0)} 個",
                default_note_summary,
                "文字直接配對："
                + str(int(diameter_analysis.get("matched_label_count") or 0))
                + "/"
                + str(int(diameter_analysis.get("label_count") or 0)),
                "其中主管標註："
                + str(int(diameter_analysis.get("main_matched_label_count") or 0))
                + " 個（不參與支管管徑判定）",
                "座標錨點："
                + str(int(diameter_analysis.get("anchor_group_count") or 0))
                + " 組｜最大殘差 "
                + (
                    f"{float(diameter_analysis.get('anchor_max_residual_mm')):.3f} mm"
                    if diameter_analysis.get("anchor_max_residual_mm") is not None
                    else "未通過"
                ),
                f"已判斷管段：{int(diameter_analysis.get('resolved_segment_count') or 0)} 段",
                f"待確認管段：{int(diameter_analysis.get('unresolved_segment_count') or 0)} 段",
                "線段顏色："
                + str(
                    int(
                        (diameter_analysis.get("evidence_counts") or {}).get(
                            "line_color_reference"
                        )
                        or 0
                    )
                )
                + " 段",
                "圖層備援："
                + str(
                    int(
                        (diameter_analysis.get("evidence_counts") or {}).get(
                            "layer_reference"
                        )
                        or 0
                    )
                )
                + " 段",
                "CAD 整段精確吻合："
                + str(int(diameter_analysis.get("cad_geometry_exact_count") or 0))
                + "/"
                + str(int(diameter_analysis.get("resolved_segment_count") or 0)),
                "CAD 幾何待核對："
                + str(int(diameter_analysis.get("cad_geometry_review_count") or 0))
                + " 段",
                f"異徑三通候選：{sum(item.get('kind') == 'reducing_tee' for item in (diameter_analysis.get('junctions') or []))} 處",
                f"支管途中變徑候選：{len(diameter_analysis.get('reducers') or [])} 處",
                "落水管規則："
                + str(int(preview_payload.get("sprinkler_count") or 0))
                + " 顆灑水頭均固定以 DN25 接管",
                "落水拆段建模：尚未啟用",
                "目前階段：水平管徑只供分析與預覽，待沙盒驗證落水拆段後才開放正式建立",
            ]
        )

    rule_version, rule_hash = _rule_identity()
    return {
        "status": status,
        "summary_lines": lines,
        "rule_version": rule_version,
        "rule_hash": rule_hash,
        "diameter_analysis": diameter_analysis,
        "diameter_mode": "analysis_only" if diameter_analysis else "unavailable",
        "message": (
            "路徑分析完成，可以進行測試建立。"
            if status == "ready"
            else "部分內容仍需確認，請先查看預覽與說明。"
        ),
    }


def _cad_path_verified(cad_check: dict[str, Any] | None) -> bool:
    """Return whether CAD geometry is safe to use as route evidence.

    Coordinate anchors alone only prove that the two files share a coordinate
    system.  They do not prove that the selected Revit route was matched to
    the CAD route.  The explicit verifier status is therefore required before
    CAD geometry, colour, length, or intersections can influence the plan.
    """

    check = cad_check if isinstance(cad_check, dict) else {}
    return (
        str(check.get("status") or "").strip().casefold() == "matched"
        and bool(check.get("coordinate_verified"))
    )


def _build_diameter_analysis(
    cad_check: dict[str, Any],
    revit_anchors: list[dict[str, Any]],
    anchor_error: str = "",
    view_orientation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_path = str(cad_check.get("selected_source_path") or "").strip()
    probe_segments = list(cad_check.get("diameter_probe_segments") or [])
    cad_route_geometry_segments = list(
        cad_check.get("cad_route_geometry_segments") or []
    )
    main_context_segments = list(cad_check.get("main_context_segments") or [])
    cad_status = str(cad_check.get("status") or "")
    cad_verified = _cad_path_verified(cad_check)
    # A non-matched CAD result is a review state, not an instruction to erase
    # the analysis.  Keep the planned segments visible so the user can see why
    # the route needs correction.  Hard-unavailable/invalid coordinate states
    # still return no diameter plan because pairing would be unsafe.
    if cad_status in {"cad_unavailable", "invalid_transform"} or not source_path or not probe_segments:
        return {}
    if not cad_check.get("coordinate_verified"):
        return {
            "status": "needs_attention",
            "cad_path_verified": False,
            "message": "CAD 對位尚未驗證，暫不判定管徑；請先確認 CAD 路徑來源。",
            "label_count": 0,
            "resolved_segment_count": 0,
            "unresolved_segment_count": len(probe_segments),
            "segments": [],
            "reducers": [],
            "warning_codes": ["cad_coordinate_unverified"],
        }

    from .diameter_analysis import (
        _is_default_note,
        analyze_diameter_evidence,
        split_routes_by_cad_geometry,
    )
    from .dwg_diameter_reader import read_dwg_diameter_texts

    try:
        drawing = read_dwg_diameter_texts(source_path)
        unit_to_feet = float(drawing.get("unit_to_feet") or 1.0)
        segments = []
        for raw in probe_segments:
            item = dict(raw)
            # A colour from a CAD probe is evidence only after the route itself
            # has matched.  Keep the raw key for audit, but do not let it drive
            # diameter resolution while the path is still a mismatch.
            item["color"] = item.get("color_key") if cad_verified else None
            if not cad_verified:
                for key in (
                    "cad_geometry_start",
                    "cad_geometry_end",
                    "cad_geometry_exact",
                    "cad_geometry_exact_length_mm",
                    "cad_geometry_source_count",
                    "cad_geometry_split",
                    "planned_length_mm",
                ):
                    item.pop(key, None)
            segments.append(item)
        if cad_verified and cad_route_geometry_segments:
            segments = split_routes_by_cad_geometry(
                segments,
                cad_route_geometry_segments,
                maximum_offset=150.0 / 304.8,
                maximum_angle_degrees=15.0,
            )
        raw_texts = list(drawing.get("texts") or [])
        try:
            calibration = _calibrate_dwg_to_revit(
                list(drawing.get("block_points") or []),
                revit_anchors,
                unit_to_feet,
            )
            texts = [
                _transform_dwg_text(item, calibration, unit_to_feet)
                for item in raw_texts
            ]
        except ValueError as exc:
            default_note_texts = [
                item
                for item in raw_texts
                if _is_default_note(str(item.get("text") or ""))
            ]
            result = analyze_diameter_evidence(
                texts=default_note_texts,
                segments=segments,
                main_context_segments=main_context_segments,
                maximum_label_distance=500.0 / 304.8,
            )
            result.update(
                {
                    "status": "needs_attention",
                    "cad_path_verified": False,
                    "matched_label_count": 0,
                    "coordinate_verified": False,
                    "coordinate_source": "revit_linked_geometry_anchors",
                    "anchor_group_count": 0,
                    "anchor_max_residual_mm": None,
                    "warning_codes": ["cad_text_anchor_calibration_failed"],
                    "message": anchor_error or str(exc),
                }
            )
            _attach_drawing_metadata(result, drawing, source_path, unit_to_feet)
            _attach_view_orientation(result, view_orientation)
            return result
        result = analyze_diameter_evidence(
            texts=texts,
            segments=segments,
            main_context_segments=main_context_segments,
            maximum_label_distance=500.0 / 304.8,
        )
        if not main_context_segments:
            result["status"] = "needs_attention"
            result["warning_codes"] = list(
                dict.fromkeys(
                    list(result.get("warning_codes") or [])
                    + ["main_context_unavailable"]
                )
            )
        if cad_status != "matched":
            result["status"] = "needs_attention"
            result["warning_codes"] = list(
                dict.fromkeys(
                    list(result.get("warning_codes") or [])
                    + ["cad_route_not_matched"]
                )
            )
            result["message"] = (
                "CAD 路徑尚未吻合；目前保留 Revit 路徑與文字配對結果供核對，"
                "不會把這份結果視為可直接建模計畫。"
            )
        result["cad_path_verified"] = cad_verified
        if not cad_verified:
            result["cad_geometry_audit_available"] = False
            result["cad_geometry_exact_count"] = 0
            result["cad_geometry_review_count"] = len(result.get("segments") or [])
            result["warning_codes"] = list(
                dict.fromkeys(
                    list(result.get("warning_codes") or [])
                    + ["cad_path_unverified"]
                )
            )
            for item in result.get("segments") or []:
                item["cad_geometry_verified"] = False
                item["evidence"] = "unresolved"
        _attach_drawing_metadata(result, drawing, source_path, unit_to_feet)
        result["coordinate_verified"] = True
        result["coordinate_source"] = "revit_linked_geometry_anchors"
        result["anchor_group_count"] = calibration["anchor_group_count"]
        result["anchor_max_residual_mm"] = calibration["max_residual_mm"]
        result["anchor_average_residual_mm"] = calibration["average_residual_mm"]
        _attach_view_orientation(result, view_orientation)
        return result
    except Exception as exc:
        result = {
            "status": "needs_attention",
            "cad_path_verified": False,
            "label_count": 0,
            "resolved_segment_count": 0,
            "unresolved_segment_count": len(probe_segments),
            "reducers": [],
            "warning_codes": ["diameter_source_unavailable"],
            "message": str(exc),
        }
        _attach_view_orientation(result, view_orientation)
        return result


def _attach_view_orientation(
    result: dict[str, Any],
    view_orientation: dict[str, Any] | None,
) -> None:
    if view_orientation:
        result["view_orientation"] = dict(view_orientation)


def _transform_dwg_text(
    item: dict[str, Any],
    transform: dict[str, float],
    unit_to_feet: float = 1.0,
) -> dict[str, Any]:
    source_x = float(item.get("x") or 0) * unit_to_feet
    source_y = float(item.get("y") or 0) * unit_to_feet
    source_z = float(item.get("z") or 0) * unit_to_feet
    result = dict(item)
    result["source_x"] = source_x
    result["source_y"] = source_y
    result["source_z"] = source_z
    result["x"], result["y"] = _transform_dwg_xy(source_x, source_y, transform)
    result["z"] = float(transform.get("tz") or 0) + float(
        transform.get("scale") or 1
    ) * source_z
    bounds = item.get("bounds") or {}
    required_bounds = ("min_x", "min_y", "max_x", "max_y")
    if all(key in bounds for key in required_bounds):
        corners = [
            _transform_dwg_xy(
                float(x) * unit_to_feet,
                float(y) * unit_to_feet,
                transform,
            )
            for x, y in (
                (bounds["min_x"], bounds["min_y"]),
                (bounds["min_x"], bounds["max_y"]),
                (bounds["max_x"], bounds["min_y"]),
                (bounds["max_x"], bounds["max_y"]),
            )
        ]
        result["bounds"] = {
            "min_x": min(point[0] for point in corners),
            "min_y": min(point[1] for point in corners),
            "max_x": max(point[0] for point in corners),
            "max_y": max(point[1] for point in corners),
        }
    direction = item.get("direction") or {}
    if "x" in direction and "y" in direction:
        direction_x = float(direction["x"])
        direction_y = float(direction["y"])
        a = float(transform.get("a") or 0)
        b = float(transform.get("b") or 0)
        length = math.hypot(a * direction_x - b * direction_y, b * direction_x + a * direction_y)
        result["direction"] = {
            "x": (a * direction_x - b * direction_y) / (length or 1),
            "y": (b * direction_x + a * direction_y) / (length or 1),
        }
    return result


def _transform_dwg_xy(
    source_x: float,
    source_y: float,
    transform: dict[str, float],
) -> tuple[float, float]:
    a = float(transform.get("a") or 0)
    b = float(transform.get("b") or 0)
    return (
        float(transform.get("tx") or 0) + a * source_x - b * source_y,
        float(transform.get("ty") or 0) + b * source_x + a * source_y,
    )


def _attach_drawing_metadata(
    result: dict[str, Any],
    drawing: dict[str, Any],
    source_path: str,
    unit_to_feet: float,
) -> None:
    result["source_path"] = source_path
    result["source_unit_code"] = int(drawing.get("unit_code") or 0)
    result["source_unit"] = str(drawing.get("unit_name") or "未指定")
    result["source_unit_to_feet"] = unit_to_feet
    result["extracted_text_count"] = len(drawing.get("texts") or [])


def _calibrate_dwg_to_revit(
    source_points: list[dict[str, Any]],
    model_points: list[dict[str, Any]],
    unit_to_feet: float,
) -> dict[str, float | int]:
    source_groups = _group_anchor_points(source_points, unit_to_feet)
    model_groups = _group_anchor_points(model_points, 1.0)
    pairs = []
    for name in sorted(set(source_groups) & set(model_groups)):
        source_group = source_groups[name]
        model_group = model_groups[name]
        if len(source_group) != len(model_group):
            continue
        pairs.append((_centroid(source_group), _centroid(model_group), name))
    if len(pairs) < 3 or not _has_non_collinear_points([item[0] for item in pairs]):
        raise ValueError("找不到至少三組非共線的同名 CAD 錨點。")

    active = list(pairs)
    while len(active) >= 3:
        transform = _fit_similarity(active)
        centroid_residuals = [
            math.dist(_transform_dwg_xy(source[0], source[1], transform), target[:2])
            * 304.8
            for source, target, _name in active
        ]
        point_residuals = _anchor_point_residuals(
            active,
            source_groups,
            model_groups,
            transform,
        )
        residuals = centroid_residuals + [
            residual
            for group_residuals in point_residuals.values()
            for residual in group_residuals
        ]
        if residuals and max(residuals) <= 1.0:
            transform.update(
                {
                    "anchor_group_count": len(active),
                    "max_residual_mm": max(residuals),
                    "average_residual_mm": sum(residuals) / len(residuals),
                }
            )
            return transform
        worst_name = max(
            active,
            key=lambda item: max(point_residuals.get(item[2]) or [float("inf")]),
        )[2]
        active = [item for item in active if item[2] != worst_name]
        if not _has_non_collinear_points([item[0] for item in active]):
            break
    raise ValueError("DWG 與 Revit 錨點殘差超過 1 mm，已停止文字座標配對。")


def _anchor_point_residuals(
    pairs: list[
        tuple[tuple[float, float, float], tuple[float, float, float], str]
    ],
    source_groups: dict[str, list[tuple[float, float, float]]],
    model_groups: dict[str, list[tuple[float, float, float]]],
    transform: dict[str, float],
) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for _source, _target, name in pairs:
        available = list(model_groups[name])
        residuals = []
        for source_point in source_groups[name]:
            transformed = _transform_dwg_xy(source_point[0], source_point[1], transform)
            nearest_index = min(
                range(len(available)),
                key=lambda index: math.dist(transformed, available[index][:2]),
            )
            residuals.append(
                math.dist(transformed, available[nearest_index][:2]) * 304.8
            )
            available.pop(nearest_index)
        result[name] = residuals
    return result


def _group_anchor_points(
    points: list[dict[str, Any]], unit_scale: float
) -> dict[str, list[tuple[float, float, float]]]:
    groups: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    for point in points:
        name = _normalize_block_name(
            str(point.get("block_name") or point.get("revit_geometry_name") or "")
        )
        if not name:
            continue
        try:
            groups[name].append(
                (
                    float(point.get("x") or 0) * unit_scale,
                    float(point.get("y") or 0) * unit_scale,
                    float(point.get("z") or 0) * unit_scale,
                )
            )
        except (TypeError, ValueError):
            continue
    return groups


def _normalize_block_name(name: str) -> str:
    return name.strip().rsplit(".", 1)[-1].casefold()


def _centroid(points: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    count = len(points)
    return tuple(sum(point[index] for point in points) / count for index in range(3))


def _has_non_collinear_points(points: list[tuple[float, float, float]]) -> bool:
    if len(points) < 3:
        return False
    first = points[0]
    for index in range(1, len(points) - 1):
        second = points[index]
        for third in points[index + 1 :]:
            area = abs(
                (second[0] - first[0]) * (third[1] - first[1])
                - (second[1] - first[1]) * (third[0] - first[0])
            )
            if area > 1e-9:
                return True
    return False


def _fit_similarity(
    pairs: list[
        tuple[tuple[float, float, float], tuple[float, float, float], str]
    ],
) -> dict[str, float]:
    source_x = sum(item[0][0] for item in pairs) / len(pairs)
    source_y = sum(item[0][1] for item in pairs) / len(pairs)
    target_x = sum(item[1][0] for item in pairs) / len(pairs)
    target_y = sum(item[1][1] for item in pairs) / len(pairs)
    denominator = 0.0
    numerator_a = 0.0
    numerator_b = 0.0
    for source, target, _name in pairs:
        dx = source[0] - source_x
        dy = source[1] - source_y
        du = target[0] - target_x
        dv = target[1] - target_y
        denominator += dx * dx + dy * dy
        numerator_a += dx * du + dy * dv
        numerator_b += dx * dv - dy * du
    if denominator <= 1e-12:
        raise ValueError("CAD 錨點分布不足，無法建立座標校正。")
    a = numerator_a / denominator
    b = numerator_b / denominator
    scale = math.hypot(a, b)
    if not all(math.isfinite(value) for value in (a, b, scale)) or scale <= 0:
        raise ValueError("CAD 錨點產生無效的座標比例。")
    source_z = sum(item[0][2] for item in pairs) / len(pairs)
    target_z = sum(item[1][2] for item in pairs) / len(pairs)
    return {
        "a": a,
        "b": b,
        "tx": target_x - a * source_x + b * source_y,
        "ty": target_y - b * source_x - a * source_y,
        "tz": target_z - scale * source_z,
        "scale": scale,
    }
