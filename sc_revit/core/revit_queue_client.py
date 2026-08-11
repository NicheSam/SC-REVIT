import json
import time
from typing import Any

from queue_protocol import ERROR_DIR, RESPONSE_DIR, ensure_queue_dirs, finish_gui_request
from sc_revit.core.batch import record_request_failed, record_request_succeeded
from rfa_reader import RfaReaderError


class RevitQueueTimeoutError(RfaReaderError):
    pass


def _format_revit_error(payload: dict[str, Any], fallback: str) -> str:
    message = str(payload.get("error") or fallback)
    details = list(payload.get("failure_details") or [])
    if not details:
        return message
    lines = [message, "", "Connection failure details:"]
    for item in details[:12]:
        if not isinstance(item, dict):
            lines.append(str(item))
            continue
        target = item.get("sprinkler_id")
        if target is None:
            target = item.get("row", "-")
        reason = item.get("reason", "unknown")
        detail = item.get("detail")
        line = f"{target}: {reason}"
        if detail:
            line += f" | {detail}"
        unconnected_sprinklers = list(item.get("unconnected_sprinkler_ids") or [])
        unconnected_pipes = list(item.get("unconnected_pipe_ids") or [])
        wrong_system_sprinklers = list(item.get("wrong_system_sprinkler_ids") or [])
        wrong_system_pipes = list(item.get("wrong_system_pipe_ids") or [])
        missing_system_pipes = list(item.get("missing_system_pipe_ids") or [])
        missing_connector_sprinklers = list(item.get("missing_connector_sprinkler_ids") or [])
        missing_system_sprinklers = list(item.get("missing_system_sprinkler_ids") or [])
        actual_system_types = list(item.get("actual_system_type_ids") or [])
        system_change_failures = list(item.get("system_change_failures") or [])
        if unconnected_sprinklers:
            line += " | unconnected sprinklers=" + ",".join(map(str, unconnected_sprinklers))
        if unconnected_pipes:
            line += " | unconnected pipes=" + ",".join(map(str, unconnected_pipes))
        if wrong_system_sprinklers:
            line += " | wrong-system sprinklers=" + ",".join(map(str, wrong_system_sprinklers))
        if wrong_system_pipes:
            line += " | wrong-system pipes=" + ",".join(map(str, wrong_system_pipes))
        if missing_system_pipes:
            line += " | missing-system pipes=" + ",".join(map(str, missing_system_pipes))
        if missing_connector_sprinklers:
            line += " | missing-connector sprinklers=" + ",".join(map(str, missing_connector_sprinklers))
        if missing_system_sprinklers:
            line += " | missing-system sprinklers=" + ",".join(map(str, missing_system_sprinklers))
        if actual_system_types:
            line += " | actual system types=" + ",".join(map(str, actual_system_types))
        if system_change_failures:
            line += " | system-change failures=" + json.dumps(
                system_change_failures,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        lines.append(line)
    if len(details) > 12:
        lines.append(f"... and {len(details) - 12} more failures")
    return "\n".join(lines)


def wait_for_revit_response(
    request_id: str,
    timeout_seconds: int,
    *,
    failure_message: str = "Revit 請求失敗",
    timeout_message: str = "等待 Revit 回傳資料逾時",
) -> dict[str, Any]:
    """Wait for one queue response from the Revit add-in.

    This is the shared boundary between Python modules and the C# Revit listener.
    Domain modules should create requests, then call this function instead of
    duplicating queue polling logic.
    """
    ensure_queue_dirs()
    output_path = RESPONSE_DIR / f"{request_id}.json"
    error_path = ERROR_DIR / f"{request_id}.json"
    deadline = time.time() + timeout_seconds

    try:
        while time.time() < deadline:
            if output_path.exists():
                payload = json.loads(output_path.read_text(encoding="utf-8"))
                output_path.unlink(missing_ok=True)
                record_request_succeeded(request_id, payload)
                return payload
            if error_path.exists():
                try:
                    payload = json.loads(error_path.read_text(encoding="utf-8"))
                    message = _format_revit_error(payload, failure_message)
                except json.JSONDecodeError:
                    message = failure_message
                error_path.unlink(missing_ok=True)
                record_request_failed(request_id, message)
                raise RfaReaderError(message)
            time.sleep(0.5)

        record_request_failed(request_id, timeout_message)
        raise RevitQueueTimeoutError(timeout_message)
    finally:
        finish_gui_request(request_id)
