from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ElementRef:
    element_id: str
    unique_id: str = ""

    def as_payload(self) -> dict[str, str]:
        return {"element_id": self.element_id, "unique_id": self.unique_id}


@dataclass(frozen=True)
class DrainageRoutePolicy:
    route_policy_id: str = "sc-drainage-route-policy"
    route_policy_version: str = "1.1.0"
    side_entry_angle_degrees: float = 45.0
    side_entry_tolerance_degrees: float = 5.0
    radial_minimum_degrees: float = 0.0
    radial_maximum_degrees: float = 45.0
    radial_tolerance_degrees: float = 5.0
    minimum_tangent_mm: float = 100.0
    minimum_junction_spacing_mm: float = 300.0
    collision_clearance_mm: float = 25.0
    maximum_double45_lateral_offset_mm: float = 25.0

    def validate(self) -> None:
        if self.route_policy_id != "sc-drainage-route-policy":
            raise ValueError("unsupported route policy id")
        if self.route_policy_version != "1.1.0":
            raise ValueError("unsupported route policy version")
        if abs(self.side_entry_angle_degrees - 45) > 0.001:
            raise ValueError("side entry angle must be 45 degrees")
        if not 0 <= self.side_entry_tolerance_degrees <= 15:
            raise ValueError("side entry tolerance must be between 0 and 15 degrees")
        if not -15 <= self.radial_minimum_degrees <= self.radial_maximum_degrees <= 90:
            raise ValueError("radial angle range is invalid")
        if not 0 <= self.radial_tolerance_degrees <= 15:
            raise ValueError("radial tolerance must be between 0 and 15 degrees")
        if not 25 <= self.minimum_tangent_mm <= 3000:
            raise ValueError("minimum tangent must be between 25 and 3000 mm")
        if not 100 <= self.minimum_junction_spacing_mm <= 10000:
            raise ValueError("minimum junction spacing must be between 100 and 10000 mm")
        if not 0 <= self.collision_clearance_mm <= 1000:
            raise ValueError("collision clearance must be between 0 and 1000 mm")
        if not 0 <= self.maximum_double45_lateral_offset_mm <= 1000:
            raise ValueError(
                "maximum_double45_lateral_offset_mm must be between "
                "0 and 1000"
            )

    def as_payload(self) -> dict[str, Any]:
        return {
            "route_policy_id": self.route_policy_id,
            "route_policy_version": self.route_policy_version,
            "side_entry_angle_degrees": self.side_entry_angle_degrees,
            "side_entry_tolerance_degrees": self.side_entry_tolerance_degrees,
            "radial_minimum_degrees": self.radial_minimum_degrees,
            "radial_maximum_degrees": self.radial_maximum_degrees,
            "radial_tolerance_degrees": self.radial_tolerance_degrees,
            "minimum_tangent_mm": self.minimum_tangent_mm,
            "minimum_junction_spacing_mm": self.minimum_junction_spacing_mm,
            "collision_clearance_mm": self.collision_clearance_mm,
            "maximum_double45_lateral_offset_mm":
                self.maximum_double45_lateral_offset_mm,
        }


