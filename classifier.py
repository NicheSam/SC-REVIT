import json
import re
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).parent
RULES_PATH = BASE_DIR / "rules.json"

FIELD_WEIGHTS = {
    "family_name": 40,
    "type_name": 25,
    "file_name": 20,
    "revit_category": 30,
    "notes": 10,
}


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).casefold()).strip()


def load_rules() -> Dict[str, Any]:
    with RULES_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def resolve_structured_systems(metadata: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
    routing = config.get("structured_routing", {})
    normalized_values = {
        normalize(metadata.get(field, ""))
        for field in routing.get("fields", [])
        if metadata.get(field, "")
    }
    if not normalized_values:
        return []

    systems: List[str] = []
    for route in routing.get("routes", []):
        categories = {normalize(item) for item in route.get("categories", [])}
        if normalized_values & categories:
            systems.append(route["system"])
    return systems


def evaluate_rule(metadata: Dict[str, Any], rule: Dict[str, Any]) -> Dict[str, Any]:
    score = 0
    matched: Dict[str, List[str]] = {}
    combined_text = " ".join(
        normalize(metadata.get(field, ""))
        for field in FIELD_WEIGHTS
        if metadata.get(field, "")
    )

    excluded_hits = [
        term for term in rule.get("exclude_terms", []) if normalize(term) in combined_text
    ]
    if excluded_hits:
        return {
            "id": rule["id"],
            "system": rule["system"],
            "path": rule["path"],
            "score": 0,
            "matched": {"excluded": excluded_hits},
        }

    for field, weight in FIELD_WEIGHTS.items():
        value = normalize(metadata.get(field, ""))
        if not value:
            continue

        hits = [term for term in rule.get("terms", []) if normalize(term) in value]
        if hits:
            matched[field] = hits
            score += weight

    has_term_match = any(field in matched for field in FIELD_WEIGHTS)
    category = normalize(metadata.get("revit_category", ""))
    preferred_categories = [normalize(item) for item in rule.get("preferred_categories", [])]
    category_match = category and category in preferred_categories
    if category_match and (
        has_term_match or rule.get("allow_category_only", False)
    ):
        matched["preferred_category"] = [metadata["revit_category"]]
        score += FIELD_WEIGHTS["revit_category"]

    if has_term_match or (rule.get("allow_category_only", False) and category_match):
        score += int(rule.get("priority", 0))

    return {
        "id": rule["id"],
        "system": rule["system"],
        "path": rule["path"],
        "score": score,
        "matched": matched,
    }


def classify(metadata: Dict[str, Any]) -> Dict[str, Any]:
    config = load_rules()
    routed_systems = resolve_structured_systems(metadata, config)
    has_structured_value = any(
        metadata.get(field, "")
        for field in config.get("structured_routing", {}).get("fields", [])
    )
    if has_structured_value and not routed_systems:
        return {
            "status": "needs_review",
            "path": config["fallback_path"],
            "reason": "已有 Revit 主類別，但尚未建立對應系統",
            "routed_systems": [],
            "matches": [],
        }

    candidate_rules = [
        rule
        for rule in config["rules"]
        if not routed_systems or rule["system"] in routed_systems
    ]
    evaluations = [
        evaluation
        for evaluation in (evaluate_rule(metadata, rule) for rule in candidate_rules)
        if evaluation["score"] > 0
    ]

    if not evaluations:
        return {
            "status": "needs_review",
            "path": config["fallback_path"],
            "reason": "沒有命中任何規則",
            "matches": [],
        }

    evaluations.sort(key=lambda item: item["score"], reverse=True)
    best = evaluations[0]
    tied = [item for item in evaluations if item["score"] == best["score"]]

    if len(tied) > 1:
        return {
            "status": "needs_review",
            "path": config["fallback_path"],
            "reason": "多個規則同分，需人工確認",
            "matches": tied,
        }

    if best["score"] >= config["thresholds"]["auto_classify"]:
        return {
            "status": "classified",
            "path": best["path"],
            "system": best["system"],
            "score": best["score"],
            "routed_systems": routed_systems,
            "matched": best["matched"],
            "matches": evaluations,
        }

    if best["score"] >= config["thresholds"]["suggest_review"]:
        return {
            "status": "suggest_review",
            "path": best["path"],
            "system": best["system"],
            "score": best["score"],
            "routed_systems": routed_systems,
            "matched": best["matched"],
            "reason": "信心不足，建議人工確認",
            "matches": evaluations,
        }

    return {
        "status": "needs_review",
        "path": config["fallback_path"],
        "reason": "分數過低，需人工確認",
        "matches": evaluations,
    }


if __name__ == "__main__":
    sample = {
        "file_name": "Smoke Detector Ceiling.rfa",
        "family_name": "煙霧偵測器",
        "type_name": "天花型",
        "revit_category": "Fire Alarm Devices",
    }
    print(json.dumps(classify(sample), ensure_ascii=False, indent=2))
