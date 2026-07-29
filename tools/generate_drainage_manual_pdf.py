from __future__ import annotations

import html
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "SC_REVIT_drainage_operation_manual.md"
OUTPUT = ROOT / "docs" / "SC_REVIT_drainage_operation_manual.pdf"
FONT_REGULAR = Path(r"C:\Windows\Fonts\msjh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msjhbd.ttc")


def register_fonts() -> tuple[str, str]:
    regular_name = "SCJhengHei"
    bold_name = "SCJhengHeiBold"
    pdfmetrics.registerFont(
        TTFont(regular_name, str(FONT_REGULAR), subfontIndex=0)
    )
    pdfmetrics.registerFont(
        TTFont(bold_name, str(FONT_BOLD), subfontIndex=0)
    )
    pdfmetrics.registerFontFamily(
        regular_name,
        normal=regular_name,
        bold=bold_name,
    )
    return regular_name, bold_name


def inline_markup(value: str) -> str:
    value = html.escape(value.strip())

    def format_code(match: re.Match[str]) -> str:
        content = match.group(1)
        font_name = "Courier" if content.isascii() else "SCJhengHei"
        return f'<font name="{font_name}">{content}</font>'

    value = re.sub(r"`([^`]+)`", format_code, value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<link href="\2" color="#2563EB">\1</link>',
        value,
    )
    return value


def make_styles(font_name: str, bold_name: str):
    base = getSampleStyleSheet()
    styles = {
        "body": ParagraphStyle(
            "BodyCJK",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=9.4,
            leading=14.5,
            textColor=colors.HexColor("#243449"),
            wordWrap="CJK",
            spaceAfter=3 * mm,
        ),
        "h1": ParagraphStyle(
            "H1CJK",
            parent=base["Heading1"],
            fontName=bold_name,
            fontSize=22,
            leading=29,
            textColor=colors.HexColor("#14324A"),
            wordWrap="CJK",
            spaceBefore=4 * mm,
            spaceAfter=5 * mm,
        ),
        "h2": ParagraphStyle(
            "H2CJK",
            parent=base["Heading2"],
            fontName=bold_name,
            fontSize=15,
            leading=21,
            textColor=colors.HexColor("#0F5E78"),
            wordWrap="CJK",
            spaceBefore=6 * mm,
            spaceAfter=3 * mm,
        ),
        "h3": ParagraphStyle(
            "H3CJK",
            parent=base["Heading3"],
            fontName=bold_name,
            fontSize=11.5,
            leading=17,
            textColor=colors.HexColor("#164E63"),
            wordWrap="CJK",
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        ),
        "bullet": ParagraphStyle(
            "BulletCJK",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=9.2,
            leading=14.2,
            leftIndent=6 * mm,
            firstLineIndent=-3.5 * mm,
            bulletIndent=1.5 * mm,
            wordWrap="CJK",
            textColor=colors.HexColor("#243449"),
            spaceAfter=1.5 * mm,
        ),
        "callout": ParagraphStyle(
            "CalloutCJK",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=9.2,
            leading=14.2,
            leftIndent=4 * mm,
            rightIndent=4 * mm,
            borderWidth=0.8,
            borderColor=colors.HexColor("#F59E0B"),
            borderPadding=4 * mm,
            backColor=colors.HexColor("#FFF7E6"),
            textColor=colors.HexColor("#713F12"),
            wordWrap="CJK",
            spaceBefore=2 * mm,
            spaceAfter=5 * mm,
        ),
        "table": ParagraphStyle(
            "TableCJK",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=7.6,
            leading=11.2,
            wordWrap="CJK",
            textColor=colors.HexColor("#243449"),
        ),
        "table_header": ParagraphStyle(
            "TableHeaderCJK",
            parent=base["BodyText"],
            fontName=bold_name,
            fontSize=7.8,
            leading=11.5,
            wordWrap="CJK",
            textColor=colors.white,
            alignment=TA_LEFT,
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName=bold_name,
            fontSize=27,
            leading=36,
            textColor=colors.HexColor("#14324A"),
            alignment=TA_CENTER,
            wordWrap="CJK",
            spaceAfter=5 * mm,
        ),
        "cover_meta": ParagraphStyle(
            "CoverMeta",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=10,
            leading=16,
            textColor=colors.HexColor("#526477"),
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
    }
    return styles


def page_decor(canvas, document):
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(colors.HexColor("#D6E0E8"))
    canvas.line(18 * mm, height - 14 * mm, width - 18 * mm, height - 14 * mm)
    canvas.setFont("SCJhengHei", 7.5)
    canvas.setFillColor(colors.HexColor("#667788"))
    canvas.drawString(18 * mm, height - 11 * mm, "SC REVIT｜Revit 2024 排水建模操作手冊")
    canvas.drawRightString(
        width - 18 * mm,
        10 * mm,
        f"{document.page}",
    )
    canvas.restoreState()


def make_table(rows, styles):
    converted = []
    for row_index, row in enumerate(rows):
        style = styles["table_header"] if row_index == 0 else styles["table"]
        converted.append(
            [Paragraph(inline_markup(cell), style) for cell in row]
        )
    column_count = max(len(row) for row in rows)
    usable = A4[0] - 36 * mm
    if column_count == 3:
        widths = [usable * 0.22, usable * 0.31, usable * 0.47]
    else:
        widths = [usable / column_count] * column_count
    table = Table(
        converted,
        colWidths=widths,
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F5E78")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B7C7D3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                    colors.white,
                    colors.HexColor("#F3F7F9"),
                ]),
            ]
        )
    )
    return table


