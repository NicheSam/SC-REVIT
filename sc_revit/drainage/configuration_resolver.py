from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


STRATEGY_VERSION = "sc-drainage-configuration-resolver.v1"


def get_operation_journal_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return (
            Path(local_app_data)
            / "RevitFamilyClassifier"
            / "runtime"
            / "queue"
            / "operations"
        )
    return (
        Path.home()
        / "AppData"
        / "Local"
        / "RevitFamilyClassifier"
        / "runtime"
        / "queue"
        / "operations"
    )


def recommend_drainage_configuration(
    *,
    context: dict[str, Any],
    main_pipe: dict[str, Any],
    diameter_mm: float,
    saved_settings: dict[str, Any] | None = None,
    operation_journal_dir: Path | None = None,
    history_limit: int = 100,
) -> dict[str, Any]:
    if not 25 <= diameter_mm <= 300:
        raise ValueError("diameter_mm must be between 25 and 300")
    if not 1 <= history_limit <= 200:
        raise ValueError("history_limit must be between 1 and 200")

    document = context.get("document") or {}
    document_fingerprint = str(document.get("fingerprint") or "")
    if not document_fingerprint:
        raise ValueError("context document fingerprint is required")

    pipe_type = _find_by_element_id(
        context.get("pipe_types"),
        main_pipe.get("pipe_type_id"),
    )
    system_type = _find_by_element_id(
        context.get("system_types"),
        main_pipe.get("system_type_id"),
    )
    level = _find_by_element_id(
        context.get("levels"),
        main_pipe.get("level_id"),
    )
    blocking_issues: list[str] = []
    if pipe_type is None:
        blocking_issues.append("MAIN_PIPE_TYPE_NOT_IN_CONTEXT")
    if system_type is None:
        blocking_issues.append("MAIN_SYSTEM_TYPE_NOT_IN_CONTEXT")
    if level is None:
        blocking_issues.append("MAIN_LEVEL_NOT_IN_CONTEXT")

    profile = next(
        (
            item
            for item in context.get("routing_profiles") or []
            if str(item.get("pipe_type_id") or "")
            == str(main_pipe.get("pipe_type_id") or "")
        ),
        {},
    )
    junctions = _applicable_candidates(
        profile.get("junctions"),
        diameter_mm,
    )
    elbows = _applicable_candidates(
        profile.get("elbows"),
        diameter_mm,
    )
    if not junctions:
        blocking_issues.append("JUNCTION_CANDIDATE_NOT_FOUND")
    if not elbows:
        blocking_issues.append("ELBOW_CANDIDATE_NOT_FOUND")

    history = _read_operation_history(
        operation_journal_dir or get_operation_journal_dir(),
        document_fingerprint=document_fingerprint,
        diameter_mm=diameter_mm,
        history_limit=history_limit,
    )
    settings = saved_settings or {}
    settings_match_document = (
        str(settings.get("document_fingerprint") or "")
        == document_fingerprint
    )
    if not settings_match_document:
        settings = {}

    ranked_junctions = _rank_fitting_candidates(
        junctions,
        usage_counts=history["junction_counts"],
        saved_unique_id=str(
            settings.get("junction_type_unique_id") or ""
        ),
    )
    ranked_elbows = _rank_fitting_candidates(
        elbows,
        usage_counts=history["elbow_counts"],
        saved_unique_id=str(
            settings.get("elbow_type_unique_id") or ""
        ),
    )
    junction_confidence = _candidate_confidence(ranked_junctions)
    elbow_confidence = _candidate_confidence(ranked_elbows)
    auto_select_allowed = (
        not blocking_issues
        and junction_confidence["level"] == "high"
        and elbow_confidence["level"] == "high"
    )

    warnings: list[str] = []
    if history["matching_operations"] == 0:
        warnings.append("NO_MATCHING_OPERATION_HISTORY")
    if ranked_junctions and junction_confidence["level"] != "high":
        warnings.append("JUNCTION_REQUIRES_HUMAN_REVIEW")
    if ranked_elbows and elbow_confidence["level"] != "high":
        warnings.append("ELBOW_REQUIRES_HUMAN_REVIEW")

    recommended = {
        "pipe_type": _element_ref(pipe_type),
        "system_type": _element_ref(system_type),
        "level": _element_ref(level),
        "junction": _element_ref(
            ranked_junctions[0] if ranked_junctions else None
        ),
        "elbow": _element_ref(
            ranked_elbows[0] if ranked_elbows else None
        ),
    }
    return {
        "strategy_version": STRATEGY_VERSION,
        "document": document,
        "main_pipe": {
            "element_id": main_pipe.get("element_id"),
            "unique_id": main_pipe.get("unique_id"),
            "diameter_mm": main_pipe.get("diameter_mm"),
        },
        "diameter_mm": diameter_mm,
        "selection_policy": {
            "model_scan": "none",
            "main_context": "explicit_current_selection",
            "routing_basis": "size-compatible routing preference order",
            "usage_basis":
                "bounded same-document committed operation history",
            "history_limit": history_limit,
            "auto_select_rule":
                "unique candidate, valid saved human choice, or "
                "dominant same-document usage",
        },
        "history_evidence": history,
        "saved_human_settings_used": bool(settings),
        "junction_candidates": ranked_junctions,
        "elbow_candidates": ranked_elbows,
        "recommended_configuration": recommended,
        "confidence": {
            "junction": junction_confidence,
            "elbow": elbow_confidence,
            "overall": (
                "blocked"
                if blocking_issues
                else "high"
                if auto_select_allowed
                else "review"
            ),
        },
        "auto_select_allowed": auto_select_allowed,
        "requires_human_choice": (
            bool(blocking_issues) or not auto_select_allowed
        ),
        "blocking_issues": blocking_issues,
        "warnings": warnings,
    }


