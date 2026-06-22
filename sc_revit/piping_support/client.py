from queue_protocol import create_preview_piping_support_points_request
from sc_revit.core.revit_queue_client import wait_for_revit_response

_FAILURE = "Revit 管支撐候選點請求失敗"
_TIMEOUT = "等待 Revit 回傳管支撐候選點資料逾時"


def request_preview_piping_support_points(
    *,
    spacing_cm: float = 150,
    start_offset_cm: float = 30,
    end_offset_cm: float = 30,
    marker_size_cm: float = 10,
    support_family_id: str | int | None = None,
    support_type_id: str | int | None = None,
    timeout_seconds: int = 180,
) -> dict:
    request = create_preview_piping_support_points_request(
        spacing_cm=spacing_cm,
        start_offset_cm=start_offset_cm,
        end_offset_cm=end_offset_cm,
        marker_size_cm=marker_size_cm,
        support_family_id=support_family_id,
        support_type_id=support_type_id,
    )
    return wait_for_revit_response(
        request.request_id,
        timeout_seconds,
        failure_message=_FAILURE,
        timeout_message=_TIMEOUT,
    )
