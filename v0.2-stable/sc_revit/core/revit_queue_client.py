import json
import time
from typing import Any

from queue_protocol import ERROR_DIR, RESPONSE_DIR, ensure_queue_dirs
from rfa_reader import RfaReaderError


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

    while time.time() < deadline:
        if output_path.exists():
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            output_path.unlink(missing_ok=True)
            return payload
        if error_path.exists():
            try:
                payload = json.loads(error_path.read_text(encoding="utf-8"))
                message = payload.get("error", failure_message)
            except json.JSONDecodeError:
                message = failure_message
            error_path.unlink(missing_ok=True)
            raise RfaReaderError(message)
        time.sleep(0.5)

    raise RfaReaderError(timeout_message)
