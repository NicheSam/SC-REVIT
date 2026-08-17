from __future__ import annotations

import csv
import shutil
import tempfile
from pathlib import Path

from dwg_block_reader import (
    DwgBlockReaderError,
    INSUNITS_LABEL,
    INSUNITS_TO_FEET,
    _acad_path,
    _run_with_timeout,
    find_accoreconsole,
    read_dwg_blocks,
)


_FIXED_TEXT_BLOCK_LITERALS = {
    "bt11_10": '1 1/4"',
    "bt11_15": '1 1/2"',
    "bt11_20": '2"',
    "bt11_25": '2 1/2"',
    "bt11_35": '4"',
}


def read_dwg_diameter_texts(
    dwg_path: str | Path,
    timeout_seconds: int = 45,
) -> dict:
    source = Path(dwg_path)
    if not source.exists():
        raise DwgBlockReaderError(f"DWG file does not exist: {source}")
    if source.suffix.lower() != ".dwg":
        raise DwgBlockReaderError("Diameter evidence source must be a DWG file")

    with tempfile.TemporaryDirectory(prefix="sc_fire_diameter_") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        local_dwg = temp_dir / "input.dwg"
        lisp_path = temp_dir / "export_diameter_texts.lsp"
        script_path = temp_dir / "run.scr"
        output_path = temp_dir / "diameters.tsv"
        shutil.copy2(source, local_dwg)
        lisp_path.write_text(_render_lisp(), encoding="ascii")
        script_path.write_text(
            '(setvar "SECURELOAD" 0)\n'
            f'(load "{_acad_path(lisp_path)}")\n'
            f'(SC_EXPORT_DIAMETER_TEXTS "{_acad_path(output_path)}")\n'
            '_.QUIT\n',
            encoding="ascii",
        )
        completed = _run_with_timeout(
            [str(find_accoreconsole()), "/i", str(local_dwg), "/s", str(script_path)],
            min(timeout_seconds, 45),
        )
        if completed.returncode != 0 or not output_path.exists():
            raise DwgBlockReaderError(
                "AutoCAD Core Console could not extract fire-pipe diameter text"
            )
        result = _read_text_output(output_path)
        if not result.get("complete"):
            raise DwgBlockReaderError(
                "AutoCAD Core Console returned an incomplete diameter text export"
            )
        existing_handles = {str(item.get("handle") or "") for item in result["texts"]}
        block_result = read_dwg_blocks(source, timeout_seconds=timeout_seconds)
        for point in block_result.get("points") or []:
            block_name = str(point.get("block_name") or "")
            literal = _FIXED_TEXT_BLOCK_LITERALS.get(block_name.casefold())
            handle = str(point.get("handle") or "")
            if literal is None or (handle and handle in existing_handles):
                continue
            result["texts"].append(
                {
                    "text": literal,
                    "x": float(point.get("x") or 0),
                    "y": float(point.get("y") or 0),
                    "z": float(point.get("z") or 0),
                    "color": None,
                    "layer": str(point.get("layer") or ""),
                    "handle": handle,
                    "annotation_block_name": block_name,
                }
            )
        result["block_points"] = list(block_result.get("points") or [])
        result["dwg_path"] = str(source)
        return result


