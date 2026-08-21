import json
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from sc_revit.core.batch import get_active_batch_id, record_request_created


BASE_DIR = Path(__file__).parent
QUEUE_DIR = (
    Path(
        os.environ.get(
            "SC_REVIT_RUNTIME_DIR",
            str(Path(os.environ.get("LOCALAPPDATA", str(BASE_DIR))) / "RevitFamilyClassifier" / "runtime"),
        )
    )
    / "queue"
)
REQUEST_DIR = QUEUE_DIR / "requests"
RESPONSE_DIR = QUEUE_DIR / "responses"
ERROR_DIR = QUEUE_DIR / "errors"
HEARTBEAT_FILE = QUEUE_DIR / "listener_heartbeat.json"
AGENT_LISTENER_ENABLED_FILE = QUEUE_DIR / "agent_listener.enabled"
_GUI_REQUEST_MODE = False
_GUI_REQUEST_IDS: set[str] = set()
_GUI_REQUEST_LOCK = threading.Lock()
_GUI_OWNS_LISTENER_MARKER = False


@dataclass(frozen=True)
class QueueRequest:
    request_id: str
    rfa_path: str
    action: str = "read_metadata"


def ensure_queue_dirs() -> None:
    for path in (REQUEST_DIR, RESPONSE_DIR, ERROR_DIR):
        path.mkdir(parents=True, exist_ok=True)


def is_agent_listener_enabled() -> bool:
    return AGENT_LISTENER_ENABLED_FILE.is_file()


def set_agent_listener_enabled(enabled: bool) -> None:
    ensure_queue_dirs()
    if enabled:
        AGENT_LISTENER_ENABLED_FILE.write_text("enabled\n", encoding="ascii")
        return
    AGENT_LISTENER_ENABLED_FILE.unlink(missing_ok=True)
    HEARTBEAT_FILE.unlink(missing_ok=True)


def set_gui_request_mode(enabled: bool) -> None:
    global _GUI_REQUEST_MODE
    _GUI_REQUEST_MODE = enabled


def _begin_gui_request(request_id: str) -> None:
    global _GUI_OWNS_LISTENER_MARKER
    if not _GUI_REQUEST_MODE:
        return
    with _GUI_REQUEST_LOCK:
        if not _GUI_REQUEST_IDS:
            _GUI_OWNS_LISTENER_MARKER = not is_agent_listener_enabled()
            if _GUI_OWNS_LISTENER_MARKER:
                set_agent_listener_enabled(True)
        _GUI_REQUEST_IDS.add(request_id)


def finish_gui_request(request_id: str) -> None:
    global _GUI_OWNS_LISTENER_MARKER
    with _GUI_REQUEST_LOCK:
        _GUI_REQUEST_IDS.discard(request_id)
        if _GUI_REQUEST_IDS or not _GUI_OWNS_LISTENER_MARKER:
            return
        set_agent_listener_enabled(False)
        _GUI_OWNS_LISTENER_MARKER = False




def _write_request_json(request: QueueRequest, payload: dict) -> None:
    batch_id = get_active_batch_id()
    if batch_id:
        payload["sc_batch_id"] = batch_id
    record_request_created(request.request_id, request.action, payload)
    _begin_gui_request(request.request_id)
    request_path = REQUEST_DIR / f"{request.request_id}.json"
    temporary_path = REQUEST_DIR / f".{request.request_id}.{uuid.uuid4().hex}.tmp"
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary_path, request_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        finish_gui_request(request.request_id)
        raise

def create_request(rfa_path: str) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(request_id=str(uuid.uuid4()), rfa_path=rfa_path)
    payload = {
        "request_id": request.request_id,
        "rfa_path": request.rfa_path,
        "action": request.action,
    }
    _write_request_json(request, payload)
    return request


def create_add_parameters_request(rfa_path: str, parameters: list[dict]) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path=rfa_path,
        action="add_missing_string_parameters",
    )
    payload = {
        "request_id": request.request_id,
        "rfa_path": request.rfa_path,
        "action": request.action,
        "parameters": parameters,
    }
    _write_request_json(request, payload)
    return request


def create_set_string_values_request(rfa_path: str, values: dict[str, str]) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path=rfa_path,
        action="set_string_parameter_values",
    )
    payload = {
        "request_id": request.request_id,
        "rfa_path": request.rfa_path,
        "action": request.action,
        "values": values,
    }
    _write_request_json(request, payload)
    return request


