import argparse
import csv
import json
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path


def find_accoreconsole() -> Path:
    candidate = shutil.which("accoreconsole.exe")
    if candidate:
        return Path(candidate)
    root = Path(r"C:\Program Files\Autodesk")
    matches = sorted(root.glob("AutoCAD *\\accoreconsole.exe"), reverse=True)
    if matches:
        return matches[0]
    raise RuntimeError("找不到 AutoCAD Core Console")


def inspect_dwg_paths(dwg_path: str | Path, timeout_seconds: int = 60) -> dict:
    source = Path(dwg_path)
    if not source.is_file() or source.suffix.lower() != ".dwg":
        raise ValueError(f"找不到 DWG：{source}")

    with tempfile.TemporaryDirectory(prefix="sc_dwg_paths_") as raw_temp:
        temp_dir = Path(raw_temp)
        local_dwg = temp_dir / "input.dwg"
        lisp_path = temp_dir / "export_paths.lsp"
        script_path = temp_dir / "run.scr"
        output_path = temp_dir / "paths.tsv"
        shutil.copy2(source, local_dwg)
        lisp_path.write_text(_render_lisp(), encoding="ascii")
        script_path.write_text(
            '(setvar "SECURELOAD" 0)\n'
            f'(load "{_acad_path(lisp_path)}")\n'
            '(if (not SC_EXPORT_PATHS) (princ "\\nSC_LOAD_FAILED\\n"))\n'
            f'(SC_EXPORT_PATHS "{_acad_path(output_path)}")\n'
            '_.QUIT\n',
            encoding="ascii",
        )
        completed = subprocess.run(
            [str(find_accoreconsole()), "/i", str(local_dwg), "/s", str(script_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, min(timeout_seconds, 120)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not output_path.exists():
            raise RuntimeError(
                "AutoCAD Core Console 無法抽取 DWG 路徑。\n"
                + (completed.stdout or "")[-2000:]
                + (completed.stderr or "")[-2000:]
            )
        return _read_output(source, output_path)


def _read_output(source: Path, output_path: Path) -> dict:
    raw = output_path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp950", errors="replace")
    lines = text.splitlines()
    metadata: dict[str, object] = {}
    rows: list[dict] = []
    data_lines: list[str] = []
    for line in lines:
        if line.startswith("#INSUNITS\t"):
            metadata["unit_code"] = int(line.split("\t", 1)[1])
        elif line.startswith("#EXTMIN\t"):
            metadata["extmin"] = _parse_xyz(line)
        elif line.startswith("#EXTMAX\t"):
            metadata["extmax"] = _parse_xyz(line)
        elif line.strip():
            data_lines.append(line)
    if data_lines:
        for row in csv.DictReader(data_lines, delimiter="\t"):
            try:
                rows.append(
                    {
                        "entity_type": row.get("entity_type") or "",
                        "layer": row.get("layer") or "",
                        "handle": row.get("handle") or "",
                        "start": [float(row["x1"]), float(row["y1"]), float(row["z1"])],
                        "end": [float(row["x2"]), float(row["y2"]), float(row["z2"])],
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    layer_counts = Counter(str(row["layer"]) for row in rows)
    type_counts = Counter(str(row["entity_type"]) for row in rows)
    return {
        "dwg_path": str(source),
        **metadata,
        "segment_count": len(rows),
        "entity_type_counts": dict(type_counts.most_common()),
        "layer_counts": [
            {"layer": layer, "segment_count": count}
            for layer, count in layer_counts.most_common()
        ],
        "segments": rows,
    }


def _parse_xyz(line: str) -> list[float]:
    values = line.split("\t")[1:4]
    return [float(value) for value in values]


def _acad_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _render_lisp() -> str:
    return r'''
(defun SC-DXF (code data defaultValue / pair)
  (setq pair (assoc code data))
  (if pair (cdr pair) defaultValue)
)

(defun SC-POINT (point elevation)
  (list (car point) (cadr point) (if (caddr point) (caddr point) elevation))
)

(defun SC-XYZ (point)
  (strcat (rtos (car point) 2 10) "\t" (rtos (cadr point) 2 10) "\t" (rtos (caddr point) 2 10))
)

(defun SC-SAFE (value)
  (vl-string-translate "\t\r\n" "   " (vl-princ-to-string value))
)

(defun SC-WRITE (fh kind layer handle p1 p2)
  (write-line
    (strcat kind "\t" (SC-SAFE layer) "\t" (SC-SAFE handle) "\t" (SC-XYZ p1) "\t" (SC-XYZ p2))
    fh
  )
)

(defun SC-LWPOINTS (data elevation / result pair)
  (setq result '())
  (foreach pair data
    (if (= (car pair) 10)
      (setq result (append result (list (SC-POINT (cdr pair) elevation))))
    )
  )
  result
)

(defun SC-WRITE-PATH (fh entity / data kind layer handle p1 p2 points previous current flags elevation center radius a1 a2 span parts index)
  (setq data (entget entity))
  (setq kind (SC-DXF 0 data ""))
  (setq layer (SC-DXF 8 data ""))
  (setq handle (SC-DXF 5 data ""))
  (cond
    ((= kind "LINE")
      (SC-WRITE fh kind layer handle (SC-DXF 10 data '(0.0 0.0 0.0)) (SC-DXF 11 data '(0.0 0.0 0.0)))
    )
    ((= kind "LWPOLYLINE")
      (setq elevation (SC-DXF 38 data 0.0))
      (setq points (SC-LWPOINTS data elevation))
      (setq previous nil)
      (foreach current points
        (if previous (SC-WRITE fh kind layer handle previous current))
        (setq previous current)
      )
      (setq flags (SC-DXF 70 data 0))
      (if (and (> (length points) 2) (= (logand flags 1) 1))
        (SC-WRITE fh kind layer handle (car (last points)) (car points))
      )
    )
    ((= kind "ARC")
      (setq center (SC-DXF 10 data '(0.0 0.0 0.0)))
      (setq radius (SC-DXF 40 data 0.0))
      (setq a1 (SC-DXF 50 data 0.0))
      (setq a2 (SC-DXF 51 data 0.0))
      (if (< a2 a1) (setq a2 (+ a2 (* 2.0 pi))))
      (setq span (- a2 a1))
      (setq parts (max 1 (fix (+ 0.999 (/ span (/ pi 18.0))))))
      (setq index 0)
      (setq previous (polar center a1 radius))
      (while (< index parts)
        (setq index (+ index 1))
        (setq current (polar center (+ a1 (* span (/ index parts))) radius))
        (SC-WRITE fh kind layer handle (SC-POINT previous (caddr center)) (SC-POINT current (caddr center)))
        (setq previous current)
      )
    )
  )
)

(defun SC_EXPORT_PATHS (outputPath / fh ss index entity)
  (setq fh (open outputPath "w"))
  (write-line (strcat "#INSUNITS\t" (itoa (getvar "INSUNITS"))) fh)
  (write-line (strcat "#EXTMIN\t" (SC-XYZ (getvar "EXTMIN"))) fh)
  (write-line (strcat "#EXTMAX\t" (SC-XYZ (getvar "EXTMAX"))) fh)
  (write-line "entity_type\tlayer\thandle\tx1\ty1\tz1\tx2\ty2\tz2" fh)
  (setq ss (ssget "_X" '((0 . "LINE,LWPOLYLINE,ARC"))))
  (if ss
    (progn
      (setq index 0)
      (while (< index (sslength ss))
        (setq entity (ssname ss index))
        (SC-WRITE-PATH fh entity)
        (setq index (+ index 1))
      )
    )
  )
  (close fh)
  (princ)
)
'''


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect LINE/LWPOLYLINE/ARC paths in a DWG without modifying it.")
    parser.add_argument("dwg")
    parser.add_argument("--output")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    result = inspect_dwg_paths(args.dwg)
    if args.summary_only:
        result = {key: value for key, value in result.items() if key != "segments"}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
