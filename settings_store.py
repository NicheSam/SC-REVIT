import json
import os
from pathlib import Path
from typing import Any, Dict


APP_NAME = "RevitFamilyClassifier"


def get_settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME / "settings.json"
    return Path.home() / f".{APP_NAME}" / "settings.json"


def load_settings() -> Dict[str, Any]:
    path = get_settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_library_root(library_root: str) -> None:
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = load_settings()
    payload["library_root"] = library_root
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_drainage_settings(settings: Dict[str, Any]) -> None:
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = load_settings()
    payload["drainage"] = dict(settings)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
