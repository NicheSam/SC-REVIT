from queue_protocol import (
    create_fire_branch_context_request,
    create_fire_branch_focus_request,
    create_fire_branch_pipes_request,
    create_fire_branch_preview_request,
    create_fire_branch_selection_request,
    create_fire_branch_snapshot_request,
)
from sc_revit.core.revit_queue_client import (
    format_fire_branch_verification_failure,
    wait_for_revit_response,
)
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


def request_fire_branch_snapshot(
    *,
    main_pipe_id: str | int | None = None,
    main_pipe_ids: list[str | int] | None = None,
    timeout_seconds: int = 120,
) -> dict:
    request = create_fire_branch_snapshot_request(
        main_pipe_id=main_pipe_id,
        main_pipe_ids=main_pipe_ids,
    )
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
    execution_mode: str = "commit",
    diameter_plan: list[dict] | None = None,
    topology_plan: dict | None = None,
    sandbox_scope: str | None = None,
    preview_snapshot_id: str | None = None,
    pilot_source_row_index: int | None = None,
    require_diameter_plan: bool = False,
    model_plan_hash: str | None = None,
    source_mode: str = "cad",
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
        execution_mode=execution_mode,
        diameter_plan=diameter_plan,
        topology_plan=topology_plan,
        sandbox_scope=sandbox_scope,
        preview_snapshot_id=preview_snapshot_id,
        pilot_source_row_index=pilot_source_row_index,
        require_diameter_plan=require_diameter_plan,
        model_plan_hash=model_plan_hash,
        source_mode=source_mode,
    )
    payload = _wait(request.request_id, timeout_seconds)
    verification_status = payload.get("verification_status")
    retained_partial = (
        execution_mode != "sandbox"
        and
        verification_status == "partial"
        and payload.get("partial_success") is True
        and payload.get("retention_decision") == "kept"
        and payload.get("model_changes_kept") is True
    )
    if verification_status != "verified" and not retained_partial:
        error = RfaReaderError(format_fire_branch_verification_failure(payload))
        error.payload = payload
        raise error
    return payload


def request_create_fire_branch_preview(
    *,
    main_pipe_id: str | int,
    main_pipe_ids: list[str | int] | None = None,
    sprinkler_ids: list[str | int],
    level_id: str | int,
    branch_offset_cm: float,
    height_reference: str,
    source_mode: str = "cad",
    timeout_seconds: int = 180,
) -> dict:
    request = create_fire_branch_preview_request(
        main_pipe_id=main_pipe_id,
        main_pipe_ids=main_pipe_ids,
        sprinkler_ids=sprinkler_ids,
        level_id=level_id,
        branch_offset_cm=branch_offset_cm,
        height_reference=height_reference,
        source_mode=source_mode,
    )
    return _wait(request.request_id, timeout_seconds)


def request_focus_fire_branch_segment(
    *,
    start: dict,
    end: dict,
    display_z: float | None = None,
    padding_mm: float = 750,
    timeout_seconds: int = 30,
) -> dict:
    request = create_fire_branch_focus_request(
        start=start,
        end=end,
        display_z=display_z,
        padding_mm=padding_mm,
    )
    return _wait(request.request_id, timeout_seconds)
