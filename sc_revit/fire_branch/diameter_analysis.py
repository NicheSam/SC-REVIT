from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any


_INCH_TO_NOMINAL_MM = {
    0.75: 20.0,
    1.0: 25.0,
    1.25: 32.0,
    1.5: 40.0,
    2.0: 50.0,
    2.5: 65.0,
    3.0: 80.0,
    4.0: 100.0,
    5.0: 125.0,
    6.0: 150.0,
    8.0: 200.0,
    10.0: 250.0,
}

_UNICODE_FRACTIONS = {
    "¼": 0.25,
    "½": 0.5,
    "¾": 0.75,
}

_NON_ROUTE_GEOMETRY_KINDS = {
    "arc",
    "circle",
    "ellipse",
    "hermite_spline",
    "hermitespline",
    "nurb_spline",
    "nurbspline",
    "spline",
}


def _interval_union_length(intervals: list[tuple[float, float]]) -> float:
    total = 0.0
    current_start: float | None = None
    current_end: float | None = None
    for start, end in sorted(intervals):
        if current_start is None:
            current_start = start
            current_end = end
            continue
        if start <= float(current_end) + 1e-9:
            current_end = max(float(current_end), end)
            continue
        total += float(current_end) - current_start
        current_start = start
        current_end = end
    if current_start is not None:
        total += float(current_end) - current_start
    return total


def _select_supported_route_tracks(
    candidates: list[dict[str, Any]],
    *,
    maximum_offset: float,
) -> list[dict[str, Any]]:
    """Select one continuous CAD lane and suppress local symbol fragments."""

    usable = [
        item
        for item in candidates
        if not bool((item.get("source") or {}).get("closed_geometry"))
        and str((item.get("source") or {}).get("geometry_kind") or "").casefold()
        not in _NON_ROUTE_GEOMETRY_KINDS
    ]
    if not usable:
        return []

    lane_tolerance = max(maximum_offset * 0.20, 1e-6)
    gap_tolerance = max(maximum_offset * 0.05, 1e-6)
    tracks: list[dict[str, Any]] = []
    for candidate in sorted(
        usable,
        key=lambda item: (
            item["layer"],
            str(item["color"] or ""),
            float(item["signed_offset"]),
            float(item["start_parameter"]),
        ),
    ):
        signature = (candidate["layer"], str(candidate["color"] or ""))
        matching = [
            track
            for track in tracks
            if track["signature"] == signature
            and abs(float(track["signed_offset"]) - float(candidate["signed_offset"]))
            <= lane_tolerance
            and float(candidate["start_parameter"])
            <= float(track["end_parameter"]) + gap_tolerance
        ]
        if not matching:
            tracks.append(
                {
                    **dict(candidate),
                    "signature": signature,
                    "source_count": 1,
                }
            )
            continue
        track = max(matching, key=lambda item: float(item["end_parameter"]))
        candidate_length = float(candidate["end_parameter"]) - float(
            candidate["start_parameter"]
        )
        source_length = float(track["end_parameter"]) - float(
            track["start_parameter"]
        )
        track["start_parameter"] = min(
            float(track["start_parameter"]),
            float(candidate["start_parameter"]),
        )
        track["end_parameter"] = max(
            float(track["end_parameter"]),
            float(candidate["end_parameter"]),
        )
        if candidate_length > source_length:
            track["source"] = candidate.get("source") or {}
        track["source_count"] = int(track["source_count"]) + 1
        track["signed_offset"] = (
            float(track["signed_offset"]) + float(candidate["signed_offset"])
        ) * 0.5
        track["offset"] = abs(float(track["signed_offset"]))

    lanes: list[dict[str, Any]] = []
    for track in sorted(tracks, key=lambda item: abs(float(item["signed_offset"]))):
        lane = next(
            (
                item
                for item in lanes
                if abs(float(item["signed_offset"]) - float(track["signed_offset"]))
                <= lane_tolerance
            ),
            None,
        )
        if lane is None:
            lanes.append(
                {
                    "signed_offset": float(track["signed_offset"]),
                    "tracks": [track],
                }
            )
        else:
            lane["tracks"].append(track)
            lane["signed_offset"] = sum(
                float(item["signed_offset"]) for item in lane["tracks"]
            ) / len(lane["tracks"])

    for lane in lanes:
        lane["coverage"] = _interval_union_length(
            [
                (float(item["start_parameter"]), float(item["end_parameter"]))
                for item in lane["tracks"]
            ]
        )
    dominant_lane = max(
        lanes,
        key=lambda item: (
            float(item["coverage"]),
            -abs(float(item["signed_offset"])),
        ),
    )
    lane_tracks = list(dominant_lane["tracks"])
    boundaries = sorted(
        {
            value
            for item in lane_tracks
            for value in (
                float(item["start_parameter"]),
                float(item["end_parameter"]),
            )
        }
    )
    selected: list[dict[str, Any]] = []
    for start, end in zip(boundaries, boundaries[1:]):
        if end - start <= 1e-9:
            continue
        midpoint = (start + end) * 0.5
        active = [
            item
            for item in lane_tracks
            if float(item["start_parameter"]) <= midpoint + 1e-9
            and float(item["end_parameter"]) >= midpoint - 1e-9
        ]
        if not active:
            continue
        winner = max(
            active,
            key=lambda item: (
                float(item["end_parameter"]) - float(item["start_parameter"]),
                -abs(float(item["signed_offset"])),
            ),
        )
        if selected and selected[-1]["signature"] == winner["signature"]:
            selected[-1]["end_parameter"] = end
            selected[-1]["source_count"] = max(
                int(selected[-1].get("source_count") or 1),
                int(winner.get("source_count") or 1),
            )
            continue
        selected.append({**dict(winner), "start_parameter": start, "end_parameter": end})
    return selected


