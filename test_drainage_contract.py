import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import queue_protocol
from sc_revit.core.actions import ALL_ACTIONS, DRAINAGE_ACTIONS
from sc_revit.drainage.agent_cli import _error_code


class DrainageContractTests(unittest.TestCase):
    def test_gateway_extracts_stable_domain_error_code(self) -> None:
        self.assertEqual(
            _error_code(
                RuntimeError(
                    "PREFLIGHT_BLOCKED: route has blocking issues"
                )
            ),
            "PREFLIGHT_BLOCKED",
        )

    def test_all_drainage_actions_are_routable(self) -> None:
        self.assertTrue(DRAINAGE_ACTIONS.issubset(ALL_ACTIONS))

    def test_preview_request_uses_one_percent_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            request_dir = Path(temp_dir) / "requests"
            response_dir = Path(temp_dir) / "responses"
            error_dir = Path(temp_dir) / "errors"
            with (
                patch.object(queue_protocol, "REQUEST_DIR", request_dir),
                patch.object(queue_protocol, "RESPONSE_DIR", response_dir),
                patch.object(queue_protocol, "ERROR_DIR", error_dir),
                patch.object(queue_protocol, "record_request_created"),
            ):
                request = queue_protocol.create_drainage_preview_request(
                    document_fingerprint="sha256:doc",
                    document_revision=7,
                    main_pipe_id=11550234,
                    main_pipe_unique_id="main-uid",
                    fixture_ids=[13274671],
                    fixture_unique_ids=["fixture-uid"],
                    selection_source="current_selection",
                    main_candidate_count=1,
                    pipe_type_id=11550234,
                    pipe_type_unique_id="pipe-type-uid",
                    system_type_id=11550260,
                    system_type_unique_id="system-type-uid",
                    level_id=13289996,
                    level_unique_id="level-uid",
                    junction_type_id=2201,
                    junction_type_unique_id="junction-uid",
                    elbow_type_id=2202,
                    elbow_type_unique_id="elbow-uid",
                    slope_ratio=0.01,
                    diameter_mm=100,
                    downstream_mode="end1",
                )
                payload = json.loads(
                    (request_dir / f"{request.request_id}.json").read_text(encoding="utf-8")
                )
        self.assertEqual(payload["action"], "create_drainage_preview")
        self.assertEqual(payload["document_fingerprint"], "sha256:doc")
        self.assertEqual(payload["document_revision"], 7)
        self.assertEqual(payload["slope_ratio"], 0.01)
        self.assertEqual(payload["diameter_mm"], 100)
        self.assertEqual(payload["fixture_ids"], ["13274671"])
        self.assertEqual(payload["pipe_type_id"], "11550234")
        self.assertEqual(
            payload["pipe_type_unique_id"],
            "pipe-type-uid",
        )
        self.assertEqual(payload["system_type_id"], "11550260")
        self.assertEqual(
            payload["system_type_unique_id"],
            "system-type-uid",
        )
        self.assertEqual(payload["level_id"], "13289996")
        self.assertEqual(payload["level_unique_id"], "level-uid")
        self.assertEqual(payload["junction_type_id"], "2201")
        self.assertEqual(
            payload["junction_type_unique_id"],
            "junction-uid",
        )
        self.assertEqual(payload["elbow_type_id"], "2202")
        self.assertEqual(
            payload["elbow_type_unique_id"],
            "elbow-uid",
        )
        self.assertEqual(payload["downstream_mode"], "end1")

    def test_create_request_accepts_only_snapshot_confirmation_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            request_dir = Path(temp_dir) / "requests"
            response_dir = Path(temp_dir) / "responses"
            error_dir = Path(temp_dir) / "errors"
            with (
                patch.object(queue_protocol, "REQUEST_DIR", request_dir),
                patch.object(queue_protocol, "RESPONSE_DIR", response_dir),
                patch.object(queue_protocol, "ERROR_DIR", error_dir),
                patch.object(queue_protocol, "record_request_created"),
            ):
                request = queue_protocol.create_drainage_pipes_request(
                    snapshot_id="DPS-test",
                    snapshot_hash="sha256:test",
                    confirmation_id="DPC-test",
                    operation_id="DOP-test",
                    idempotency_key="DIK-test",
                )
                payload = json.loads(
                    (request_dir / f"{request.request_id}.json").read_text(encoding="utf-8")
                )
        self.assertEqual(payload["snapshot_id"], "DPS-test")
        self.assertEqual(payload["snapshot_hash"], "sha256:test")
        self.assertEqual(payload["confirmation_id"], "DPC-test")
        self.assertEqual(payload["operation_id"], "DOP-test")
        self.assertEqual(payload["idempotency_key"], "DIK-test")
        self.assertNotIn("main_pipe_id", payload)
        self.assertNotIn("slope_ratio", payload)

    def test_validation_is_bound_to_durable_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            request_dir = Path(temp_dir) / "requests"
            response_dir = Path(temp_dir) / "responses"
            error_dir = Path(temp_dir) / "errors"
            with (
                patch.object(queue_protocol, "REQUEST_DIR", request_dir),
                patch.object(queue_protocol, "RESPONSE_DIR", response_dir),
                patch.object(queue_protocol, "ERROR_DIR", error_dir),
                patch.object(queue_protocol, "record_request_created"),
            ):
                request = queue_protocol.create_validate_drainage_result_request(
                    [],
                    operation_id="DOP-test1234",
                    expected_slope_ratio=0.01,
                )
                payload = json.loads(
                    (request_dir / f"{request.request_id}.json").read_text(
                        encoding="utf-8"
                    )
                )
        self.assertEqual(payload["operation_id"], "DOP-test1234")
        self.assertEqual(payload["expected_slope_ratio"], 0.01)


if __name__ == "__main__":
    unittest.main()
