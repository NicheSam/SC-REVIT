from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, TextIO

from .agent_cli import (
    _error_code,
    _is_retryable,
    _validate_arguments,
    _validate_value,
    dispatch,
)
from .agent_tools import AGENT_TOOL_SCHEMAS, DrainageAgentTools


PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {
    "2025-06-18",
}
SERVER_NAME = "sc-revit-drainage"
SERVER_VERSION = "1.3.0"


@dataclass
class McpSession:
    initialize_seen: bool = False
    initialized: bool = False
    negotiated_version: str = ""


def _tool_annotations(
    name: str,
    definition: dict[str, Any],
) -> dict[str, bool]:
    risk = str(definition.get("risk") or "")
    return {
        "readOnlyHint": risk == "readOnly",
        "destructiveHint": (
            name == "drainage.commit_confirmed_snapshot"
        ),
        "idempotentHint": (
            risk == "readOnly"
            or name == "drainage.commit_confirmed_snapshot"
        ),
        "openWorldHint": False,
    }


def _list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": str(
                definition.get("description")
                or "SC Revit drainage workflow tool."
            ),
            "inputSchema": definition["input_schema"],
            "outputSchema": definition["output_schema"],
            "annotations": _tool_annotations(name, definition),
        }
        for name, definition in AGENT_TOOL_SCHEMAS.items()
    ]


def handle_message(
    message: dict[str, Any],
    *,
    tools: DrainageAgentTools | None = None,
    session: McpSession | None = None,
) -> dict[str, Any] | None:
    active_session = session or McpSession()
    method = str(message.get("method") or "")
    request_id = message.get("id")
    if method == "notifications/initialized":
        if active_session.initialize_seen:
            active_session.initialized = True
        return None
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        parameters = message.get("params") or {}
        if not isinstance(parameters, dict):
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": "initialize params must be an object.",
                },
            }
        requested_version = str(
            parameters.get("protocolVersion") or ""
        )
        negotiated_version = (
            requested_version
            if requested_version in SUPPORTED_PROTOCOL_VERSIONS
            else PROTOCOL_VERSION
        )
        active_session.initialize_seen = True
        active_session.initialized = False
        active_session.negotiated_version = negotiated_version
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": negotiated_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if not active_session.initialized:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32002,
                "message": (
                    "MCP session is not initialized; call initialize "
                    "and send notifications/initialized first."
                ),
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": _list_tools()},
        }
    if method == "tools/call":
        parameters = message.get("params") or {}
        if not isinstance(parameters, dict):
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": "tools/call params must be an object.",
                },
            }
        tool_name = str(parameters.get("name") or "")
        arguments = parameters.get("arguments") or {}
        if not isinstance(arguments, dict):
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": "tool arguments must be an object.",
                },
            }
        if tool_name not in AGENT_TOOL_SCHEMAS:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": "Unknown tool: " + tool_name,
                },
            }
        try:
            _validate_arguments(tool_name, arguments)
        except ValueError as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": str(exc),
                },
            }
        try:
            result = {
                "contract_version": SERVER_VERSION,
                "status": "ok",
                "tool_name": tool_name,
                "result": dispatch(
                    tool_name,
                    arguments,
                    tools=tools,
                ),
            }
            _validate_value(
                "structuredContent",
                result,
                AGENT_TOOL_SCHEMAS[tool_name]["output_schema"],
            )
            serialized = json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
            )
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": serialized}],
                    "structuredContent": result,
                    "isError": False,
                },
            }
        except Exception as exc:
            error = {
                "contract_version": SERVER_VERSION,
                "status": "error",
                "tool_name": tool_name,
                "error": {
                    "code": _error_code(exc),
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "retryable": _is_retryable(exc),
                },
            }
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                error,
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        }
                    ],
                    "structuredContent": error,
                    "isError": True,
                },
            }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32601,
            "message": "Method not found: " + method,
        },
    }


def serve(
    source: TextIO = sys.stdin,
    sink: TextIO = sys.stdout,
) -> None:
    session = McpSession()
    for line in source:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": "Parse error: " + str(exc),
                },
            }
        else:
            if not isinstance(message, dict):
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32600,
                        "message": "Invalid Request: expected a JSON object.",
                    },
                }
            else:
                try:
                    response = handle_message(
                        message,
                        session=session,
                    )
                except Exception as exc:
                    response = {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "error": {
                            "code": -32603,
                            "message": (
                                "Internal error: "
                                + type(exc).__name__
                            ),
                        },
                    }
        if response is None:
            continue
        sink.write(
            json.dumps(
                response,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
        sink.flush()


def main() -> int:
    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