def split_routes_by_cad_geometry(
    planned_segments: list[dict[str, Any]],
    cad_segments: list[dict[str, Any]],
    *,
    maximum_offset: float,
    maximum_angle_degrees: float,
) -> list[dict[str, Any]]:
    """Split selected routes at actual CAD geometry/property boundaries."""

    result: list[dict[str, Any]] = []
    next_sequence_by_row: dict[int, int] = defaultdict(int)
    minimum_alignment = math.cos(math.radians(maximum_angle_degrees))
    ordered_planned_segments = sorted(
        planned_segments,
        key=lambda item: (
            int(item.get("row_index") or 0),
            int(item.get("sequence") or 0),
        ),
    )
    for planned in ordered_planned_segments:
        row_index = int(planned.get("row_index") or 0)
        start = planned.get("start") or {}
        end = planned.get("end") or {}
        x1 = float(start.get("x") or 0)
        y1 = float(start.get("y") or 0)
        x2 = float(end.get("x") or 0)
        y2 = float(end.get("y") or 0)
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            continue
        ux = dx / length
        uy = dy / length
        candidates: list[dict[str, Any]] = []
        for raw in cad_segments:
            cad_start = raw.get("start") or {}
            cad_end = raw.get("end") or {}
            ax = float(cad_start.get("x") or 0)
            ay = float(cad_start.get("y") or 0)
            bx = float(cad_end.get("x") or 0)
            by = float(cad_end.get("y") or 0)
            cdx = bx - ax
            cdy = by - ay
            cad_length = math.hypot(cdx, cdy)
            if cad_length <= 1e-9:
                continue
            alignment = abs((cdx / cad_length) * ux + (cdy / cad_length) * uy)
            if alignment < minimum_alignment:
                continue
            midpoint_x = (ax + bx) * 0.5
            midpoint_y = (ay + by) * 0.5
            signed_offset = (midpoint_x - x1) * uy - (midpoint_y - y1) * ux
            offset = abs(signed_offset)
            if offset > maximum_offset:
                continue
            first_parameter = (ax - x1) * ux + (ay - y1) * uy
            second_parameter = (bx - x1) * ux + (by - y1) * uy
            interval_start = max(0.0, min(first_parameter, second_parameter))
            interval_end = min(length, max(first_parameter, second_parameter))
            if interval_end - interval_start <= 1e-9:
                continue
            candidates.append(
                {
                    "start_parameter": interval_start,
                    "end_parameter": interval_end,
                    "offset": offset,
                    "signed_offset": signed_offset,
                    "layer": str(raw.get("layer") or ""),
                    "color": raw.get("color", raw.get("color_key")),
                    "source": raw,
                }
            )
        if not candidates:
            sequence = next_sequence_by_row[row_index]
            item = dict(planned)
            item["segment_id"] = f"row-{row_index}-{sequence}"
            item["sequence"] = sequence
            result.append(item)
            next_sequence_by_row[row_index] = sequence + 1
            continue

        ordered = _select_supported_route_tracks(
            candidates,
            maximum_offset=maximum_offset,
        )
        if not ordered:
            sequence = next_sequence_by_row[row_index]
            item = dict(planned)
            item["segment_id"] = f"row-{row_index}-{sequence}"
            item["sequence"] = sequence
            result.append(item)
            next_sequence_by_row[row_index] = sequence + 1
            continue

        boundaries = [0.0]
        for previous, current in zip(ordered, ordered[1:]):
            boundary = (
                float(previous["end_parameter"])
                + float(current["start_parameter"])
            ) * 0.5
            boundaries.append(max(boundaries[-1], min(length, boundary)))
        boundaries.append(length)
        for local_sequence, candidate in enumerate(ordered):
            segment_start = boundaries[local_sequence]
            segment_end = boundaries[local_sequence + 1]
            if segment_end - segment_start <= 1e-9:
                continue
            sequence = next_sequence_by_row[row_index]
            item = dict(planned)
            is_terminal_piece = bool(planned.get("is_sprinkler_terminal")) and (
                local_sequence == len(ordered) - 1
            )
            if not is_terminal_piece:
                item.pop("sprinkler_id", None)
            planned_start_point = {
                "x": x1 + ux * segment_start,
                "y": y1 + uy * segment_start,
                "z": float(start.get("z") or 0),
            }
            planned_end_point = {
                "x": x1 + ux * segment_end,
                "y": y1 + uy * segment_end,
                "z": float(end.get("z") or start.get("z") or 0),
            }
            source = candidate.get("source") or {}
            cad_geometry_start = _project_point_to_cad_segment(
                planned_start_point,
                source,
            )
            cad_geometry_end = _project_point_to_cad_segment(
                planned_end_point,
                source,
            )
            for stale_key in (
                "cad_geometry_exact",
                "cad_start_offset_mm",
                "cad_end_offset_mm",
                "cad_length_mm",
                "length_delta_mm",
                "cad_angle_delta_degrees",
            ):
                item.pop(stale_key, None)
            item.update(
                {
                    "segment_id": f"row-{row_index}-{sequence}",
                    "sequence": sequence,
                    "start": planned_start_point,
                    "end": planned_end_point,
                    "cad_geometry_start": cad_geometry_start,
                    "cad_geometry_end": cad_geometry_end,
                    "layer": candidate["layer"],
                    "color": candidate["color"],
                    "planned_length_mm": (segment_end - segment_start) * 304.8,
                    "cad_geometry_split": True,
                    "cad_geometry_source_count": int(candidate.get("source_count") or 1),
                    "is_sprinkler_terminal": is_terminal_piece,
                }
            )
            result.append(item)
            next_sequence_by_row[row_index] = sequence + 1
    return result


