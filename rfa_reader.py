import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
from queue_protocol import create_request, ensure_queue_dirs


BASE_DIR = Path(__file__).parent
BRIDGE_DIR = BASE_DIR / "revit_bridge"
BRIDGE_EXE = BRIDGE_DIR / "bin" / "RfaMetadataBridge.exe"
ADDIN_OUTPUT_CONTRACT = {
    "file_name",
    "family_name",
    "revit_category",
    "family_types",
    "family_parameters",
    "family_parameter_details",
}


class RfaReaderError(RuntimeError):
    pass


@dataclass(frozen=True)
class RfaMetadata:
    file_name: str
    family_name: str
    revit_category: str
    family_types: list[str]
    family_parameters: list[str]
    family_parameter_details: list[dict[str, Any]]

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "RfaMetadata":
        return cls(
            file_name=payload.get("file_name", ""),
            family_name=payload.get("family_name", ""),
            revit_category=payload.get("revit_category", ""),
            family_types=list(payload.get("family_types", [])),
            family_parameters=list(payload.get("family_parameters", [])),
            family_parameter_details=list(payload.get("family_parameter_details", [])),
        )

    def to_classifier_metadata(self) -> Dict[str, Any]:
        return {
            "file_name": self.file_name,
            "family_name": self.family_name,
            "type_name": " ".join(self.family_types),
            "revit_category": self.revit_category,
            "notes": " ".join(self.family_parameters),
        }


def validate_rfa_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.exists():
        raise RfaReaderError("指定的 RFA 檔案不存在")
    if not path.is_file():
        raise RfaReaderError("指定路徑不是檔案")
    if path.suffix.casefold() != ".rfa":
        raise RfaReaderError("指定檔案不是 .rfa")
    return path


def read_rfa_metadata(raw_path: str, bridge_exe: Path = BRIDGE_EXE) -> RfaMetadata:
    rfa_path = validate_rfa_path(raw_path)

    if not bridge_exe.exists():
        raise RfaReaderError(
            "尚未找到 RFA 讀取橋接器，請先建置 revit_bridge 模組"
        )

    completed = subprocess.run(
        [str(bridge_exe), str(rfa_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    if completed.returncode != 0:
        message = completed.stderr.strip() or "RFA 讀取橋接器執行失敗"
        raise RfaReaderError(message)

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RfaReaderError("RFA 讀取橋接器回傳了無效 JSON") from exc

    return RfaMetadata.from_dict(payload)


def read_metadata_from_json(raw_path: str) -> RfaMetadata:
    json_path = Path(raw_path)
    if not json_path.exists():
        raise RfaReaderError("指定的 JSON 檔案不存在")
    if not json_path.is_file():
        raise RfaReaderError("指定路徑不是 JSON 檔案")

    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RfaReaderError("RFA 中繼資料 JSON 格式錯誤") from exc

    missing = sorted(ADDIN_OUTPUT_CONTRACT - set(payload.keys()))
    if missing:
        raise RfaReaderError("RFA 中繼資料缺少必要欄位：" + ", ".join(missing))

    return RfaMetadata.from_dict(payload)


def request_metadata_from_revit(raw_path: str, timeout_seconds: int = 120) -> RfaMetadata:
    from sc_revit.core.revit_queue_client import wait_for_revit_response

    rfa_path = validate_rfa_path(raw_path)
    ensure_queue_dirs()
    request = create_request(str(rfa_path))
    payload = wait_for_revit_response(
        request.request_id,
        timeout_seconds,
        failure_message="Revit 讀取失敗",
        timeout_message=(
            "等待 Revit 回傳 RFA 中繼資料逾時；請確認 Revit 已開啟、"
            "外掛已安裝，且重新啟動 Revit 後再試"
        ),
    )
    missing = sorted(ADDIN_OUTPUT_CONTRACT - set(payload.keys()))
    if missing:
        raise RfaReaderError("RFA 中繼資料缺少必要欄位：" + ", ".join(missing))
    return RfaMetadata.from_dict(payload)
