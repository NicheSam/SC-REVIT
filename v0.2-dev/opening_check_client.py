from queue_protocol import (
    create_opening_context_request,
    create_place_opening_markers_request,
    create_scan_opening_candidates_request,
    create_view_opening_candidate_request,
    ensure_queue_dirs,
)
from point_placement_client import _wait_for_response


def request_opening_context(timeout_seconds: int = 120) -> dict:
    ensure_queue_dirs()
    request = create_opening_context_request()
    return _wait_for_response(request.request_id, timeout_seconds)


def request_scan_opening_candidates(
    *,
    link_id: str | int,
    mep_types: list[str],
    host_types: list[str],
    clearance_mm: float,
    timeout_seconds: int = 240,
) -> dict:
    ensure_queue_dirs()
    request = create_scan_opening_candidates_request(
        link_id=link_id,
        mep_types=mep_types,
        host_types=host_types,
        clearance_mm=clearance_mm,
    )
    return _wait_for_response(request.request_id, timeout_seconds)


def request_view_opening_candidate(
    *,
    candidate: dict,
    box_size_cm: float = 250,
    timeout_seconds: int = 120,
) -> dict:
    ensure_queue_dirs()
    request = create_view_opening_candidate_request(
        candidate=candidate,
        box_size_cm=box_size_cm,
    )
    return _wait_for_response(request.request_id, timeout_seconds)


def request_place_opening_markers(
    *,
    candidates: list[dict],
    clear_existing: bool = True,
    view_name_prefix: str = "SC 預留套管平面",
    dimension_type_id: str | int | None = None,
    timeout_seconds: int = 240,
) -> dict:
    ensure_queue_dirs()
    request = create_place_opening_markers_request(
        candidates=candidates,
        clear_existing=clear_existing,
        view_name_prefix=view_name_prefix,
        dimension_type_id=dimension_type_id,
    )
    return _wait_for_response(request.request_id, timeout_seconds)
