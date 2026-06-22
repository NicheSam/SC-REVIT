import json
import zipfile
from datetime import datetime
from html import escape
from pathlib import Path

from library_index import ensure_schema, fetch_recent_records, get_records_dir


XLSX_NAME = "library_index.xlsx"
HEADERS = [
    "\u5165\u5eab\u6642\u9593",
    "\u7cfb\u7d71",
    "\u4e3b\u540d",
    "\u6700\u7d42\u6a94\u540d",
    "Revit \u4e3b\u985e\u5225",
    "\u65cf\u7fa4\u540d\u7a31",
    "\u6700\u7d42\u5206\u985e",
    "\u539f\u59cb\u6a94\u540d",
    "\u4fdd\u7559\u5f8c\u7db4",
    "\u662f\u5426\u6539\u540d",
    "\u662f\u5426\u6539\u8cc7\u6599\u593e",
    "\u662f\u5426\u649e\u540d",
]

OPENING_HEADERS = [
    "\u5e8f\u865f",
    "\u958b\u5b54\u7de8\u865f",
    "\u72c0\u614b",
    "\u7cfb\u7d71",
    "MEP \u985e\u578b",
    "MEP \u5143\u7d20 ID",
    "MEP \u540d\u7a31",
    "\u571f\u5efa\u69cb\u4ef6",
    "\u571f\u5efa\u69cb\u4ef6 ID",
    "\u571f\u5efa\u69cb\u4ef6\u540d\u7a31",
    "\u571f\u5efa Link",
    "\u6a13\u5c64",
    "\u5b54\u578b",
    "\u958b\u5b54\u5c3a\u5bf8",
    "\u6a19\u8a3b\u72c0\u614b",
    "\u6a19\u8a3b\u57fa\u6e96",
    "\u6a19\u8a3b\u8ddd\u96e2(cm)",
    "\u6a19\u8a3b\u8aaa\u660e",
    "\u4e2d\u5fc3\u4f86\u6e90",
    "X \u5ea7\u6a19(cm)",
    "Y \u5ea7\u6a19(cm)",
    "Z \u5ea7\u6a19(cm)",
    "\u4ea4\u6703\u9577\u5ea6(mm)",
    "\u5099\u8a3b",
]

STATUS_DISPLAY = {
    "classified": "\u5df2\u5206\u985e",
    "suggest_review": "\u9700\u78ba\u8a8d",
    "needs_review": "\u5f85\u5be9\u6838",
}


def bool_text(value: object) -> str:
    return "\u662f" if bool(value) else "\u5426"


def suffix_text(raw_json: str) -> str:
    try:
        values = json.loads(raw_json or "[]")
    except json.JSONDecodeError:
        return ""
    return "\u3001".join(str(item.get("value", "")) for item in values if item.get("value"))


def ft_to_cm(value: object) -> str:
    try:
        return f"{float(value or 0) * 30.48:.1f}"
    except (TypeError, ValueError):
        return ""


def mm_text(value: object) -> str:
    try:
        return f"{float(value or 0):.1f}"
    except (TypeError, ValueError):
        return ""


def _candidate_system(candidate: dict) -> str:
    return str(
        candidate.get("system")
        or candidate.get("system_name")
        or candidate.get("mep_system")
        or candidate.get("mep_type")
        or ""
    )


def _opening_dimension_status(candidate: dict) -> str:
    return "\u53ef\u6a19\u8a3b" if bool(candidate.get("dimension_is_reliable")) else "\u4e0d\u81ea\u52d5\u6a19\u8a3b"


def _opening_dimension_ref(candidate: dict) -> str:
    values = [
        str(candidate.get("dimension_ref_kind") or "").strip(),
        str(candidate.get("dimension_ref_name") or "").strip(),
    ]
    return "\uff5c".join(value for value in values if value)


def _cm_text(value: object) -> str:
    try:
        return f"{float(value or 0):.1f}"
    except (TypeError, ValueError):
        return ""


