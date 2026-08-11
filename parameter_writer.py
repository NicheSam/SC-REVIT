from queue_protocol import (
    create_add_parameters_request,
    create_set_string_values_request,
    ensure_queue_dirs,
)
from rfa_reader import RfaReaderError, validate_rfa_path
from sc_revit.core.revit_queue_client import wait_for_revit_response


def request_add_missing_string_parameters(
    raw_path: str,
    parameter_names: list[str],
    timeout_seconds: int = 120,
) -> dict:
    rfa_path = validate_rfa_path(raw_path)
    ensure_queue_dirs()
    request = create_add_parameters_request(
        str(rfa_path),
        [{"name": name} for name in parameter_names],
    )
    return wait_for_revit_response(
        request.request_id,
        timeout_seconds,
        failure_message="新增參數失敗",
        timeout_message="等待 Revit 新增參數逾時",
    )


def request_set_string_parameter_values(
    raw_path: str,
    values: dict[str, str],
    timeout_seconds: int = 120,
) -> dict:
    rfa_path = validate_rfa_path(raw_path)
    ensure_queue_dirs()
    request = create_set_string_values_request(str(rfa_path), values)
    return wait_for_revit_response(
        request.request_id,
        timeout_seconds,
        failure_message="寫入參數值失敗",
        timeout_message="等待 Revit 寫入參數值逾時",
    )
