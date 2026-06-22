from queue_protocol import create_inspect_selected_elements_request
from sc_revit.core.revit_queue_client import wait_for_revit_response

_FAILURE = "Revit 元件檢查請求失敗"
_TIMEOUT = "等待 Revit 回傳元件檢查資料逾時"


def request_inspect_selected_elements(timeout_seconds: int = 120) -> dict:
    request = create_inspect_selected_elements_request()
    return wait_for_revit_response(
        request.request_id,
        timeout_seconds,
        failure_message=_FAILURE,
        timeout_message=_TIMEOUT,
    )
