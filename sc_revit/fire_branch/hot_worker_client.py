from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .hot_analysis import build_preview_summary


def _resolve_project_root() -> Path | None:
    candidates: list[Path] = []
    configured_root = os.environ.get("SC_REVIT_HOME", "").strip()
    if configured_root:
        candidates.append(Path(configured_root))
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        candidates.extend(executable.parents[:4])
    candidates.append(Path(__file__).resolve().parents[2])
    candidates.extend([Path.cwd(), *Path.cwd().parents[:3]])

    for candidate in candidates:
        if (candidate / "sc_revit" / "fire_branch" / "hot_worker.py").is_file():
            return candidate
        marker = candidate / "development_root.txt"
        if not marker.is_file():
            continue
        try:
            marked_root = Path(marker.read_text(encoding="utf-8").strip())
        except (OSError, UnicodeError):
            continue
        if (marked_root / "sc_revit" / "fire_branch" / "hot_worker.py").is_file():
            return marked_root
    return None


def run_hot_preview_analysis(
    preview_payload: dict[str, Any],
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Run analysis in a fresh Python process so source edits apply next run."""

    project_root = _resolve_project_root()
    if project_root is None:
        result = build_preview_summary(preview_payload)
        result["reload_mode"] = "embedded"
        return result
    configured = os.environ.get("SC_REVIT_DEV_PYTHON", "").strip()
    python_path = configured or ("" if getattr(sys, "frozen", False) else sys.executable)
    if not python_path:
        python_path = shutil.which("python.exe") or shutil.which("python") or ""
    if not python_path:
        result = build_preview_summary(preview_payload)
        result["reload_mode"] = "embedded"
        return result

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    request_bytes = json.dumps(preview_payload, ensure_ascii=False).encode("utf-8")
    completed = subprocess.run(
        [python_path, "-m", "sc_revit.fire_branch.hot_worker"],
        cwd=project_root,
        input=request_bytes,
        capture_output=True,
        timeout=timeout_seconds,
        creationflags=creationflags,
        check=False,
    )
    if completed.returncode != 0:
        detail = (
            completed.stderr.decode("utf-8", errors="replace").strip()
            or completed.stdout.decode("utf-8", errors="replace").strip()
        )
        raise RuntimeError(detail or "背景分析程式沒有回傳結果。")
    result = json.loads(completed.stdout.decode("utf-8"))
    result["reload_mode"] = "fresh_process"
    return result
