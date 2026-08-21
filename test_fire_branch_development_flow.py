import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import queue_protocol


ROOT = Path(__file__).resolve().parent


class FireBranchDevelopmentFlowTests(unittest.TestCase):
    def test_create_client_returns_retained_partial_result_to_gui(self) -> None:
        from sc_revit.fire_branch import client

        retained_partial = {
            "verification_status": "partial",
            "partial_success": True,
            "retention_decision": "kept",
            "model_changes_kept": True,
            "failed": [{"reason": "connector_verification_failed"}],
        }
        with patch.object(
            client,
            "create_fire_branch_pipes_request",
            return_value=SimpleNamespace(request_id="partial-request"),
        ), patch.object(client, "_wait", return_value=retained_partial):
            result = client.request_create_fire_branch_pipes(
                main_pipe_id=1,
                sprinkler_ids=[2],
                pipe_type_id=3,
                system_type_id=4,
                level_id=5,
                diameter_mm=25,
                branch_offset_cm=0,
                height_reference="center",
            )

        self.assertIs(result, retained_partial)

    def test_create_client_rejects_retained_partial_result_in_sandbox(self) -> None:
        from sc_revit.fire_branch import client

        invalid_sandbox_partial = {
            "verification_status": "partial",
            "partial_success": True,
            "retention_decision": "kept",
            "model_changes_kept": True,
            "failed": [{"reason": "connector_verification_failed"}],
        }
        with patch.object(
            client,
            "create_fire_branch_pipes_request",
            return_value=SimpleNamespace(request_id="sandbox-partial-request"),
        ), patch.object(client, "_wait", return_value=invalid_sandbox_partial):
            with self.assertRaisesRegex(client.RfaReaderError, "partial"):
                client.request_create_fire_branch_pipes(
                    main_pipe_id=1,
                    sprinkler_ids=[2],
                    pipe_type_id=3,
                    system_type_id=4,
                    level_id=5,
                    diameter_mm=25,
                    branch_offset_cm=0,
                    height_reference="center",
                    execution_mode="sandbox",
                )

    def test_verification_failure_formatter_explains_root_cause_and_recovery(self) -> None:
        from sc_revit.core.revit_queue_client import format_fire_branch_verification_failure

        message = format_fire_branch_verification_failure(
            {
                "verification_status": "failed",
                "rollback_status": "verified",
                "restoration_verified": True,
                "connected_sprinkler_count": 25,
                "unconnected_sprinkler_count": 4,
                "failed": [
                    {
                        "reason": "opposite_side_endpoint_tee_creation_failed",
                        "row": 58.09,
                        "topology": "OppositeSidesSameElevation",
                        "detail": "Revit rejected the fitting without an exception detail.",
                    },
                    {
                        "reason": "connector_verification_failed",
                        "unreachable_sprinkler_ids": [13599867, 13599868],
                    },
                ],
            }
        )

        self.assertIn("主管端點兩側三通建立失敗", message)
        self.assertIn("主管端點的第一個管件建立失敗", message)
        self.assertIn("沙盒檢查已自動回復", message)
        self.assertIn("13599867、13599868", message)
        self.assertIn("完整診斷已保留", message)

    def test_hot_rule_identity_includes_diameter_analysis_rules(self) -> None:
        from sc_revit.fire_branch import diameter_analysis, hot_analysis

        rule_paths = hot_analysis._rule_source_paths()

        self.assertIn(Path(diameter_analysis.__file__).resolve(), rule_paths)
        self.assertIn(Path(hot_analysis.__file__).resolve(), rule_paths)

    def test_hot_analysis_returns_plain_language_preview_summary(self) -> None:
        from sc_revit.fire_branch.hot_analysis import build_preview_summary

        result = build_preview_summary(
            {
                "row_count": 18,
                "estimated_pipe_count": 46,
                "sprinkler_count": 32,
                "skipped": [],
                "cad_path_check": {
                    "status": "matched",
                    "coverage_ratio": 0.94,
                    "coordinate_verified": True,
                },
            }
        )

        self.assertEqual(result["status"], "ready")
        self.assertIn("找到支管：18 排", result["summary_lines"])
        self.assertIn("預估管段：46 段", result["summary_lines"])
        self.assertIn("CAD 路徑：吻合 94%", result["summary_lines"])
        self.assertTrue(result["rule_version"])
        self.assertEqual(len(result["rule_hash"]), 12)

    def test_hot_analysis_explains_ambiguous_cad_without_technical_codes(self) -> None:
        from sc_revit.fire_branch.hot_analysis import build_preview_summary

        result = build_preview_summary(
            {
                "row_count": 3,
                "estimated_pipe_count": 9,
                "sprinkler_count": 5,
                "skipped": [{"sprinkler_id": 101}],
                "cad_path_check": {"status": "ambiguous", "coverage_ratio": 0.45},
            }
        )

        self.assertEqual(result["status"], "needs_attention")
        self.assertIn("CAD 路徑：目前無法確定", result["summary_lines"])
        self.assertIn("略過灑水頭：1 顆", result["summary_lines"])
        self.assertNotIn("review_required", "\n".join(result["summary_lines"]))

    def test_hot_analysis_does_not_reset_to_unanalyzed_when_cad_route_is_missing(self) -> None:
        from sc_revit.fire_branch.hot_analysis import build_preview_summary

        result = build_preview_summary(
            {
                "row_count": 1,
                "estimated_pipe_count": 3,
                "sprinkler_count": 2,
                "skipped": [],
                "cad_path_check": {
                    "status": "cad_no_paths",
                    "selected_source_path": "Z:/example.dwg",
                    "coordinate_verified": False,
                    "diameter_probe_segments": [
                        {"segment_id": "row-0-0", "row_index": 0, "sequence": 0}
                    ],
                },
            }
        )

        self.assertEqual(result["status"], "needs_attention")
        analysis = result["diameter_analysis"]
        self.assertEqual(analysis["status"], "needs_attention")
        self.assertIn("CAD 對位尚未驗證", analysis["message"])

    def test_sandbox_request_is_explicit_and_preserves_preview(self) -> None:
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
                request = queue_protocol.create_fire_branch_pipes_request(
                    main_pipe_id=100,
                    sprinkler_ids=[200],
                    pipe_type_id=300,
                    system_type_id=400,
                    level_id=500,
                    diameter_mm=25,
                    branch_offset_cm=0,
                    height_reference="管中心",
                    preview_group_id=600,
                    execution_mode="sandbox",
                    sandbox_scope="single_sprinkler",
                    preview_snapshot_id="preview-123",
                    pilot_source_row_index=0,
                    require_diameter_plan=True,
                    model_plan_hash="a" * 64,
                    source_mode="uniform",
                    diameter_plan=[
                        {
                            "segment_id": "row-0-0",
                            "row_index": 0,
                            "sequence": 0,
                            "start": {"x": 0, "y": 0},
                            "end": {"x": 10, "y": 0},
                            "diameter_mm": 40,
                        }
                    ],
                    topology_plan={
                        "schema_version": "fire_branch_topology_plan.v2",
                        "junctions": [],
                        "reducers": [],
                    },
                )
                payload = json.loads(
                    (request_dir / f"{request.request_id}.json").read_text(encoding="utf-8")
                )

        self.assertEqual("test_fire_branch_pipes", request.action)
        self.assertEqual("test_fire_branch_pipes", payload["action"])
        self.assertEqual(payload["execution_mode"], "sandbox")
        self.assertEqual(
            "fire_branch_topology_plan.v2",
            payload["topology_plan"]["schema_version"],
        )
        self.assertFalse(payload["delete_preview_after_create"])
        self.assertEqual(40, payload["diameter_plan"][0]["diameter_mm"])
        self.assertEqual("single_sprinkler", payload["sandbox_scope"])
        self.assertEqual("preview-123", payload["preview_snapshot_id"])
        self.assertEqual(0, payload["pilot_source_row_index"])
        self.assertTrue(payload["require_diameter_plan"])
        self.assertEqual("a" * 64, payload["model_plan_hash"])
        self.assertEqual("uniform", payload["source_mode"])

    def test_topology_only_sandbox_scope_is_carried_to_revit_request(self) -> None:
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
                request = queue_protocol.create_fire_branch_pipes_request(
                    main_pipe_id=100,
                    sprinkler_ids=[200, 201],
                    pipe_type_id=300,
                    system_type_id=400,
                    level_id=500,
                    diameter_mm=25,
                    branch_offset_cm=0,
                    height_reference="管中心",
                    execution_mode="sandbox",
                    sandbox_scope="topology_only",
                )
                payload = json.loads(
                    (request_dir / f"{request.request_id}.json").read_text(encoding="utf-8")
                )

        self.assertEqual("test_fire_branch_pipes", payload["action"])
        self.assertEqual("sandbox", payload["execution_mode"])
        self.assertEqual("topology_only", payload["sandbox_scope"])
        self.assertFalse(payload["delete_preview_after_create"])

    def test_preview_request_carries_uniform_source_mode_to_revit(self) -> None:
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
                request = queue_protocol.create_fire_branch_preview_request(
                    main_pipe_id=100,
                    sprinkler_ids=[200],
                    level_id=500,
                    branch_offset_cm=0,
                    height_reference="管中心",
                    source_mode="uniform",
                )
                payload = json.loads(
                    (request_dir / f"{request.request_id}.json").read_text(encoding="utf-8")
                )

        self.assertEqual("uniform", payload["source_mode"])

    def test_gui_exposes_plain_language_development_flow(self) -> None:
        source = (ROOT / "gui_app.py").read_text(encoding="utf-8")

        self.assertIn("目前狀態", source)
        self.assertIn("分析並顯示預覽", source)
        self.assertIn("背景安全檢核", source)
        self.assertIn("建立消防支管", source)
        self.assertNotIn("select_single_sprinkler(", source)
        self.assertNotIn("build_single_sprinkler_model_plan(", source)
        self.assertNotIn("len(sprinklers) != 1", source)
        self.assertIn('self._start_fire_branch_pipes("sandbox")', source)
        self.assertIn("self._fire_commit_requested", source)
        self.assertIn("sandbox_scope=None", source)
        self.assertIn('self.fire_commit_button.configure(state="normal")', source)
        self.assertIn("詳細資料", source)

        self.assertIn('"diameter_analysis": diameter_analysis', source)
        self.assertIn('diameter_analysis["topology_plan"]', source)
        self.assertIn("管徑分析：已判斷", source)

    def test_revit_routes_uniform_mode_through_the_stable_nearest_main_path(self) -> None:
        source = (ROOT / "revit_addin" / "src" / "Handlers" / "FireBranchHandler.cs").read_text(
            encoding="utf-8"
        )

        self.assertIn("BuildLegacyUniformFireBranchItems", source)
        self.assertIn('sourceMode == "uniform"', source)
        self.assertIn("FireBranchSandboxFailurePreprocessor", source)
        self.assertIn("FailureProcessingResult.ProceedWithRollBack", source)

    def test_gui_resets_test_approval_when_context_changes_or_request_fails(self) -> None:
        source = (ROOT / "gui_app.py").read_text(encoding="utf-8")

        self.assertIn("def _reset_fire_sandbox_approval", source)
        self.assertIn('self._reset_fire_sandbox_approval("請重新分析後再建立")', source)
        self.assertIn('self._reset_fire_sandbox_approval("安全檢核未通過，請修正後重試")', source)

    def test_hot_worker_client_can_reload_from_project_source(self) -> None:
        from sc_revit.fire_branch.hot_worker_client import run_hot_preview_analysis

        result = run_hot_preview_analysis(
            {
                "segment_count": 2,
                "estimated_pipe_count": 2,
                "cad_path_check": {"status": "matched", "coverage_ratio": 1.0},
                "skipped": [],
            }
        )

        self.assertEqual("fresh_process", result["reload_mode"])
        self.assertEqual("ready", result["status"])

    def test_installed_gui_uses_development_root_marker_for_hot_analysis(self) -> None:
        from sc_revit.fire_branch import hot_worker_client

        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir) / "SC_REVIT"
            executable = install_root / "dist" / "RevitFamilyClassifier" / "RevitFamilyClassifier.exe"
            bundled_module = (
                install_root
                / "dist"
                / "RevitFamilyClassifier"
                / "_internal"
                / "sc_revit"
                / "fire_branch"
                / "hot_worker_client.py"
            )
            executable.parent.mkdir(parents=True)
            bundled_module.parent.mkdir(parents=True)
            (install_root / "development_root.txt").write_text(str(ROOT), encoding="utf-8")
            original_cwd = Path.cwd()
            try:
                os.chdir(executable.parent)
                with (
                    patch.dict(os.environ, {"SC_REVIT_HOME": str(install_root)}, clear=False),
                    patch.object(sys, "frozen", True, create=True),
                    patch.object(sys, "executable", str(executable)),
                    patch.object(hot_worker_client, "__file__", str(bundled_module)),
                ):
                    result = hot_worker_client.run_hot_preview_analysis({})
            finally:
                os.chdir(original_cwd)

        self.assertEqual("fresh_process", result["reload_mode"])

    def test_hot_analysis_preserves_chinese_unc_paths_across_process_boundary(self) -> None:
        from sc_revit.fire_branch.hot_worker_client import run_hot_preview_analysis

        result = run_hot_preview_analysis(
            {
                "cad_path_check": {
                    "status": "matched",
                    "selected_source_path": (
                        "\\\\192.168.2.66\\Office\\"
                        "\u6b77\u5e74\u5716\u6a94\\00-BIm&\u6e05\u5716&\u65bd\u5de5\u5716\\"
                        "1-BIM\\1150119 \u5927\u7532\u5206\u5c40\\04-\u6d88\u9632\\"
                        "\u53c3\u5716\\\u6492\u6c34\\"
                        "\u81ea\u52d5\u6492\u6c34\u8a2d\u5099\u914d\u7f6e\u5716-"
                        "\u5730\u4e0b\u58f9\u5c64.dwg"
                    ),
                }
            }
        )

        self.assertEqual("fresh_process", result["reload_mode"])
        self.assertEqual("ready", result["status"])

    def test_hot_analysis_adds_diameter_and_reducer_preview_from_matched_cad(self) -> None:
        from sc_revit.fire_branch.hot_analysis import build_preview_summary

        with patch(
            "sc_revit.fire_branch.dwg_diameter_reader.read_dwg_diameter_texts",
            return_value={
                "unit_to_feet": 1.0,
                "block_points": [
                    {"block_name": "A", "x": 0, "y": 0, "z": 0},
                    {"block_name": "B", "x": 10, "y": 0, "z": 0},
                    {"block_name": "C", "x": 0, "y": 10, "z": 0},
                ],
                "texts": [
                    {"text": '1 1/2"', "x": 5, "y": 1, "z": 0, "color": None},
                    {"text": '1"', "x": 15, "y": 1, "z": 0, "color": None},
                ]
            },
        ):
            result = build_preview_summary(
                {
                    "sprinkler_count": 2,
                    "cad_coordinate_anchors": [
                        {"block_name": "sample.A", "x": 0, "y": 0, "z": 0},
                        {"block_name": "sample.B", "x": 10, "y": 0, "z": 0},
                        {"block_name": "sample.C", "x": 0, "y": 10, "z": 0},
                    ],
                    "cad_path_check": {
                        "status": "matched",
                        "coordinate_verified": True,
                        "selected_source_path": "sample.dwg",
                        "import_transform": {
                            "origin": {"x": 0, "y": 0, "z": 0},
                            "basis_x": {"x": 1, "y": 0, "z": 0},
                            "basis_y": {"x": 0, "y": 1, "z": 0},
                            "basis_z": {"x": 0, "y": 0, "z": 1},
                        },
                        "diameter_probe_segments": [
                            {
                                "segment_id": "row-0-0",
                                "row_index": 0,
                                "sequence": 0,
                                "start": {"x": 0, "y": 0},
                                "end": {"x": 10, "y": 0},
                                "color_key": "red",
                            },
                            {
                                "segment_id": "row-0-1",
                                "row_index": 0,
                                "sequence": 1,
                                "start": {"x": 10, "y": 0},
                                "end": {"x": 20, "y": 0},
                                "color_key": "blue",
                            },
                        ],
                        "main_context_segments": [
                            {
                                "segment_id": "main-1001",
                                "topology_role": "main",
                                "source_element_id": 1001,
                                "start": {"x": 0, "y": 20},
                                "end": {"x": 20, "y": 20},
                            }
                        ],
                    },
                    "skipped": [],
                }
            )

        self.assertEqual("ready", result["diameter_analysis"]["status"])
        self.assertEqual(2, result["diameter_analysis"]["resolved_segment_count"])
        self.assertEqual(1, len(result["diameter_analysis"]["reducers"]))
        self.assertIn("文字直接配對：2/2", result["summary_lines"])
        self.assertIn(
            "其中主管標註：0 個（不參與支管管徑判定）",
            result["summary_lines"],
        )
        self.assertIn("圖層備援：0 段", result["summary_lines"])
        self.assertIn(
            "落水管規則：2 顆灑水頭均固定以 DN25 接管",
            result["summary_lines"],
        )
        self.assertIn(
            "落水拆段建模：尚未啟用",
            result["summary_lines"],
        )

    def test_hot_analysis_reports_chinese_drawing_default_note(self) -> None:
        from sc_revit.fire_branch.hot_analysis import build_preview_summary

        with patch(
            "sc_revit.fire_branch.dwg_diameter_reader.read_dwg_diameter_texts",
            return_value={
                "unit_to_feet": 1.0,
                "block_points": [],
                "texts": [
                    {
                        "text": '備註2：未標註之管徑均為1"。',
                        "x": 0,
                        "y": 0,
                        "z": 0,
                        "color": 7,
                    }
                ],
            },
        ):
            result = build_preview_summary(
                {
                    "cad_path_check": {
                        "status": "matched",
                        "coordinate_verified": True,
                        "selected_source_path": "sample.dwg",
                        "diameter_probe_segments": [
                            {
                                "segment_id": "row-0-0",
                                "row_index": 0,
                                "sequence": 0,
                                "start": {"x": 0, "y": 0},
                                "end": {"x": 10, "y": 0},
                            }
                        ],
                    },
                    "skipped": [],
                }
            )

        self.assertIn(
            "CAD 備註預設：已偵測 1 筆｜未標註管徑 25 mm",
            result["summary_lines"],
        )

    def test_hot_analysis_transforms_text_bounds_and_direction_with_linked_cad(self) -> None:
        from sc_revit.fire_branch.hot_analysis import build_preview_summary

        with patch(
            "sc_revit.fire_branch.dwg_diameter_reader.read_dwg_diameter_texts",
            return_value={
                "unit_to_feet": 1.0,
                "block_points": [
                    {"block_name": "A", "x": 0, "y": 0, "z": 0},
                    {"block_name": "B", "x": 1, "y": 0, "z": 0},
                    {"block_name": "C", "x": 0, "y": 1, "z": 0},
                ],
                "texts": [
                    {
                        "text": '1 1/4"',
                        "x": 2.5,
                        "y": 0.5,
                        "z": 0,
                        "color": 7,
                        "layer": "FIRE-ANNO",
                        "bounds": {
                            "min_x": 1,
                            "min_y": 0.25,
                            "max_x": 4,
                            "max_y": 0.75,
                        },
                        "direction": {"x": 1, "y": 0},
                    }
                ]
            },
        ):
            result = build_preview_summary(
                {
                    "cad_coordinate_anchors": [
                        {"block_name": "sample.A", "x": 10, "y": 0, "z": 0},
                        {"block_name": "sample.B", "x": 10, "y": 2, "z": 0},
                        {"block_name": "sample.C", "x": 8, "y": 0, "z": 0},
                    ],
                    "cad_path_check": {
                        "status": "matched",
                        "coordinate_verified": True,
                        "selected_source_path": "sample.dwg",
                        "import_transform": {
                            "origin": {"x": 10, "y": 0, "z": 0},
                            "basis_x": {"x": 0, "y": 2, "z": 0},
                            "basis_y": {"x": -2, "y": 0, "z": 0},
                            "basis_z": {"x": 0, "y": 0, "z": 2},
                        },
                        "diameter_probe_segments": [
                            {
                                "segment_id": "vertical-branch",
                                "row_index": 0,
                                "sequence": 0,
                                "start": {"x": 10, "y": 0},
                                "end": {"x": 10, "y": 10},
                                "color_key": "orange",
                            },
                            {
                                "segment_id": "horizontal-main",
                                "row_index": 1,
                                "sequence": 0,
                                "start": {"x": 5, "y": 5},
                                "end": {"x": 15, "y": 5},
                                "color_key": "cyan",
                            },
                        ],
                    },
                    "skipped": [],
                }
            )

        analysis = result["diameter_analysis"]
        self.assertEqual(32.0, analysis["segments"][0]["diameter_mm"])
        self.assertIsNone(analysis["segments"][1]["diameter_mm"])
        self.assertEqual("vertical-branch", analysis["label_matches"][0]["segment_id"])

    def test_hot_analysis_converts_millimetre_dwg_coordinates_to_revit_feet(self) -> None:
        from sc_revit.fire_branch.hot_analysis import build_preview_summary

        source_points = [
            {"block_name": "ANCHOR-A", "x": 300000000, "y": 45000000, "z": 0},
            {"block_name": "ANCHOR-B", "x": 300000304.8, "y": 45000000, "z": 0},
            {"block_name": "ANCHOR-C", "x": 300000000, "y": 45000304.8, "z": 0},
        ]
        model_points = [
            {"block_name": "sample.ANCHOR-A", "x": 10, "y": 20, "z": 0},
            {"block_name": "sample.ANCHOR-B", "x": 20, "y": 20, "z": 0},
            {"block_name": "sample.ANCHOR-C", "x": 10, "y": 30, "z": 0},
        ]

        with patch(
            "sc_revit.fire_branch.dwg_diameter_reader.read_dwg_diameter_texts",
            return_value={
                "unit_code": 4,
                "unit_name": "毫米",
                "unit_to_feet": 1.0 / 304.8,
                "block_points": source_points,
                "texts": [
                    {
                        "text": '1 1/4"',
                        "x": 300000152.4,
                        "y": 45000030.48,
                        "z": 0,
                        "color": 7,
                        "layer": "FIRE-ANNO",
                        "bounds": {
                            "min_x": 300000060.96,
                            "min_y": 45000015.24,
                            "max_x": 300000243.84,
                            "max_y": 45000045.72,
                        },
                        "direction": {"x": 1, "y": 0},
                    }
                ],
            },
        ):
            result = build_preview_summary(
                {
                    "cad_coordinate_anchors": model_points,
                    "cad_path_check": {
                        "status": "matched",
                        "coordinate_verified": True,
                        "selected_source_path": "millimetre-sample.dwg",
                        "import_transform": {
                            "origin": {"x": 0, "y": 0, "z": 0},
                            "basis_x": {"x": 1, "y": 0, "z": 0},
                            "basis_y": {"x": 0, "y": 1, "z": 0},
                            "basis_z": {"x": 0, "y": 0, "z": 1},
                        },
                        "diameter_probe_segments": [
                            {
                                "segment_id": "row-0-0",
                                "row_index": 0,
                                "sequence": 0,
                                "start": {"x": 10, "y": 21},
                                "end": {"x": 20, "y": 21},
                                "color_key": "orange",
                            }
                        ],
                    },
                    "skipped": [],
                }
            )

        analysis = result["diameter_analysis"]
        self.assertEqual(1, analysis["matched_label_count"])
        self.assertEqual(32.0, analysis["segments"][0]["diameter_mm"])
        self.assertEqual("毫米", analysis["source_unit"])
        self.assertEqual("revit_linked_geometry_anchors", analysis["coordinate_source"])
        self.assertLessEqual(analysis["anchor_max_residual_mm"], 1.0)
        self.assertIn("DWG 單位：毫米", result["summary_lines"])

    def test_anchor_calibration_rejects_mismatched_repeated_blocks(self) -> None:
        from sc_revit.fire_branch.hot_analysis import _calibrate_dwg_to_revit

        source = [
            {"block_name": "A", "x": 0, "y": 0},
            {"block_name": "A", "x": 10, "y": 0},
            {"block_name": "B", "x": 0, "y": 10},
            {"block_name": "C", "x": 10, "y": 10},
        ]
        model = [
            {"block_name": "A", "x": 0, "y": 0},
            {"block_name": "A", "x": 20, "y": 0},
            {"block_name": "B", "x": 0, "y": 10},
            {"block_name": "C", "x": 10, "y": 10},
        ]

        with self.assertRaisesRegex(ValueError, "殘差超過 1 mm"):
            _calibrate_dwg_to_revit(source, model, 1.0)

    def test_revit_host_rolls_back_sandbox_and_only_commit_can_keep_partial_evidence(self) -> None:
        source = (
            ROOT / "revit_addin" / "src" / "Handlers" / "FireBranchHandler.cs"
        ).read_text(encoding="utf-8")
        self.assertIn('action == "test_fire_branch_pipes"', source)
        self.assertIn('executionMode == "sandbox"', source)
        self.assertIn("transactionGroup.RollBack()", source)
        self.assertIn('fireBranchStage = "sandbox_restore_after_failure"', source)
        self.assertIn("sandboxRolledBackEarly = true", source)
        self.assertIn('fireBranchStage = "partial_failure_decision"', source)
        self.assertIn('new TaskDialog("SC REVIT 消防支管")', source)
        self.assertIn("保留成功部分", source)
        self.assertIn("全部復原", source)
        self.assertIn("TaskDialogResult.CommandLink1", source)
        self.assertIn('reason = "diagnostic_evidence_kept"', source)
        self.assertIn("evidence_element_ids = evidenceElementIds", source)
        self.assertIn("partial_success = partialFailureKept", source)
        self.assertIn("retention_decision = retentionDecision", source)
        self.assertIn("restoration_verified = restorationVerified", source)
        self.assertIn("residual_created_element_ids = residualCreatedElementIds", source)
        self.assertNotIn("model_restored = isSandbox", source)
        self.assertIn("model_changes_kept = !isSandbox", source)
        self.assertIn("diagnostic_evidence_element_ids = evidenceElementIds", source)
        self.assertIn('partialFailureKept ? "partial" : "failed"', source)

        gui_source = (ROOT / "gui_app.py").read_text(encoding="utf-8")
        self.assertIn("format_fire_branch_failure_item", gui_source)
        self.assertIn('if payload.get("partial_success")', gui_source)
        self.assertIn("actionable_failed", gui_source)
        self.assertIn("部分建立完成｜已保留成功部分", gui_source)
        self.assertIn("可在 Revit 使用一次復原", gui_source)

    def test_revit_host_applies_segment_diameters_before_verifying_connections(self) -> None:
        source = (
            ROOT / "revit_addin" / "src" / "Handlers" / "FireBranchHandler.cs"
        ).read_text(encoding="utf-8")

        self.assertIn("ReadFireBranchDiameterPlan", source)
        self.assertIn("ApplyFireBranchDiameterPlan", source)
        self.assertIn("RoutingPreferenceRuleGroupType.Junctions", source)
        self.assertIn("RoutingPreferenceRuleGroupType.Transitions", source)
        self.assertIn("CreateFireDropWithTransition", source)
        self.assertIn("FireSprinklerDropDiameterMillimeters", source)
        self.assertIn("variable_diameter_applied", source)

    def test_revit_host_requires_single_sprinkler_pilot_contract(self) -> None:
        source = (
            ROOT / "revit_addin" / "src" / "Handlers" / "FireBranchHandler.cs"
        ).read_text(encoding="utf-8")

        self.assertIn('sandboxScope == "single_sprinkler"', source)
        self.assertIn("preview_snapshot_id", source)
        self.assertIn("pilot_source_row_index", source)
        self.assertIn("require_diameter_plan", source)
        self.assertIn("model_plan_hash", source)

    def test_revit_host_uses_stable_explicit_system_dn25_drop_sequence(self) -> None:
        source = (
            ROOT / "revit_addin" / "src" / "Handlers" / "FireBranchHandler.cs"
        ).read_text(encoding="utf-8")
        self.assertIn("CreateFireDropForSystem", source)
        self.assertIn("pipeConnector.ConnectTo(startConnector)", source)
        self.assertIn("explicit-system pipe creation returned null", source)
        self.assertIn(
            "Pipe pipe = CreateFirePipe(",
            source,
        )
        drop_start = source.index("private static FireDropAssembly CreateFireDropWithTransition")
        drop_end = source.index("private static List<ElementId> ResolveConnectedFireSystemIds", drop_start)
        drop_method = source[drop_start:drop_end]
        self.assertIn("CreateFireDropForSystem(", drop_method)
        self.assertNotIn("CreateFirePipeConnectedToSprinkler(", drop_method)
        self.assertNotIn("DN25 drop was deleted or left disconnected after reducing tee creation", drop_method)
        self.assertIn("TryConnectPipeToRun", drop_method)
        self.assertIn("TryConnectCompletedDropToSprinkler", source)
        self.assertIn("IsPhysicallyReachableFromFireElement(", source)
        self.assertIn("FireSprinklerDropDiameterMillimeters", source)
        self.assertLess(
            source.index("ApplyFireBranchDiameterPlan(", source.index("CreateFireDropWithTransition(")),
            source.index("TryConnectCompletedDropToSprinkler(", source.index("CreateFireDropWithTransition(")),
        )
        self.assertIn("doc.GetElement(sprinklerId) as FamilyInstance", source)
        self.assertIn("FindConnectorNear(currentSprinkler, sprinklerPoint)", source)
        self.assertIn("pipe.MEPSystem", source)

    def test_revit_host_does_not_preassign_sprinklers_before_physical_connection(self) -> None:
        source = (
            ROOT / "revit_addin" / "src" / "Handlers" / "FireBranchHandler.cs"
        ).read_text(encoding="utf-8")

        self.assertNotIn("targetPipingSystem.Add(sprinklerConnectorSet)", source)
        self.assertNotIn("sprinklerSystemMembershipReady", source)


if __name__ == "__main__":
    unittest.main()