def _read_text_output(output_path: Path) -> dict:
    lines = output_path.read_text(encoding="utf-8", errors="replace").splitlines()
    unit_code = 0
    complete = False
    data_lines: list[str] = []
    for line in lines:
        if line.startswith("#INSUNITS\t"):
            try:
                unit_code = int(line.split("\t", 1)[1])
            except ValueError:
                unit_code = 0
        elif line == "#COMPLETE\t1":
            complete = True
        elif line.strip():
            data_lines.append(line)

    texts: list[dict] = []
    if data_lines:
        for row in csv.DictReader(data_lines, delimiter="\t"):
            try:
                block_name = str(row.get("block_name") or "")
                text = str(row.get("text") or "")
                if not text and block_name.casefold() in _FIXED_TEXT_BLOCK_LITERALS:
                    text = _FIXED_TEXT_BLOCK_LITERALS[block_name.casefold()]
                if not text:
                    continue
                item = {
                    "text": text,
                    "x": float(row.get("x") or 0),
                    "y": float(row.get("y") or 0),
                    "z": float(row.get("z") or 0),
                    "color": int(row.get("color") or 0),
                    "layer": str(row.get("layer") or ""),
                    "handle": str(row.get("handle") or ""),
                    "annotation_block_name": block_name,
                }
                bounds_values = [
                    row.get("min_x"),
                    row.get("min_y"),
                    row.get("max_x"),
                    row.get("max_y"),
                ]
                if all(value not in (None, "") for value in bounds_values):
                    item["bounds"] = {
                        "min_x": float(bounds_values[0]),
                        "min_y": float(bounds_values[1]),
                        "max_x": float(bounds_values[2]),
                        "max_y": float(bounds_values[3]),
                    }
                direction_values = [row.get("direction_x"), row.get("direction_y")]
                if all(value not in (None, "") for value in direction_values):
                    item["direction"] = {
                        "x": float(direction_values[0]),
                        "y": float(direction_values[1]),
                    }
                texts.append(item)
            except (TypeError, ValueError):
                continue
    return {
        "unit_code": unit_code,
        "unit_name": INSUNITS_LABEL.get(unit_code, f"INSUNITS={unit_code}"),
        "unit_to_feet": INSUNITS_TO_FEET.get(unit_code, 1.0),
        "texts": texts,
        "complete": complete,
    }


