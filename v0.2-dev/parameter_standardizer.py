import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).parent
TEMPLATE_DIR = BASE_DIR / "parameter_templates"


def load_templates_for_system(system: str | None) -> list[dict[str, Any]]:
    templates = []
    common = TEMPLATE_DIR / "common.json"
    if common.exists():
        templates.append(json.loads(common.read_text(encoding="utf-8")))
    if system:
        system_template = TEMPLATE_DIR / f"{system}.json"
        if system_template.exists():
            templates.append(json.loads(system_template.read_text(encoding="utf-8")))
    return templates


def build_parameter_preview(
    existing_parameters: list[str],
    system: str | None,
    parameter_details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    existing = set(existing_parameters)
    templates = load_templates_for_system(system)
    expected = [
        parameter
        for template in templates
        for parameter in template.get("parameters", [])
    ]
    missing = [
        parameter
        for parameter in expected
        if parameter["name"] not in existing
    ]
    present = [
        parameter
        for parameter in expected
        if parameter["name"] in existing
    ]
    detail_by_name = {
        detail.get("name"): detail
        for detail in (parameter_details or [])
        if detail.get("name")
    }
    mismatches = []
    for parameter in present:
        detail = detail_by_name.get(parameter["name"])
        if not detail:
            continue
        expected_kind = parameter.get("expected_kind")
        actual_kind = "instance" if detail.get("is_instance") else "type"
        expected_storage_type = parameter.get("expected_storage_type")
        if expected_kind and expected_kind != actual_kind:
            mismatches.append(
                {
                    "name": parameter["name"],
                    "issue": "參數層級",
                    "expected": expected_kind,
                    "actual": actual_kind,
                }
            )
        if expected_storage_type and expected_storage_type != detail.get("storage_type"):
            mismatches.append(
                {
                    "name": parameter["name"],
                    "issue": "儲存型別",
                    "expected": expected_storage_type,
                    "actual": detail.get("storage_type"),
                }
            )
    mismatch_names = {item["name"] for item in mismatches}
    actions = {
        "add": [
            {
                "name": item["name"],
                "reason": "缺少標準參數",
                "required": item.get("required", False),
            }
            for item in missing
        ],
        "modify": [
            {
                "name": item["name"],
                "reason": item["issue"],
                "expected": item["expected"],
                "actual": item["actual"],
            }
            for item in mismatches
        ],
        "keep": [
            {
                "name": item["name"],
                "reason": "已符合模板",
            }
            for item in present
            if item["name"] not in mismatch_names
        ],
    }
    actions["safe_add"] = [
        item
        for item in missing
        if item.get("expected_kind") == "type"
        and item.get("expected_storage_type") == "String"
        and str(item.get("name", "")).startswith("SC_")
    ]
    return {
        "templates": [template["template_name"] for template in templates],
        "existing_count": len(existing_parameters),
        "parameter_details": parameter_details or [],
        "missing": missing,
        "present": present,
        "mismatches": mismatches,
        "actions": actions,
    }
