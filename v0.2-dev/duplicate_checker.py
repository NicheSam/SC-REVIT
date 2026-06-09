from pathlib import Path


def find_duplicate_names(library_root: str | None, original_name: str, planned_name: str) -> dict:
    if not library_root:
        return {
            "original_name_exists": False,
            "planned_name_exists": False,
            "original_matches": [],
            "planned_matches": [],
        }

    root = Path(library_root)
    if not root.exists():
        return {
            "original_name_exists": False,
            "planned_name_exists": False,
            "original_matches": [],
            "planned_matches": [],
        }

    original_matches = [str(path) for path in root.rglob(original_name)]
    planned_matches = [str(path) for path in root.rglob(planned_name)]
    return {
        "original_name_exists": bool(original_matches),
        "planned_name_exists": bool(planned_matches),
        "original_matches": original_matches,
        "planned_matches": planned_matches,
    }


def build_available_copy_name(
    library_root: str | None,
    planned_name: str,
    force_copy: bool = False,
) -> str:
    if not library_root:
        return planned_name

    root = Path(library_root)
    stem = Path(planned_name).stem
    suffix = Path(planned_name).suffix or ".rfa"
    candidate = planned_name
    copy_index = 0

    while force_copy or any(root.rglob(candidate)):
        copy_index += 1
        copy_suffix = "複製" if copy_index == 1 else f"複製{copy_index}"
        candidate = f"{stem}-{copy_suffix}{suffix}"
        force_copy = False
    return candidate
