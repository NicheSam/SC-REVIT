from pathlib import Path

from queue_protocol import (
    create_export_project_families_request,
    create_scan_project_families_request,
    ensure_queue_dirs,
)
from rfa_reader import RfaReaderError
from sc_revit.core.revit_queue_client import wait_for_revit_response


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
    return wait_for_revit_response(
        request.request_id,
        timeout_seconds,
        failure_message="Revit 專案族群掃描失敗",
        timeout_message="等待 Revit 回傳專案族群清單逾時",
    )


def request_project_family_export(
    family_ids: list[int | str],
    output_dir: str,
    timeout_seconds: int = 300,
) -> dict:
    ensure_queue_dirs()
    request = create_export_project_families_request(family_ids, output_dir)
    return wait_for_revit_response(
        request.request_id,
        timeout_seconds,
        failure_message="Revit 專案族群匯出失敗",
        timeout_message="等待 Revit 匯出專案族群逾時",
    )
