import json
import unittest
from io import StringIO
from unittest.mock import Mock, patch

from sc_revit.drainage.agent_cli import dispatch
from sc_revit.drainage.agent_tools import (
    AGENT_TOOL_SCHEMAS,
    DrainageAgentTools,
)
from sc_revit.drainage.application import DrainageApplicationService
from sc_revit.drainage.models import (
    ConfirmationRef,
    DrainageIntent,
    DrainageRoutePolicy,
    OperationRef,
    SnapshotRef,
)
from sc_revit.drainage.mcp_server import (
    McpSession,
    handle_message,
    serve,
)
from sc_revit.core.revit_queue_client import RevitQueueTimeoutError


class DrainageApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DrainageApplicationService()
        self.intent = DrainageIntent(
            document_fingerprint="sha256:doc",
            document_revision=7,
            main_pipe_id="10",
            main_pipe_unique_id="main-uid",
            fixture_ids=("20",),
            fixture_unique_ids=("fixture-uid",),
            selection_source="current_selection",
            main_candidate_count=1,
            candidate_set_token=None,
            pipe_type_id="30",
            pipe_type_unique_id="pipe-type-uid",
            system_type_id="40",
            system_type_unique_id="system-type-uid",
            level_id="50",
            level_unique_id="level-uid",
            junction_type_id="60",
            junction_type_unique_id="junction-uid",
            elbow_type_id="70",
            elbow_type_unique_id="elbow-uid",
            slope_ratio=0.01,
            diameter_mm=100,
            downstream_mode="end1",
        )
        self.preview_payload = {
            "document": {"fingerprint": "sha256:doc", "revision": 7},
            "snapshot_id": "DPS-test",
            "snapshot_hash": "sha256:snapshot",
            "ready_to_create": True,
        }

    def test_preview_requires_document_bound_snapshot(self) -> None:
        with patch(
            "sc_revit.drainage.application.client.request_create_drainage_preview",
            return_value=self.preview_payload,
        ) as request:
            payload, snapshot = self.service.preview(self.intent)
        self.assertEqual(payload, self.preview_payload)
        self.assertEqual(snapshot.snapshot_id, "DPS-test")
        self.assertEqual(snapshot.document_revision, 7)
        request.assert_called_once_with(
            document_fingerprint="sha256:doc",
            document_revision=7,
            main_pipe_id="10",
            main_pipe_unique_id="main-uid",
            fixture_ids=["20"],
            fixture_unique_ids=["fixture-uid"],
            selection_source="current_selection",
            main_candidate_count=1,
            candidate_set_token=None,
            pipe_type_id="30",
            pipe_type_unique_id="pipe-type-uid",
            system_type_id="40",
            system_type_unique_id="system-type-uid",
            level_id="50",
            level_unique_id="level-uid",
            junction_type_id="60",
            junction_type_unique_id="junction-uid",
            elbow_type_id="70",
            elbow_type_unique_id="elbow-uid",
            slope_ratio=0.01,
            diameter_mm=100,
            downstream_mode="end1",
            timeout_seconds=120,
        )

    def test_agent_preview_requires_valid_configuration_token(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "CONFIGURATION_RECOMMENDATION_TOKEN_INVALID",
        ):
            self.service.preview(
                self.intent,
                configuration_recommendation_token="DCR-invalid",
                require_configuration_token=True,
            )

    def test_gui_workspace_reuses_matching_context_without_model_scan(
        self,
    ) -> None:
        document = {"fingerprint": "sha256:doc", "revision": 7}
        cached_context = {"document": document}
        selection = {
            "document": document,
            "pipes": [
                {
                    "element_id": "10",
                    "unique_id": "main-uid",
                }
            ],
            "fixtures": [{"element_id": "20"}],
        }
        with (
            patch.object(
                self.service,
                "read_selection",
                return_value=selection,
            ),
            patch.object(self.service, "get_context") as get_context,
            patch(
                "sc_revit.drainage.application."
                "recommend_drainage_configuration",
                return_value={"auto_select_allowed": True},
            ) as recommend,
            patch(
                "sc_revit.drainage.application.load_settings",
                return_value={},
            ),
        ):
            result = self.service.get_gui_workspace(
                diameter_mm=100,
                cached_context=cached_context,
            )
        get_context.assert_not_called()
        recommend.assert_called_once()
        self.assertEqual(result["selection"], selection)

    def test_high_confidence_recommendation_issues_agent_token(
        self,
    ) -> None:
        document = {"fingerprint": "sha256:doc", "revision": 7}
        recommendation = {
            "auto_select_allowed": True,
            "recommended_configuration": {
                "pipe_type": {"unique_id": "pipe-type-uid"},
                "system_type": {"unique_id": "system-type-uid"},
                "level": {"unique_id": "level-uid"},
                "junction": {"unique_id": "junction-uid"},
                "elbow": {"unique_id": "elbow-uid"},
            },
        }
        with (
            patch.object(
                self.service,
                "get_context",
                return_value={"document": document},
            ),
            patch.object(
                self.service,
                "read_selection",
                return_value={
                    "document": document,
                    "pipes": [
                        {
                            "element_id": "10",
                            "unique_id": "main-uid",
                        }
                    ],
                },
            ),
            patch(
                "sc_revit.drainage.application."
                "recommend_drainage_configuration",
                return_value=recommendation,
            ),
            patch(
                "sc_revit.drainage.application.load_settings",
                return_value={},
            ),
        ):
            result = self.service.recommend_configuration(
                document_fingerprint="sha256:doc",
                document_revision=7,
                main_pipe_id="10",
                main_pipe_unique_id="main-uid",
                diameter_mm=100,
            )
        self.assertTrue(
            result["recommendation_token"].startswith("DCR-")
        )
        self.assertGreater(
            result["recommendation_token_expires_at_unix"],
            0,
        )

    def test_commit_only_forwards_snapshot_confirmation_and_operation(self) -> None:
        snapshot = SnapshotRef(
            snapshot_id="DPS-test",
            snapshot_hash="sha256:snapshot",
            document_fingerprint="sha256:doc",
            document_revision=7,
            ready_to_commit=True,
        )
        confirmation = ConfirmationRef(
            confirmation_id="DPC-test",
            snapshot_id="DPS-test",
            snapshot_hash="sha256:snapshot",
        )
        operation = OperationRef("DOP-test1234", "DIK-test123456")
        with patch(
            "sc_revit.drainage.application.client.request_create_drainage_pipes",
            return_value={"operation_id": operation.operation_id},
        ) as request, patch.object(
            self.service,
            "get_context",
            return_value={"document": {"fingerprint": "sha256:doc", "revision": 7}},
        ):
            payload, returned_operation = self.service.commit(
                snapshot,
                confirmation,
                operation=operation,
            )
        self.assertEqual(payload["operation_id"], operation.operation_id)
        self.assertEqual(returned_operation, operation)
        forwarded = request.call_args.kwargs
        self.assertEqual(
            set(forwarded),
            {
                "snapshot_id",
                "snapshot_hash",
                "confirmation_id",
                "operation_id",
                "idempotency_key",
                "actor_kind",
                "timeout_seconds",
            },
        )
        self.assertEqual(forwarded["actor_kind"], "human_gui")

    def test_blocked_snapshot_cannot_commit(self) -> None:
        snapshot = SnapshotRef(
            snapshot_id="DPS-test",
            snapshot_hash="sha256:snapshot",
            document_fingerprint="sha256:doc",
            document_revision=7,
            ready_to_commit=False,
        )
        confirmation = ConfirmationRef("DPC-test", "DPS-test", "sha256:snapshot")
        with self.assertRaises(ValueError):
            self.service.commit(snapshot, confirmation)

    def test_agent_commit_schema_has_no_free_model_parameters(self) -> None:
        schema = AGENT_TOOL_SCHEMAS["drainage.commit_confirmed_snapshot"]["input_schema"]
        required = set(schema["required"])
        self.assertIn("snapshot_id", required)
        self.assertIn("confirmation_id", required)
        self.assertIn("idempotency_key", required)
        self.assertNotIn("main_pipe_id", required)
        self.assertNotIn("slope_ratio", required)
        self.assertFalse(schema["additionalProperties"])

    def test_only_human_can_confirm_snapshot(self) -> None:
        snapshot = SnapshotRef(
            "DPS-test",
            "sha256:snapshot",
            "sha256:doc",
            7,
            True,
        )
        with self.assertRaises(ValueError):
            self.service.confirm(snapshot, actor_kind="policy")

    def test_confirmation_must_match_snapshot_id_and_hash(self) -> None:
        snapshot = SnapshotRef(
            "DPS-test",
            "sha256:snapshot",
            "sha256:doc",
            7,
            True,
        )
        with patch(
            "sc_revit.drainage.application.client.request_confirm_drainage_snapshot",
            return_value={
                "confirmation_id": "DPC-test",
                "snapshot_id": "DPS-other",
                "snapshot_hash": "sha256:snapshot",
            },
        ):
            with self.assertRaises(RuntimeError):
                self.service.confirm(snapshot, actor_kind="human")

    def test_validate_operation_uses_durable_committed_result(self) -> None:
        committed = {
            "status": "committed",
            "result": {
                "created_element_ids": [101, 102],
                "created": [{"element_id": 101}],
                "slope_ratio": 0.01,
            },
        }
        with (
            patch.object(self.service, "get_operation", return_value=committed),
            patch.object(
                self.service,
                "validate_commit",
                return_value={"valid": True},
            ) as validate,
        ):
            result = self.service.validate_operation("DOP-test1234")
        self.assertTrue(result["valid"])
        validate.assert_called_once_with(
            committed["result"],
            expected_slope_ratio=0.01,
            timeout_seconds=120,
        )

    def test_agent_preview_schema_is_closed_and_typed(self) -> None:
        schema = AGENT_TOOL_SCHEMAS["drainage.preview"]["input_schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["properties"]["downstream_mode"]["enum"],
            ["auto", "end0", "end1"],
        )
        self.assertEqual(schema["properties"]["slope_ratio"]["minimum"], 0.001)
        self.assertIn("document_fingerprint", schema["required"])
        self.assertIn("document_revision", schema["required"])
        self.assertIn(
            "configuration_recommendation_token",
            schema["required"],
        )
        self.assertFalse(
            schema["properties"]["route_policy"]["additionalProperties"]
        )
        route_policy_schema = schema["properties"]["route_policy"]
        self.assertEqual(
            route_policy_schema["properties"]["route_policy_version"]["const"],
            "1.1.0",
        )
        self.assertIn(
            "maximum_double45_lateral_offset_mm",
            route_policy_schema["properties"],
        )

    def test_agent_search_targets_is_document_bound_and_bounded(self) -> None:
        schema = AGENT_TOOL_SCHEMAS["drainage.search_targets"]["input_schema"]
        self.assertIn("document_fingerprint", schema["required"])
        self.assertEqual(
            schema["properties"]["scope"]["enum"],
            ["active_view", "document"],
        )
        self.assertEqual(
            schema["properties"]["max_results"]["maximum"],
            1000,
        )
        for filter_name in (
            "explicit_element_ids",
            "pipe_type_ids",
            "system_type_ids",
            "level_ids",
        ):
            self.assertIn(filter_name, schema["properties"])
            self.assertEqual(
                schema["properties"][filter_name]["items"]["type"],
                "string",
            )
        preview_schema = AGENT_TOOL_SCHEMAS["drainage.preview"]["input_schema"]
        self.assertIn("target_selection", preview_schema["required"])
        self.assertEqual(
            preview_schema["properties"]["target_selection"]
            ["properties"]["main_candidate_count"]["const"],
            1,
        )
        self.assertEqual(
            preview_schema["properties"]["target_selection"]
            ["properties"]["candidate_set_token"]["pattern"],
            "^DCT-",
        )

    def test_search_result_requires_server_candidate_set_token(self) -> None:
        with self.assertRaises(ValueError):
            DrainageIntent(
                **{
                    **self.intent.__dict__,
                    "selection_source": "search_result",
                    "candidate_set_token": None,
                }
            ).validate()
        intent = DrainageIntent(
            **{
                **self.intent.__dict__,
                "selection_source": "search_result",
                "candidate_set_token": "DCT-test123456",
            }
        )
        intent.validate()

    def test_preview_forwards_versioned_route_policy(self) -> None:
        intent = DrainageIntent(
            **{
                **self.intent.__dict__,
                "route_policy": DrainageRoutePolicy(
                    minimum_tangent_mm=125,
                    minimum_junction_spacing_mm=450,
                    maximum_double45_lateral_offset_mm=18,
                ),
            }
        )
        with patch(
            "sc_revit.drainage.application.client.request_create_drainage_preview",
            return_value=self.preview_payload,
        ) as request:
            self.service.preview(intent)
        self.assertEqual(
            request.call_args.kwargs["route_policy"]["minimum_tangent_mm"],
            125,
        )
        self.assertEqual(
            request.call_args.kwargs["route_policy"][
                "minimum_junction_spacing_mm"
            ],
            450,
        )
        self.assertEqual(
            request.call_args.kwargs["route_policy"][
                "maximum_double45_lateral_offset_mm"
            ],
            18,
        )

    def test_route_policy_rejects_invalid_double45_lateral_offset(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "maximum_double45_lateral_offset_mm",
        ):
            DrainageRoutePolicy(
                maximum_double45_lateral_offset_mm=-1,
            ).validate()

    def test_agent_can_request_but_not_forge_human_confirmation(self) -> None:
        from sc_revit.drainage.agent_tools import DrainageAgentTools

        service = Mock()
        service.confirm.return_value = ConfirmationRef(
            "DPC-test",
            "DPS-test",
            "sha256:snapshot",
        )
        tools = DrainageAgentTools(service)
        result = tools.request_human_confirmation(
            {
                "snapshot_id": "DPS-test",
                "snapshot_hash": "sha256:snapshot",
                "document_fingerprint": "sha256:doc",
                "document_revision": 7,
            }
        )
        self.assertEqual(result["status"], "confirmed")
        service.confirm.assert_called_once()
        self.assertEqual(
            service.confirm.call_args.kwargs["actor_kind"],
            "human",
        )

    def test_agent_validation_schema_uses_journal_slope(self) -> None:
        schema = AGENT_TOOL_SCHEMAS["drainage.validate_operation"]["input_schema"]
        self.assertEqual(schema["required"], ["operation_id"])
        self.assertNotIn("expected_slope_ratio", schema["properties"])

    def test_clear_preview_is_document_bound(self) -> None:
        schema = AGENT_TOOL_SCHEMAS["drainage.clear_preview"]["input_schema"]
        self.assertEqual(
            set(schema["required"]),
            {
                "snapshot_id",
                "snapshot_hash",
                "document_fingerprint",
                "document_revision",
            },
        )

    def test_agent_gateway_dispatches_without_free_form_execution(self) -> None:
        class FakeTools:
            def get_operation(self, operation_id: str) -> dict:
                return {
                    "action": "get_drainage_operation",
                    "operation_id": operation_id,
                    "operation_schema_version":
                        "sc.drainage.operation.v2",
                    "idempotency_key": "DIK-test123456",
                    "snapshot_id": "DPS-test",
                    "snapshot_hash": "sha256:snapshot",
                    "document_fingerprint": "sha256:doc",
                    "document_revision": 7,
                    "document_title": "test",
                    "document_path_kind": "local",
                    "dependency_hash": "sha256:dependency",
                    "confirmation_id": "DPC-test",
                    "confirmation_actor_kind": "human",
                    "initiator_surface": "agent",
                    "tool_contract_version": "1.3.0",
                    "assembly_module_version_id": "module-id",
                    "assembly_sha256": "sha256:dll",
                    "request_tool_name":
                        "drainage.commit_confirmed_snapshot",
                    "addin_version": "0.5.0-drainage-dev",
                    "status": "committed",
                    "error": None,
                    "updated_at_utc": "2026-07-24T00:00:00Z",
                    "result": {},
                    "validation_evidence": None,
                }

        result = dispatch(
            "drainage.get_operation",
            {"operation_id": "DOP-test1234"},
            tools=FakeTools(),
        )
        self.assertEqual(result["operation_id"], "DOP-test1234")
        with self.assertRaises(ValueError):
            dispatch("drainage.execute_csharp", {}, tools=FakeTools())

    def test_agent_gateway_rejects_unknown_arguments(self) -> None:
        with self.assertRaises(ValueError):
            dispatch(
                "drainage.get_operation",
                {
                    "operation_id": "DOP-test1234",
                    "csharp": "unsafe",
                },
            )

    def test_agent_gateway_rejects_unknown_route_policy_fields(self) -> None:
        arguments = {
            "document_fingerprint": "sha256:doc",
            "document_revision": 7,
            "main_pipe": {
                "element_id": "10",
                "unique_id": "main-uid",
            },
            "fixtures": [
                {
                    "element_id": "20",
                    "unique_id": "fixture-uid",
                }
            ],
            "target_selection": {
                "source": "current_selection",
                "main_candidate_count": 1,
            },
            "pipe_type": {
                "element_id": "30",
                "unique_id": "pipe-type-uid",
            },
            "system_type": {
                "element_id": "40",
                "unique_id": "system-type-uid",
            },
            "level": {
                "element_id": "50",
                "unique_id": "level-uid",
            },
            "fitting_profile": {
                "junction": {
                    "element_id": "60",
                    "unique_id": "junction-uid",
                },
                "elbow": {
                    "element_id": "70",
                    "unique_id": "elbow-uid",
                },
            },
            "slope_ratio": 0.01,
            "diameter_mm": 100,
            "downstream_mode": "end1",
            "route_policy": {"unsafe_override": 1},
        }
        with self.assertRaises(ValueError):
            dispatch("drainage.preview", arguments)

    def test_agent_preview_requires_and_forwards_unique_ids(self) -> None:
        service = Mock()
        service.preview.return_value = (
            self.preview_payload,
            SnapshotRef.from_preview(self.preview_payload),
        )
        tools = DrainageAgentTools(service)
        tools.preview(
            {
                "document_fingerprint": "sha256:doc",
                "document_revision": 7,
                "main_pipe": {
                    "element_id": "10",
                    "unique_id": "main-uid",
                },
                "fixtures": [
                    {
                        "element_id": "20",
                        "unique_id": "fixture-uid",
                    }
                ],
                "target_selection": {
                    "source": "current_selection",
                    "main_candidate_count": 1,
                },
                "pipe_type": {
                    "element_id": "30",
                    "unique_id": "pipe-type-uid",
                },
                "system_type": {
                    "element_id": "40",
                    "unique_id": "system-type-uid",
                },
                "level": {
                    "element_id": "50",
                    "unique_id": "level-uid",
                },
                "fitting_profile": {
                    "junction": {
                        "element_id": "60",
                        "unique_id": "junction-uid",
                    },
                    "elbow": {
                        "element_id": "70",
                        "unique_id": "elbow-uid",
                    },
                },
                "slope_ratio": 0.01,
                "diameter_mm": 100,
                "downstream_mode": "end1",
                "configuration_recommendation_token": "DCR-test",
            }
        )
        intent = service.preview.call_args.args[0]
        self.assertEqual(intent.main_pipe_unique_id, "main-uid")
        self.assertEqual(
            intent.fixture_unique_ids,
            ("fixture-uid",),
        )
        self.assertEqual(intent.pipe_type_unique_id, "pipe-type-uid")
        self.assertEqual(intent.system_type_unique_id, "system-type-uid")
        self.assertEqual(intent.level_unique_id, "level-uid")
        self.assertEqual(intent.junction_type_id, "60")
        self.assertEqual(
            intent.junction_type_unique_id,
            "junction-uid",
        )
        self.assertEqual(intent.elbow_type_id, "70")
        self.assertEqual(intent.elbow_type_unique_id, "elbow-uid")
        self.assertEqual(
            service.preview.call_args.kwargs[
                "configuration_recommendation_token"
            ],
            "DCR-test",
        )
        self.assertTrue(
            service.preview.call_args.kwargs[
                "require_configuration_token"
            ]
        )

    def test_mcp_server_lists_and_dispatches_typed_tools(self) -> None:
        session = McpSession()
        initialized = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            },
            session=session,
        )
        self.assertEqual(
            initialized["result"]["protocolVersion"],
            "2025-06-18",
        )
        handle_message(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
            session=session,
        )
        listed = handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            session=session,
        )
        names = {
            tool["name"]
            for tool in listed["result"]["tools"]
        }
        self.assertIn("drainage.preview", names)
        self.assertIn("drainage.recommend_configuration", names)
        self.assertIn("drainage.request_human_confirmation", names)
        commit_tool = next(
            tool
            for tool in listed["result"]["tools"]
            if tool["name"]
            == "drainage.commit_confirmed_snapshot"
        )
        self.assertTrue(
            commit_tool["annotations"]["destructiveHint"]
        )
        self.assertIn("oneOf", commit_tool["outputSchema"])

        class FakeTools:
            def get_operation(self, operation_id: str) -> dict:
                return {
                    "action": "get_drainage_operation",
                    "operation_id": operation_id,
                    "operation_schema_version":
                        "sc.drainage.operation.v2",
                    "idempotency_key": "DIK-test123456",
                    "snapshot_id": "DPS-test",
                    "snapshot_hash": "sha256:snapshot",
                    "document_fingerprint": "sha256:doc",
                    "document_revision": 7,
                    "document_title": "test",
                    "document_path_kind": "local",
                    "dependency_hash": "sha256:dependency",
                    "confirmation_id": "DPC-test",
                    "confirmation_actor_kind": "human",
                    "initiator_surface": "agent",
                    "tool_contract_version": "1.3.0",
                    "assembly_module_version_id": "module-id",
                    "assembly_sha256": "sha256:dll",
                    "request_tool_name":
                        "drainage.commit_confirmed_snapshot",
                    "addin_version": "0.5.0-drainage-dev",
                    "status": "committed",
                    "error": None,
                    "updated_at_utc": "2026-07-24T00:00:00Z",
                    "result": {},
                    "validation_evidence": None,
                }

        called = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "drainage.get_operation",
                    "arguments": {"operation_id": "DOP-test1234"},
                },
            },
            tools=FakeTools(),
            session=session,
        )
        self.assertFalse(called["result"]["isError"])
        self.assertEqual(
            called["result"]["structuredContent"]["result"]["operation_id"],
            "DOP-test1234",
        )

    def test_mcp_server_rejects_tools_before_initialized(self) -> None:
        response = handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            session=McpSession(),
        )
        self.assertEqual(response["error"]["code"], -32002)

    def test_mcp_server_rejects_scalar_params_and_arguments(self) -> None:
        session = McpSession(
            initialize_seen=True,
            initialized=True,
            negotiated_version="2025-06-18",
        )
        bad_params = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": 1,
            },
            session=session,
        )
        self.assertEqual(bad_params["error"]["code"], -32602)
        bad_arguments = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "drainage.get_operation",
                    "arguments": 1,
                },
            },
            session=session,
        )
        self.assertEqual(
            bad_arguments["error"]["code"],
            -32602,
        )

    def test_mcp_server_rejects_output_schema_violation(self) -> None:
        session = McpSession(
            initialize_seen=True,
            initialized=True,
            negotiated_version="2025-06-18",
        )

        class InvalidTools:
            def get_operation(self, operation_id: str) -> dict:
                return {
                    "operation_id": operation_id,
                    "status": "committed",
                }

        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "drainage.get_operation",
                    "arguments": {
                        "operation_id": "DOP-test1234"
                    },
                },
            },
            tools=InvalidTools(),
            session=session,
        )
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(
            response["result"]["structuredContent"]["status"],
            "error",
        )

    def test_mcp_stdio_returns_parse_error_and_continues(self) -> None:
        source = StringIO(
            "{bad json}\n"
            + json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18"
                    },
                }
            )
            + "\n"
        )
        sink = StringIO()
        serve(source=source, sink=sink)
        responses = [
            json.loads(line)
            for line in sink.getvalue().splitlines()
        ]
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(
            responses[1]["result"]["protocolVersion"],
            "2025-06-18",
        )

    def test_agent_commit_timeout_returns_unknown_and_recovery_action(self) -> None:
        from sc_revit.drainage.agent_tools import DrainageAgentTools

        service = Mock()
        service.commit.side_effect = RevitQueueTimeoutError("timeout")
        tools = DrainageAgentTools(service)
        result = tools.commit_confirmed_snapshot(
            {
                "snapshot_id": "DPS-test",
                "snapshot_hash": "sha256:snapshot",
                "document_fingerprint": "sha256:doc",
                "document_revision": 7,
                "confirmation_id": "DPC-test",
                "operation_id": "DOP-test1234",
                "idempotency_key": "DIK-test123456",
            }
        )
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["next_action"], "drainage.get_operation")

    def test_connect_to_main_schema_computes_configuration_fields(self) -> None:
        schema = AGENT_TOOL_SCHEMAS[
            "drainage.connect_to_main"
        ]["input_schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("main_pipe", schema["required"])
        self.assertIn("fixtures", schema["required"])
        self.assertNotIn("fitting_profile", schema["properties"])
        self.assertNotIn(
            "configuration_recommendation_token",
            schema["properties"],
        )

    def test_connect_to_main_reuses_recommendation_and_preview(self) -> None:
        tools = DrainageAgentTools(Mock())
        tools.recommend_configuration = Mock(
            return_value={
                "auto_select_allowed": True,
                "recommendation_token": "DCR-test",
                "recommended_configuration": {
                    "pipe_type": {"element_id": "1", "unique_id": "pt"},
                    "system_type": {"element_id": "2", "unique_id": "st"},
                    "level": {"element_id": "3", "unique_id": "lv"},
                    "junction": {"element_id": "4", "unique_id": "jn"},
                    "elbow": {"element_id": "5", "unique_id": "el"},
                },
            }
        )
        tools.preview = Mock(
            return_value={
                "status": "ready",
                "snapshot": {"snapshot_hash": "sha256:route"},
                "preview": {"plans": []},
            }
        )
        result = tools.connect_to_main(
            {
                "main_pipe": {
                    "element_id": "10",
                    "unique_id": "main",
                },
                "fixtures": [
                    {"element_id": "20", "unique_id": "source"}
                ],
                "diameter_mm": 100,
            }
        )
        self.assertEqual(
            result["next_action"],
            "drainage.request_human_confirmation",
        )
        preview_arguments = tools.preview.call_args.args[0]
        self.assertEqual(
            preview_arguments["configuration_recommendation_token"],
            "DCR-test",
        )
        self.assertEqual(
            preview_arguments["fitting_profile"]["junction"]["element_id"],
            "4",
        )


if __name__ == "__main__":
    unittest.main()