def parse_markdown(lines, styles):
    story = []
    paragraph_buffer = []
    table_rows = []

    def flush_paragraph():
        if paragraph_buffer:
            story.append(
                Paragraph(
                    inline_markup(" ".join(paragraph_buffer)),
                    styles["body"],
                )
            )
            paragraph_buffer[:] = []

    def flush_table():
        if table_rows:
            rows = [
                row
                for row in table_rows
                if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in row)
            ]
            story.append(make_table(rows, styles))
            story.append(Spacer(1, 3 * mm))
            table_rows[:] = []

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("<") or line.startswith("  <"):
            continue
        if not line:
            flush_paragraph()
            flush_table()
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            table_rows.append(
                [cell.strip() for cell in line.strip("|").split("|")]
            )
            continue
        flush_table()
        if line.startswith("# "):
            flush_paragraph()
            continue
        if line.startswith("## "):
            flush_paragraph()
            story.append(
                Paragraph(inline_markup(line[3:]), styles["h2"])
            )
            continue
        if line.startswith("### "):
            flush_paragraph()
            story.append(
                Paragraph(inline_markup(line[4:]), styles["h3"])
            )
            continue
        if line.startswith("> "):
            flush_paragraph()
            story.append(
                Paragraph(inline_markup(line[2:]), styles["callout"])
            )
            continue
        bullet_match = re.match(r"^-\s+(.*)$", line)
        number_match = re.match(r"^(\d+)\.\s+(.*)$", line)
        if bullet_match:
            flush_paragraph()
            story.append(
                Paragraph(
                    inline_markup(bullet_match.group(1)),
                    styles["bullet"],
                    bulletText="•",
                )
            )
            continue
        if number_match:
            flush_paragraph()
            story.append(
                Paragraph(
                    inline_markup(number_match.group(2)),
                    styles["bullet"],
                    bulletText=number_match.group(1) + ".",
                )
            )
            continue
        paragraph_buffer.append(line.rstrip("  "))

    flush_paragraph()
    flush_table()
    return story


def build_pdf():
    font_name, bold_name = register_fonts()
    styles = make_styles(font_name, bold_name)
    lines = SOURCE.read_text(encoding="utf-8").splitlines()

    document = BaseDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=17 * mm,
        title="SC REVIT 排水建模操作手冊",
        author="SC REVIT",
        subject="Revit 2024 drainage workflow",
    )
    frame = Frame(
        document.leftMargin,
        document.bottomMargin,
        document.width,
        document.height,
        id="manual",
    )
    document.addPageTemplates(
        [PageTemplate(id="manual", frames=[frame], onPage=page_decor)]
    )

    story = [Spacer(1, 24 * mm)]
    icon_paths = [
        ROOT / "docs" / "user-guide-assets" / "drainage_connect.png",
        ROOT / "docs" / "user-guide-assets" / "drainage_settings.png",
        ROOT / "docs" / "user-guide-assets" / "align_centerline.png",
    ]
    icon_row = []
    for path in icon_paths:
        image = Image(str(path), width=18 * mm, height=18 * mm)
        icon_row.append(image)
    icon_table = Table([icon_row], colWidths=[28 * mm] * 3, hAlign="CENTER")
    icon_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.extend(
        [
            icon_table,
            Spacer(1, 10 * mm),
            Paragraph("SC REVIT", styles["cover_meta"]),
            Paragraph("排水建模操作手冊", styles["cover_title"]),
            Paragraph(
                "Revit 2024｜main / snapshot-676ce995fd74",
                styles["cover_meta"],
            ),
            Spacer(1, 12 * mm),
            Paragraph(
                "目前使用者介面：排水接入幹管、管件設定、管中心對齊",
                styles["callout"],
            ),
            Spacer(1, 28 * mm),
            Paragraph(
                "開發預覽文件｜正式專案使用前請先在測試模型驗收",
                styles["cover_meta"],
            ),
            PageBreak(),
        ]
    )
    story.extend(parse_markdown(lines[4:], styles))
    document.build(story)
    print(OUTPUT)


if __name__ == "__main__":
    try:
        build_pdf()
    except Exception as exc:
        print(f"PDF generation failed: {exc}", file=sys.stderr)
        raise
