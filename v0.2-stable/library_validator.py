from pathlib import Path
from typing import Dict, List


REQUIRED_PATHS = [
    "01 機電",
    "01 機電\\01 HVAC 空調",
    "01 機電\\02 PLB 給排水",
    "01 機電\\03 FP 消防",
    "01 機電\\04 PWR 動力",
    "01 機電\\05 LTG 照明",
    "01 機電\\06 ELV 弱電",
    "02 土建",
    "03 管理區",
    "03 管理區\\03 無法自動分類",
    "03 管理區\\05 專案回收族群",
]


def validate_library_root(raw_path: str) -> Dict[str, object]:
    if not raw_path or not raw_path.strip():
        return {
            "valid": False,
            "error": "尚未選擇資料夾",
            "missing_paths": REQUIRED_PATHS,
        }

    root = Path(raw_path).expanduser()

    if not root.exists():
        return {
            "valid": False,
            "error": "指定路徑不存在",
            "missing_paths": REQUIRED_PATHS,
        }

    if not root.is_dir():
        return {
            "valid": False,
            "error": "指定路徑不是資料夾",
            "missing_paths": REQUIRED_PATHS,
        }

    missing_paths: List[str] = [
        relative_path
        for relative_path in REQUIRED_PATHS
        if not (root / relative_path).is_dir()
    ]

    if missing_paths:
        return {
            "valid": False,
            "error": "選取的資料夾不是有效的族群庫根目錄",
            "missing_paths": missing_paths,
        }

    return {
        "valid": True,
        "root": str(root.resolve()),
        "missing_paths": [],
    }
