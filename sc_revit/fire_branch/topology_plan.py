from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any


TOPOLOGY_PLAN_SCHEMA_VERSION = "fire_branch_topology_plan.v5"
_SOURCE_MODES = {"cad", "uniform"}
_EDITABLE_JUNCTION_KINDS = {
    "tee",
    "reducing_tee",
    "endpoint_tee",
    "reducing_endpoint_tee",
    "cross",
    "reducing_cross",
    "elbow",
    "coupling",
}


def build_uniform_route_analysis(
    *,
    route_segments: list[dict[str, Any]],
    main_segments: list[dict[str, Any]],
    diameter_mm: float,
    main_diameter_mm: float | None = None,
) -> dict[str, Any]:
    """Adapt preview geometry to a no-CAD, uniform-diameter analysis.

    This adapter deliberately consumes only route geometry.  It never reads
    CAD text, colour or layer evidence, and it does not introduce a second
    Revit modelling path.
    """

    selected_diameter = float(diameter_mm)
    if not math.isfinite(selected_diameter) or selected_diameter <= 0:
        raise ValueError("統一支管管徑必須大於 0")
    segments = copy.deepcopy(list(route_segments or []))
    mains = copy.deepcopy(list(main_segments or []))
    if not segments:
        raise ValueError("預覽未回傳可用的支管路徑")
    for index, segment in enumerate(segments):
        segment.setdefault("segment_id", f"uniform-{index}")
        segment["diameter_mm"] = selected_diameter
        segment["evidence"] = "uniform_user_setting"
        segment["confidence"] = "user_confirmed"
        segment["review_required"] = False

    first_by_row: dict[int, dict[str, Any]] = {}
    for segment in segments:
        row_index = int(segment.get("row_index") or 0)
        current = first_by_row.get(row_index)
        if current is None or int(segment.get("sequence") or 0) < int(
            current.get("sequence") or 0
        ):
            first_by_row[row_index] = segment

    junctions: list[dict[str, Any]] = []
    for row_index, segment in sorted(first_by_row.items()):
        main, point = _nearest_main_segment(segment, mains)
        main_diameter = _float_or_none(
            (main or {}).get("diameter_mm")
            if main is not None
            else main_diameter_mm
        )
        if main_diameter is None:
            main_diameter = _float_or_none(main_diameter_mm)
        junctions.append(
            {
                "kind": (
                    "tee"
                    if main_diameter is not None
                    and math.isclose(main_diameter, selected_diameter)
                    else "reducing_tee"
                ),
                "row_index": row_index,
                "branch_segment_id": str(segment.get("segment_id") or ""),
                "main_segment_id": str((main or {}).get("segment_id") or ""),
                "point": point,
                "main_diameter_mm": main_diameter,
                "branch_diameter_mm": selected_diameter,
                "review_required": main is None,
            }
        )
    return {
        "status": "ready",
        "source_mode": "uniform",
        "cad_path_verified": False,
        "resolved_segment_count": len(segments),
        "unresolved_segment_count": 0,
        "segments": segments,
        "main_context_segments": mains,
        "junctions": junctions,
        "reducers": [],
        "warning_codes": [],
    }


