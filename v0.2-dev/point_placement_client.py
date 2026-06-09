import json
import time

from queue_protocol import (
    ERROR_DIR,
    RESPONSE_DIR,
    create_dwg_preview_markers_request,
    create_fire_branch_context_request,
    create_fire_branch_pipes_request,
    create_fire_branch_preview_request,
    create_fire_branch_selection_request,
    create_list_cad_block_names_request,
    create_place_cad_block_points_request,
    create_place_dwg_block_points_request,
    create_point_placement_context_request,
    create_scan_cad_block_points_request,
    create_transform_dwg_block_points_request,
    ensure_queue_dirs,
)
from rfa_reader import RfaReaderError


def _wait_for_response(request_id: str, timeout_seconds: int) -> dict:
    output_path = RESPONSE_DIR / f"{request_id}.json"
    error_path = ERROR_DIR / f"{request_id}.json"
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        if output_path.exists():
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            output_path.unlink(missing_ok=True)
            return payload
        if error_path.exists():
            try:
                payload = json.loads(error_path.read_text(encoding="utf-8"))
                message = payload.get("error", "Revit 批量點位放置請求失敗")
            except json.JSONDecodeError:
                message = "Revit 批量點位放置請求失敗"
            error_path.unlink(missing_ok=True)
            raise RfaReaderError(message)
        time.sleep(0.5)

    raise RfaReaderError("等待 Revit 回傳批量點位放置資料逾時")


def request_point_placement_context(timeout_seconds: int = 120) -> dict:
    ensure_queue_dirs()
    request = create_point_placement_context_request()
    return _wait_for_response(request.request_id, timeout_seconds)


def request_cad_block_preview(
    import_id: str | int,
    block_filter: str,
    limit: int = 10,
    timeout_seconds: int = 120,
) -> dict:
    ensure_queue_dirs()
    request = create_scan_cad_block_points_request(import_id, block_filter, limit)
    return _wait_for_response(request.request_id, timeout_seconds)


def request_cad_block_names(
    import_id: str | int,
    timeout_seconds: int = 120,
) -> dict:
    ensure_queue_dirs()
    request = create_list_cad_block_names_request(import_id)
    return _wait_for_response(request.request_id, timeout_seconds)


def request_place_cad_blocks(
    *,
    import_id: str | int,
    symbol_id: str | int,
    level_id: str | int,
    block_filter: str,
    limit: int,
    offset_mm: float,
    duplicate_tolerance_mm: float,
    timeout_seconds: int = 180,
) -> dict:
    ensure_queue_dirs()
    request = create_place_cad_block_points_request(
        import_id=import_id,
        symbol_id=symbol_id,
        level_id=level_id,
        block_filter=block_filter,
        limit=limit,
        offset_mm=offset_mm,
        duplicate_tolerance_mm=duplicate_tolerance_mm,
    )
    return _wait_for_response(request.request_id, timeout_seconds)


def request_transform_dwg_points(
    import_id: str | int,
    points: list[dict],
    limit: int = 10,
    timeout_seconds: int = 120,
) -> dict:
    ensure_queue_dirs()
    request = create_transform_dwg_block_points_request(import_id, points, limit)
    return _wait_for_response(request.request_id, timeout_seconds)


def request_place_dwg_blocks(
    *,
    import_id: str | int,
    symbol_id: str | int,
    level_id: str | int,
    points: list[dict],
    offset_mm: float,
    duplicate_tolerance_mm: float,
    preview_group_id: str | int | None = None,
    preview_origin: dict | None = None,
    delete_preview_after_place: bool = True,
    timeout_seconds: int = 180,
) -> dict:
    ensure_queue_dirs()
    request = create_place_dwg_block_points_request(
        import_id=import_id,
        symbol_id=symbol_id,
        level_id=level_id,
        points=points,
        offset_mm=offset_mm,
        duplicate_tolerance_mm=duplicate_tolerance_mm,
        preview_group_id=preview_group_id,
        preview_origin=preview_origin,
        delete_preview_after_place=delete_preview_after_place,
    )
    return _wait_for_response(request.request_id, timeout_seconds)


def request_create_dwg_preview_markers(
    *,
    import_id: str | int,
    level_id: str | int,
    points: list[dict],
    offset_mm: float,
    marker_size_mm: float = 150,
    timeout_seconds: int = 180,
) -> dict:
    ensure_queue_dirs()
    request = create_dwg_preview_markers_request(
        import_id=import_id,
        level_id=level_id,
        points=points,
        offset_mm=offset_mm,
        marker_size_mm=marker_size_mm,
    )
    return _wait_for_response(request.request_id, timeout_seconds)


def request_fire_branch_context(timeout_seconds: int = 120) -> dict:
    ensure_queue_dirs()
    request = create_fire_branch_context_request()
    return _wait_for_response(request.request_id, timeout_seconds)


def request_fire_branch_selection(timeout_seconds: int = 120) -> dict:
    ensure_queue_dirs()
    request = create_fire_branch_selection_request()
    return _wait_for_response(request.request_id, timeout_seconds)


def request_create_fire_branch_pipes(
    *,
    main_pipe_id: str | int,
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
    ensure_queue_dirs()
    request = create_fire_branch_pipes_request(
        main_pipe_id=main_pipe_id,
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
    return _wait_for_response(request.request_id, timeout_seconds)


def request_create_fire_branch_preview(
    *,
    main_pipe_id: str | int,
    sprinkler_ids: list[str | int],
    level_id: str | int,
    branch_offset_cm: float,
    height_reference: str,
    timeout_seconds: int = 180,
) -> dict:
    ensure_queue_dirs()
    request = create_fire_branch_preview_request(
        main_pipe_id=main_pipe_id,
        sprinkler_ids=sprinkler_ids,
        level_id=level_id,
        branch_offset_cm=branch_offset_cm,
        height_reference=height_reference,
    )
    return _wait_for_response(request.request_id, timeout_seconds)
