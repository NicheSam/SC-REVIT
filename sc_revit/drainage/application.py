from __future__ import annotations

import uuid
import time
from typing import Any

from settings_store import load_settings

from . import client
from .configuration_resolver import recommend_drainage_configuration
from .models import ConfirmationRef, DrainageIntent, OperationRef, SnapshotRef


class DrainageApplicationService:
    """Shared orchestration used by both the Tk presenter and Agent adapter."""

    def __init__(self) -> None:
        self._configuration_tokens: dict[str, dict[str, Any]] = {}

    def get_context(self, *, timeout_seconds: int = 120) -> dict[str, Any]:
        payload = client.request_drainage_context(timeout_seconds)
        self._require_document(payload)
        return payload

    def read_selection(self, *, timeout_seconds: int = 120) -> dict[str, Any]:
        payload = client.request_drainage_selection(timeout_seconds)
        self._require_document(payload)
        return payload

    def search_targets(
        self,
        *,
        document_fingerprint: str,
        document_revision: int,
        scope: str = "active_view",
        max_results: int = 200,
        explicit_element_ids: list[str] | None = None,
        pipe_type_ids: list[str] | None = None,
        system_type_ids: list[str] | None = None,
        level_ids: list[str] | None = None,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        payload = client.request_drainage_target_search(
            document_fingerprint=document_fingerprint,
            document_revision=document_revision,
            scope=scope,
            max_results=max_results,
            explicit_element_ids=explicit_element_ids or [],
            pipe_type_ids=pipe_type_ids or [],
            system_type_ids=system_type_ids or [],
            level_ids=level_ids or [],
            timeout_seconds=timeout_seconds,
        )
        self._require_document(payload)
        return payload

    def recommend_configuration(
        self,
        *,
        document_fingerprint: str,
        document_revision: int,
        main_pipe_id: str,
        main_pipe_unique_id: str,
        diameter_mm: float,
        history_limit: int = 100,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        context = self.get_context(timeout_seconds=timeout_seconds)
        document = context["document"]
        if (
            str(document.get("fingerprint") or "")
            != document_fingerprint
            or int(document.get("revision") or 0)
            != document_revision
        ):
            raise RuntimeError(
                "RECOMMENDATION_DOCUMENT_MISMATCH"
            )
        selection = self.read_selection(
            timeout_seconds=timeout_seconds
        )
        matching_pipes = [
            item
            for item in selection.get("pipes") or []
            if str(item.get("element_id") or "") == main_pipe_id
            and str(item.get("unique_id") or "")
            == main_pipe_unique_id
        ]
        if len(matching_pipes) != 1:
            raise RuntimeError(
                "RECOMMENDATION_MAIN_NOT_IN_CURRENT_SELECTION"
            )
        saved_settings = load_settings().get("drainage") or {}
        result = recommend_drainage_configuration(
            context=context,
            main_pipe=matching_pipes[0],
            diameter_mm=diameter_mm,
            saved_settings=(
                saved_settings
                if isinstance(saved_settings, dict)
                else {}
            ),
            history_limit=history_limit,
        )
        result["recommendation_token"] = ""
        result["recommendation_token_expires_at_unix"] = 0
        if result.get("auto_select_allowed"):
            token = "DCR-" + uuid.uuid4().hex
            expires_at = time.time() + 300
            recommendation = (
                result.get("recommended_configuration") or {}
            )
            self._configuration_tokens[token] = {
                "expires_at": expires_at,
                "document_fingerprint": document_fingerprint,
                "document_revision": document_revision,
                "main_pipe_id": main_pipe_id,
                "main_pipe_unique_id": main_pipe_unique_id,
                "diameter_mm": diameter_mm,
                "pipe_type_unique_id": str(
                    (recommendation.get("pipe_type") or {}).get(
                        "unique_id"
                    )
                    or ""
                ),
                "system_type_unique_id": str(
                    (recommendation.get("system_type") or {}).get(
                        "unique_id"
                    )
                    or ""
                ),
                "level_unique_id": str(
                    (recommendation.get("level") or {}).get(
                        "unique_id"
                    )
                    or ""
                ),
                "junction_type_unique_id": str(
                    (recommendation.get("junction") or {}).get(
                        "unique_id"
                    )
                    or ""
                ),
                "elbow_type_unique_id": str(
                    (recommendation.get("elbow") or {}).get(
                        "unique_id"
                    )
                    or ""
                ),
            }
            result["recommendation_token"] = token
            result["recommendation_token_expires_at_unix"] = expires_at
        return result

    def get_gui_workspace(
        self,
        *,
        diameter_mm: float,
        cached_context: dict[str, Any] | None = None,
        history_limit: int = 100,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        """Load the current selection and its bounded project configuration."""
        selection = self.read_selection(timeout_seconds=timeout_seconds)
        selection_document = selection["document"]
        context = cached_context
        context_document = (context or {}).get("document") or {}
        if (
            not context
            or str(context_document.get("fingerprint") or "")
            != str(selection_document.get("fingerprint") or "")
            or int(context_document.get("revision") or 0)
            != int(selection_document.get("revision") or 0)
        ):
            context = self.get_context(timeout_seconds=timeout_seconds)

        pipes = list(selection.get("pipes") or [])
        recommendation = None
        if len(pipes) == 1:
            saved_settings = load_settings().get("drainage") or {}
            recommendation = recommend_drainage_configuration(
                context=context,
                main_pipe=pipes[0],
                diameter_mm=diameter_mm,
                saved_settings=(
                    saved_settings
                    if isinstance(saved_settings, dict)
                    else {}
                ),
                history_limit=history_limit,
            )
        return {
            "context": context,
            "selection": selection,
            "recommendation": recommendation,
        }

    def preview(
        self,
        intent: DrainageIntent,
        *,
        configuration_recommendation_token: str = "",
        require_configuration_token: bool = False,
        timeout_seconds: int = 120,
    ) -> tuple[dict[str, Any], SnapshotRef]:
        intent.validate()
        if require_configuration_token:
            self._validate_configuration_token(
                configuration_recommendation_token,
                intent,
            )
        preview_arguments = dict(
            document_fingerprint=intent.document_fingerprint,
            document_revision=intent.document_revision,
            main_pipe_id=intent.main_pipe_id,
            main_pipe_unique_id=intent.main_pipe_unique_id,
            fixture_ids=list(intent.fixture_ids),
            fixture_unique_ids=list(intent.fixture_unique_ids),
            selection_source=intent.selection_source,
            main_candidate_count=intent.main_candidate_count,
            candidate_set_token=intent.candidate_set_token,
            pipe_type_id=intent.pipe_type_id,
            pipe_type_unique_id=intent.pipe_type_unique_id,
            system_type_id=intent.system_type_id,
            system_type_unique_id=intent.system_type_unique_id,
            level_id=intent.level_id,
            level_unique_id=intent.level_unique_id,
            junction_type_id=intent.junction_type_id,
            junction_type_unique_id=intent.junction_type_unique_id,
            elbow_type_id=intent.elbow_type_id,
            elbow_type_unique_id=intent.elbow_type_unique_id,
            slope_ratio=intent.slope_ratio,
            diameter_mm=intent.diameter_mm,
            downstream_mode=intent.downstream_mode,
            timeout_seconds=timeout_seconds,
        )
        if intent.source_connector_origin is not None:
            preview_arguments["source_connector_origin"] = (
                intent.source_connector_origin
            )
        if intent.route_policy is not None:
            preview_arguments["route_policy"] = (
                intent.route_policy.as_payload()
            )
        payload = client.request_create_drainage_preview(
            **preview_arguments,
        )
        snapshot = SnapshotRef.from_preview(payload)
        return payload, snapshot

    def _validate_configuration_token(
        self,
        token: str,
        intent: DrainageIntent,
    ) -> None:
        record = self._configuration_tokens.get(token)
        try:
            expires_at = float((record or {}).get("expires_at") or 0)
        except (TypeError, ValueError):
            expires_at = 0
        if not record or expires_at < time.time():
            self._configuration_tokens.pop(token, None)
            raise RuntimeError(
                "CONFIGURATION_RECOMMENDATION_TOKEN_INVALID"
            )
        expected = {
            "document_fingerprint": intent.document_fingerprint,
            "document_revision": intent.document_revision,
            "main_pipe_id": intent.main_pipe_id,
            "main_pipe_unique_id": intent.main_pipe_unique_id,
            "diameter_mm": intent.diameter_mm,
            "pipe_type_unique_id": intent.pipe_type_unique_id,
            "system_type_unique_id": intent.system_type_unique_id,
            "level_unique_id": intent.level_unique_id,
            "junction_type_unique_id":
                intent.junction_type_unique_id,
            "elbow_type_unique_id": intent.elbow_type_unique_id,
        }
        for key, value in expected.items():
            recorded = record.get(key)
            if isinstance(value, float):
                try:
                    matches = (
                        abs(float(recorded) - value) <= 0.01
                    )
                except (TypeError, ValueError):
                    matches = False
                if not matches:
                    raise RuntimeError(
                        "CONFIGURATION_RECOMMENDATION_TOKEN_MISMATCH"
                    )
            elif recorded != value:
                raise RuntimeError(
                    "CONFIGURATION_RECOMMENDATION_TOKEN_MISMATCH"
                )

    def confirm(
        self,
        snapshot: SnapshotRef,
        *,
        actor_kind: str,
        timeout_seconds: int = 120,
    ) -> ConfirmationRef:
        if actor_kind != "human":
            raise ValueError("actor_kind must be human")
        payload = client.request_confirm_drainage_snapshot(
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            document_fingerprint=snapshot.document_fingerprint,
            document_revision=snapshot.document_revision,
            actor_kind=actor_kind,
            timeout_seconds=timeout_seconds,
        )
        confirmation = ConfirmationRef.from_response(payload)
        if (
            confirmation.snapshot_id != snapshot.snapshot_id
            or confirmation.snapshot_hash != snapshot.snapshot_hash
        ):
            raise RuntimeError("confirmation is not bound to the requested snapshot")
        return confirmation

    def clear_preview(
        self,
        *,
        snapshot_id: str,
        snapshot_hash: str,
        document_fingerprint: str,
        document_revision: int,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        return client.request_clear_drainage_preview(
            snapshot_id=snapshot_id,
            snapshot_hash=snapshot_hash,
            document_fingerprint=document_fingerprint,
            document_revision=document_revision,
            timeout_seconds=timeout_seconds,
        )

    def commit(
        self,
        snapshot: SnapshotRef,
        confirmation: ConfirmationRef,
        *,
        operation: OperationRef | None = None,
        actor_kind: str = "human_gui",
        timeout_seconds: int = 180,
    ) -> tuple[dict[str, Any], OperationRef]:
        if not snapshot.ready_to_commit:
            raise ValueError("snapshot is blocked and cannot be committed")
        if confirmation.snapshot_hash != snapshot.snapshot_hash:
            raise ValueError("confirmation does not match snapshot")
        current_context = self.get_context(timeout_seconds=timeout_seconds)
        current_document = current_context["document"]
        if (
            str(current_document.get("fingerprint") or "")
            != snapshot.document_fingerprint
            or int(current_document.get("revision") or 0)
            != snapshot.document_revision
        ):
            raise RuntimeError("active Revit document no longer matches snapshot")
        operation = operation or OperationRef(
            operation_id="DOP-" + uuid.uuid4().hex,
            idempotency_key="DIK-" + uuid.uuid4().hex,
        )
        payload = client.request_create_drainage_pipes(
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            confirmation_id=confirmation.confirmation_id,
            operation_id=operation.operation_id,
            idempotency_key=operation.idempotency_key,
            actor_kind=actor_kind,
            timeout_seconds=timeout_seconds,
        )
        return payload, operation

    def get_operation(
        self,
        operation_id: str,
        *,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        return client.request_get_drainage_operation(operation_id, timeout_seconds)

    def validate_operation(
        self,
        operation_id: str,
        *,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        operation = self.get_operation(
            operation_id,
            timeout_seconds=timeout_seconds,
        )
        if operation.get("status") != "committed":
            raise RuntimeError(
                "operation is not committed: "
                + str(operation.get("status") or "unknown")
            )
        result = operation.get("result") or {}
        expected_slope_ratio = float(result.get("slope_ratio") or 0)
        if expected_slope_ratio <= 0:
            raise RuntimeError(
                "committed operation has no slope evidence"
            )
        return self.validate_commit(
            result,
            expected_slope_ratio=expected_slope_ratio,
            timeout_seconds=timeout_seconds,
        )

    def validate_commit(
        self,
        commit_payload: dict[str, Any],
        *,
        expected_slope_ratio: float,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        return client.request_validate_drainage_result(
            commit_payload.get("created_element_ids", []),
            operation_id=str(commit_payload.get("operation_id") or ""),
            expected_slope_ratio=expected_slope_ratio,
            route_evidence=commit_payload.get("created", []),
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _require_document(payload: dict[str, Any]) -> dict[str, Any]:
        document = payload.get("document") or {}
        if not document.get("fingerprint"):
            raise RuntimeError("Revit response is missing document fingerprint")
        return document


default_service = DrainageApplicationService()


def request_drainage_context(timeout_seconds: int = 120) -> dict[str, Any]:
    return default_service.get_context(timeout_seconds=timeout_seconds)


def request_drainage_selection(timeout_seconds: int = 120) -> dict[str, Any]:
    return default_service.read_selection(timeout_seconds=timeout_seconds)
