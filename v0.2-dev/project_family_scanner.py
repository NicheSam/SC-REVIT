import json
import time
from pathlib import Path

from queue_protocol import (
    ERROR_DIR,
    RESPONSE_DIR,
    create_export_project_families_request,
    create_scan_project_families_request,
    ensure_queue_dirs,
)
from rfa_reader import RfaReaderError


PROJECT_RECOVERY_RELATIVE_DIR = Path("03 管理區") / "05 專案回收族群"


def get_project_recovery_dir(library_root: str | None) -> Path:
    if not library_root:
        raise RfaReaderError("尚未設定族群庫位置")
    output_dir = Path(library_root) / PROJECT_RECOVERY_RELATIVE_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def request_project_family_scan(timeout_seconds: int = 120) -> dict:
    ensure_queue_dirs()
    request = create_scan_project_families_request()
    output_path = RESPONSE_DIR / f"{request.request_id}.json"
    error_path = ERROR_DIR / f"{request.request_id}.json"
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        if output_path.exists():
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            output_path.unlink(missing_ok=True)
            return payload
        if error_path.exists():
            try:
                payload = json.loads(error_path.read_text(encoding="utf-8"))
                message = payload.get("error", "Revit 專案族群掃描失敗")
            except json.JSONDecodeError:
                message = "Revit 專案族群掃描失敗"
            error_path.unlink(missing_ok=True)
            raise RfaReaderError(message)
        time.sleep(0.5)

    raise RfaReaderError("等待 Revit 回傳專案族群清單逾時")


def request_project_family_export(
    family_ids: list[int | str],
    output_dir: str,
    timeout_seconds: int = 300,
) -> dict:
    ensure_queue_dirs()
    request = create_export_project_families_request(family_ids, output_dir)
    output_path = RESPONSE_DIR / f"{request.request_id}.json"
    error_path = ERROR_DIR / f"{request.request_id}.json"
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        if output_path.exists():
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            output_path.unlink(missing_ok=True)
            return payload
        if error_path.exists():
            try:
                payload = json.loads(error_path.read_text(encoding="utf-8"))
                message = payload.get("error", "Revit 專案族群匯出失敗")
            except json.JSONDecodeError:
                message = "Revit 專案族群匯出失敗"
            error_path.unlink(missing_ok=True)
            raise RfaReaderError(message)
        time.sleep(0.5)

    raise RfaReaderError("等待 Revit 匯出專案族群逾時")