def create_scan_project_families_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="scan_project_families",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
    }
    _write_request_json(request, payload)
    return request


def create_export_project_families_request(
    family_ids: list[int | str],
    output_dir: str,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="export_project_families",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "family_ids": [str(item) for item in family_ids],
        "output_dir": output_dir,
    }
    _write_request_json(request, payload)
    return request


def create_point_placement_context_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="list_point_placement_context",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
    }
    _write_request_json(request, payload)
    return request


def create_scan_cad_block_points_request(
    import_id: str | int,
    block_filter: str,
    limit: int,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="scan_cad_block_points",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
        "block_filter": block_filter,
        "limit": limit,
    }
    _write_request_json(request, payload)
    return request


def create_list_cad_block_names_request(import_id: str | int) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="list_cad_block_names",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
    }
    _write_request_json(request, payload)
    return request


def create_get_cad_import_path_request(import_id: str | int) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="get_cad_import_path",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
    }
    _write_request_json(request, payload)
    return request


def create_transform_dwg_block_points_request(
    import_id: str | int,
    points: list[dict],
    limit: int,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="transform_dwg_block_points",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
        "points": points,
        "limit": limit,
    }
    _write_request_json(request, payload)
    return request


def create_place_cad_block_points_request(
    *,
    import_id: str | int,
    symbol_id: str | int,
    level_id: str | int,
    block_filter: str,
    limit: int,
    offset_mm: float,
    duplicate_tolerance_mm: float,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="place_cad_block_points",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
        "symbol_id": str(symbol_id),
        "level_id": str(level_id),
        "block_filter": block_filter,
        "limit": limit,
        "offset_mm": offset_mm,
        "duplicate_tolerance_mm": duplicate_tolerance_mm,
    }
    _write_request_json(request, payload)
    return request


def create_place_dwg_block_points_request(
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
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="place_dwg_block_points",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
        "symbol_id": str(symbol_id),
        "level_id": str(level_id),
        "points": points,
        "offset_mm": offset_mm,
        "duplicate_tolerance_mm": duplicate_tolerance_mm,
        "preview_group_id": str(preview_group_id or ""),
        "preview_origin": preview_origin or {},
        "delete_preview_after_place": delete_preview_after_place,
        "points_are_model_coordinates": points_are_model_coordinates,
    }
    _write_request_json(request, payload)
    return request


def create_dwg_preview_markers_request(
    *,
    import_id: str | int,
    level_id: str | int,
    points: list[dict],
    offset_mm: float,
    marker_size_mm: float = 150,
    points_are_model_coordinates: bool = False,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="create_dwg_preview_markers",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "import_id": str(import_id),
        "level_id": str(level_id),
        "points": points,
        "offset_mm": offset_mm,
        "marker_size_mm": marker_size_mm,
        "points_are_model_coordinates": points_are_model_coordinates,
    }
    _write_request_json(request, payload)
    return request


def create_clear_dwg_preview_markers_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="clear_dwg_preview_markers",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
    }
    _write_request_json(request, payload)
    return request


def create_fire_branch_context_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="list_fire_branch_context",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
    }
    _write_request_json(request, payload)
    return request


def create_fire_branch_selection_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="read_fire_branch_selection",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
    }
    _write_request_json(request, payload)
    return request


def create_fire_branch_snapshot_request(
    *,
    main_pipe_id: str | int | None = None,
    main_pipe_ids: list[str | int] | None = None,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="read_fire_branch_snapshot",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
    }
    if main_pipe_id is not None:
        payload["main_pipe_id"] = str(main_pipe_id)
    if main_pipe_ids:
        payload["main_pipe_ids"] = [str(item) for item in main_pipe_ids]
    _write_request_json(request, payload)
    return request


