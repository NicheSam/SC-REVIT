import json
import time
from typing import Any

from queue_protocol import ERROR_DIR, RESPONSE_DIR, ensure_queue_dirs, finish_gui_request
from sc_revit.core.batch import record_request_failed, record_request_succeeded
from rfa_reader import RfaReaderError


class RevitQueueTimeoutError(RfaReaderError):
    pass


_FIRE_BRANCH_REASON_LABELS = {
    "opposite_side_endpoint_tee_creation_failed": "主管端點兩側三通建立失敗",
    "opposite_side_cross_creation_failed": "四通建立失敗",
    "opposite_side_cross_missing_branch": "四通缺少一側支管",
    "connector_verification_failed": "管路連通檢查未通過",
    "system_type_verification_failed": "系統類型檢查未通過",
    "sprinkler_drop_creation_failed": "灑水頭垂管建立失敗",
    "diagnostic_evidence_kept": "已保留成功建立部分供檢查",
}

_FIRE_BRANCH_DETAIL_LABELS = {
    "revit rejected the fitting without an exception detail": (
        "Revit 拒絕這個管件，但沒有回傳更底層的錯誤說明"
    ),
    "oppositesidessameelevation": "兩側支管位於同一高度的主管端點配置",
    "fitting does not physically reference all three planned pipes": (
        "管件沒有實際引用計畫中的三段管線"
    ),
    "tie point is not valid on all four runs": (
        "交點位於主管端點，或未同時落在四條有效管段上"
    ),
    "planned cross fitting path verification failed": "四通與相鄰管段的實體連接未通過",
    "cross branch diameter is smaller than an adjacent branch run": (
        "四通出口管徑小於相鄰支管，無法依目前配置連接"
    ),
}


def _summarize_ids(values: list[Any], limit: int = 8) -> str:
    shown = ",".join(map(str, values[:limit]))
    return shown + (f" 等 {len(values)} 項" if len(values) > limit else "")


def _format_all_ids(values: list[Any], *, per_line: int = 6, limit: int = 60) -> str:
    visible = values[:limit]
    lines = [
        "、".join(map(str, visible[index:index + per_line]))
        for index in range(0, len(visible), per_line)
    ]
    if len(values) > limit:
        lines.append(f"另有 {len(values) - limit} 項，請查看完整診斷紀錄")
    return "\n".join(lines)


