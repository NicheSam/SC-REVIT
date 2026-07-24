from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from .agent_tools import AGENT_TOOL_SCHEMAS, DrainageAgentTools


def dispatch(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    tools: DrainageAgentTools | None = None,
) -> dict[str, Any]:
    _validate_arguments(tool_name, arguments)
    adapter = tools or DrainageAgentTools()
    if tool_name == "drainage.get_context":
        return adapter.get_context()
    if tool_name == "drainage.inspect_current_selection":
        return adapter.inspect_current_selection()
    if tool_name == "drainage.search_targets":
        return adapter.search_targets(arguments)
    if tool_name == "drainage.recommend_configuration":
        return adapter.recommend_configuration(arguments)
    if tool_name == "drainage.connect_to_main":
        return adapter.connect_to_main(arguments)
    if tool_name == "drainage.preview":
        return adapter.preview(arguments)
    if tool_name == "drainage.clear_preview":
        return adapter.clear_preview(arguments)
    if tool_name == "drainage.request_human_confirmation":
        return adapter.request_human_confirmation(arguments)
    if tool_name == "drainage.commit_confirmed_snapshot":
        return adapter.commit_confirmed_snapshot(arguments)
    if tool_name == "drainage.get_operation":
        return adapter.get_operation(str(arguments.get("operation_id") or ""))
    if tool_name == "drainage.validate_operation":
        return adapter.validate_operation(arguments)
    raise ValueError("unsupported drainage agent tool: " + tool_name)


def _validate_arguments(tool_name: str, arguments: dict[str, Any]) -> None:
    definition = AGENT_TOOL_SCHEMAS.get(tool_name)
    if definition is None:
        raise ValueError("unsupported drainage agent tool: " + tool_name)
    schema = definition["input_schema"]
    properties = schema.get("properties", {})
    unknown = set(arguments) - set(properties)
    if schema.get("additionalProperties") is False and unknown:
        raise ValueError("unexpected arguments: " + ", ".join(sorted(unknown)))
    missing = set(schema.get("required", [])) - set(arguments)
    if missing:
        raise ValueError("missing arguments: " + ", ".join(sorted(missing)))
    for name, value in arguments.items():
        rule = properties.get(name)
        if rule:
            _validate_value(name, value, rule)


def _validate_value(name: str, value: Any, rule: dict[str, Any]) -> None:
    if "oneOf" in rule:
        matches = 0
        last_error = ""
        for variant in rule["oneOf"]:
            try:
                _validate_value(name, value, variant)
                matches += 1
            except ValueError as exc:
                last_error = str(exc)
        if matches != 1:
            raise ValueError(
                name
                + " must match exactly one schema variant"
                + (": " + last_error if last_error else "")
            )
        return
    expected_type = rule.get("type")
    if isinstance(expected_type, list):
        for allowed_type in expected_type:
            try:
                _validate_value(
                    name,
                    value,
                    {
                        **rule,
                        "type": allowed_type,
                    },
                )
                return
            except ValueError:
                continue
        raise ValueError(name + " has an invalid type")
    if expected_type == "string" and not isinstance(value, str):
        raise ValueError(name + " must be a string")
    if expected_type == "integer" and (
        not isinstance(value, int) or isinstance(value, bool)
    ):
        raise ValueError(name + " must be an integer")
    if expected_type == "number" and (
        not isinstance(value, (int, float)) or isinstance(value, bool)
    ):
        raise ValueError(name + " must be a number")
    if expected_type == "array" and not isinstance(value, list):
        raise ValueError(name + " must be an array")
    if expected_type == "object" and not isinstance(value, dict):
        raise ValueError(name + " must be an object")
    if expected_type == "boolean" and not isinstance(value, bool):
        raise ValueError(name + " must be a boolean")
    if expected_type == "null" and value is not None:
        raise ValueError(name + " must be null")
    if "minLength" in rule and len(value) < rule["minLength"]:
        raise ValueError(name + " is too short")
    if "minimum" in rule and value < rule["minimum"]:
        raise ValueError(name + " is below minimum")
    if "maximum" in rule and value > rule["maximum"]:
        raise ValueError(name + " is above maximum")
    if "enum" in rule and value not in rule["enum"]:
        raise ValueError(name + " is not an allowed value")
    if "const" in rule and value != rule["const"]:
        raise ValueError(name + " must equal the required constant")
    if "pattern" in rule and re.search(rule["pattern"], value) is None:
        raise ValueError(name + " has an invalid format")
    if expected_type == "array":
        if len(value) < rule.get("minItems", 0):
            raise ValueError(name + " has too few items")
        item_rule = rule.get("items", {})
        for index, item in enumerate(value):
            _validate_value(f"{name}[{index}]", item, item_rule)
    if expected_type == "object":
        properties = rule.get("properties", {})
        unknown = set(value) - set(properties)
        if rule.get("additionalProperties") is False and unknown:
            raise ValueError(
                name + " has unexpected properties: "
                + ", ".join(sorted(unknown))
            )
        missing = set(rule.get("required", [])) - set(value)
        if missing:
            raise ValueError(
                name + " is missing properties: "
                + ", ".join(sorted(missing))
            )
        for child_name, child_value in value.items():
            child_rule = properties.get(child_name)
            if child_rule:
                _validate_value(
                    name + "." + child_name,
                    child_value,
                    child_rule,
                )


def _error_code(exc: Exception) -> str:
    match = re.search(r"(?:^|:\s*)([A-Z][A-Z0-9_]{2,})(?:[:\s]|$)", str(exc))
    return match.group(1) if match else "AGENT_TOOL_ERROR"


def _is_retryable(exc: Exception) -> bool:
    return type(exc).__name__ in {
        "RevitQueueTimeoutError",
        "TimeoutError",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Typed Agent gateway for SC Revit drainage operations."
    )
    parser.add_argument("tool_name", nargs="?")
    parser.add_argument("--arguments-json", default="{}")
    parser.add_argument("--describe", action="store_true")
    options = parser.parse_args(argv)
    try:
        if options.describe:
            result: Any = AGENT_TOOL_SCHEMAS
        else:
            if not options.tool_name:
                parser.error("tool_name is required unless --describe is used")
            arguments = json.loads(options.arguments_json)
            if not isinstance(arguments, dict):
                raise ValueError("arguments JSON must be an object")
            result = dispatch(options.tool_name, arguments)
            result = {
                "contract_version": "1.3.0",
                "status": "ok",
                "tool_name": options.tool_name,
                "result": result,
            }
        json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        json.dump(
            {
                "contract_version": "1.3.0",
                "status": "error",
                "tool_name": options.tool_name or "",
                "error": {
                    "code": _error_code(exc),
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "retryable": _is_retryable(exc),
                },
            },
            sys.stderr,
            ensure_ascii=False,
            sort_keys=True,
        )
        sys.stderr.write("\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
