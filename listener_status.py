import json
from datetime import datetime, timezone

from queue_protocol import HEARTBEAT_FILE, is_agent_listener_enabled


def get_listener_status(max_age_seconds: int = 90) -> dict:
    if not is_agent_listener_enabled():
        return {
            "connected": False,
            "enabled": False,
            "label": "待命",
            "detail": "執行功能時會自動建立暫時 Revit 連線",
        }
    if not HEARTBEAT_FILE.exists():
        return {
            "connected": False,
            "enabled": True,
            "label": "未連線",
            "detail": "尚未偵測到 Revit 監聽器",
        }

    try:
        payload = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8-sig"))
        timestamp = datetime.fromisoformat(payload["utc"])
    except Exception:
        return {
            "connected": False,
            "enabled": True,
            "label": "未連線",
            "detail": "Revit 監聽器心跳格式錯誤",
        }

    age = (datetime.now(timezone.utc) - timestamp).total_seconds()
    if age <= max_age_seconds:
        return {
            "connected": True,
            "enabled": True,
            "label": "已連線",
            "detail": f"最近心跳 {age:.1f} 秒前",
        }

    return {
        "connected": False,
        "enabled": True,
        "label": "未連線",
        "detail": f"最近心跳已超過 {age:.1f} 秒，可能需重啟 Revit",
    }