@dataclass(frozen=True)
class DrainageIntent:
    document_fingerprint: str
    document_revision: int
    main_pipe_id: str
    main_pipe_unique_id: str
    fixture_ids: tuple[str, ...]
    fixture_unique_ids: tuple[str, ...]
    selection_source: str
    main_candidate_count: int
    pipe_type_id: str
    pipe_type_unique_id: str
    system_type_id: str
    system_type_unique_id: str
    level_id: str
    level_unique_id: str
    junction_type_id: str
    junction_type_unique_id: str
    elbow_type_id: str
    elbow_type_unique_id: str
    slope_ratio: float
    diameter_mm: float
    downstream_mode: str
    route_policy: DrainageRoutePolicy | None = None
    candidate_set_token: str | None = None
    source_connector_origin: dict[str, float] | None = None

    def validate(self) -> None:
        if not self.document_fingerprint.startswith("sha256:"):
            raise ValueError("document_fingerprint is required")
        if self.document_revision < 0:
            raise ValueError("document_revision must be non-negative")
        if not self.main_pipe_id:
            raise ValueError("main_pipe_id is required")
        if not self.fixture_ids:
            raise ValueError("at least one fixture_id is required")
        if not self.main_pipe_unique_id.strip():
            raise ValueError("main_pipe_unique_id is required")
        if (
            len(self.fixture_unique_ids) != len(self.fixture_ids)
            or any(not item.strip() for item in self.fixture_unique_ids)
        ):
            raise ValueError(
                "fixture_unique_ids must match fixture_ids"
            )
        if self.selection_source not in {
            "current_selection",
            "search_result",
            "explicit_user_refs",
        }:
            raise ValueError("selection_source is invalid")
        if self.main_candidate_count != 1:
            raise ValueError(
                "exactly one main candidate is required"
            )
        if self.selection_source == "search_result":
            if not (self.candidate_set_token or "").startswith("DCT-"):
                raise ValueError(
                    "search_result requires a server-issued "
                    "candidate_set_token"
                )
        elif self.candidate_set_token is not None:
            raise ValueError(
                "candidate_set_token is only valid for search_result"
            )
        if not self.pipe_type_id or not self.system_type_id or not self.level_id:
            raise ValueError("pipe, system, and level type IDs are required")
        if (
            not self.pipe_type_unique_id.strip()
            or not self.system_type_unique_id.strip()
            or not self.level_unique_id.strip()
        ):
            raise ValueError(
                "pipe, system, and level UniqueIds are required"
            )
        if (
            not self.junction_type_id
            or not self.junction_type_unique_id.strip()
            or not self.elbow_type_id
            or not self.elbow_type_unique_id.strip()
        ):
            raise ValueError(
                "junction and elbow ElementId/UniqueId are required"
            )
        if not 0.001 <= self.slope_ratio <= 0.10:
            raise ValueError("slope_ratio must be between 0.001 and 0.10")
        if not 25 <= self.diameter_mm <= 300:
            raise ValueError("diameter_mm must be between 25 and 300")
        if self.downstream_mode not in {"auto", "end0", "end1"}:
            raise ValueError("downstream_mode must be auto, end0, or end1")
        if self.route_policy is not None:
            self.route_policy.validate()


@dataclass(frozen=True)
class SnapshotRef:
    snapshot_id: str
    snapshot_hash: str
    document_fingerprint: str
    document_revision: int
    ready_to_commit: bool

    @classmethod
    def from_preview(cls, payload: dict[str, Any]) -> "SnapshotRef":
        document = payload.get("document") or {}
        snapshot = cls(
            snapshot_id=str(payload.get("snapshot_id") or ""),
            snapshot_hash=str(payload.get("snapshot_hash") or ""),
            document_fingerprint=str(document.get("fingerprint") or ""),
            document_revision=int(document.get("revision") or 0),
            ready_to_commit=bool(payload.get("ready_to_create")),
        )
        if not snapshot.snapshot_id or not snapshot.snapshot_hash:
            raise ValueError("preview response has no immutable snapshot")
        if not snapshot.document_fingerprint:
            raise ValueError("preview response has no document fingerprint")
        return snapshot


@dataclass(frozen=True)
class ConfirmationRef:
    confirmation_id: str
    snapshot_id: str
    snapshot_hash: str

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> "ConfirmationRef":
        confirmation = cls(
            confirmation_id=str(payload.get("confirmation_id") or ""),
            snapshot_id=str(payload.get("snapshot_id") or ""),
            snapshot_hash=str(payload.get("snapshot_hash") or ""),
        )
        if not confirmation.confirmation_id:
            raise ValueError("confirmation response has no confirmation_id")
        return confirmation


@dataclass(frozen=True)
class OperationRef:
    operation_id: str
    idempotency_key: str