def format_fire_branch_failure_item(item: dict[str, Any]) -> str:
    reason = str(item.get("reason") or "unknown")
    label = _FIRE_BRANCH_REASON_LABELS.get(reason, "建立項目未完成")
    target = item.get("sprinkler_id")
    if target is None:
        target = item.get("row")
    heading = label if target in (None, "-") else f"位置 {target}：{label}"
    lines = [heading]

    detail = str(item.get("detail") or "")
    for source, translated in _FIRE_BRANCH_DETAIL_LABELS.items():
        if source in detail.lower():
            lines.append(translated)
            break
    topology = str(item.get("topology") or "")
    if topology:
        topology_label = {
            "OppositeSidesSameElevation": "兩側同高端點",
        }.get(topology, topology)
        lines.append(f"拓樸情況：{topology_label}")
    if reason == "opposite_side_endpoint_tee_creation_failed":
        lines.append(
            "判讀：這是主管端點的第一個管件建立失敗；後續灑水頭不可達屬於連鎖結果。"
        )
        lines.append(
            "目前回傳沒有更底層的 Revit 連接器原因，需檢查端點位置、方向與管件族群配置。"
        )

    unconnected_sprinklers = list(item.get("unconnected_sprinkler_ids") or [])
    unconnected_pipes = list(item.get("unconnected_pipe_ids") or [])
    missing_created_pipes = list(item.get("missing_created_pipe_ids") or [])
    unreachable_sprinklers = list(item.get("unreachable_sprinkler_ids") or [])
    wrong_system_sprinklers = list(item.get("wrong_system_sprinkler_ids") or [])
    wrong_system_pipes = list(item.get("wrong_system_pipe_ids") or [])
    missing_system_pipes = list(item.get("missing_system_pipe_ids") or [])
    missing_connector_sprinklers = list(item.get("missing_connector_sprinkler_ids") or [])
    missing_system_sprinklers = list(item.get("missing_system_sprinkler_ids") or [])
    actual_system_types = list(item.get("actual_system_type_ids") or [])
    system_change_failures = list(item.get("system_change_failures") or [])

    if reason == "connector_verification_failed":
        lines.extend(
            [
                "這是最終連通驗證結果，不是第一個失敗原因。",
                f"灑水頭接頭直接斷線：{len(unconnected_sprinklers)} 顆",
                f"新建管線未連接：{len(unconnected_pipes)} 段",
                f"新建管線遺失：{len(missing_created_pipes)} 段",
                f"無法由主管到達：{len(unreachable_sprinklers)} 顆",
            ]
        )
        if (
            unreachable_sprinklers
            and not unconnected_sprinklers
            and not unconnected_pipes
            and not missing_created_pipes
        ):
            lines.append(
                "判讀：灑水頭端與新建管線沒有回報直接斷線，但整批路網仍無法接回主管。"
            )
            lines.append(
                "較可能是共用上游接點未完成，請優先檢查主管交點的四通、三通或異徑接頭。"
            )
        if unreachable_sprinklers:
            lines.append(
                f"受影響灑水頭 ElementId（{len(unreachable_sprinklers)} 顆）：\n"
                + _format_all_ids(unreachable_sprinklers)
            )

    if unreachable_sprinklers:
        if reason != "connector_verification_failed":
            lines.append(f"{len(unreachable_sprinklers)} 顆灑水頭尚未連到主管")
    if unconnected_sprinklers:
        lines.append(f"{len(unconnected_sprinklers)} 顆灑水頭接頭尚未連接")
    if unconnected_pipes:
        lines.append(f"{len(unconnected_pipes)} 段管線仍有未連接端")
    if missing_created_pipes:
        lines.append(f"{len(missing_created_pipes)} 段預計建立管線不存在")
    if wrong_system_sprinklers or wrong_system_pipes:
        lines.append(
            f"{len(wrong_system_sprinklers)} 顆灑水頭、"
            f"{len(wrong_system_pipes)} 段管線的系統類型不符"
        )
    if missing_system_pipes or missing_system_sprinklers:
        lines.append(
            f"{len(missing_system_sprinklers)} 顆灑水頭、"
            f"{len(missing_system_pipes)} 段管線沒有系統類型"
        )
    if missing_connector_sprinklers:
        lines.append(f"{len(missing_connector_sprinklers)} 顆灑水頭找不到可用接頭")

    technical = [f"技術代碼：{reason}"]
    if detail:
        technical.append(detail)
    if unconnected_sprinklers:
        technical.append("unconnected sprinklers=" + _summarize_ids(unconnected_sprinklers))
    if unconnected_pipes:
        technical.append("unconnected pipes=" + _summarize_ids(unconnected_pipes))
    if missing_created_pipes:
        technical.append("deleted/invalid created pipes=" + _summarize_ids(missing_created_pipes))
    if unreachable_sprinklers:
        technical.append(
            "sprinklers not reachable from selected main="
            + _summarize_ids(unreachable_sprinklers)
        )
    if wrong_system_sprinklers:
        technical.append("wrong-system sprinklers=" + _summarize_ids(wrong_system_sprinklers))
    if wrong_system_pipes:
        technical.append("wrong-system pipes=" + _summarize_ids(wrong_system_pipes))
    if missing_system_pipes:
        technical.append("missing-system pipes=" + _summarize_ids(missing_system_pipes))
    if missing_connector_sprinklers:
        technical.append(
            "missing-connector sprinklers=" + _summarize_ids(missing_connector_sprinklers)
        )
    if missing_system_sprinklers:
        technical.append("missing-system sprinklers=" + _summarize_ids(missing_system_sprinklers))
    if actual_system_types:
        technical.append("actual system types=" + _summarize_ids(actual_system_types))
    if system_change_failures:
        technical.append(
            "system-change failures="
            + json.dumps(system_change_failures, ensure_ascii=False, separators=(",", ":"))
        )
    lines.append("｜".join(technical))
    return "\n".join(lines)


