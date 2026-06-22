from queue_protocol import create_scan_sc_parameters_request
from sc_revit.core.revit_queue_client import wait_for_revit_response

_FAILURE = "Revit SC 參數掃描請求失敗"
_TIMEOUT = "等待 Revit 回傳 SC 參數掃描資料逾時"


def request_scan_sc_parameters(
    *,
    scope: str = "selection",
    parameter_prefix: str = "SC_",
    expected_parameters: list[str] | None = None,
    timeout_seconds: int = 120,
) -> dict:
    request = create_scan_sc_parameters_request(
        scope=scope,
        parameter_prefix=parameter_prefix,
        expected_parameters=expected_parameters,
    )
    return wait_for_revit_response(
        request.request_id,
        timeout_seconds,
        failure_message=_FAILURE,
        timeout_message=_TIMEOUT,
    )