def create_topology_plan(
    diameter_analysis: dict[str, Any],
    *,
    source_mode: str = "cad",
    preview_snapshot_id: str = "",
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the versioned plan consumed by both SVG and Revit adapters."""

    mode = str(source_mode or "").strip().casefold()
    if mode not in _SOURCE_MODES:
        raise ValueError("拓樸計畫來源模式必須是 cad 或 uniform")

    # Imported lazily so the contract Module can wrap the current topology
    # implementation without creating a module import cycle during migration.
    from .model_plan import build_fire_branch_topology_plan

    resolved = build_fire_branch_topology_plan(diameter_analysis)
    plan = {
        "schema_version": TOPOLOGY_PLAN_SCHEMA_VERSION,
        "plan_id": str(preview_snapshot_id or "").strip(),
        "revision": 1,
        "parent_plan_hash": None,
        "source_mode": mode,
        "settings": copy.deepcopy(settings or {}),
        "segments": copy.deepcopy(list(diameter_analysis.get("segments") or [])),
        "main_segments": copy.deepcopy(
            list(diameter_analysis.get("main_context_segments") or [])
        ),
        "junctions": copy.deepcopy(list(resolved.get("junctions") or [])),
        "reducers": copy.deepcopy(list(resolved.get("reducers") or [])),
        "evidence": {
            "cad_path_verified": bool(diameter_analysis.get("cad_path_verified")),
            "analysis_status": str(diameter_analysis.get("status") or "unknown"),
            "warning_codes": copy.deepcopy(
                list(diameter_analysis.get("warning_codes") or [])
            ),
            "route_candidate_decision": copy.deepcopy(
                diameter_analysis.get("route_candidate_decision")
            ),
            "route_candidate_decisions": copy.deepcopy(
                list(diameter_analysis.get("route_candidate_decisions") or [])
            ),
            "main_continuation_decision": copy.deepcopy(
                diameter_analysis.get("main_continuation_decision")
            ),
        },
    }
    _assign_plan_entity_ids(plan)
    if not plan["plan_id"]:
        plan["plan_id"] = "plan-" + _hash_payload(plan)[:16]
    plan["validation"] = validate_topology_plan(plan)
    plan["plan_hash"] = _hash_payload(plan)
    return plan


def create_uniform_topology_plan(
    route_analysis: dict[str, Any],
    *,
    diameter_mm: float,
    preview_snapshot_id: str = "",
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Adapt the legacy no-CAD route geometry into the common plan contract."""

    selected_diameter = float(diameter_mm)
    if not math.isfinite(selected_diameter) or selected_diameter <= 0:
        raise ValueError("統一支管管徑必須大於 0")

    analysis = copy.deepcopy(route_analysis)
    analysis["status"] = "ready"
    analysis["cad_path_verified"] = False
    analysis["unresolved_segment_count"] = 0
    analysis["reducers"] = []
    for segment in analysis.get("segments") or []:
        segment["diameter_mm"] = selected_diameter
        segment["evidence"] = "uniform_user_setting"
        segment["confidence"] = "user_confirmed"
        segment["review_required"] = False
    for junction in analysis.get("junctions") or []:
        junction["branch_diameter_mm"] = selected_diameter
        junction["review_required"] = False
        kind = str(junction.get("kind") or "")
        if kind.startswith("unresolved"):
            main_diameter = _float_or_none(junction.get("main_diameter_mm"))
            junction["kind"] = (
                "tee"
                if main_diameter is not None
                and math.isclose(main_diameter, selected_diameter)
                else "reducing_tee"
            )

    merged_settings = copy.deepcopy(settings or {})
    merged_settings["uniform_diameter_mm"] = selected_diameter
    plan = create_topology_plan(
        analysis,
        source_mode="uniform",
        preview_snapshot_id=preview_snapshot_id,
        settings=merged_settings,
    )
    plan["reducers"] = []
    plan["validation"] = validate_topology_plan(plan)
    plan["plan_hash"] = _hash_payload(plan)
    return plan


def revise_topology_plan(
    plan: dict[str, Any],
    command: dict[str, Any],
) -> dict[str, Any]:
    """Apply one constrained edit and return a new immutable plan revision."""

    _require_supported_plan(plan)
    expected_plan_id = str(command.get("plan_id") or "").strip()
    if expected_plan_id and expected_plan_id != str(plan.get("plan_id") or ""):
        raise ValueError("拓樸計畫識別碼不一致，請重新整理後再修改")
    expected_revision = command.get("expected_revision")
    if expected_revision is not None and int(expected_revision) != int(
        plan.get("revision") or 1
    ):
        raise ValueError("拓樸計畫版本不一致，請重新整理後再修改")
    expected_hash = str(
        command.get("expected_plan_hash") or command.get("expected_hash") or ""
    ).strip()
    current_hash = str(plan.get("plan_hash") or _hash_payload(plan))
    if expected_hash and expected_hash != current_hash:
        raise ValueError("拓樸計畫已不是目前版本，請重新整理後再修改")
    command_type = str(command.get("type") or "").strip()
    revised = copy.deepcopy(plan)
    parent_hash = current_hash
    revised.pop("plan_hash", None)

    if command_type in {"set_segment_diameter", "change_segment_diameter"}:
        _set_segment_diameter(revised, command)
        _rebuild_engineering_reducers(revised)
    elif command_type in {"set_junction_kind", "change_junction_type"}:
        _set_junction_kind(revised, command)
    elif command_type in {"set_reducer", "change_reducer_sizes"}:
        _set_reducer(revised, command)
    elif command_type == "choose_route_candidate":
        _choose_candidate(revised, command, "route")
    elif command_type == "choose_main_continuation":
        _choose_candidate(revised, command, "main")
    elif command_type == "mark_reviewed":
        _mark_reviewed(revised, command)
    else:
        raise ValueError(f"不支援的拓樸修正：{command_type or '未指定'}")

    revised["revision"] = int(plan.get("revision") or 1) + 1
    revised["parent_plan_hash"] = parent_hash
    revised["last_command"] = copy.deepcopy(command)
    _assign_plan_entity_ids(revised)
    validation = validate_topology_plan(revised)
    if validation["status"] == "valid":
        validation["status"] = "topology_valid"
        validation["requires_revit_preflight"] = True
    revised["validation"] = validation
    revised["plan_hash"] = _hash_payload(revised)
    return revised


def _rebuild_engineering_reducers(plan: dict[str, Any]) -> None:
    segment_by_id = {
        str(item.get("segment_id") or ""): item
        for item in (plan.get("segments") or [])
        if str(item.get("segment_id") or "")
    }
    regenerated: list[dict[str, Any]] = []
    for junction in plan.get("junctions") or []:
        branch_ids = _junction_branch_segment_ids(junction)
        if not branch_ids:
            continue
        source_diameters = [
            _float_or_none(segment_by_id.get(segment_id, {}).get("diameter_mm"))
            for segment_id in branch_ids
        ]
        valid_source_diameters = [
            float(item) for item in source_diameters if item is not None
        ]
        if not valid_source_diameters:
            continue
        common = max(valid_source_diameters)
        junction["source_branch_diameters_mm"] = source_diameters
        junction["common_branch_diameter_mm"] = common
        kind = str(junction.get("kind") or "")
        if len(branch_ids) >= 2 and kind in {
            "cross",
            "reducing_cross",
            "endpoint_tee",
            "reducing_endpoint_tee",
        }:
            main_diameter = _float_or_none(junction.get("main_diameter_mm"))
            if main_diameter is not None and all(
                math.isclose(item, main_diameter) for item in valid_source_diameters
            ):
                junction["kind"] = "cross" if "cross" in kind else "endpoint_tee"
                outlet_diameters = valid_source_diameters
            else:
                junction["kind"] = (
                    "reducing_cross" if "cross" in kind else "reducing_endpoint_tee"
                )
                outlet_diameters = [common for _ in branch_ids]
                placement = (
                    "after_cross" if "cross" in junction["kind"] else "after_endpoint_tee"
                )
                for branch_id, source_diameter in zip(branch_ids, source_diameters):
                    if source_diameter is None or math.isclose(source_diameter, common):
                        continue
                    regenerated.append(
                        {
                            "branch_segment_id": branch_id,
                            "placement": placement,
                            "point": copy.deepcopy(junction.get("point") or {}),
                            "row_index": int(
                                segment_by_id.get(branch_id, {}).get("row_index") or 0
                            ),
                            "from_diameter_mm": float(common),
                            "to_diameter_mm": float(source_diameter),
                            "evidence": "engineering_rule",
                            "plan_entity_id": f"reducer:{branch_id}:{placement}",
                        }
                    )
        else:
            outlet_diameters = valid_source_diameters
        junction["branch_outlet_diameters_mm"] = outlet_diameters
        junction["branch_outlet_diameters_by_segment_id"] = {
            branch_id: diameter
            for branch_id, diameter in zip(branch_ids, outlet_diameters)
        }

    rows: dict[int, list[dict[str, Any]]] = {}
    for segment in segment_by_id.values():
        rows.setdefault(int(segment.get("row_index") or 0), []).append(segment)
    for row_segments in rows.values():
        ordered = sorted(row_segments, key=lambda item: int(item.get("sequence") or 0))
        for before, after in zip(ordered, ordered[1:]):
            before_diameter = _float_or_none(before.get("diameter_mm"))
            after_diameter = _float_or_none(after.get("diameter_mm"))
            if (
                before_diameter is None
                or after_diameter is None
                or not before_diameter > after_diameter
            ):
                continue
            before_id = str(before.get("segment_id") or "")
            after_id = str(after.get("segment_id") or "")
            regenerated.append(
                {
                    "before_segment_id": before_id,
                    "after_segment_id": after_id,
                    "placement": "along_branch",
                    "row_index": int(after.get("row_index") or 0),
                    "from_diameter_mm": float(before_diameter),
                    "to_diameter_mm": float(after_diameter),
                    "evidence": "engineering_rule",
                    "plan_entity_id": f"reducer:{before_id}:{after_id}",
                }
            )
    preserved = [
        item
        for item in (plan.get("reducers") or [])
        if str(item.get("placement") or "along_branch")
        not in {"along_branch", "after_cross", "after_endpoint_tee"}
    ]
    plan["reducers"] = preserved + regenerated


def validate_topology_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate contract-level invariants without mutating Revit."""

    issues: list[dict[str, str]] = []
    mode = str(plan.get("source_mode") or "").strip().casefold()
    if mode not in _SOURCE_MODES:
        issues.append({"code": "invalid_source_mode", "message": "來源模式無效"})

    segment_ids: set[str] = set()
    entity_ids: set[str] = set()
    segment_by_id: dict[str, dict[str, Any]] = {}
    for index, segment in enumerate(plan.get("segments") or []):
        segment_id = str(segment.get("segment_id") or "").strip()
        if not segment_id:
            issues.append(
                {"code": "missing_segment_id", "message": f"第 {index + 1} 段缺少識別碼"}
            )
        elif segment_id in segment_ids:
            issues.append(
                {"code": "duplicate_segment_id", "message": f"管段 {segment_id} 重複"}
            )
        segment_ids.add(segment_id)
        if segment_id:
            segment_by_id[segment_id] = segment
        _validate_entity_id(segment, entity_ids, issues, f"管段 {segment_id or index + 1}")
        diameter = _float_or_none(segment.get("diameter_mm"))
        if diameter is None or not math.isfinite(diameter) or diameter <= 0:
            issues.append(
                {"code": "invalid_segment_diameter", "message": f"管段 {segment_id or index + 1} 管徑無效"}
            )

    main_segment_ids = {
        str(segment.get("segment_id") or "").strip()
        for segment in (plan.get("main_segments") or [])
        if str(segment.get("segment_id") or "").strip()
    }
    for index, main_segment in enumerate(plan.get("main_segments") or []):
        _validate_entity_id(
            main_segment,
            entity_ids,
            issues,
            f"主管管段 {main_segment.get('segment_id') or index + 1}",
        )
    for junction in plan.get("junctions") or []:
        _validate_entity_id(junction, entity_ids, issues, "接頭")
        branch_segment_ids = [
            str(segment_id).strip()
            for segment_id in (junction.get("branch_segment_ids") or [])
            if str(segment_id).strip()
        ]
        singular_branch_id = str(junction.get("branch_segment_id") or "").strip()
        if not branch_segment_ids and singular_branch_id:
            branch_segment_ids = [singular_branch_id]
        missing = [
            str(segment_id)
            for segment_id in branch_segment_ids
            if str(segment_id) not in segment_ids
        ]
        if missing:
            issues.append(
                {
                    "code": "junction_segment_missing",
                    "message": "接頭引用不存在管段：" + ", ".join(missing),
                }
            )
        main_segment_id = str(junction.get("main_segment_id") or "").strip()
        if main_segment_ids and main_segment_id and main_segment_id not in main_segment_ids:
            issues.append(
                {
                    "code": "junction_main_segment_missing",
                    "message": f"接頭引用不存在主管管段：{main_segment_id}",
                }
            )
        kind = str(junction.get("kind") or "").strip()
        required_branch_count = (
            2
            if kind in {
                "cross",
                "reducing_cross",
                "endpoint_tee",
                "reducing_endpoint_tee",
            }
            else 1 if kind in {"tee", "reducing_tee"} else None
        )
        if required_branch_count is not None and len(branch_segment_ids) != required_branch_count:
            issues.append(
                {
                    "code": "junction_branch_count_mismatch",
                    "message": (
                        f"接頭 {kind} 需要 {required_branch_count} 個支管方向，"
                        f"目前為 {len(branch_segment_ids)} 個"
                    ),
                }
            )
        if junction.get("review_required"):
            issues.append(
                {"code": "junction_review_required", "message": "仍有接頭需要確認"}
            )

    for reducer in plan.get("reducers") or []:
        _validate_entity_id(reducer, entity_ids, issues, "異徑")
        before_id = str(reducer.get("before_segment_id") or "").strip()
        after_id = str(reducer.get("after_segment_id") or "").strip()
        branch_id = str(reducer.get("branch_segment_id") or "").strip()
        referenced_ids = [item for item in (before_id, after_id, branch_id) if item]
        missing_ids = [item for item in referenced_ids if item not in segment_ids]
        if missing_ids:
            issues.append(
                {
                    "code": "reducer_segment_missing",
                    "message": "異徑引用不存在管段：" + ", ".join(missing_ids),
                }
            )
        if before_id and after_id and before_id == after_id:
            issues.append(
                {
                    "code": "reducer_same_segment",
                    "message": "異徑前後不可引用同一管段",
                }
            )
        before = _float_or_none(reducer.get("from_diameter_mm"))
        after = _float_or_none(reducer.get("to_diameter_mm"))
        if before is None or after is None or before <= 0 or after <= 0 or after > before:
            issues.append(
                {
                    "code": "invalid_reducer_diameter",
                    "message": "異徑尺寸必須沿供水方向由大縮小",
                }
            )
            continue
        if before_id in segment_by_id and not math.isclose(
            float(segment_by_id[before_id].get("diameter_mm") or 0), before
        ):
            issues.append(
                {
                    "code": "reducer_before_diameter_mismatch",
                    "message": f"異徑前管段 {before_id} 與異徑尺寸不一致",
                }
            )
        target_id = after_id or branch_id
        if target_id in segment_by_id and not math.isclose(
            float(segment_by_id[target_id].get("diameter_mm") or 0), after
        ):
            issues.append(
                {
                    "code": "reducer_after_diameter_mismatch",
                    "message": f"異徑後管段 {target_id} 與異徑尺寸不一致",
                }
            )

    return {
        "status": "invalid" if issues else "valid",
        "issues": issues,
        "requires_revit_preflight": False,
    }


def _set_segment_diameter(plan: dict[str, Any], command: dict[str, Any]) -> None:
    segment_id = str(command.get("segment_id") or command.get("target_id") or "").strip()
    if segment_id.startswith("segment:"):
        segment_id = segment_id[len("segment:") :]
    diameter = float(command.get("diameter_mm") or command.get("after_diameter_mm") or 0)
    if not segment_id or not math.isfinite(diameter) or diameter <= 0:
        raise ValueError("修改管徑需要有效的管段與正數管徑")
    target = next(
        (
            item
            for item in (plan.get("segments") or [])
            if str(item.get("segment_id") or "") == segment_id
        ),
        None,
    )
    if target is None:
        raise ValueError(f"找不到管段：{segment_id}")
    target["diameter_mm"] = diameter
    target["evidence"] = "user_revision"
    target["confidence"] = "user_confirmed"
    target["review_required"] = False

    for junction in plan.get("junctions") or []:
        branch_ids = [str(item) for item in junction.get("branch_segment_ids") or []]
        singular_branch_id = str(junction.get("branch_segment_id") or "").strip()
        if not branch_ids and singular_branch_id:
            branch_ids = [singular_branch_id]
        if segment_id not in branch_ids:
            continue
        diameters = list(junction.get("source_branch_diameters_mm") or [])
        position = branch_ids.index(segment_id)
        while len(diameters) < len(branch_ids):
            diameters.append(None)
        diameters[position] = diameter
        junction["source_branch_diameters_mm"] = diameters
        valid = [float(item) for item in diameters if item is not None]
        junction["common_branch_diameter_mm"] = max(valid) if valid else diameter
        junction["review_required"] = False


def _junction_branch_segment_ids(junction: dict[str, Any]) -> list[str]:
    branch_ids = [
        str(item).strip()
        for item in (junction.get("branch_segment_ids") or [])
        if str(item).strip()
    ]
    singular_branch_id = str(junction.get("branch_segment_id") or "").strip()
    if not branch_ids and singular_branch_id:
        branch_ids = [singular_branch_id]
    return branch_ids


def _set_junction_kind(plan: dict[str, Any], command: dict[str, Any]) -> None:
    index_value = command.get("junction_index")
    target_id = str(command.get("target_id") or "").strip()
    index = int(index_value) if index_value is not None else -1
    kind = str(command.get("kind") or "").strip()
    junctions = list(plan.get("junctions") or [])
    if target_id and index < 0:
        index = next(
            (
                position
                for position, item in enumerate(junctions)
                if str(item.get("plan_entity_id") or "") == target_id
                or str(item.get("junction_id") or "") == target_id
            ),
            -1,
        )
    if index < 0 or index >= len(junctions):
        raise ValueError("找不到指定接頭")
    if kind not in _EDITABLE_JUNCTION_KINDS:
        raise ValueError(f"不允許的接頭類型：{kind or '未指定'}")
    junctions[index]["kind"] = kind
    junctions[index]["review_required"] = False


def _set_reducer(plan: dict[str, Any], command: dict[str, Any]) -> None:
    index_value = command.get("reducer_index")
    target_id = str(command.get("target_id") or "").strip()
    index = int(index_value) if index_value is not None else -1
    reducers = list(plan.get("reducers") or [])
    if target_id and index < 0:
        index = next(
            (
                position
                for position, item in enumerate(reducers)
                if str(item.get("plan_entity_id") or "") == target_id
                or str(item.get("reducer_id") or "") == target_id
            ),
            -1,
        )
    if index < 0 or index >= len(reducers):
        raise ValueError("找不到指定異徑")
    before = float(command.get("from_diameter_mm") or 0)
    after = float(command.get("to_diameter_mm") or 0)
    if before <= 0 or after <= 0 or after > before:
        raise ValueError("異徑只能沿供水方向由大管徑縮小")
    reducer = reducers[index]
    before_segment_id = str(reducer.get("before_segment_id") or "").strip()
    after_segment_id = str(reducer.get("after_segment_id") or "").strip()
    branch_segment_id = str(reducer.get("branch_segment_id") or "").strip()
    if before_segment_id:
        _set_segment_diameter(
            plan,
            {"segment_id": before_segment_id, "diameter_mm": before},
        )
    target_segment_id = after_segment_id or branch_segment_id
    if target_segment_id:
        _set_segment_diameter(
            plan,
            {"segment_id": target_segment_id, "diameter_mm": after},
        )
    reducer["from_diameter_mm"] = before
    reducer["to_diameter_mm"] = after
    reducer["evidence"] = "user_revision"


def _require_supported_plan(plan: dict[str, Any]) -> None:
    if str(plan.get("schema_version") or "") != TOPOLOGY_PLAN_SCHEMA_VERSION:
        raise ValueError("目前拓樸計畫版本不支援修正，請重新分析")


def _assign_plan_entity_ids(plan: dict[str, Any]) -> None:
    """Assign deterministic IDs shared by SVG review and model execution."""

    used: set[str] = set()

    def assign(item: dict[str, Any], base: str) -> None:
        existing = str(item.get("plan_entity_id") or "").strip()
        value = existing or base
        if value in used:
            suffix = 2
            while f"{value}:{suffix}" in used:
                suffix += 1
            value = f"{value}:{suffix}"
        used.add(value)
        item["plan_entity_id"] = value

    for index, segment in enumerate(plan.get("segments") or []):
        segment_id = str(segment.get("segment_id") or f"row-{index}-0").strip()
        segment.setdefault("segment_id", segment_id)
        assign(segment, f"segment:{segment_id}")
    for index, segment in enumerate(plan.get("main_segments") or []):
        segment_id = str(segment.get("segment_id") or f"main-{index + 1}").strip()
        segment.setdefault("segment_id", segment_id)
        assign(segment, f"main:{segment_id}")
    for index, junction in enumerate(plan.get("junctions") or []):
        main_id = str(junction.get("main_segment_id") or "main").strip()
        branch_ids = [
            str(item).strip()
            for item in (junction.get("branch_segment_ids") or [])
            if str(item).strip()
        ]
        singular = str(junction.get("branch_segment_id") or "").strip()
        if not branch_ids and singular:
            branch_ids = [singular]
        base = f"junction:{main_id}:{':'.join(sorted(branch_ids))}" if branch_ids else f"junction:{index}"
        assign(junction, base)
    for index, reducer in enumerate(plan.get("reducers") or []):
        before = str(reducer.get("before_segment_id") or "").strip()
        after = str(reducer.get("after_segment_id") or reducer.get("branch_segment_id") or "").strip()
        base = f"reducer:{before}:{after}" if before or after else f"reducer:{index}"
        assign(reducer, base)


def _validate_entity_id(
    item: dict[str, Any],
    used: set[str],
    issues: list[dict[str, str]],
    label: str,
) -> None:
    entity_id = str(item.get("plan_entity_id") or "").strip()
    if not entity_id:
        issues.append({"code": "missing_plan_entity_id", "message": f"{label}缺少計畫識別碼"})
    elif entity_id in used:
        issues.append({"code": "duplicate_plan_entity_id", "message": f"計畫識別碼重複：{entity_id}"})
    else:
        used.add(entity_id)


def _choose_candidate(plan: dict[str, Any], command: dict[str, Any], kind: str) -> None:
    candidate_id = str(
        command.get("candidate_id") or command.get("target_id") or ""
    ).strip()
    if not candidate_id:
        raise ValueError("選擇路徑需要候選識別碼")
    key = "route_candidate_decision" if kind == "route" else "main_continuation_decision"
    evidence = plan.setdefault("evidence", {})
    decision = evidence.get(key)
    decisions = evidence.get(f"{key}s")
    if isinstance(decisions, list):
        candidates = [item for item in decisions if isinstance(item, dict)]
        sprinkler_id = str(command.get("sprinkler_id") or "").strip()
        matching = [
            item
            for item in candidates
            if candidate_id in (item.get("candidates") or {})
            and (
                not sprinkler_id
                or str(item.get("sprinkler_id") or "").strip() == sprinkler_id
            )
        ]
        if len(matching) > 1:
            raise ValueError("候選路徑對應多顆灑水頭，請指定 sprinkler_id")
        if matching:
            decision = matching[0]
        elif len(candidates) == 1:
            decision = candidates[0]
    if not isinstance(decision, dict):
        raise ValueError("計畫中沒有可供選擇的候選路徑")
    known = set((decision.get("candidates") or {}).keys())
    if known and candidate_id not in known:
        raise ValueError(f"找不到候選路徑：{candidate_id}")
    decision["selected_candidate_id"] = candidate_id
    decision["selection_source"] = "user_override"
    decision["selection_message"] = "使用者在 SVG 計畫中指定此候選路徑。"
    selected_key = f"selected_{kind}_candidate_id"
    evidence[selected_key] = candidate_id
    if isinstance(decisions, list) and kind == "route":
        selected_by_sprinkler = evidence.setdefault(
            "selected_route_candidate_ids", {}
        )
        decision_sprinkler_id = str(
            decision.get("sprinkler_id") or command.get("sprinkler_id") or ""
        ).strip()
        if decision_sprinkler_id:
            selected_by_sprinkler[decision_sprinkler_id] = candidate_id


def _mark_reviewed(plan: dict[str, Any], command: dict[str, Any]) -> None:
    target_id = str(command.get("target_id") or "").strip()
    if not target_id:
        raise ValueError("確認項目需要計畫識別碼")
    collections = (
        ("segments", plan.get("segments") or []),
        ("main_segments", plan.get("main_segments") or []),
        ("junctions", plan.get("junctions") or []),
        ("reducers", plan.get("reducers") or []),
    )
    for _, items in collections:
        for item in items:
            if str(item.get("plan_entity_id") or "") == target_id:
                item["review_required"] = False
                item["reviewed_by_user"] = True
                if command.get("reason"):
                    item["review_reason"] = str(command["reason"])
                return
    raise ValueError(f"找不到確認項目：{target_id}")


def _hash_payload(payload: dict[str, Any]) -> str:
    value = copy.deepcopy(payload)
    value.pop("plan_hash", None)
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def _nearest_main_segment(
    branch: dict[str, Any],
    mains: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, float]]:
    candidates = [branch.get("start") or {}, branch.get("end") or {}]
    best: tuple[float, dict[str, Any], dict[str, float]] | None = None
    for main in mains:
        start = main.get("start") or {}
        end = main.get("end") or {}
        ax, ay = float(start.get("x") or 0), float(start.get("y") or 0)
        bx, by = float(end.get("x") or 0), float(end.get("y") or 0)
        vx, vy = bx - ax, by - ay
        length_squared = vx * vx + vy * vy
        if length_squared <= 1e-18:
            continue
        for candidate in candidates:
            px = float(candidate.get("x") or 0)
            py = float(candidate.get("y") or 0)
            t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / length_squared))
            projected = {
                "x": ax + vx * t,
                "y": ay + vy * t,
                "z": float(candidate.get("z") or start.get("z") or 0),
            }
            distance = math.hypot(px - projected["x"], py - projected["y"])
            if best is None or distance < best[0]:
                best = (distance, main, projected)
    if best is not None:
        return best[1], best[2]
    fallback = candidates[0]
    return None, {
        "x": float(fallback.get("x") or 0),
        "y": float(fallback.get("y") or 0),
        "z": float(fallback.get("z") or 0),
    }
