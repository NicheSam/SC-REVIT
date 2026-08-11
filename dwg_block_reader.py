import csv
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


class DwgBlockReaderError(RuntimeError):
    pass


INSUNITS_TO_FEET = {
    0: 1.0,  # Unitless: assume feet for first prototype; users can calibrate later.
    1: 1.0 / 12.0,  # Inches
    2: 1.0,  # Feet
    3: 5280.0,  # Miles
    4: 1.0 / 304.8,  # Millimeters
    5: 1.0 / 30.48,  # Centimeters
    6: 1.0 / 0.3048,  # Meters
    7: 1000.0 / 0.3048,  # Kilometers
}

INSUNITS_LABEL = {
    0: "未指定",
    1: "英吋",
    2: "英尺",
    3: "英里",
    4: "毫米",
    5: "公分",
    6: "公尺",
    7: "公里",
}


def find_accoreconsole() -> Path:
    candidate = shutil.which("accoreconsole.exe")
    if candidate:
        return Path(candidate)
    autodesk_root = Path(r"C:\Program Files\Autodesk")
    if autodesk_root.exists():
        matches = sorted(
            autodesk_root.glob("AutoCAD *\\accoreconsole.exe"),
            reverse=True,
        )
        if matches:
            return matches[0]
    raise DwgBlockReaderError("找不到 AutoCAD Core Console（accoreconsole.exe），無法直接讀取 DWG 圖塊。")


def read_dwg_blocks(dwg_path: str | Path, timeout_seconds: int = 45) -> dict:
    source = Path(dwg_path)
    timeout_seconds = min(timeout_seconds, 45)
    _write_log(f"start source={source}")
    if not source.exists():
        _write_log(f"missing source={source}")
        raise DwgBlockReaderError(f"找不到 DWG 檔案：{source}")
    if source.suffix.lower() != ".dwg":
        raise DwgBlockReaderError("請選擇 .dwg 檔案")

    accoreconsole = find_accoreconsole()
    _write_log(f"accoreconsole={accoreconsole}")
    with tempfile.TemporaryDirectory(prefix="sc_dwg_blocks_") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        local_dwg = temp_dir / "input.dwg"
        lisp_path = temp_dir / "export_blocks.lsp"
        script_path = temp_dir / "run.scr"
        output_path = temp_dir / "blocks.tsv"
        try:
            shutil.copy2(source, local_dwg)
            _write_log(f"copied source to local temp={local_dwg}")
        except Exception as exc:
            _write_log(f"copy failed: {exc}")
            raise DwgBlockReaderError(
                "無法複製 DWG 到本機暫存區。請確認網路路徑權限，或先把 DWG 複製到本機後再選取。"
            ) from exc
        lisp_path.write_text(_render_lisp(), encoding="ascii")
        script_path.write_text(
            '(setvar "SECURELOAD" 0)\n'
            f'(load "{_acad_path(lisp_path)}")\n'
            '(if (not SC_EXPORT_BLOCKS) (princ "\\nSC_LOAD_FAILED\\n"))\n'
            f'(SC_EXPORT_BLOCKS "{_acad_path(output_path)}")\n'
            '_.QUIT\n',
            encoding="ascii",
        )
        command = [
            str(accoreconsole),
            "/i",
            str(local_dwg),
            "/s",
            str(script_path),
        ]
        _write_log("run " + " ".join(command))
        completed = _run_with_timeout(command, timeout_seconds)
        _write_log(f"returncode={completed.returncode}")
        if completed.stdout:
            _write_log("stdout=" + completed.stdout[-2000:])
        if completed.stderr:
            _write_log("stderr=" + completed.stderr[-2000:])
        if completed.returncode != 0:
            raise DwgBlockReaderError(
                "AutoCAD Core Console 讀取 DWG 失敗。\n"
                f"returncode={completed.returncode}\n"
                f"{completed.stdout}\n{completed.stderr}"
            )
        if "SC_LOAD_FAILED" in (completed.stdout or ""):
            raise DwgBlockReaderError(
                "AutoCAD 無法載入 DWG 圖塊讀取腳本。請確認 AutoCAD 允許載入 LISP，或將外掛資料夾加入 AutoCAD 信任位置。"
            )
        if not output_path.exists():
            _write_log("output missing")
            raise DwgBlockReaderError(
                "AutoCAD 已執行，但沒有產生圖塊清單。可能是 AutoCAD 安全設定阻擋 LISP，或 DWG 開啟後沒有可讀取的 ModelSpace 圖塊。"
            )
        result = _read_tsv_output(source, output_path)
        _write_log(f"done blocks={len(result.get('blocks', []))} points={len(result.get('points', []))}")
        return result