def create_fire_branch_pipes_request(
    *,
    main_pipe_id: str | int,
    main_pipe_ids: list[str | int] | None = None,
    sprinkler_ids: list[str | int],
    pipe_type_id: str | int,
    system_type_id: str | int,
    level_id: str | int,
    diameter_mm: float,
    branch_offset_cm: float,
    height_reference: str,
    preview_group_id: str | int | None = None,
    delete_preview_after_create: bool = True,
    execution_mode: str = "commit",
    diameter_plan: list[dict] | None = None,
    topology_plan: dict | None = None,
    sandbox_scope: str | None = None,
    preview_snapshot_id: str | None = None,
    pilot_source_row_index: int | None = None,
    require_diameter_plan: bool = False,
    model_plan_hash: str | None = None,
    source_mode: str = "cad",
) -> QueueRequest:
    if execution_mode not in {"commit", "sandbox"}:
        raise ValueError("execution_mode must be 'commit' or 'sandbox'")
    if execution_mode == "sandbox":
        delete_preview_after_create = False
    if sandbox_scope == "single_sprinkler" and len(sprinkler_ids) != 1:
        raise ValueError("single_sprinkler sandbox requires exactly one sprinkler")
    if require_diameter_plan and not diameter_plan:
        raise ValueError("require_diameter_plan requires a non-empty diameter plan")
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action=(
            "test_fire_branch_pipes"
            if execution_mode == "sandbox"
            else "create_fire_branch_pipes"
        ),
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "main_pipe_id": str(main_pipe_id),
        "main_pipe_ids": [str(item) for item in (main_pipe_ids or [main_pipe_id])],
        "sprinkler_ids": [str(item) for item in sprinkler_ids],
        "pipe_type_id": str(pipe_type_id),
        "system_type_id": str(system_type_id),
        "level_id": str(level_id),
        "diameter_mm": diameter_mm,
        "branch_offset_cm": branch_offset_cm,
        "height_reference": height_reference,
        "delete_preview_after_create": delete_preview_after_create,
        "execution_mode": execution_mode,
        "require_diameter_plan": bool(require_diameter_plan),
        "source_mode": str(source_mode or "cad"),
    }
    if diameter_plan:
        payload["diameter_plan"] = diameter_plan
    if topology_plan:
        payload["topology_plan"] = topology_plan
    if preview_group_id:
        payload["preview_group_id"] = str(preview_group_id)
    if sandbox_scope:
        payload["sandbox_scope"] = str(sandbox_scope)
    if preview_snapshot_id:
        payload["preview_snapshot_id"] = str(preview_snapshot_id)
    if pilot_source_row_index is not None:
        payload["pilot_source_row_index"] = int(pilot_source_row_index)
    if model_plan_hash:
        payload["model_plan_hash"] = str(model_plan_hash)
    _write_request_json(request, payload)
    return request


def create_fire_branch_preview_request(
    *,
    main_pipe_id: str | int,
    main_pipe_ids: list[str | int] | None = None,
    sprinkler_ids: list[str | int],
    level_id: str | int,
    branch_offset_cm: float,
    height_reference: str,
    source_mode: str = "cad",
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="create_fire_branch_preview",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "main_pipe_id": str(main_pipe_id),
        "main_pipe_ids": [str(item) for item in (main_pipe_ids or [main_pipe_id])],
        "sprinkler_ids": [str(item) for item in sprinkler_ids],
        "level_id": str(level_id),
        "branch_offset_cm": branch_offset_cm,
        "height_reference": height_reference,
        "source_mode": str(source_mode or "cad"),
    }
    _write_request_json(request, payload)
    return request


def create_fire_branch_focus_request(
    *,
    start: dict,
    end: dict,
    display_z: float | None = None,
    padding_mm: float = 750,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="focus_fire_branch_preview_segment",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "start": {axis: float(start.get(axis) or 0) for axis in ("x", "y", "z")},
        "end": {axis: float(end.get(axis) or 0) for axis in ("x", "y", "z")},
        "padding_mm": float(padding_mm),
    }
    if display_z is not None:
        payload["display_z"] = float(display_z)
    _write_request_json(request, payload)
    return request


def create_drainage_context_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="list_drainage_context",
    )
    _write_request_json(request, {"request_id": request.request_id, "action": request.action})
    return request


def create_drainage_selection_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="read_drainage_selection",
    )
    _write_request_json(request, {"request_id": request.request_id, "action": request.action})
    return request


