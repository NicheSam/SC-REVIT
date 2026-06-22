from queue_protocol import (
    create_connect_pipe_fittings_request,
    create_diagnose_mep_connectors_request,
)
from sc_revit.core.revit_queue_client import wait_for_revit_response

_FAILURE = "Revit 接頭診斷請求失敗"
_TIMEOUT = "等待 Revit 回傳接頭診斷資料逾時"


def request_diagnose_mep_connectors(
    *,
    max_distance_mm: float = 50,
    timeout_seconds: int = 120,
) -> dict:
    request = create_diagnose_mep_connectors_request(max_distance_mm=max_distance_mm)
    return wait_for_revit_response(
        request.request_id,
        timeout_seconds,
        failure_message=_FAILURE,
        timeout_message=_TIMEOUT,
    )


def request_connect_pipe_fittings(
    *,
    max_distance_mm: float = 50,
    timeout_seconds: int = 180,
) -> dict:
    request = create_connect_pipe_fittings_request(max_distance_mm=max_distance_mm)
    return wait_for_revit_response(
        request.request_id,
        timeout_seconds,
        failure_message=_FAILURE,
        timeout_message=_TIMEOUT,
    )