def _run_with_timeout(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        stdout, stderr = process.communicate()
        _write_log(f"timeout after {timeout_seconds}s")
        raise DwgBlockReaderError(
            f"讀取 DWG 超過 {timeout_seconds} 秒仍未完成，已中止。\n"
            "建議先把 DWG 複製到本機資料夾，或確認 AutoCAD Core Console 可正常開啟該 DWG。"
        ) from exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _read_tsv_output(source: Path, output_path: Path) -> dict:
    lines = output_path.read_text(encoding="utf-8", errors="replace").splitlines()
    unit_code = 0
    insbase = [0.0, 0.0, 0.0]
    extmin = [0.0, 0.0, 0.0]
    extmax = [0.0, 0.0, 0.0]
    data_lines = []
    for line in lines:
        if line.startswith("#INSUNITS\t"):
            try:
                unit_code = int(line.split("\t", 1)[1])
            except ValueError:
                unit_code = 0
        elif line.startswith("#INSBASE\t"):
            insbase = _parse_coordinate_header(line)
        elif line.startswith("#EXTMIN\t"):
            extmin = _parse_coordinate_header(line)
        elif line.startswith("#EXTMAX\t"):
            extmax = _parse_coordinate_header(line)
        elif line.strip():
            data_lines.append(line)
    points = []
    if data_lines:
        reader = csv.DictReader(data_lines, delimiter="\t")
        for row in reader:
            try:
                points.append(
                    {
                        "block_name": row.get("name", ""),
                        "x": float(row.get("x") or 0),
                        "y": float(row.get("y") or 0),
                        "z": float(row.get("z") or 0),
                        "rotation_degrees": float(row.get("rotation_degrees") or 0),
                        "layer": row.get("layer", ""),
                        "handle": row.get("handle", ""),
                    }
                )
            except ValueError:
                continue
    counts: dict[str, int] = {}
    for point in points:
        name = str(point.get("block_name") or "")
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    blocks = [
        {"block_name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: item[0])
    ]
    return {
        "dwg_path": str(source),
        "unit_code": unit_code,
        "unit_name": INSUNITS_LABEL.get(unit_code, f"INSUNITS={unit_code}"),
        "unit_to_feet": INSUNITS_TO_FEET.get(unit_code, 1.0),
        "insbase": {"x": insbase[0], "y": insbase[1], "z": insbase[2]},
        "extmin": {"x": extmin[0], "y": extmin[1], "z": extmin[2]},
        "extmax": {"x": extmax[0], "y": extmax[1], "z": extmax[2]},
        "blocks": blocks,
        "points": points,
    }


def _parse_coordinate_header(line: str) -> list[float]:
    values = line.split("\t")[1:4]
    if len(values) != 3:
        return [0.0, 0.0, 0.0]
    try:
        return [float(value) for value in values]
    except ValueError:
        return [0.0, 0.0, 0.0]


def _acad_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _write_log(message: str) -> None:
    try:
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.cwd()))) / "RevitFamilyClassifier" / "runtime"
        base.mkdir(parents=True, exist_ok=True)
        line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + message + "\n"
        with (base / "dwg_reader.log").open("a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        pass


def _render_lisp() -> str:
    return r'''
(defun SC-TAB-SAFE (value / text)
  (setq text (vl-princ-to-string value))
  (setq text (vl-string-translate "\t\r\n" "   " text))
  text
)

(defun SC-DXF (code data defaultValue / pair)
  (setq pair (assoc code data))
  (if pair (cdr pair) defaultValue)
)

(defun SC-POINT-TSV (point)
  (strcat
    (rtos (car point) 2 12) "\t"
    (rtos (cadr point) 2 12) "\t"
    (rtos (caddr point) 2 12)
  )
)

(defun SC_EXPORT_BLOCKS (outputPath / fh ss index entity data point name rotation layer handle)
  (setq fh (open outputPath "w"))
  (write-line (strcat "#INSUNITS\t" (itoa (getvar "INSUNITS"))) fh)
  (write-line (strcat "#INSBASE\t" (SC-POINT-TSV (getvar "INSBASE"))) fh)
  (write-line (strcat "#EXTMIN\t" (SC-POINT-TSV (getvar "EXTMIN"))) fh)
  (write-line (strcat "#EXTMAX\t" (SC-POINT-TSV (getvar "EXTMAX"))) fh)
  (write-line "name\tx\ty\tz\trotation_degrees\tlayer\thandle" fh)
  (setq ss (ssget "_X" '((0 . "INSERT"))))
  (if ss
    (progn
      (setq index 0)
      (while (< index (sslength ss))
        (setq entity (ssname ss index))
        (setq data (entget entity))
        (setq point (SC-DXF 10 data '(0.0 0.0 0.0)))
        (setq name (SC-DXF 2 data ""))
        (setq rotation (* (/ (SC-DXF 50 data 0.0) pi) 180.0))
        (setq layer (SC-DXF 8 data ""))
        (setq handle (SC-DXF 5 data ""))
        (if (and name (/= name ""))
          (write-line
            (strcat
              (SC-TAB-SAFE name) "\t"
              (rtos (nth 0 point) 2 10) "\t"
              (rtos (nth 1 point) 2 10) "\t"
              (rtos (nth 2 point) 2 10) "\t"
              (rtos rotation 2 10) "\t"
              (SC-TAB-SAFE layer) "\t"
              (SC-TAB-SAFE handle)
            )
            fh
          )
        )
        (setq index (+ index 1))
      )
    )
  )
  (close fh)
  (princ)
)
'''