def _render_lisp() -> str:
    return r'''
(vl-load-com)

(defun SC-TAB-SAFE (value / text)
  (setq text (vl-princ-to-string value))
  (setq text (vl-string-translate "\t\r\n" "   " text))
  text
)

(defun SC-DXF (code data defaultValue / pair)
  (setq pair (assoc code data))
  (if pair (cdr pair) defaultValue)
)

(defun SC-DXF-TEXT (data / result pair)
  (setq result "")
  (foreach pair data
    (if (or (= (car pair) 3) (= (car pair) 1))
      (setq result (strcat result (cdr pair)))
    )
  )
  result
)

(defun SC-RESOLVED-COLOR (data layer inheritedColor / color layerData)
  (setq color (SC-DXF 62 data 256))
  (if (= color 0)
    (setq color inheritedColor)
  )
  (if (= color 256)
    (progn
      (setq layerData (tblsearch "LAYER" layer))
      (setq color (abs (SC-DXF 62 layerData 7)))
    )
  )
  (abs color)
)

(defun SC-MAT-POINT (matrix point)
  (list
    (+ (* (nth 0 matrix) (car point)) (* (nth 1 matrix) (cadr point)) (nth 4 matrix))
    (+ (* (nth 2 matrix) (car point)) (* (nth 3 matrix) (cadr point)) (nth 5 matrix))
    (if (caddr point) (caddr point) 0.0)
  )
)

(defun SC-MAT-VECTOR (matrix vector)
  (list
    (+ (* (nth 0 matrix) (car vector)) (* (nth 1 matrix) (cadr vector)))
    (+ (* (nth 2 matrix) (car vector)) (* (nth 3 matrix) (cadr vector)))
    0.0
  )
)

(defun SC-MAT-MULTIPLY (parent local)
  (list
    (+ (* (nth 0 parent) (nth 0 local)) (* (nth 1 parent) (nth 2 local)))
    (+ (* (nth 0 parent) (nth 1 local)) (* (nth 1 parent) (nth 3 local)))
    (+ (* (nth 2 parent) (nth 0 local)) (* (nth 3 parent) (nth 2 local)))
    (+ (* (nth 2 parent) (nth 1 local)) (* (nth 3 parent) (nth 3 local)))
    (+ (* (nth 0 parent) (nth 4 local)) (* (nth 1 parent) (nth 5 local)) (nth 4 parent))
    (+ (* (nth 2 parent) (nth 4 local)) (* (nth 3 parent) (nth 5 local)) (nth 5 parent))
  )
)

(defun SC-INSERT-MATRIX (data blockData / point base sx sy angle cosine sine a b c d)
  (setq point (SC-DXF 10 data '(0.0 0.0 0.0)))
  (setq base (SC-DXF 10 blockData '(0.0 0.0 0.0)))
  (setq sx (SC-DXF 41 data 1.0))
  (setq sy (SC-DXF 42 data 1.0))
  (setq angle (SC-DXF 50 data 0.0))
  (setq cosine (cos angle))
  (setq sine (sin angle))
  (setq a (* cosine sx))
  (setq b (* -1.0 sine sy))
  (setq c (* sine sx))
  (setq d (* cosine sy))
  (list
    a b c d
    (- (car point) (* a (car base)) (* b (cadr base)))
    (- (cadr point) (* c (car base)) (* d (cadr base)))
  )
)

(defun SC-TEXT-BOUNDS (object matrix / errorValue minPoint maxPoint corners transformed xs ys)
  (setq errorValue
    (vl-catch-all-apply 'vla-GetBoundingBox (list object 'minPoint 'maxPoint))
  )
  (if (vl-catch-all-error-p errorValue)
    nil
    (progn
      (setq minPoint (vlax-safearray->list minPoint))
      (setq maxPoint (vlax-safearray->list maxPoint))
      (setq corners
        (list
          (list (car minPoint) (cadr minPoint) 0.0)
          (list (car minPoint) (cadr maxPoint) 0.0)
          (list (car maxPoint) (cadr minPoint) 0.0)
          (list (car maxPoint) (cadr maxPoint) 0.0)
        )
      )
      (setq transformed
        (mapcar '(lambda (corner) (SC-MAT-POINT matrix corner)) corners)
      )
      (setq xs (mapcar 'car transformed))
      (setq ys (mapcar 'cadr transformed))
      (list (apply 'min xs) (apply 'min ys) (apply 'max xs) (apply 'max ys))
    )
  )
)

(defun SC-WRITE-TEXT (fh entity matrix parentLayer inheritedColor / data point target layer handle color text object textValue bounds rotationValue direction geometryText)
  (setq data (entget entity))
  (setq point (SC-DXF 10 data '(0.0 0.0 0.0)))
  (setq target (SC-MAT-POINT matrix point))
  (setq layer (SC-DXF 8 data ""))
  (if (= layer "0") (setq layer parentLayer))
  (setq handle (SC-DXF 5 data ""))
  (setq color (SC-RESOLVED-COLOR data layer inheritedColor))
  (setq text (SC-DXF-TEXT data))
  (setq object (vl-catch-all-apply 'vlax-ename->vla-object (list entity)))
  (if (or (vl-catch-all-error-p object) (null object))
    (progn
      (setq object nil)
      (setq bounds nil)
      (setq rotationValue (SC-DXF 50 data 0.0))
    )
    (progn
      (setq textValue (vl-catch-all-apply 'vla-get-TextString (list object)))
      (if (not (vl-catch-all-error-p textValue)) (setq text textValue))
      (setq bounds (SC-TEXT-BOUNDS object matrix))
      (setq rotationValue (vl-catch-all-apply 'vla-get-Rotation (list object)))
      (if (vl-catch-all-error-p rotationValue)
        (setq rotationValue (SC-DXF 50 data 0.0))
      )
    )
  )
  (setq direction
    (SC-MAT-VECTOR matrix (list (cos rotationValue) (sin rotationValue) 0.0))
  )
  (setq geometryText
    (if bounds
      (strcat
        "\t" (rtos (nth 0 bounds) 2 12)
        "\t" (rtos (nth 1 bounds) 2 12)
        "\t" (rtos (nth 2 bounds) 2 12)
        "\t" (rtos (nth 3 bounds) 2 12)
      )
      "\t\t\t\t"
    )
  )
  (write-line
    (strcat
      "text\t" (SC-TAB-SAFE text) "\t\t"
      (rtos (car target) 2 12) "\t"
      (rtos (cadr target) 2 12) "\t"
      (rtos (caddr target) 2 12) "\t"
      (itoa color) "\t"
      (SC-TAB-SAFE layer) "\t"
      (SC-TAB-SAFE handle)
      geometryText "\t"
      (rtos (car direction) 2 12) "\t"
      (rtos (cadr direction) 2 12)
    )
    fh
  )
)

(defun SC-WRITE-INSERT-MARKER (fh entity matrix parentLayer inheritedColor / data point target layer handle color blockName)
  (setq data (entget entity))
  (setq point (SC-DXF 10 data '(0.0 0.0 0.0)))
  (setq target (SC-MAT-POINT matrix point))
  (setq layer (SC-DXF 8 data parentLayer))
  (if (= layer "0") (setq layer parentLayer))
  (setq handle (SC-DXF 5 data ""))
  (setq color (SC-RESOLVED-COLOR data layer inheritedColor))
  (setq blockName (SC-DXF 2 data ""))
  (write-line
    (strcat
      "block\t\t" (SC-TAB-SAFE blockName) "\t"
      (rtos (car target) 2 12) "\t"
      (rtos (cadr target) 2 12) "\t"
      (rtos (caddr target) 2 12) "\t"
      (itoa color) "\t"
      (SC-TAB-SAFE layer) "\t"
      (SC-TAB-SAFE handle) "\t\t\t\t\t\t"
    )
    fh
  )
)

(defun SC-WALK-INSERT (fh insertEntity parentMatrix parentLayer inheritedColor depth / data blockName blockEntity blockData matrix layer color attribute attributeData attributeType child childData childType)
  (if (< depth 12)
    (progn
      (setq data (entget insertEntity))
      (SC-WRITE-INSERT-MARKER fh insertEntity parentMatrix parentLayer inheritedColor)
      (setq blockName (SC-DXF 2 data ""))
      (setq blockEntity (tblobjname "BLOCK" blockName))
      (if blockEntity
        (progn
          (setq blockData (entget blockEntity))
          (setq matrix (SC-MAT-MULTIPLY parentMatrix (SC-INSERT-MATRIX data blockData)))
          (setq layer (SC-DXF 8 data parentLayer))
          (if (= layer "0") (setq layer parentLayer))
          (setq color (SC-RESOLVED-COLOR data layer inheritedColor))
          (if (= (SC-DXF 66 data 0) 1)
            (progn
              (setq attribute (entnext insertEntity))
              (while attribute
                (setq attributeData (entget attribute))
                (setq attributeType (SC-DXF 0 attributeData ""))
                (cond
                  ((= attributeType "SEQEND") (setq attribute nil))
                  ((= attributeType "ATTRIB")
                    (SC-WRITE-TEXT fh attribute parentMatrix layer color)
                    (setq attribute (entnext attribute))
                  )
                  (T (setq attribute nil))
                )
              )
            )
          )
          (setq child (entnext blockEntity))
          (while child
            (setq childData (entget child))
            (setq childType (SC-DXF 0 childData ""))
            (cond
              ((= childType "ENDBLK") (setq child nil))
              ((or (= childType "TEXT") (= childType "MTEXT") (= childType "ATTDEF"))
                (SC-WRITE-TEXT fh child matrix layer color)
                (setq child (entnext child))
              )
              ((= childType "INSERT")
                (SC-WALK-INSERT fh child matrix layer color (+ depth 1))
                (setq child (entnext child))
              )
              (T (setq child (entnext child)))
            )
          )
        )
      )
    )
  )
)

(defun SC_EXPORT_DIAMETER_TEXTS (outputPath / fh ss index entity data entityType identity layer color)
  (setq fh (open outputPath "w" "utf8"))
  (write-line (strcat "#INSUNITS\t" (itoa (getvar "INSUNITS"))) fh)
  (write-line "kind\ttext\tblock_name\tx\ty\tz\tcolor\tlayer\thandle\tmin_x\tmin_y\tmax_x\tmax_y\tdirection_x\tdirection_y" fh)
  (setq identity '(1.0 0.0 0.0 1.0 0.0 0.0))
  (setq ss (ssget "_X" '((0 . "TEXT,MTEXT,INSERT") (410 . "Model"))))
  (if ss
    (progn
      (setq index 0)
      (while (< index (sslength ss))
        (setq entity (ssname ss index))
        (setq data (entget entity))
        (setq entityType (SC-DXF 0 data ""))
        (setq layer (SC-DXF 8 data ""))
        (setq color (SC-RESOLVED-COLOR data layer 7))
        (if (= entityType "INSERT")
          (SC-WALK-INSERT fh entity identity layer color 0)
          (SC-WRITE-TEXT fh entity identity layer color)
        )
        (setq index (+ index 1))
      )
    )
  )
  (write-line "#COMPLETE\t1" fh)
  (close fh)
  (princ)
)
'''
