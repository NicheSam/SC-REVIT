from queue_protocol import (
    create_fire_branch_context_request,
    create_fire_branch_pipes_request,
    create_fire_branch_preview_request,
    create_fire_branch_selection_request,
)
from sc_revit.core.revit_queue_client import wait_for_revit_response
from rfa_reader import RfaReaderError

_FAILURE = "Revit 消防支管建立請求失敗"
_TIMEOUT = "等待 Revit 回傳消防支管資料逾時"


def _wait(request_id: str, timeout_seconds: int) -> dict:
    return wait_for_revit_response(
        request_id,
        timeout_seconds,
        failure_message=_FAILURE,
        timeout_message=_TIMEOUT,
    )


def request_fire_branch_context(timeout_seconds: int = 120) -> dict:
    request = create_fire_branch_context_request()
    return _wait(request.request_id, timeout_seconds)


def request_fire_branch_selection(timeout_seconds: int = 120) -> dict:
    request = create_fire_branch_selection_request()
    return _wait(request.request_id, timeout_seconds)


def request_create_fire_branch_pipes(
    *,
    main_pipe_id: str | int,
    main_pipe_ids: list[str | int] | None = None,
    sprinkler_ids: list[str | int],
    pipe_type_id: str | int,
    system_type_id: str | int,
    level_id: str | int,
    diameter_mm: float,
    branch_offset_cm: float,
    height_reference: str,
    preview_group_id: str | int | None = None,
    delete_preview_after_create: bool = True,
    timeout_seconds: int = 180,
) -> dict:
    request = create_fire_branch_pipes_request(
        main_pipe_id=main_pipe_id,
        main_pipe_ids=main_pipe_ids,
        sprinkler_ids=sprinkler_ids,
        pipe_type_id=pipe_type_id,
        system_type_id=system_type_id,
        level_id=level_id,
        diameter_mm=diameter_mm,
        branch_offset_cm=branch_offset_cm,
        height_reference=height_reference,
        preview_group_id=preview_group_id,
        delete_preview_after_create=delete_preview_after_create,
    )
    payload = _wait(request.request_id, timeout_seconds)
    if payload.get("verification_status") != "verified":
        raise RfaReaderError(
            "Revit 消防支管建立未回傳連接驗證結果；請確認已載入最新版 SC REVIT 外掛。"
        )
    return payload


def request_create_fire_branch_preview(
    *,
    main_pipe_id: str | int,
    main_pipe_ids: list[str | int] | None = None,
    sprinkler_ids: list[str | int],
    level_id: str | int,
    branch_offset_cm: float,
    height_reference: str,
    timeout_seconds: int = 180,
) -> dict:
    request = create_fire_branch_preview_request(
        main_pipe_id=main_pipe_id,
        main_pipe_ids=main_pipe_ids,
        sprinkler_ids=sprinkler_ids,
        level_id=level_id,
        branch_offset_cm=branch_offset_cm,
        height_reference=height_reference,
    )
    return _wait(request.request_id, timeout_seconds)