def _project_point_to_cad_segment(
    point: dict[str, Any],
    cad_segment: dict[str, Any],
) -> dict[str, float]:
    start = cad_segment.get("start") or {}
    end = cad_segment.get("end") or {}
    x1 = float(start.get("x") or 0)
    y1 = float(start.get("y") or 0)
    x2 = float(end.get("x") or 0)
    y2 = float(end.get("y") or 0)
    dx = x2 - x1
    dy = y2 - y1
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        return {"x": x1, "y": y1, "z": float(start.get("z") or 0)}
    px = float(point.get("x") or 0)
    py = float(point.get("y") or 0)
    ratio = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_squared))
    return {
        "x": x1 + ratio * dx,
        "y": y1 + ratio * dy,
        "z": float(start.get("z") or point.get("z") or 0),
    }


def parse_diameter_text(value: str) -> float | None:
    """Return the Revit nominal millimetre size represented by an inch label."""

    text = str(value or "").strip()
    if not text:
        return None

    normalized = text.replace("英寸", "吋")
    for quote in ("＂", "″", "“", "”", "„", "‟", "〃", "〞"):
        normalized = normalized.replace(quote, '"')
    marker = None
    marker_pattern = (
        r"(?<![\d.])(?P<whole>\d{1,2})"
        r"(?:\s*(?:-|\s)\s*(?P<num>[123])\s*/\s*(?P<den>[248])|\s*(?P<unicode>[¼½¾]))?"
        r"\s*(?:\"|吋)"
    )
    for candidate in re.finditer(marker_pattern, normalized):
        if re.search(r"/\s*$", normalized[: candidate.start()]):
            continue
        marker = candidate
        break
    if marker is None:
        return None

    inches = float(marker.group("whole"))
    if marker.group("unicode"):
        inches += _UNICODE_FRACTIONS[marker.group("unicode")]
    elif marker.group("num") and marker.group("den"):
        inches += float(marker.group("num")) / float(marker.group("den"))

    rounded = round(inches, 4)
    return _INCH_TO_NOMINAL_MM.get(rounded)


