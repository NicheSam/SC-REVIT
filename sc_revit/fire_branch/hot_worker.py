from __future__ import annotations

import json
import sys

from .hot_analysis import build_preview_summary


def _write_json(payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def main() -> int:
    try:
        raw_payload = sys.stdin.buffer.read()
        payload = json.loads(raw_payload.decode("utf-8"))
        result = build_preview_summary(payload)
        _write_json(result)
        return 0
    except Exception as exc:
        _write_json(
            {"status": "error", "message": f"分析程式無法完成：{exc}"},
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