def create_drainage_target_search_request(
    *,
    document_fingerprint: str,
    document_revision: int,
    scope: str = "active_view",
    max_results: int = 200,
    explicit_element_ids: list[str] | None = None,
    pipe_type_ids: list[str] | None = None,
    system_type_ids: list[str] | None = None,
    level_ids: list[str] | None = None,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="search_drainage_targets",
    )
    _write_request_json(
        request,
        {
            "request_id": request.request_id,
            "action": request.action,
            "document_fingerprint": document_fingerprint,
            "document_revision": document_revision,
            "scope": scope,
            "max_results": max_results,
            "explicit_element_ids":
                list(explicit_element_ids or []),
            "pipe_type_ids": list(pipe_type_ids or []),
            "system_type_ids": list(system_type_ids or []),
            "level_ids": list(level_ids or []),
        },
    )
    return request


def create_drainage_preview_request(
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
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="create_drainage_preview",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "document_fingerprint": document_fingerprint,
        "document_revision": document_revision,
        "main_pipe_id": str(main_pipe_id),
        "main_pipe_unique_id": main_pipe_unique_id,
        "fixture_ids": [str(item) for item in fixture_ids],
        "fixture_unique_ids": list(fixture_unique_ids),
        "selection_source": selection_source,
        "main_candidate_count": main_candidate_count,
        "pipe_type_id": str(pipe_type_id),
        "pipe_type_unique_id": pipe_type_unique_id,
        "system_type_id": str(system_type_id),
        "system_type_unique_id": system_type_unique_id,
        "level_id": str(level_id),
        "level_unique_id": level_unique_id,
        "junction_type_id": str(junction_type_id),
        "junction_type_unique_id": junction_type_unique_id,
        "elbow_type_id": str(elbow_type_id),
        "elbow_type_unique_id": elbow_type_unique_id,
        "slope_ratio": slope_ratio,
        "diameter_mm": diameter_mm,
        "downstream_mode": downstream_mode,
    }
    if candidate_set_token is not None:
        payload["candidate_set_token"] = candidate_set_token
    if source_connector_origin is not None:
        payload["source_connector_origin"] = {
            key: float(source_connector_origin[key])
            for key in ("x", "y", "z")
        }
    if route_policy is not None:
        payload["route_policy"] = route_policy
    _write_request_json(request, payload)
    return request


def create_confirm_drainage_snapshot_request(
    *,
    snapshot_id: str,
    snapshot_hash: str,
    document_fingerprint: str,
    document_revision: int,
    actor_kind: str = "human",
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="confirm_drainage_snapshot",
    )
    _write_request_json(
        request,
        {
            "request_id": request.request_id,
            "action": request.action,
            "snapshot_id": snapshot_id,
            "snapshot_hash": snapshot_hash,
            "document_fingerprint": document_fingerprint,
            "document_revision": document_revision,
            "actor_kind": actor_kind,
        },
    )
    return request


def create_clear_drainage_preview_request(
    *,
    snapshot_id: str,
    snapshot_hash: str,
    document_fingerprint: str,
    document_revision: int,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="clear_drainage_preview",
    )
    _write_request_json(
        request,
        {
            "request_id": request.request_id,
            "action": request.action,
            "snapshot_id": snapshot_id,
            "snapshot_hash": snapshot_hash,
            "document_fingerprint": document_fingerprint,
            "document_revision": document_revision,
        },
    )
    return request


def create_drainage_pipes_request(
    *,
    snapshot_id: str,
    snapshot_hash: str,
    confirmation_id: str,
    operation_id: str,
    idempotency_key: str,
    actor_kind: str = "human_gui",
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="create_drainage_pipes",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "snapshot_id": snapshot_id,
        "snapshot_hash": snapshot_hash,
        "confirmation_id": confirmation_id,
        "operation_id": operation_id,
        "idempotency_key": idempotency_key,
        "actor_kind": actor_kind,
    }
    _write_request_json(request, payload)
    return request


def create_get_drainage_operation_request(operation_id: str) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="get_drainage_operation",
    )
    _write_request_json(
        request,
        {
            "request_id": request.request_id,
            "action": request.action,
            "operation_id": operation_id,
        },
    )
    return request


def create_validate_drainage_result_request(
    element_ids: list[str | int],
    *,
    operation_id: str = "",
    expected_slope_ratio: float = 0.01,
    route_evidence: list[dict] | None = None,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="validate_drainage_result",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "operation_id": operation_id,
        "element_ids": [str(item) for item in element_ids],
        "expected_slope_ratio": expected_slope_ratio,
        "route_evidence": route_evidence or [],
    }
    _write_request_json(request, payload)
    return request


