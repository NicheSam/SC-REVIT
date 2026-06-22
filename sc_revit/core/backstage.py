from queue_protocol import create_delete_tracked_elements_request, create_sync_tracked_elements_request
from sc_revit.core.batch import BatchStore, activate_batch
from sc_revit.core.revit_queue_client import wait_for_revit_response

_FAILURE = "Revit 後台管理失敗，請確認 Revit 仍可操作且沒有警告視窗卡住。"
_TIMEOUT = "等待 Revit 後台管理回應逾時，請確認 Revit 沒有停在警告或對話框。"


def request_delete_tracked_elements(batch_id: str, timeout_seconds: int = 120) -> dict:
    store = BatchStore()
    element_ids = store.list_active_revit_element_ids(batch_id)
    if not element_ids:
        return {
            "batch_id": batch_id,
            "requested_count": 0,
            "deleted_count": 0,
            "deleted_element_ids": [],
            "failed": [],
            "ungrouped_group_ids": [],
        }
    with activate_batch(batch_id):
        request = create_delete_tracked_elements_request(batch_id=batch_id, element_ids=element_ids)
        payload = wait_for_revit_response(
            request.request_id,
            timeout_seconds,
            failure_message=_FAILURE,
            timeout_message=_TIMEOUT,
        )
    deleted = [str(item) for item in payload.get("deleted_element_ids", [])]
    store.mark_products_deleted(batch_id, deleted)
    return payload


def request_sync_tracked_elements(batch_id: str, timeout_seconds: int = 30) -> dict:
    store = BatchStore()
    products = store.list_active_revit_products(batch_id)
    if not products:
        return {
            "batch_id": batch_id,
            "existing_count": 0,
            "missing_count": 0,
            "unknown_count": 0,
            "existing_element_ids": [],
            "missing_element_ids": [],
            "unknown_element_ids": [],
        }
    request = create_sync_tracked_elements_request(batch_id, products=products)
    payload = wait_for_revit_response(
        request.request_id,
        timeout_seconds=timeout_seconds,
        failure_message=_FAILURE,
        timeout_message=_TIMEOUT,
    )
    existing = [str(item) for item in payload.get("existing_element_ids", [])]
    missing = [str(item) for item in payload.get("missing_element_ids", [])]
    unknown = [str(item) for item in payload.get("unknown_element_ids", [])]
    document_mismatch = [str(item) for item in payload.get("document_mismatch_element_ids", [])]
    store.update_product_sync_status(
        batch_id,
        existing,
        missing,
        unknown,
        document_mismatch_ids=document_mismatch,
        relinked=payload.get("relinked_elements", []),
        element_states=payload.get("element_states", []),
    )
    return payload