def export_opening_candidates_xlsx(candidates: list[dict], output_path_or_dir: str | Path) -> Path:
    target = Path(output_path_or_dir)
    if target.suffix.casefold() == ".xlsx":
        output_path = target
        output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        target.mkdir(parents=True, exist_ok=True)
        output_path = target / f"SC_\u958b\u5b54\u5019\u9078\u6e05\u55ae_{datetime.now().strftime('%Y%m%d-%H%M%S')}.xlsx"

    rows = [OPENING_HEADERS]
    for index, candidate in enumerate(candidates, start=1):
        center = candidate.get("center") or {}
        rows.append(
            [
                index,
                candidate.get("opening_id", ""),
                candidate.get("status", ""),
                _candidate_system(candidate),
                candidate.get("mep_type", ""),
                candidate.get("mep_id", ""),
                candidate.get("mep_name", ""),
                candidate.get("host_type", ""),
                candidate.get("host_id", ""),
                candidate.get("host_name", ""),
                candidate.get("link_name", ""),
                candidate.get("level", ""),
                candidate.get("shape", ""),
                candidate.get("size_text", ""),
                _opening_dimension_status(candidate),
                _opening_dimension_ref(candidate),
                _cm_text(candidate.get("dimension_distance_cm")) if candidate.get("dimension_is_reliable") else "",
                candidate.get("dimension_note", ""),
                candidate.get("center_source", ""),
                ft_to_cm(center.get("x")),
                ft_to_cm(center.get("y")),
                ft_to_cm(center.get("z")),
                mm_text(candidate.get("intersection_length_mm")),
                candidate.get("note", ""),
            ]
        )

    write_xlsx(output_path, "\u958b\u5b54\u5019\u9078\u6e05\u55ae", rows)
    return output_path


def export_library_index_xlsx(library_root: str) -> Path:
    ensure_schema(library_root)
    records = fetch_recent_records(library_root, limit=1_000_000)
    output_path = get_records_dir(library_root) / XLSX_NAME
    rows = [HEADERS]
    for record in records:
        rows.append(
            [
                record.get("ingested_at", ""),
                record.get("system_name", ""),
                record.get("base_name", ""),
                record.get("final_file_name", ""),
                record.get("revit_category", ""),
                record.get("family_name", ""),
                record.get("classification_path", ""),
                record.get("source_file_name", ""),
                suffix_text(record.get("selected_suffixes_json", "")),
                bool_text(record.get("name_overridden")),
                bool_text(record.get("folder_overridden")),
                bool_text(
                    record.get("duplicate_original_name")
                    or record.get("duplicate_planned_name")
                ),
            ]
        )

    write_xlsx(output_path, "\u65cf\u7fa4\u7d22\u5f15", rows)
    return output_path


def write_xlsx(output_path: Path, sheet_name: str, rows: list[list[object]]) -> None:
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="{escape(sheet_name, quote=True)}" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/styles.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Microsoft JhengHei"/></font>
    <font><b/><sz val="11"/><name val="Microsoft JhengHei"/></font>
  </fonts>
  <fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
  <borders count="1"><border/></borders>
  <cellStyleXfs count="1"><xf fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2">
    <xf fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf fontId="1" fillId="0" borderId="0" xfId="0"/>
  </cellXfs>
</styleSheet>""",
        )
        archive.writestr("xl/worksheets/sheet1.xml", build_sheet_xml(rows))


def build_sheet_xml(rows: list[list[object]]) -> str:
    body = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            ref = f"{column_name(column_index)}{row_index}"
            style = ' s="1"' if row_index == 1 else ""
            cells.append(
                f'<c r="{ref}" t="inlineStr"{style}><is><t>{escape(str(value or ""))}</t></is></c>'
            )
        body.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>'
        + "".join(body)
        + "</sheetData></worksheet>"
    )


def column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name
