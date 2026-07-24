from queue_protocol import (
    create_clear_drainage_preview_request,
    create_confirm_drainage_snapshot_request,
    create_drainage_context_request,
    create_drainage_pipes_request,
    create_drainage_preview_request,
    create_drainage_selection_request,
    create_drainage_target_search_request,
    create_get_drainage_operation_request,
    create_validate_drainage_result_request,
)
from sc_revit.core.revit_queue_client import wait_for_revit_response

_FAILURE = "Revit 排水建模請求失敗"
_TIMEOUT = "等待 Revit 回傳排水建模資料逾時"


def _wait(request_id: str, timeout_seconds: int) -> dict:
    return wait_for_revit_response(
        request_id,
        timeout_seconds,
        failure_message=_FAILURE,
        timeout_message=_TIMEOUT,
    )


def request_drainage_context(timeout_seconds: int = 120) -> dict:
    return _wait(create_drainage_context_request().request_id, timeout_seconds)


def request_drainage_selection(timeout_seconds: int = 120) -> dict:
    return _wait(create_drainage_selection_request().request_id, timeout_seconds)


def request_drainage_target_search(
    *,
    document_fingerprint: str,
    document_revision: int,
    scope: str = "active_view",
    max_results: int = 200,
    explicit_element_ids: list[str] | None = None,
    pipe_type_ids: list[str] | None = None,
    system_type_ids: list[str] | None = None,
    level_ids: list[str] | None = None,
    timeout_seconds: int = 120,
) -> dict:
    request = create_drainage_target_search_request(
        document_fingerprint=document_fingerprint,
        document_revision=document_revision,
        scope=scope,
        max_results=max_results,
        explicit_element_ids=explicit_element_ids or [],
        pipe_type_ids=pipe_type_ids or [],
        system_type_ids=system_type_ids or [],
        level_ids=level_ids or [],
    )
    return _wait(request.request_id, timeout_seconds)


def request_create_drainage_preview(
    *,
    document_fingerprint: str,
    document_revision: int,
    main_pipe_id: str | int,
    main_pipe_unique_id: str,
    fixture_ids: list[str | int],
    fixture_unique_ids: list[str],
    selection_source: str,
    main_candidate_count: int,
    candidate_set_token: str | None = None,
    pipe_type_id: str | int,
    pipe_type_unique_id: str,
    system_type_id: str | int,
    system_type_unique_id: str,
    level_id: str | int,
    level_unique_id: str,
    junction_type_id: str | int,
    junction_type_unique_id: str,
    elbow_type_id: str | int,
    elbow_type_unique_id: str,
    slope_ratio: float = 0.01,
    diameter_mm: float = 100,
    downstream_mode: str = "auto",
    source_connector_origin: dict[str, float] | None = None,
    route_policy: dict[str, float] | None = None,
    timeout_seconds: int = 120,
) -> dict:
    request = create_drainage_preview_request(
        document_fingerprint=document_fingerprint,
        document_revision=document_revision,
        main_pipe_id=main_pipe_id,
        main_pipe_unique_id=main_pipe_unique_id,
        fixture_ids=fixture_ids,
        fixture_unique_ids=fixture_unique_ids,
        selection_source=selection_source,
        main_candidate_count=main_candidate_count,
        candidate_set_token=candidate_set_token,
        pipe_type_id=pipe_type_id,
        pipe_type_unique_id=pipe_type_unique_id,
        system_type_id=system_type_id,
        system_type_unique_id=system_type_unique_id,
        level_id=level_id,
        level_unique_id=level_unique_id,
        junction_type_id=junction_type_id,
        junction_type_unique_id=junction_type_unique_id,
        elbow_type_id=elbow_type_id,
        elbow_type_unique_id=elbow_type_unique_id,
        slope_ratio=slope_ratio,
        diameter_mm=diameter_mm,
        downstream_mode=downstream_mode,
        source_connector_origin=source_connector_origin,
        route_policy=route_policy,
    )
    return _wait(request.request_id, timeout_seconds)


def request_confirm_drainage_snapshot(
    *,
    snapshot_id: str,
    snapshot_hash: str,
    document_fingerprint: str,
    document_revision: int,
    actor_kind: str = "human",
    timeout_seconds: int = 120,
) -> dict:
    request = create_confirm_drainage_snapshot_request(
        snapshot_id=snapshot_id,
        snapshot_hash=snapshot_hash,
        document_fingerprint=document_fingerprint,
        document_revision=document_revision,
        actor_kind=actor_kind,
    )
    return _wait(request.request_id, timeout_seconds)


def request_clear_drainage_preview(
    *,
    snapshot_id: str,
    snapshot_hash: str,
    document_fingerprint: str,
    document_revision: int,
    timeout_seconds: int = 120,
) -> dict:
    request = create_clear_drainage_preview_request(
        snapshot_id=snapshot_id,
        snapshot_hash=snapshot_hash,
        document_fingerprint=document_fingerprint,
        document_revision=document_revision,
    )
    return _wait(request.request_id, timeout_seconds)


def request_create_drainage_pipes(
    *,
    snapshot_id: str,
    snapshot_hash: str,
    confirmation_id: str,
    operation_id: str,
    idempotency_key: str,
    actor_kind: str = "human_gui",
    timeout_seconds: int = 180,
) -> dict:
    request = create_drainage_pipes_request(
        snapshot_id=snapshot_id,
        snapshot_hash=snapshot_hash,
        confirmation_id=confirmation_id,
        operation_id=operation_id,
        idempotency_key=idempotency_key,
        actor_kind=actor_kind,
    )
    return _wait(request.request_id, timeout_seconds)


def request_get_drainage_operation(
    operation_id: str,
    timeout_seconds: int = 120,
) -> dict:
    request = create_get_drainage_operation_request(operation_id)
    return _wait(request.request_id, timeout_seconds)


def request_validate_drainage_result(
    element_ids: list[str | int],
    *,
    operation_id: str = "",
    expected_slope_ratio: float = 0.01,
    route_evidence: list[dict] | None = None,
    timeout_seconds: int = 120,
) -> dict:
    request = create_validate_drainage_result_request(
        element_ids,
        operation_id=operation_id,
        expected_slope_ratio=expected_slope_ratio,
        route_evidence=route_evidence,
    )
    return _wait(request.request_id, timeout_seconds)
