import shutil
from dataclasses import dataclass
from pathlib import Path

from duplicate_checker import build_available_copy_name


class IngestError(RuntimeError):
    pass


@dataclass(frozen=True)
class IngestResult:
    destination_path: Path
    final_name: str


def ingest_copy_only(
    source_path: str,
    library_root: str | None,
    relative_folder: str | None,
    planned_name: str | None,
) -> IngestResult:
    if not library_root:
        raise IngestError("尚未設定族群庫位置")
    if not relative_folder:
        raise IngestError("尚未確認入庫資料夾")
    if not planned_name:
        raise IngestError("尚未確認預計修改名稱")

    source = Path(source_path)
    if not source.exists() or not source.is_file():
        raise IngestError("來源 RFA 檔案不存在")

    root = Path(library_root)
    destination_dir = root / relative_folder
    if not destination_dir.exists() or not destination_dir.is_dir():
        raise IngestError("目標資料夾不存在")

    final_name = build_available_copy_name(
        str(root),
        planned_name,
        force_copy=any(root.rglob(planned_name)),
    )
    destination = destination_dir / final_name
    shutil.copy2(source, destination)
    return IngestResult(destination_path=destination, final_name=final_name)