def analyze_diameter_evidence(
    *,
    texts: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    maximum_label_distance: float,
    main_context_segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assign drawing diameter evidence to ordered branch segments.

    Evidence precedence is direct text, line colour, layer name, and finally the
    drawing's unmarked-pipe default note.
    """

    parsed_texts: list[dict[str, Any]] = []
    default_values: list[float] = []
    default_notes: list[dict[str, Any]] = []
    for raw in texts:
        diameter = parse_diameter_text(str(raw.get("text") or ""))
        if diameter is None:
            continue
        item = dict(raw)
        item["diameter_mm"] = diameter
        if _is_default_note(str(raw.get("text") or "")):
            default_values.append(diameter)
            default_notes.append(
                {
                    "text": str(raw.get("text") or ""),
                    "diameter_mm": diameter,
                }
            )
        else:
            parsed_texts.append(item)

    warnings: list[str] = []
    unique_defaults = sorted(set(default_values))
    default_diameter = unique_defaults[0] if len(unique_defaults) == 1 else None
    if len(unique_defaults) > 1:
        warnings.append("conflicting_drawing_defaults")

    branch_candidates = [dict(item, topology_role="branch") for item in segments]
    main_candidates = [
        dict(item, topology_role="main") for item in (main_context_segments or [])
    ]
    match_candidates = branch_candidates + main_candidates
    label_matches: list[dict[str, Any]] = []
    main_label_matches: list[dict[str, Any]] = []
    labels_by_segment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in parsed_texts:
        match = _best_segment_match(item, match_candidates, maximum_label_distance)
        if match is None:
            continue
        target = match["segment"]
        segment_id = str(target.get("segment_id") or "")
        topology_role = str(target.get("topology_role") or "branch")
        item["target_segment_id"] = segment_id
        item["target_topology_role"] = topology_role
        item["target_color"] = target.get("color")
        item["target_layer"] = target.get("layer")
        item["match_distance"] = match["distance"]
        item["match_score"] = match["score"]
        item["orientation_alignment"] = match["orientation_alignment"]
        match_record = {
            "text": item.get("text"),
            "diameter_mm": item["diameter_mm"],
            "segment_id": segment_id,
            "topology_role": topology_role,
            "source_element_id": target.get("source_element_id"),
            "distance": match["distance"],
            "score": match["score"],
            "orientation_alignment": match["orientation_alignment"],
        }
        if topology_role == "main":
            main_label_matches.append(match_record)
        else:
            labels_by_segment[segment_id].append(item)
            label_matches.append(match_record)

    colors: dict[str, set[float]] = defaultdict(set)
    layers: dict[str, set[float]] = defaultdict(set)
    for item in parsed_texts:
        if item.get("target_topology_role") != "branch":
            continue
        target_layer_diameter = _parse_layer_diameter_hint(
            str(item.get("target_layer") or "")
        )
        if (
            float(item.get("orientation_alignment") or 0) < 0.8
            and target_layer_diameter is not None
            and not math.isclose(float(item["diameter_mm"]), target_layer_diameter)
        ):
            continue
        color = _key(item.get("target_color"))
        layer = _key(item.get("layer"))
        if color:
            colors[color].add(float(item["diameter_mm"]))
        if layer:
            layers[layer].add(float(item["diameter_mm"]))

    conflicting_colors = {key for key, values in colors.items() if len(values) > 1}
    if conflicting_colors:
        warnings.append("conflicting_color_labels")

    line_color_hints: dict[str, set[float]] = defaultdict(set)
    for segment in segments:
        color = _key(segment.get("color"))
        layer_diameter = _parse_layer_diameter_hint(str(segment.get("layer") or ""))
        if color and layer_diameter is not None:
            line_color_hints[color].add(layer_diameter)
    conflicting_line_colors = {
        key for key, values in line_color_hints.items() if len(values) > 1
    }
    if conflicting_line_colors:
        warnings.append("conflicting_line_color_references")
    line_color_references = {
        key: next(iter(values))
        for key, values in line_color_hints.items()
        if len(values) == 1
    }

    results: list[dict[str, Any]] = []
    for raw_segment in segments:
        item = dict(raw_segment)
        color = _key(item.get("color"))
        layer = _key(item.get("layer"))
        diameter: float | None = None
        evidence = "unresolved"
        confidence = "review"
        direct_labels = labels_by_segment.get(str(item.get("segment_id") or ""), [])
        aligned_direct_labels = [
            label
            for label in direct_labels
            if float(label.get("orientation_alignment") or 0) >= 0.8
        ]
        if aligned_direct_labels:
            direct_labels = aligned_direct_labels
        elif _parse_layer_diameter_hint(str(item.get("layer") or "")) is not None:
            direct_labels = []
        direct_diameters = {float(label["diameter_mm"]) for label in direct_labels}

        if len(direct_diameters) > 1:
            evidence = "conflicting_label"
        elif len(direct_diameters) == 1:
            diameter = next(iter(direct_diameters))
            raw_colors = {_key(label.get("color")) for label in direct_labels}
            evidence = (
                "explicit_color"
                if not raw_colors - {"", color}
                else "explicit_nearby"
            )
            confidence = "high"
            best_label = min(direct_labels, key=lambda label: float(label["match_score"]))
            item["label_distance"] = float(best_label["match_distance"])
            item["label_score"] = float(best_label["match_score"])
            item["label_orientation_alignment"] = float(
                best_label["orientation_alignment"]
            )
        elif color and color in conflicting_colors:
            if layer and len(layers.get(layer, set())) == 1:
                diameter = next(iter(layers[layer]))
                evidence = "layer_reference"
                confidence = "medium"
            elif _parse_layer_diameter_hint(str(item.get("layer") or "")) is not None:
                diameter = _parse_layer_diameter_hint(str(item.get("layer") or ""))
                evidence = "layer_reference"
                confidence = "medium"
            else:
                evidence = "conflicting_color"
        elif color and len(colors.get(color, set())) == 1:
            diameter = next(iter(colors[color]))
            evidence = "explicit_color"
            confidence = "high"
        elif color and color in line_color_references:
            diameter = line_color_references[color]
            evidence = "line_color_reference"
            confidence = "medium"
        else:
            if layer and len(layers.get(layer, set())) == 1:
                diameter = next(iter(layers[layer]))
                evidence = "layer_reference"
                confidence = "medium"
            elif _parse_layer_diameter_hint(str(item.get("layer") or "")) is not None:
                diameter = _parse_layer_diameter_hint(str(item.get("layer") or ""))
                evidence = "layer_reference"
                confidence = "medium"
            elif default_diameter is not None:
                diameter = default_diameter
                evidence = "drawing_default"
                confidence = "medium"

        item["diameter_mm"] = diameter
        item["evidence"] = evidence
        item["confidence"] = confidence
        results.append(item)

    reducers: list[dict[str, Any]] = []
    ordered_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for segment in results:
        ordered_rows[int(segment.get("row_index") or 0)].append(segment)
    diameter_increase_found = False
    for row_index, row_segments in ordered_rows.items():
        row_segments.sort(key=lambda item: int(item.get("sequence") or 0))
        for previous, current in zip(row_segments, row_segments[1:]):
            before = previous.get("diameter_mm")
            after = current.get("diameter_mm")
            if before is None or after is None or math.isclose(float(before), float(after)):
                continue
            if float(after) > float(before):
                current["evidence"] = "diameter_increase_conflict"
                current["confidence"] = "low"
                diameter_increase_found = True
                continue
            reducers.append(
                {
                    "row_index": row_index,
                    "after_segment_id": previous.get("segment_id"),
                    "before_segment_id": current.get("segment_id"),
                    "point": previous.get("end"),
                    "from_diameter_mm": float(before),
                    "to_diameter_mm": float(after),
                }
            )

    main_diameters_by_segment: dict[str, set[float]] = defaultdict(set)
    main_matches_by_segment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for match in main_label_matches:
        main_matches_by_segment[str(match.get("segment_id") or "")].append(match)
    for segment_id, matches in main_matches_by_segment.items():
        aligned_matches = [
            match
            for match in matches
            if float(match.get("orientation_alignment") or 0) >= 0.8
        ]
        diameter_matches = aligned_matches or matches
        for match in diameter_matches:
            diameter = match.get("diameter_mm")
            if segment_id and diameter is not None:
                main_diameters_by_segment[segment_id].add(float(diameter))

    junctions: list[dict[str, Any]] = []
    for row_index, row_segments in ordered_rows.items():
        row_segments.sort(key=lambda item: int(item.get("sequence") or 0))
        first = row_segments[0]
        nearest = _nearest_main_connection(first, main_candidates)
        if nearest is None:
            continue
        main_segment, point = nearest
        main_segment_id = str(main_segment.get("segment_id") or "")
        main_diameters = main_diameters_by_segment.get(main_segment_id, set())
        main_diameter = next(iter(main_diameters)) if len(main_diameters) == 1 else None
        branch_diameter = first.get("diameter_mm")
        review_required = main_diameter is None or branch_diameter is None
        if review_required:
            kind = "unresolved_tee"
        elif math.isclose(float(main_diameter), float(branch_diameter)):
            kind = "tee"
        else:
            kind = "reducing_tee"
        junctions.append(
            {
                "row_index": row_index,
                "branch_segment_id": first.get("segment_id"),
                "main_segment_id": main_segment_id,
                "main_source_element_id": main_segment.get("source_element_id"),
                "point": point,
                "kind": kind,
                "main_diameter_mm": main_diameter,
                "branch_diameter_mm": (
                    float(branch_diameter) if branch_diameter is not None else None
                ),
                "review_required": review_required,
                "evidence": "cad_text" if main_diameter is not None else "unresolved",
            }
        )

    unresolved_count = sum(item.get("diameter_mm") is None for item in results)
    if unresolved_count:
        warnings.append("unresolved_segments")
    if diameter_increase_found:
        warnings.append("outward_diameter_increase")
    geometry_audit_available = bool(results) and all(
        "cad_geometry_exact" in item for item in results
    )
    geometry_exact_count = (
        sum(bool(item.get("cad_geometry_exact")) for item in results)
        if geometry_audit_available
        else 0
    )
    geometry_review_count = (
        len(results) - geometry_exact_count if geometry_audit_available else 0
    )
    if geometry_review_count:
        warnings.append("cad_segment_geometry_review_required")
    warning_codes = list(dict.fromkeys(warnings))
    evidence_counts = Counter(str(item.get("evidence") or "unresolved") for item in results)
    return {
        "status": "ready" if not warning_codes else "needs_attention",
        "default_diameter_mm": default_diameter,
        "default_note_count": len(default_notes),
        "default_notes": default_notes,
        "label_count": len(parsed_texts),
        "resolved_segment_count": len(results) - unresolved_count,
        "unresolved_segment_count": unresolved_count,
        "segments": results,
        # Keep the selected main geometry in the analysis result.  The SVG
        # renderer and the Revit execution plan must consume the same main
        # route; dropping this field here silently rebuilt a synthetic
        # straight main in the real GUI even when Revit had returned an L/U
        # or fragmented route.
        "main_context_segments": [dict(item) for item in (main_context_segments or [])],
        "reducers": reducers,
        "junctions": junctions,
        "label_matches": label_matches,
        "main_label_matches": main_label_matches,
        "main_matched_label_count": len(main_label_matches),
        "matched_label_count": len(label_matches) + len(main_label_matches),
        "unmatched_label_count": (
            len(parsed_texts) - len(label_matches) - len(main_label_matches)
        ),
        "evidence_counts": dict(evidence_counts),
        "cad_geometry_audit_available": geometry_audit_available,
        "cad_geometry_exact_count": geometry_exact_count,
        "cad_geometry_review_count": geometry_review_count,
        "cad_max_start_offset_mm": _maximum_value(results, "cad_start_offset_mm"),
        "cad_max_midpoint_offset_mm": _maximum_value(
            results,
            "cad_midpoint_offset_mm",
        ),
        "cad_max_end_offset_mm": _maximum_value(results, "cad_end_offset_mm"),
        "cad_max_angle_delta_degrees": _maximum_value(
            results,
            "cad_angle_delta_degrees",
        ),
        "cad_max_length_delta_mm": _maximum_absolute_value(
            results,
            "length_delta_mm",
        ),
        "warning_codes": warning_codes,
    }


def _nearest_main_connection(
    branch_segment: dict[str, Any],
    main_segments: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, float]] | None:
    if not main_segments:
        return None
    endpoints = [
        branch_segment.get("cad_geometry_start")
        or branch_segment.get("start")
        or {},
        branch_segment.get("cad_geometry_end")
        or branch_segment.get("end")
        or {},
    ]
    candidates: list[tuple[float, str, dict[str, Any], dict[str, float]]] = []
    for main in main_segments:
        start = main.get("start") or {}
        end = main.get("end") or {}
        for endpoint in endpoints:
            px = float(endpoint.get("x") or 0)
            py = float(endpoint.get("y") or 0)
            ax = float(start.get("x") or 0)
            ay = float(start.get("y") or 0)
            bx = float(end.get("x") or 0)
            by = float(end.get("y") or 0)
            distance = _distance_to_segment(
                px,
                py,
                ax,
                ay,
                bx,
                by,
            )
            dx = bx - ax
            dy = by - ay
            length_squared = dx * dx + dy * dy
            parameter = 0.0 if length_squared <= 1e-12 else max(
                0.0,
                min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared),
            )
            candidates.append(
                (
                    distance,
                    str(main.get("segment_id") or ""),
                    main,
                    {"x": ax + dx * parameter, "y": ay + dy * parameter},
                )
            )
    _, _, main, point = min(candidates, key=lambda item: (item[0], item[1]))
    return main, point


def _maximum_value(items: list[dict[str, Any]], key: str) -> float | None:
    values = [float(item[key]) for item in items if item.get(key) is not None]
    return max(values) if values else None


def _maximum_absolute_value(items: list[dict[str, Any]], key: str) -> float | None:
    values = [abs(float(item[key])) for item in items if item.get(key) is not None]
    return max(values) if values else None


def _is_default_note(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or ""))
    return any(
        marker in normalized
        for marker in (
            "未標示",
            "未標註",
            "未註明",
            "無標示",
            "無註明",
            "未标示",
            "未标注",
            "未注明",
            "无标示",
            "无注明",
        )
    )


def _key(value: Any) -> str:
    return str(value).strip().casefold() if value is not None else ""


def _nearest_text(
    segment: dict[str, Any],
    texts: list[dict[str, Any]],
    maximum_distance: float,
) -> dict[str, Any] | None:
    start = segment.get("start") or {}
    end = segment.get("end") or {}
    ax = float(start.get("x") or 0)
    ay = float(start.get("y") or 0)
    bx = float(end.get("x") or 0)
    by = float(end.get("y") or 0)
    best: dict[str, Any] | None = None
    best_distance = float(maximum_distance)
    for item in texts:
        distance = _distance_to_segment(
            float(item.get("x") or 0),
            float(item.get("y") or 0),
            ax,
            ay,
            bx,
            by,
        )
        if distance <= best_distance:
            best = item
            best_distance = distance
    return best


def _nearest_segment(
    text: dict[str, Any],
    segments: list[dict[str, Any]],
    maximum_distance: float,
) -> dict[str, Any] | None:
    px = float(text.get("x") or 0)
    py = float(text.get("y") or 0)
    best: dict[str, Any] | None = None
    best_distance = float(maximum_distance)
    for segment in segments:
        start = segment.get("start") or {}
        end = segment.get("end") or {}
        distance = _distance_to_segment(
            px,
            py,
            float(start.get("x") or 0),
            float(start.get("y") or 0),
            float(end.get("x") or 0),
            float(end.get("y") or 0),
        )
        if distance <= best_distance:
            best = segment
            best_distance = distance
    return best


def _best_segment_match(
    text: dict[str, Any],
    segments: list[dict[str, Any]],
    maximum_distance: float,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for segment in segments:
        distance = _text_distance_to_segment(text, segment)
        if distance > maximum_distance:
            continue
        alignment = _orientation_alignment(text, segment)
        score = distance + (1.0 - alignment) * maximum_distance * 0.5
        candidates.append(
            {
                "segment": segment,
                "distance": distance,
                "score": score,
                "orientation_alignment": alignment,
            }
        )
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            float(item["score"]),
            int(item["segment"].get("row_index") or 0),
            int(item["segment"].get("sequence") or 0),
        )
    )
    best = candidates[0]
    if len(candidates) > 1:
        ambiguity_margin = max(0.05, maximum_distance * 0.1)
        if float(candidates[1]["score"]) - float(best["score"]) <= ambiguity_margin:
            return None
    return best


def _text_distance_to_segment(
    text: dict[str, Any], segment: dict[str, Any]
) -> float:
    start = segment.get("start") or {}
    end = segment.get("end") or {}
    ax = float(start.get("x") or 0)
    ay = float(start.get("y") or 0)
    bx = float(end.get("x") or 0)
    by = float(end.get("y") or 0)
    bounds = text.get("bounds") or {}
    required = ("min_x", "min_y", "max_x", "max_y")
    if not all(key in bounds for key in required):
        return _distance_to_segment(
            float(text.get("x") or 0),
            float(text.get("y") or 0),
            ax,
            ay,
            bx,
            by,
        )

    min_x = float(bounds["min_x"])
    min_y = float(bounds["min_y"])
    max_x = float(bounds["max_x"])
    max_y = float(bounds["max_y"])
    if _segment_intersects_box(ax, ay, bx, by, min_x, min_y, max_x, max_y):
        return 0.0
    distances = [
        _distance_to_segment(x, y, ax, ay, bx, by)
        for x, y in (
            (min_x, min_y),
            (min_x, max_y),
            (max_x, min_y),
            (max_x, max_y),
        )
    ]
    distances.extend(
        [
            _distance_point_to_box(ax, ay, min_x, min_y, max_x, max_y),
            _distance_point_to_box(bx, by, min_x, min_y, max_x, max_y),
        ]
    )
    return min(distances)


def _orientation_alignment(text: dict[str, Any], segment: dict[str, Any]) -> float:
    direction = text.get("direction") or {}
    tx = float(direction.get("x") or 0)
    ty = float(direction.get("y") or 0)
    start = segment.get("start") or {}
    end = segment.get("end") or {}
    sx = float(end.get("x") or 0) - float(start.get("x") or 0)
    sy = float(end.get("y") or 0) - float(start.get("y") or 0)
    text_length = math.hypot(tx, ty)
    segment_length = math.hypot(sx, sy)
    if text_length <= 1e-12 or segment_length <= 1e-12:
        return 0.5
    return abs((tx * sx + ty * sy) / (text_length * segment_length))


def _distance_point_to_box(
    px: float,
    py: float,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> float:
    dx = max(min_x - px, 0.0, px - max_x)
    dy = max(min_y - py, 0.0, py - max_y)
    return math.hypot(dx, dy)


def _segment_intersects_box(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> bool:
    if (
        min_x <= ax <= max_x
        and min_y <= ay <= max_y
        or min_x <= bx <= max_x
        and min_y <= by <= max_y
    ):
        return True
    edges = (
        (min_x, min_y, max_x, min_y),
        (max_x, min_y, max_x, max_y),
        (max_x, max_y, min_x, max_y),
        (min_x, max_y, min_x, min_y),
    )
    return any(_segments_intersect(ax, ay, bx, by, *edge) for edge in edges)


def _segments_intersect(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
) -> bool:
    def orientation(
        px: float, py: float, qx: float, qy: float, rx: float, ry: float
    ) -> float:
        return (qy - py) * (rx - qx) - (qx - px) * (ry - qy)

    first = orientation(ax, ay, bx, by, cx, cy)
    second = orientation(ax, ay, bx, by, dx, dy)
    third = orientation(cx, cy, dx, dy, ax, ay)
    fourth = orientation(cx, cy, dx, dy, bx, by)
    return first * second <= 0 and third * fourth <= 0


def _parse_layer_diameter_hint(layer: str) -> float | None:
    if not any(marker in layer.casefold() for marker in ("sprinkler", "pipe", "撒水", "管")):
        return None
    match = re.search(r"(?:^|[^0-9])(20|25|32|40|50|65|80|100|125|150|200|250)(?:[^0-9]|$)", layer)
    return float(match.group(1)) if match is not None else None


def _distance_to_segment(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    dx = bx - ax
    dy = by - ay
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        return math.hypot(px - ax, py - ay)
    parameter = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.hypot(px - (ax + parameter * dx), py - (ay + parameter * dy))