def create_opening_context_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="list_opening_context",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
    }
    _write_request_json(request, payload)
    return request


def create_inspect_selected_elements_request() -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="inspect_selected_elements",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
    }
    _write_request_json(request, payload)
    return request


def create_scan_sc_parameters_request(
    *,
    scope: str = "selection",
    parameter_prefix: str = "SC_",
    expected_parameters: list[str] | None = None,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="scan_sc_parameters",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "scope": scope,
        "parameter_prefix": parameter_prefix,
        "expected_parameters": expected_parameters or [],
    }
    _write_request_json(request, payload)
    return request


def create_diagnose_mep_connectors_request(
    *,
    max_distance_mm: float = 50,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="diagnose_mep_connectors",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "max_distance_mm": max_distance_mm,
    }
    _write_request_json(request, payload)
    return request


def create_connect_pipe_fittings_request(
    *,
    max_distance_mm: float = 50,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="connect_pipe_fittings",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "max_distance_mm": max_distance_mm,
    }
    _write_request_json(request, payload)
    return request


def create_preview_piping_support_points_request(
    *,
    spacing_cm: float = 150,
    start_offset_cm: float = 30,
    end_offset_cm: float = 30,
    marker_size_cm: float = 10,
    support_family_id: str | int | None = None,
    support_type_id: str | int | None = None,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="preview_piping_support_points",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "spacing_cm": spacing_cm,
        "start_offset_cm": start_offset_cm,
        "end_offset_cm": end_offset_cm,
        "marker_size_cm": marker_size_cm,
        "support_family_id": "" if support_family_id is None else str(support_family_id),
        "support_type_id": "" if support_type_id is None else str(support_type_id),
    }
    _write_request_json(request, payload)
    return request


def create_scan_opening_candidates_request(
    *,
    link_id: str | int,
    mep_types: list[str],
    host_types: list[str],
    clearance_mm: float,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="scan_opening_candidates",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "link_id": str(link_id),
        "mep_types": mep_types,
        "host_types": host_types,
        "clearance_mm": clearance_mm,
    }
    _write_request_json(request, payload)
    return request


def create_view_opening_candidate_request(
    *,
    candidate: dict,
    box_size_cm: float = 250,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="view_opening_candidate",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "candidate": candidate,
        "box_size_cm": box_size_cm,
    }
    _write_request_json(request, payload)
    return request


def create_place_opening_markers_request(
    *,
    candidates: list[dict],
    clear_existing: bool = True,
    view_name_prefix: str = "SC 預留套管平面",
    dimension_type_id: str | int | None = None,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="place_opening_markers",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "candidates": candidates,
        "clear_existing": clear_existing,
        "view_name_prefix": view_name_prefix,
        "dimension_type_id": "" if dimension_type_id is None else str(dimension_type_id),
    }
    _write_request_json(request, payload)
    return request



def create_sync_tracked_elements_request(
    batch_id: str,
    element_ids: list[str | int] | None = None,
    products: list[dict] | None = None,
) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="sync_tracked_elements",
    )
    products = products or []
    element_ids = element_ids or [item.get("product_ref") for item in products if item.get("product_ref")]
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "batch_id": batch_id,
        "element_ids": [str(item) for item in element_ids],
    }
    if products:
        payload["products"] = [
            {
                "element_id": str(item.get("product_ref") or ""),
                "unique_id": str(item.get("element_unique_id") or ""),
                "document_title": str(item.get("document_title") or ""),
                "document_path": str(item.get("document_path") or ""),
                "group_id": str(item.get("group_id") or ""),
                "group_name": str(item.get("group_name") or ""),
            }
            for item in products
        ]
    _write_request_json(request, payload)
    return request


def create_delete_tracked_elements_request(batch_id: str, element_ids: list[str | int]) -> QueueRequest:
    ensure_queue_dirs()
    request = QueueRequest(
        request_id=str(uuid.uuid4()),
        rfa_path="",
        action="delete_tracked_elements",
    )
    payload = {
        "request_id": request.request_id,
        "action": request.action,
        "batch_id": batch_id,
        "element_ids": [str(item) for item in element_ids],
    }
    _write_request_json(request, payload)
    return request