def _find_by_element_id(
    items: Any,
    element_id: Any,
) -> dict[str, Any] | None:
    expected = str(element_id or "")
    return next(
        (
            item
            for item in items or []
            if str(item.get("element_id") or "") == expected
        ),
        None,
    )


def _element_ref(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {
        "element_id": item.get("element_id"),
        "unique_id": item.get("unique_id"),
        "name": item.get("name"),
        "family_name": item.get("family_name"),
    }


def _applicable_candidates(
    candidates: Any,
    diameter_mm: float,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in candidates or []:
        criteria = list(raw.get("criteria") or [])
        if criteria and not any(
            _criterion_contains(item, diameter_mm)
            for item in criteria
        ):
            continue
        candidate = dict(raw)
        candidate["routing_order"] = int(
            raw.get("order") or 0
        )
        result.append(candidate)
    return result


def _criterion_contains(
    criterion: dict[str, Any],
    diameter_mm: float,
) -> bool:
    minimum = criterion.get("minimum_mm")
    maximum = criterion.get("maximum_mm")
    return (
        (minimum is None or diameter_mm >= float(minimum) - 0.01)
        and (maximum is None or diameter_mm <= float(maximum) + 0.01)
    )


def _rank_fitting_candidates(
    candidates: list[dict[str, Any]],
    *,
    usage_counts: dict[str, int],
    saved_unique_id: str,
) -> list[dict[str, Any]]:
    total_usage = sum(
        usage_counts.get(str(item.get("unique_id") or ""), 0)
        for item in candidates
    )
    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        item = dict(candidate)
        unique_id = str(item.get("unique_id") or "")
        usage_count = usage_counts.get(unique_id, 0)
        usage_share = (
            usage_count / total_usage if total_usage else 0.0
        )
        saved_match = bool(
            saved_unique_id and unique_id == saved_unique_id
        )
        routing_order = int(item.get("routing_order") or 0)
        item.update(
            {
                "usage_count": usage_count,
                "usage_share": round(usage_share, 6),
                "saved_human_choice": saved_match,
                "score": (
                    (100000 if saved_match else 0)
                    + usage_share * 10000
                    + usage_count * 100
                    + max(0, 100 - routing_order)
                ),
            }
        )
        ranked.append(item)
    ranked.sort(
        key=lambda item: (
            -float(item["score"]),
            int(item["routing_order"]),
            str(item.get("unique_id") or ""),
        )
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
        item["selection_basis"] = (
            "saved_human_choice"
            if item["saved_human_choice"]
            else "same_document_usage"
            if item["usage_count"] > 0
            else "routing_preference_order"
        )
    return ranked


def _candidate_confidence(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if not candidates:
        return {
            "level": "blocked",
            "reason": "no_size_compatible_candidate",
        }
    top = candidates[0]
    if top.get("saved_human_choice"):
        return {
            "level": "high",
            "reason": "same_document_saved_human_choice",
        }
    if len(candidates) == 1:
        return {
            "level": "high",
            "reason": "single_size_compatible_candidate",
        }
    top_count = int(top.get("usage_count") or 0)
    top_share = float(top.get("usage_share") or 0)
    second_share = float(candidates[1].get("usage_share") or 0)
    if (
        top_count >= 3
        and top_share >= 0.70
        and top_share - second_share >= 0.25
    ):
        return {
            "level": "high",
            "reason": "dominant_same_document_usage",
        }
    return {
        "level": "review",
        "reason": "routing_order_only_or_usage_not_dominant",
    }


def _read_operation_history(
    operation_dir: Path,
    *,
    document_fingerprint: str,
    diameter_mm: float,
    history_limit: int,
) -> dict[str, Any]:
    junction_counts: dict[str, int] = {}
    elbow_counts: dict[str, int] = {}
    files_examined = 0
    matching_operations = 0
    if not operation_dir.exists():
        return {
            "journal_available": False,
            "files_examined": 0,
            "matching_operations": 0,
            "junction_counts": junction_counts,
            "elbow_counts": elbow_counts,
        }
    paths = sorted(
        operation_dir.glob("DOP-*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:history_limit]
    for path in paths:
        files_examined += 1
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(
            record.get("DocumentFingerprint")
            or record.get("document_fingerprint")
            or ""
        ) != document_fingerprint:
            continue
        if str(record.get("Status") or record.get("status") or "") != (
            "committed"
        ):
            continue
        result = record.get("Result") or record.get("result") or {}
        operation_diameter = float(result.get("diameter_mm") or 0)
        tolerance = max(1.0, diameter_mm * 0.02)
        if abs(operation_diameter - diameter_mm) > tolerance:
            continue
        matching_operations += 1
        refs_by_id = {
            str(item.get("element_id") or ""): item
            for item in result.get("fitting_element_refs") or []
        }
        for fitting in result.get("fittings") or []:
            ref = refs_by_id.get(
                str(fitting.get("element_id") or "")
            ) or {}
            unique_id = str(ref.get("type_unique_id") or "")
            if not unique_id:
                continue
            kind = str(fitting.get("kind") or "")
            counts = (
                junction_counts
                if kind == "junction"
                else elbow_counts
                if kind == "elbow"
                else None
            )
            if counts is not None:
                counts[unique_id] = counts.get(unique_id, 0) + 1
    return {
        "journal_available": True,
        "files_examined": files_examined,
        "matching_operations": matching_operations,
        "junction_counts": junction_counts,
        "elbow_counts": elbow_counts,
    }
