from __future__ import annotations

from copy import deepcopy
from typing import Any

from .application import DrainageApplicationService, default_service
from .models import (
    ConfirmationRef,
    DrainageIntent,
    DrainageRoutePolicy,
    OperationRef,
    SnapshotRef,
)
from sc_revit.core.revit_queue_client import RevitQueueTimeoutError


class DrainageAgentTools:
    """Narrow Agent-facing adapter; it never accepts C# source or free-form mutation."""

    def __init__(self, service: DrainageApplicationService | None = None) -> None:
        self._service = service or default_service

    def get_context(self) -> dict[str, Any]:
        return self._service.get_context()

    def inspect_current_selection(self) -> dict[str, Any]:
        return self._service.read_selection()

    def search_targets(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._service.search_targets(
            document_fingerprint=str(
                arguments.get("document_fingerprint") or ""
            ),
            document_revision=int(
                arguments.get("document_revision") or 0
            ),
            scope=str(arguments.get("scope") or "active_view"),
            max_results=int(arguments.get("max_results") or 200),
            explicit_element_ids=[
                str(item)
                for item in arguments.get(
                    "explicit_element_ids"
                )
                or []
            ],
            pipe_type_ids=[
                str(item)
                for item in arguments.get("pipe_type_ids")
                or []
            ],
            system_type_ids=[
                str(item)
                for item in arguments.get("system_type_ids")
                or []
            ],
            level_ids=[
                str(item)
                for item in arguments.get("level_ids")
                or []
            ],
        )

    def recommend_configuration(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        main_pipe = arguments.get("main_pipe") or {}
        return self._service.recommend_configuration(
            document_fingerprint=str(
                arguments.get("document_fingerprint") or ""
            ),
            document_revision=int(
                arguments.get("document_revision") or 0
            ),
            main_pipe_id=str(
                main_pipe.get("element_id") or ""
            ),
            main_pipe_unique_id=str(
                main_pipe.get("unique_id") or ""
            ),
            diameter_mm=float(
                arguments.get("diameter_mm") or 100
            ),
            history_limit=int(
                arguments.get("history_limit") or 100
            ),
        )

    def connect_to_main(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        recommendation = self.recommend_configuration(arguments)
        if not recommendation.get("auto_select_allowed"):
            return {
                "status": "blocked",
                "recommendation": recommendation,
                "snapshot": None,
                "preview": None,
                "next_action": "resolve_configuration_or_flow_ambiguity",
            }
        configuration = (
            recommendation.get("recommended_configuration") or {}
        )
        preview_arguments = dict(arguments)
        preview_arguments["pipe_type"] = (
            configuration.get("pipe_type") or {}
        )
        preview_arguments["system_type"] = (
            configuration.get("system_type") or {}
        )
        preview_arguments["level"] = configuration.get("level") or {}
        preview_arguments["fitting_profile"] = {
            "junction": configuration.get("junction") or {},
            "elbow": configuration.get("elbow") or {},
        }
        preview_arguments["configuration_recommendation_token"] = str(
            recommendation.get("recommendation_token") or ""
        )
        preview_result = self.preview(preview_arguments)
        return {
            "status": preview_result["status"],
            "recommendation": recommendation,
            "snapshot": preview_result["snapshot"],
            "preview": preview_result["preview"],
            "next_action": (
                "drainage.request_human_confirmation"
                if preview_result["status"] == "ready"
                else "resolve_route_preflight_issues"
            ),
        }

    def preview(self, arguments: dict[str, Any]) -> dict[str, Any]:
        route_policy_arguments = arguments.get("route_policy")
        route_policy = (
            DrainageRoutePolicy(**route_policy_arguments)
            if route_policy_arguments is not None
            else None
        )
        intent = DrainageIntent(
            document_fingerprint=str(
                arguments.get("document_fingerprint") or ""
            ),
            document_revision=int(
                arguments.get("document_revision") or 0
            ),
            main_pipe_id=str(
                (arguments.get("main_pipe") or {}).get(
                    "element_id"
                )
                or ""
            ),
            fixture_ids=tuple(
                str(item.get("element_id") or "")
                for item in arguments.get("fixtures") or []
            ),
            pipe_type_id=str(
                (arguments.get("pipe_type") or {}).get("element_id")
                or ""
            ),
            pipe_type_unique_id=str(
                (arguments.get("pipe_type") or {}).get("unique_id")
                or ""
            ),
            system_type_id=str(
                (arguments.get("system_type") or {}).get("element_id")
                or ""
            ),
            system_type_unique_id=str(
                (arguments.get("system_type") or {}).get("unique_id")
                or ""
            ),
            level_id=str(
                (arguments.get("level") or {}).get("element_id")
                or ""
            ),
            level_unique_id=str(
                (arguments.get("level") or {}).get("unique_id")
                or ""
            ),
            junction_type_id=str(
                (
                    (arguments.get("fitting_profile") or {}).get(
                        "junction"
                    )
                    or {}
                ).get("element_id")
                or ""
            ),
            junction_type_unique_id=str(
                (
                    (arguments.get("fitting_profile") or {}).get(
                        "junction"
                    )
                    or {}
                ).get("unique_id")
                or ""
            ),
            elbow_type_id=str(
                (
                    (arguments.get("fitting_profile") or {}).get(
                        "elbow"
                    )
                    or {}
                ).get("element_id")
                or ""
            ),
            elbow_type_unique_id=str(
                (
                    (arguments.get("fitting_profile") or {}).get(
                        "elbow"
                    )
                    or {}
                ).get("unique_id")
                or ""
            ),
            slope_ratio=float(arguments.get("slope_ratio", 0.01)),
            diameter_mm=float(arguments.get("diameter_mm", 100)),
            downstream_mode=str(arguments.get("downstream_mode") or "auto"),
            route_policy=route_policy,
            main_pipe_unique_id=str(
                (arguments.get("main_pipe") or {}).get(
                    "unique_id"
                )
                or ""
            ),
            fixture_unique_ids=tuple(
                str(item.get("unique_id") or "")
                for item in arguments.get("fixtures") or []
            ),
            selection_source=str(
                (arguments.get("target_selection") or {}).get(
                    "source"
                )
                or ""
            ),
            main_candidate_count=int(
                (arguments.get("target_selection") or {}).get(
                    "main_candidate_count"
                )
                or 0
            ),
            candidate_set_token=(
                str(
                    (arguments.get("target_selection") or {}).get(
                        "candidate_set_token"
                    )
                    or ""
                )
                or None
            ),
            source_connector_origin=(
                {
                    axis: float(
                        (arguments.get("source_connector_origin") or {})[
                            axis
                        ]
                    )
                    for axis in ("x", "y", "z")
                }
                if arguments.get("source_connector_origin") is not None
                else None
            ),
        )
        payload, snapshot = self._service.preview(
            intent,
            configuration_recommendation_token=str(
                arguments.get(
                    "configuration_recommendation_token"
                )
                or ""
            ),
            require_configuration_token=True,
        )
        return {
            "status": "ready" if snapshot.ready_to_commit else "blocked",
            "snapshot": snapshot.__dict__,
            "preview": payload,
        }

    def clear_preview(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._service.clear_preview(
            snapshot_id=str(arguments.get("snapshot_id") or ""),
            snapshot_hash=str(arguments.get("snapshot_hash") or ""),
            document_fingerprint=str(
                arguments.get("document_fingerprint") or ""
            ),
            document_revision=int(
                arguments.get("document_revision") or 0
            ),
        )

    def request_human_confirmation(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = SnapshotRef(
            snapshot_id=str(arguments.get("snapshot_id") or ""),
            snapshot_hash=str(arguments.get("snapshot_hash") or ""),
            document_fingerprint=str(
                arguments.get("document_fingerprint") or ""
            ),
            document_revision=int(
                arguments.get("document_revision") or 0
            ),
            ready_to_commit=True,
        )
        confirmation = self._service.confirm(
            snapshot,
            actor_kind="human",
        )
        return {
            "status": "confirmed",
            "confirmation": confirmation.__dict__,
        }

    def commit_confirmed_snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        snapshot = SnapshotRef(
            snapshot_id=str(arguments.get("snapshot_id") or ""),
            snapshot_hash=str(arguments.get("snapshot_hash") or ""),
            document_fingerprint=str(arguments.get("document_fingerprint") or ""),
            document_revision=int(arguments.get("document_revision") or 0),
            ready_to_commit=True,
        )
        confirmation = ConfirmationRef(
            confirmation_id=str(arguments.get("confirmation_id") or ""),
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
        )
        operation = OperationRef(
            operation_id=str(arguments.get("operation_id") or ""),
            idempotency_key=str(arguments.get("idempotency_key") or ""),
        )
        if not operation.operation_id or not operation.idempotency_key:
            raise ValueError("operation_id and idempotency_key are required")
        try:
            payload, operation = self._service.commit(
                snapshot,
                confirmation,
                operation=operation,
                actor_kind="agent",
            )
        except RevitQueueTimeoutError:
            return {
                "status": "unknown",
                "operation": operation.__dict__,
                "next_action": "drainage.get_operation",
            }
        return {"status": "committed", "operation": operation.__dict__, "result": payload}

    def get_operation(self, operation_id: str) -> dict[str, Any]:
        return self._service.get_operation(operation_id)

    def validate_operation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._service.validate_operation(
            str(arguments.get("operation_id") or ""),
        )


AGENT_TOOL_SCHEMAS = {
    "drainage.get_context": {
        "risk": "readOnly",
        "input_schema": {"type": "object", "additionalProperties": False},
    },
    "drainage.inspect_current_selection": {
        "risk": "readOnly",
        "input_schema": {"type": "object", "additionalProperties": False},
    },
    "drainage.search_targets": {
        "risk": "readOnly",
        "input_schema": {
            "type": "object",
            "required": [
                "document_fingerprint",
                "document_revision",
                "scope",
            ],
            "properties": {
                "document_fingerprint": {
                    "type": "string",
                    "pattern": "^sha256:",
                },
                "document_revision": {
                    "type": "integer",
                    "minimum": 0,
                },
                "scope": {
                    "type": "string",
                    "enum": ["active_view", "document"],
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                },
                "explicit_element_ids": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "minLength": 1,
                    },
                },
                "pipe_type_ids": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "minLength": 1,
                    },
                },
                "system_type_ids": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "minLength": 1,
                    },
                },
                "level_ids": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "minLength": 1,
                    },
                },
            },
            "additionalProperties": False,
        },
    },
    "drainage.recommend_configuration": {
        "risk": "readOnly",
        "input_schema": {
            "type": "object",
            "required": [
                "document_fingerprint",
                "document_revision",
                "main_pipe",
                "diameter_mm",
            ],
            "properties": {
                "document_fingerprint": {
                    "type": "string",
                    "pattern": "^sha256:",
                },
                "document_revision": {
                    "type": "integer",
                    "minimum": 0,
                },
                "main_pipe": {
                    "type": "object",
                    "required": ["element_id", "unique_id"],
                    "properties": {
                        "element_id": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "unique_id": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                    "additionalProperties": False,
                },
                "diameter_mm": {
                    "type": "number",
                    "minimum": 25,
                    "maximum": 300,
                },
                "history_limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                },
            },
            "additionalProperties": False,
        },
    },
    "drainage.preview": {
        "risk": "readOnly",
        "input_schema": {
            "type": "object",
            "required": [
                "document_fingerprint",
                "document_revision",
                "main_pipe",
                "fixtures",
                "target_selection",
                "pipe_type",
                "system_type",
                "level",
                "fitting_profile",
                "slope_ratio",
                "diameter_mm",
                "downstream_mode",
                "configuration_recommendation_token",
            ],
            "properties": {
                "document_fingerprint": {
                    "type": "string",
                    "pattern": "^sha256:",
                },
                "document_revision": {
                    "type": "integer",
                    "minimum": 0,
                },
                "main_pipe": {
                    "type": "object",
                    "required": ["element_id", "unique_id"],
                    "properties": {
                        "element_id": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "unique_id": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                    "additionalProperties": False,
                },
                "fixtures": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["element_id", "unique_id"],
                        "properties": {
                            "element_id": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "unique_id": {
                                "type": "string",
                                "minLength": 1,
                            },
                        },
                        "additionalProperties": False,
                    },
                },
                "target_selection": {
                    "type": "object",
                    "required": [
                        "source",
                        "main_candidate_count",
                    ],
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": [
                                "current_selection",
                                "search_result",
                                "explicit_user_refs",
                            ],
                        },
                        "main_candidate_count": {
                            "type": "integer",
                            "const": 1,
                        },
                        "candidate_set_token": {
                            "type": "string",
                            "pattern": "^DCT-",
                        },
                    },
                    "additionalProperties": False,
                },
                "pipe_type": {
                    "type": "object",
                    "required": ["element_id", "unique_id"],
                    "properties": {
                        "element_id": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "unique_id": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                    "additionalProperties": False,
                },
                "system_type": {
                    "type": "object",
                    "required": ["element_id", "unique_id"],
                    "properties": {
                        "element_id": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "unique_id": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                    "additionalProperties": False,
                },
                "level": {
                    "type": "object",
                    "required": ["element_id", "unique_id"],
                    "properties": {
                        "element_id": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "unique_id": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                    "additionalProperties": False,
                },
                "fitting_profile": {
                    "type": "object",
                    "required": ["junction", "elbow"],
                    "properties": {
                        "junction": {
                            "type": "object",
                            "required": [
                                "element_id",
                                "unique_id",
                            ],
                            "properties": {
                                "element_id": {
                                    "type": "string",
                                    "minLength": 1,
                                },
                                "unique_id": {
                                    "type": "string",
                                    "minLength": 1,
                                },
                            },
                            "additionalProperties": False,
                        },
                        "elbow": {
                            "type": "object",
                            "required": [
                                "element_id",
                                "unique_id",
                            ],
                            "properties": {
                                "element_id": {
                                    "type": "string",
                                    "minLength": 1,
                                },
                                "unique_id": {
                                    "type": "string",
                                    "minLength": 1,
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
                "slope_ratio": {
                    "type": "number",
                    "minimum": 0.001,
                    "maximum": 0.10,
                },
                "diameter_mm": {
                    "type": "number",
                    "minimum": 25,
                    "maximum": 300,
                },
                "downstream_mode": {
                    "type": "string",
                    "enum": ["auto", "end0", "end1"],
                },
                "source_connector_origin": {
                    "type": "object",
                    "required": ["x", "y", "z"],
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"},
                    },
                    "additionalProperties": False,
                },
                "configuration_recommendation_token": {
                    "type": "string",
                    "pattern": "^DCR-",
                },
                "route_policy": {
                    "type": "object",
                    "properties": {
                        "route_policy_id": {
                            "type": "string",
                            "const": "sc-drainage-route-policy",
                        },
                        "route_policy_version": {
                            "type": "string",
                            "const": "1.1.0",
                        },
                        "side_entry_angle_degrees": {
                            "type": "number",
                            "const": 45,
                        },
                        "side_entry_tolerance_degrees": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 15,
                        },
                        "radial_minimum_degrees": {
                            "type": "number",
                            "minimum": -15,
                            "maximum": 90,
                        },
                        "radial_maximum_degrees": {
                            "type": "number",
                            "minimum": -15,
                            "maximum": 90,
                        },
                        "radial_tolerance_degrees": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 15,
                        },
                        "minimum_tangent_mm": {
                            "type": "number",
                            "minimum": 25,
                            "maximum": 3000,
                        },
                        "minimum_junction_spacing_mm": {
                            "type": "number",
                            "minimum": 100,
                            "maximum": 10000,
                        },
                        "collision_clearance_mm": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1000,
                        },
                        "maximum_double45_lateral_offset_mm": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1000,
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
    },
    "drainage.clear_preview": {
        "risk": "readOnly",
        "input_schema": {
            "type": "object",
            "required": [
                "snapshot_id",
                "snapshot_hash",
                "document_fingerprint",
                "document_revision",
            ],
            "properties": {
                "snapshot_id": {"type": "string", "minLength": 1},
                "snapshot_hash": {
                    "type": "string",
                    "pattern": "^sha256:",
                },
                "document_fingerprint": {
                    "type": "string",
                    "pattern": "^sha256:",
                },
                "document_revision": {
                    "type": "integer",
                    "minimum": 0,
                },
            },
            "additionalProperties": False,
        },
    },
    "drainage.request_human_confirmation": {
        "risk": "confirmation",
        "opens_revit_confirmation_dialog": True,
        "input_schema": {
            "type": "object",
            "required": [
                "snapshot_id",
                "snapshot_hash",
                "document_fingerprint",
                "document_revision",
            ],
            "properties": {
                "snapshot_id": {"type": "string", "minLength": 1},
                "snapshot_hash": {
                    "type": "string",
                    "pattern": "^sha256:",
                },
                "document_fingerprint": {
                    "type": "string",
                    "pattern": "^sha256:",
                },
                "document_revision": {
                    "type": "integer",
                    "minimum": 0,
                },
            },
            "additionalProperties": False,
        },
    },
    "drainage.commit_confirmed_snapshot": {
        "risk": "modelMutation",
        "requires_human_confirmation": True,
        "input_schema": {
            "type": "object",
            "required": [
                "snapshot_id",
                "snapshot_hash",
                "document_fingerprint",
                "document_revision",
                "confirmation_id",
                "operation_id",
                "idempotency_key",
            ],
            "properties": {
                "snapshot_id": {"type": "string", "minLength": 1},
                "snapshot_hash": {"type": "string", "pattern": "^sha256:"},
                "document_fingerprint": {"type": "string", "pattern": "^sha256:"},
                "document_revision": {"type": "integer", "minimum": 0},
                "confirmation_id": {"type": "string", "minLength": 1},
                "operation_id": {
                    "type": "string",
                    "pattern": "^DOP-.{8,}$",
                },
                "idempotency_key": {
                    "type": "string",
                    "minLength": 12,
                },
            },
            "additionalProperties": False,
        },
    },
    "drainage.get_operation": {
        "risk": "readOnly",
        "input_schema": {
            "type": "object",
            "required": ["operation_id"],
            "properties": {
                "operation_id": {
                    "type": "string",
                    "pattern": "^DOP-.{8,}$",
                },
            },
            "additionalProperties": False,
        },
    },
    "drainage.validate_operation": {
        "risk": "readOnly",
        "input_schema": {
            "type": "object",
            "required": ["operation_id"],
            "properties": {
                "operation_id": {
                    "type": "string",
                    "pattern": "^DOP-.{8,}$",
                },
            },
            "additionalProperties": False,
        },
    },
}

_connect_to_main_input_schema = deepcopy(
    AGENT_TOOL_SCHEMAS["drainage.preview"]["input_schema"]
)
for _computed_field in (
    "pipe_type",
    "system_type",
    "level",
    "fitting_profile",
    "configuration_recommendation_token",
):
    _connect_to_main_input_schema["properties"].pop(
        _computed_field,
        None,
    )
    if _computed_field in _connect_to_main_input_schema["required"]:
        _connect_to_main_input_schema["required"].remove(
            _computed_field
        )
_connect_to_main_input_schema["properties"]["history_limit"] = {
    "type": "integer",
    "minimum": 1,
    "maximum": 200,
}
AGENT_TOOL_SCHEMAS["drainage.connect_to_main"] = {
    "risk": "readOnly",
    "input_schema": _connect_to_main_input_schema,
}

_TOOL_DESCRIPTIONS = {
    "drainage.get_context": "Read the active Revit document binding, MEP types, levels, and routing preferences.",
    "drainage.inspect_current_selection": "Read the currently selected drainage main and plumbing fixtures.",
    "drainage.search_targets": "List pipe and plumbing-fixture candidates in the active view or document without choosing design intent.",
    "drainage.recommend_configuration": "Rank the selected main pipe's size-compatible configuration using routing preference order, same-document human settings, and bounded committed-operation history; never scan the full model.",
    "drainage.connect_to_main": "Produce one high-level drainage connection proposal from explicit source and main references using the same recommendation and route snapshot as the low-level workflow; ambiguous cases remain blocked.",
    "drainage.preview": "Compute a document-bound drainage route snapshot and show a non-model DirectContext3D preview.",
    "drainage.clear_preview": "Clear drainage preview state for the active document without deleting model elements.",
    "drainage.request_human_confirmation": "Open a Revit TaskDialog so a human can approve one exact snapshot hash.",
    "drainage.commit_confirmed_snapshot": "Create the approved route in one guarded Revit transaction using an idempotent operation identity.",
    "drainage.get_operation": "Read the durable state and lineage of a drainage operation.",
    "drainage.validate_operation": "Validate slope, fittings, topology, and persisted evidence for a committed operation.",
}

_RESULT_FIELDS: dict[str, tuple[str, ...]] = {
    "drainage.get_context": (
        "action",
        "document",
        "default_slope_ratio",
        "default_diameter_mm",
        "default_route_policy",
        "pipe_types",
        "system_types",
        "levels",
        "routing_profiles",
    ),
    "drainage.inspect_current_selection": (
        "action",
        "document",
        "pipes",
        "fixtures",
    ),
    "drainage.search_targets": (
        "action",
        "document",
        "scope",
        "status",
        "main_candidate_count",
        "blocking_issues",
        "candidate_set_token",
        "candidate_set_expires_at_utc",
        "max_results",
        "applied_filters",
        "pipes",
        "fixtures",
        "truncated",
    ),
    "drainage.recommend_configuration": (
        "strategy_version",
        "document",
        "main_pipe",
        "diameter_mm",
        "selection_policy",
        "history_evidence",
        "saved_human_settings_used",
        "junction_candidates",
        "elbow_candidates",
        "recommended_configuration",
        "confidence",
        "auto_select_allowed",
        "requires_human_choice",
        "blocking_issues",
        "warnings",
        "recommendation_token",
        "recommendation_token_expires_at_unix",
    ),
    "drainage.connect_to_main": (
        "status",
        "recommendation",
        "snapshot",
        "preview",
        "next_action",
    ),
    "drainage.preview": ("status", "snapshot", "preview"),
    "drainage.clear_preview": (
        "action",
        "cleared",
        "snapshot_id",
        "snapshot_hash",
        "note",
    ),
    "drainage.request_human_confirmation": (
        "status",
        "confirmation",
    ),
    "drainage.commit_confirmed_snapshot": (
        "status",
        "operation",
    ),
    "drainage.get_operation": (
        "action",
        "operation_id",
        "operation_schema_version",
        "idempotency_key",
        "snapshot_id",
        "snapshot_hash",
        "document_fingerprint",
        "document_revision",
        "document_title",
        "document_path_kind",
        "dependency_hash",
        "confirmation_id",
        "confirmation_actor_kind",
        "initiator_surface",
        "tool_contract_version",
        "assembly_module_version_id",
        "assembly_sha256",
        "request_tool_name",
        "addin_version",
        "status",
        "error",
        "updated_at_utc",
        "result",
        "validation_evidence",
    ),
    "drainage.validate_operation": (
        "action",
        "document",
        "operation_id",
        "expected_slope_ratio",
        "valid",
        "topology_issues",
        "results",
        "validated_at_utc",
    ),
}

_ARRAY_RESULT_FIELDS = {
    "pipe_types",
    "system_types",
    "levels",
    "routing_profiles",
    "pipes",
    "fixtures",
    "topology_issues",
    "results",
    "blocking_issues",
    "junction_candidates",
    "elbow_candidates",
    "warnings",
}
_OBJECT_RESULT_FIELDS = {
    "document",
    "default_route_policy",
    "snapshot",
    "preview",
    "confirmation",
    "operation",
    "result",
    "validation_evidence",
    "applied_filters",
    "main_pipe",
    "selection_policy",
    "history_evidence",
    "recommended_configuration",
    "recommendation",
    "confidence",
}
_BOOLEAN_RESULT_FIELDS = {
    "truncated",
    "cleared",
    "valid",
    "saved_human_settings_used",
    "auto_select_allowed",
    "requires_human_choice",
}
_NUMBER_RESULT_FIELDS = {
    "default_slope_ratio",
    "default_diameter_mm",
    "max_results",
    "diameter_mm",
    "recommendation_token_expires_at_unix",
    "expected_slope_ratio",
    "document_revision",
    "main_candidate_count",
}


def _domain_result_schema(tool_name: str) -> dict[str, Any]:
    if tool_name == "drainage.commit_confirmed_snapshot":
        return {
            "oneOf": [
                {
                    "type": "object",
                    "required": [
                        "status",
                        "operation",
                        "result",
                    ],
                    "properties": {
                        "status": {
                            "type": "string",
                            "const": "committed",
                        },
                        "operation": {"type": "object"},
                        "result": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "required": [
                        "status",
                        "operation",
                        "next_action",
                    ],
                    "properties": {
                        "status": {
                            "type": "string",
                            "const": "unknown",
                        },
                        "operation": {"type": "object"},
                        "next_action": {
                            "type": "string",
                            "const": "drainage.get_operation",
                        },
                    },
                    "additionalProperties": False,
                },
            ]
        }
    fields = _RESULT_FIELDS[tool_name]
    properties: dict[str, Any] = {}
    for field in fields:
        if field in _ARRAY_RESULT_FIELDS:
            properties[field] = {"type": "array"}
        elif field in _OBJECT_RESULT_FIELDS:
            properties[field] = {
                "type": ["object", "null"],
            }
        elif field in _BOOLEAN_RESULT_FIELDS:
            properties[field] = {"type": "boolean"}
        elif field in _NUMBER_RESULT_FIELDS:
            properties[field] = {"type": "number"}
        elif field == "error":
            properties[field] = {"type": ["string", "null"]}
        else:
            properties[field] = {"type": "string"}
    return {
        "type": "object",
        "required": list(fields),
        "properties": properties,
        "additionalProperties": False,
    }


for _tool_name, _definition in AGENT_TOOL_SCHEMAS.items():
    _definition["contract_version"] = "1.3.0"
    _definition["output_schema"] = {
        "oneOf": [
            {
                "type": "object",
                "required": [
                    "contract_version",
                    "status",
                    "tool_name",
                    "result",
                ],
                "properties": {
                    "contract_version": {
                        "type": "string",
                        "const": "1.3.0",
                    },
                    "status": {"type": "string", "const": "ok"},
                    "tool_name": {
                        "type": "string",
                        "const": _tool_name,
                    },
                    "result": _domain_result_schema(_tool_name),
                },
                "additionalProperties": False,
            },
            {
                "type": "object",
                "required": [
                    "contract_version",
                    "status",
                    "tool_name",
                    "error",
                ],
                "properties": {
                    "contract_version": {
                        "type": "string",
                        "const": "1.3.0",
                    },
                    "status": {
                        "type": "string",
                        "const": "error",
                    },
                    "tool_name": {
                        "type": "string",
                        "const": _tool_name,
                    },
                    "error": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string"},
                            "type": {"type": "string"},
                            "message": {"type": "string"},
                            "retryable": {"type": "boolean"},
                        },
                        "required": [
                            "code",
                            "type",
                            "message",
                            "retryable",
                        ],
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
            },
        ],
    }
for _tool_name, _description in _TOOL_DESCRIPTIONS.items():
    AGENT_TOOL_SCHEMAS[_tool_name]["description"] = _description
