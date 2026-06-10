from naming_rules import SYSTEM_DISPLAY_NAMES


def build_safe_text_values(
    *,
    system: str | None,
    base_name: str | None,
    source_file_name: str,
) -> dict[str, str]:
    values = {
        "SC_原始檔名": source_file_name,
        "SC_維護狀態": "使用中",
    }
    if system:
        values["SC_系統別"] = SYSTEM_DISPLAY_NAMES.get(system, system)
    if base_name:
        values["SC_主名"] = base_name
    return values
