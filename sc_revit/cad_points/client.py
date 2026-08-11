from queue_protocol import (
    create_clear_dwg_preview_markers_request,
    create_dwg_preview_markers_request,
    create_get_cad_import_path_request,
    create_list_cad_block_names_request,
    create_place_cad_block_points_request,
    create_place_dwg_block_points_request,
    create_point_placement_context_request,
    create_scan_cad_block_points_request,
    create_transform_dwg_block_points_request,
)
from sc_revit.core.revit_queue_client import wait_for_revit_response

_FAILURE = "Revit 批量點位放置請求失敗"
_TIMEOUT = "等待 Revit 回傳批量點位放置資料逾時"


def _wait(request_id: str, timeout_seconds: int) -> dict:
    return wait_for_revit_response(
        request_id,
        timeout_seconds,
        failure_message=_FAILURE,
        timeout_message=_TIMEOUT,
    )


def request_point_placement_context(timeout_seconds: int = 120) -> dict:
    request = create_point_placement_context_request()
    return _wait(request.request_id, timeout_seconds)


def request_cad_block_preview(
    import_id: str | int,
    block_filter: str,
    limit: int = 10,
    timeout_seconds: int = 120,
) -> dict:
    request = create_scan_cad_block_points_request(import_id, block_filter, limit)
    return _wait(request.request_id, timeout_seconds)


def request_cad_block_names(import_id: str | int, timeout_seconds: int = 120) -> dict:
    request = create_list_cad_block_names_request(import_id)
    return _wait(request.request_id, timeout_seconds)


def request_cad_import_path(import_id: str | int, timeout_seconds: int = 30) -> dict:
    request = create_get_cad_import_path_request(import_id)
    return _wait(request.request_id, timeout_seconds)


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
    request = create_place_cad_block_points_request(
        import_id=import_id,
        symbol_id=symbol_id,
        level_id=level_id,
        block_filter=block_filter,
        limit=limit,
        offset_mm=offset_mm,
        duplicate_tolerance_mm=duplicate_tolerance_mm,
    )
    return _wait(request.request_id, timeout_seconds)


def request_transform_dwg_points(
    import_id: str | int,
    points: list[dict],
    limit: int = 10,
    timeout_seconds: int = 120,
) -> dict:
    request = create_transform_dwg_block_points_request(import_id, points, limit)
    return _wait(request.request_id, timeout_seconds)


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
    points_are_model_coordinates: bool = False,
    timeout_seconds: int = 180,
) -> dict:
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
        points_are_model_coordinates=points_are_model_coordinates,
    )
    return _wait(request.request_id, timeout_seconds)


def request_create_dwg_preview_markers(
    *,
    import_id: str | int,
    level_id: str | int,
    points: list[dict],
    offset_mm: float,
    marker_size_mm: float = 150,
    points_are_model_coordinates: bool = False,
    timeout_seconds: int = 180,
) -> dict:
    request = create_dwg_preview_markers_request(
        import_id=import_id,
        level_id=level_id,
        points=points,
        offset_mm=offset_mm,
        marker_size_mm=marker_size_mm,
        points_are_model_coordinates=points_are_model_coordinates,
    )
    return _wait(request.request_id, timeout_seconds)


def request_clear_dwg_preview_markers(timeout_seconds: int = 30) -> dict:
    request = create_clear_dwg_preview_markers_request()
    return _wait(request.request_id, timeout_seconds)
