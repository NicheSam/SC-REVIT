import json
import time

from queue_protocol import (
    ERROR_DIR,
    RESPONSE_DIR,
    create_add_parameters_request,
    create_set_string_values_request,
    ensure_queue_dirs,
)
from rfa_reader import RfaReaderError, validate_rfa_path


def request_add_missing_string_parameters(
    raw_path: str,
    parameter_names: list[str],
    timeout_seconds: int = 120,
) -> dict:
    rfa_path = validate_rfa_path(raw_path)
    ensure_queue_dirs()
    request = create_add_parameters_request(
        str(rfa_path),
        [{"name": name} for name in parameter_names],
    )
    output_path = RESPONSE_DIR / f"{request.request_id}.json"
    error_path = ERROR_DIR / f"{request.request_id}.json"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if output_path.exists():
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            output_path.unlink(missing_ok=True)
            return payload
        if error_path.exists():
            payload = json.loads(error_path.read_text(encoding="utf-8"))
            error_path.unlink(missing_ok=True)
            raise RfaReaderError(payload.get("error", "新增參數失敗"))
        time.sleep(0.5)
    raise RfaReaderError("等待 Revit 新增參數逾時")


def request_set_string_parameter_values(
    raw_path: str,
    values: dict[str, str],
    timeout_seconds: int = 120,
) -> dict:
    rfa_path = validate_rfa_path(raw_path)
    ensure_queue_dirs()
    request = create_set_string_values_request(str(rfa_path), values)
    output_path = RESPONSE_DIR / f"{request.request_id}.json"
    error_path = ERROR_DIR / f"{request.request_id}.json"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if output_path.exists():
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            output_path.unlink(missing_ok=True)
            return payload
        if error_path.exists():
            payload = json.loads(error_path.read_text(encoding="utf-8"))
            error_path.unlink(missing_ok=True)
            raise RfaReaderError(payload.get("error", "寫入參數值失敗"))
        time.sleep(0.5)
    raise RfaReaderError("等待 Revit 寫入參數值逾時")