def format_fire_branch_verification_failure(payload: dict[str, Any]) -> str:
    """Format a structured fire-branch verification failure for the GUI.

    The Revit queue can complete successfully while the model verification
    result is failed.  Keep the first fitting failure separate from the later
    reachability consequences so the user can act on the correct item.
    """

    status = str(payload.get("verification_status") or "未提供")
    details = [item for item in (payload.get("failed") or []) if isinstance(item, dict)]
    lines = [
        "消防支管建立未完成。",
        f"驗證狀態：{status}",
        f"已連接灑水頭：{payload.get('connected_sprinkler_count', 0)} 顆",
        f"未連接灑水頭：{payload.get('unconnected_sprinkler_count', 0)} 顆",
    ]
    if payload.get("restoration_verified") or payload.get("rollback_status") == "verified":
        lines.append("沙盒檢查已自動回復，這次測試沒有保留模型變更。")
    elif payload.get("partial_success"):
        lines.append("這次有部分模型變更，是否保留成功部分由使用者決定。")
    else:
        lines.append("模型是否保留變更，請以後續回復狀態為準。")
    if details:
        lines.append("")
        lines.append("第一個失敗原因與後續影響：")
        lines.extend(format_fire_branch_failure_item(item) for item in details[:12])
        if len(details) > 12:
            lines.append(f"另有 {len(details) - 12} 項，完整內容已保存於工作流程紀錄。")
    else:
        lines.append("Revit 沒有回傳可辨識的接頭診斷明細。")
    lines.append("")
    lines.append("完整診斷已保留於工作流程紀錄。")
    return "\n".join(lines)


def _format_revit_error(payload: dict[str, Any], fallback: str) -> str:
    message = str(payload.get("error") or fallback)
    details = list(payload.get("failure_details") or [])
    if not details:
        if message.startswith("Fire branch"):
            return "消防支管建立失敗。\n技術資訊：" + message
        return message
    is_fire_branch = message.startswith("Fire branch") or any(
        isinstance(item, dict)
        and str(item.get("reason") or "") in _FIRE_BRANCH_REASON_LABELS
        for item in details
    )
    if is_fire_branch:
        message = "消防支管建立未完成。以下為可直接判讀的問題摘要："
    lines = [message]
    original_error = str(payload.get("error") or "")
    if "No branch elements were committed" in original_error:
        lines.extend(
            [
                "本次失敗後已整批復原，模型中沒有保留這批建立結果。",
                "",
            ]
        )
    lines.append("接管問題明細：")
    detail_reasons = {
        str(item.get("reason") or "")
        for item in details
        if isinstance(item, dict)
    }
    if detail_reasons == {"connector_verification_failed"}:
        lines.append(
            "資料限制：本次回傳沒有記錄第一個失敗節點，無法只靠這份舊回傳判定是哪一個管件先失敗。"
        )
    for item in details[:12]:
        if not isinstance(item, dict):
            lines.append(str(item))
            continue
        lines.append(format_fire_branch_failure_item(item))
    if len(details) > 12:
        lines.append(f"另有 {len(details) - 12} 項問題，完整內容已保存於診斷紀錄。")
    return "\n".join(lines)


def wait_for_revit_response(
    request_id: str,
    timeout_seconds: int,
    *,
    failure_message: str = "Revit 請求失敗",
    timeout_message: str = "等待 Revit 回傳資料逾時",
) -> dict[str, Any]:
    """Wait for one queue response from the Revit add-in.

    This is the shared boundary between Python modules and the C# Revit listener.
    Domain modules should create requests, then call this function instead of
    duplicating queue polling logic.
    """
    ensure_queue_dirs()
    output_path = RESPONSE_DIR / f"{request_id}.json"
    error_path = ERROR_DIR / f"{request_id}.json"
    deadline = time.time() + timeout_seconds

    try:
        while time.time() < deadline:
            if output_path.exists():
                payload = json.loads(output_path.read_text(encoding="utf-8"))
                output_path.unlink(missing_ok=True)
                record_request_succeeded(request_id, payload)
                return payload
            if error_path.exists():
                payload = None
                try:
                    payload = json.loads(error_path.read_text(encoding="utf-8"))
                    message = _format_revit_error(payload, failure_message)
                except json.JSONDecodeError:
                    message = failure_message
                error_path.unlink(missing_ok=True)
                record_request_failed(request_id, message, payload)
                raise RfaReaderError(message)
            time.sleep(0.5)

        record_request_failed(request_id, timeout_message)
        raise RevitQueueTimeoutError(timeout_message)
    finally:
        finish_gui_request(request_id)
