import re
from dataclasses import dataclass
from pathlib import Path


INVALID_FILENAME_CHARS = '<>:"/\\|?*'
SYSTEM_DISPLAY_NAMES = {
    "HVAC": "空調",
    "PLB": "給排水",
    "FP": "消防",
    "PWR": "動力",
    "LTG": "照明",
    "ELV": "弱電",
    "ARC": "建築",
    "STR": "結構",
    "DRW": "圖面支援",
}

SUFFIX_ORDER = ["尺寸", "規格／角度", "材質", "接合方式", "安裝方式", "其他"]
DEFAULT_SELECTED = set(SUFFIX_ORDER)

MATERIAL_TERMS = {
    "pvc", "鋼", "不鏽鋼", "鋁", "壓鑄鋅", "銅", "鑄鐵", "黃銅", "磁性"
}
JOINT_TERMS = {
    "螺紋", "法蘭", "法蘭式", "壓縮", "焊接", "承插", "溝槽", "無頭一字螺絲"
}
INSTALL_TERMS = {
    "吸頂式", "壁掛式", "落地式", "埋入式", "吊掛式", "嵌入式", "吸頂", "壁掛", "落地"
}
SPEC_TERMS = {"雙聯", "單聯", "sch 40", "sch40"}


@dataclass(frozen=True)
class NameSuffix:
    category: str
    value: str
    selected: bool


@dataclass(frozen=True)
class NameAnalysis:
    base_name: str
    suffixes: list[NameSuffix]


def sanitize_name_part(value: str) -> str:
    cleaned = value.strip()
    for char in INVALID_FILENAME_CHARS:
        cleaned = cleaned.replace(char, "_")
    return cleaned


def strip_source_prefix(value: str) -> str:
    return re.sub(r"^(m_|a_|e_|generic_)", "", value.strip(), flags=re.IGNORECASE)


def classify_suffix(segment: str) -> str | None:
    normalized = segment.casefold().strip()
    if re.search(r"\b\d+(?:\.\d+)?\s*(?:-\s*\d+(?:\.\d+)?)?\s*mm\b", normalized):
        return "尺寸"
    if re.search(r"\bdn\s*\d+\b", normalized):
        return "尺寸"
    if re.search(r"\b\d+(?:\.\d+)?\s*(?:x|×)\s*\d+(?:\.\d+)?\s*mm\b", normalized):
        return "尺寸"
    if re.search(r"\b(?:45|90)\s*度\b", normalized) or normalized in SPEC_TERMS:
        return "規格／角度"
    if normalized in {term.casefold() for term in MATERIAL_TERMS}:
        return "材質"
    if normalized in {term.casefold() for term in JOINT_TERMS}:
        return "接合方式"
    if normalized in {term.casefold() for term in INSTALL_TERMS}:
        return "安裝方式"
    return None


def analyze_source_name(raw_name: str) -> NameAnalysis:
    stem = Path(raw_name).stem
    cleaned = strip_source_prefix(stem)
    segments = [segment.strip() for segment in re.split(r"\s+-\s+", cleaned) if segment.strip()]
    if not segments:
        return NameAnalysis(base_name=cleaned, suffixes=[])

    base_segment = segments[0]
    suffixes: list[NameSuffix] = []

    angle_match = re.search(r"(\d+\s*度)", base_segment)
    if angle_match:
        angle = angle_match.group(1).strip()
        base_segment = base_segment.replace(angle_match.group(1), "").strip()
        suffixes.append(NameSuffix("規格／角度", angle, True))

    for segment in segments[1:]:
        category = classify_suffix(segment) or "其他"
        suffixes.append(NameSuffix(category, segment, category in DEFAULT_SELECTED))

    return NameAnalysis(base_name=base_segment, suffixes=suffixes)


def generate_planned_name(
    raw_path: str,
    system: str | None = None,
    family_name: str | None = None,
    editable_name: str | None = None,
    suffixes: list[str] | None = None,
) -> str:
    path = Path(raw_path)
    if not system:
        return path.name

    system_name = SYSTEM_DISPLAY_NAMES.get(system, system)
    base_name = editable_name or (
        analyze_source_name(family_name or path.name).base_name
    )
    parts = ["SC", sanitize_name_part(system_name), sanitize_name_part(base_name)]
    for suffix in suffixes or []:
        if suffix:
            parts.append(sanitize_name_part(suffix))
    return "-".join(parts) + ".rfa"

