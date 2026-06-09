import json
from pathlib import Path


LIBRARY_ROOT = Path(__file__).parent.parent / "族群庫"
RULES_PATH = Path(__file__).parent / "rules.json"


def main() -> None:
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]
    rule_paths = {rule["path"] for rule in rules}
    leaf_paths = {
        str(path.relative_to(LIBRARY_ROOT)).replace("/", "\\")
        for path in LIBRARY_ROOT.rglob("*")
        if path.is_dir() and not any(child.is_dir() for child in path.iterdir())
    }
    leaf_paths = {path for path in leaf_paths if not path.startswith("03 管理區")}

    print(f"leaf_count={len(leaf_paths)}")
    print(f"rule_path_count={len(rule_paths)}")
    print(f"missing={sorted(leaf_paths - rule_paths)}")
    print(f"extra={sorted(rule_paths - leaf_paths)}")


if __name__ == "__main__":
    main()
