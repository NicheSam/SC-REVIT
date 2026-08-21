import unittest

from sc_revit.fire_branch.topology_plan import (
    build_uniform_route_analysis,
    create_topology_plan,
    create_uniform_topology_plan,
    revise_topology_plan,
    validate_topology_plan,
)


def _analysis() -> dict:
    return {
        "status": "ready",
        "cad_path_verified": True,
        "unresolved_segment_count": 0,
        "main_context_segments": [
            {
                "segment_id": "main-1",
                "source_element_id": 100,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 10, "y": 0, "z": 0},
            }
        ],
        "segments": [
            {
                "segment_id": "row-0-0",
                "row_index": 0,
                "sequence": 0,
                "start": {"x": 2, "y": 0, "z": 0},
                "end": {"x": 2, "y": 5, "z": 0},
                "diameter_mm": 32,
                "evidence": "direct_text",
            }
        ],
        "reducers": [],
        "junctions": [
            {
                "row_index": 0,
                "branch_segment_id": "row-0-0",
                "main_segment_id": "main-1",
                "point": {"x": 2, "y": 0, "z": 0},
                "main_diameter_mm": 100,
                "branch_diameter_mm": 32,
                "review_required": False,
            }
        ],
    }


class FireBranchTopologyPlanContractTests(unittest.TestCase):
    def test_cad_plan_is_versioned_hashed_and_contains_complete_geometry(self) -> None:
        plan = create_topology_plan(
            _analysis(),
            source_mode="cad",
            preview_snapshot_id="preview-1",
            settings={"height_offset_cm": 0},
        )

        self.assertEqual("fire_branch_topology_plan.v5", plan["schema_version"])
        self.assertEqual("cad", plan["source_mode"])
        self.assertEqual("preview-1", plan["plan_id"])
        self.assertEqual(1, plan["revision"])
        self.assertIsNone(plan["parent_plan_hash"])
        self.assertEqual("row-0-0", plan["segments"][0]["segment_id"])
        self.assertEqual("segment:row-0-0", plan["segments"][0]["plan_entity_id"])
        self.assertEqual("main-1", plan["main_segments"][0]["segment_id"])
        self.assertEqual("main:main-1", plan["main_segments"][0]["plan_entity_id"])
        self.assertEqual("junction:main-1:row-0-0", plan["junctions"][0]["plan_entity_id"])
        self.assertEqual("valid", plan["validation"]["status"])
        self.assertEqual(64, len(plan["plan_hash"]))

    def test_same_input_produces_the_same_plan_hash(self) -> None:
        first = create_topology_plan(
            _analysis(), source_mode="cad", preview_snapshot_id="preview-1"
        )
        second = create_topology_plan(
            _analysis(), source_mode="cad", preview_snapshot_id="preview-1"
        )

        self.assertEqual(first["plan_hash"], second["plan_hash"])

    def test_plan_keeps_per_sprinkler_route_candidate_decisions(self) -> None:
        analysis = _analysis()
        analysis["route_candidate_decisions"] = [
            {
                "sprinkler_id": "501",
                "status": "selected",
                "selection_consistent": True,
                "selected_candidate_id": "candidate-1",
                "candidates": {
                    "candidate-1": {"main_pipe_id": 10},
                    "candidate-2": {"main_pipe_id": 11},
                },
            }
        ]

        plan = create_topology_plan(
            analysis, source_mode="cad", preview_snapshot_id="preview-routes"
        )

        self.assertEqual(
            "candidate-1",
            plan["evidence"]["route_candidate_decisions"][0][
                "selected_candidate_id"
            ],
        )

    def test_route_candidate_edit_updates_the_matching_sprinkler_only(self) -> None:
        analysis = _analysis()
        analysis["route_candidate_decisions"] = [
            {
                "sprinkler_id": "501",
                "candidates": {
                    "candidate-1": {"main_pipe_id": 10},
                    "candidate-2": {"main_pipe_id": 11},
                },
                "selected_candidate_id": "candidate-1",
            },
            {
                "sprinkler_id": "502",
                "candidates": {"candidate-3": {"main_pipe_id": 12}},
                "selected_candidate_id": "candidate-3",
            },
        ]
        plan = create_topology_plan(
            analysis, source_mode="cad", preview_snapshot_id="preview-route-edit"
        )
        revised = revise_topology_plan(
            plan,
            {
                "type": "choose_route_candidate",
                "plan_id": plan["plan_id"],
                "expected_revision": plan["revision"],
                "expected_hash": plan["plan_hash"],
                "sprinkler_id": "501",
                "candidate_id": "candidate-2",
                "target_id": "candidate-2",
                "reason": "測試候選修正",
            },
        )

        decisions = revised["evidence"]["route_candidate_decisions"]
        self.assertEqual("candidate-2", decisions[0]["selected_candidate_id"])
        self.assertEqual("candidate-3", decisions[1]["selected_candidate_id"])
        self.assertEqual(
            "candidate-2",
            revised["evidence"]["selected_route_candidate_ids"]["501"],
        )

    def test_revising_a_segment_creates_a_new_revision_without_mutating_parent(self) -> None:
        original = create_topology_plan(
            _analysis(), source_mode="cad", preview_snapshot_id="preview-1"
        )
        revised = revise_topology_plan(
            original,
            {
                "type": "set_segment_diameter",
                "segment_id": "row-0-0",
                "diameter_mm": 25,
            },
        )

        self.assertEqual(32, original["segments"][0]["diameter_mm"])
        self.assertEqual(25, revised["segments"][0]["diameter_mm"])
        self.assertEqual(2, revised["revision"])
        self.assertEqual(original["plan_hash"], revised["parent_plan_hash"])
        self.assertNotEqual(original["plan_hash"], revised["plan_hash"])
        self.assertEqual("topology_valid", revised["validation"]["status"])

    def test_segment_diameter_edit_rebuilds_engineering_reducers(self) -> None:
        analysis = _analysis()
        analysis["main_context_segments"][0]["start"] = {"x": -5, "y": 0, "z": 0}
        analysis["main_context_segments"][0]["end"] = {"x": 5, "y": 0, "z": 0}
        analysis["segments"] = [
            {
                "segment_id": "small-first",
                "row_index": 0,
                "sequence": 0,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 0, "y": 2, "z": 0},
                "diameter_mm": 25,
                "evidence": "direct_text",
            },
            {
                "segment_id": "small-next",
                "row_index": 0,
                "sequence": 1,
                "start": {"x": 0, "y": 2, "z": 0},
                "end": {"x": 0, "y": 5, "z": 0},
                "diameter_mm": 25,
                "evidence": "direct_text",
            },
            {
                "segment_id": "large-opposite",
                "row_index": 1,
                "sequence": 0,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 0, "y": -4, "z": 0},
                "diameter_mm": 32,
                "evidence": "direct_text",
            },
        ]
        analysis["junctions"] = [
            {
                "row_index": 0,
                "branch_segment_id": "small-first",
                "main_segment_id": "main-1",
                "point": {"x": 0, "y": 0, "z": 0},
                "main_diameter_mm": 100,
                "branch_diameter_mm": 25,
                "review_required": False,
            },
            {
                "row_index": 1,
                "branch_segment_id": "large-opposite",
                "main_segment_id": "main-1",
                "point": {"x": 0, "y": 0, "z": 0},
                "main_diameter_mm": 100,
                "branch_diameter_mm": 32,
                "review_required": False,
            },
        ]
        plan = create_topology_plan(
            analysis, source_mode="cad", preview_snapshot_id="preview-reducer-rebuild"
        )
        original_cross_reducers = [
            item for item in plan["reducers"] if item.get("placement") == "after_cross"
        ]
        self.assertEqual(1, len(original_cross_reducers))

        revised = revise_topology_plan(
            plan,
            {
                "type": "change_segment_diameter",
                "segment_id": "small-first",
                "diameter_mm": 32,
                "expected_plan_hash": plan["plan_hash"],
            },
        )

        self.assertEqual(
            [],
            [item for item in revised["reducers"] if item.get("placement") == "after_cross"],
        )
        self.assertEqual(
            [
                {
                    "before_segment_id": "small-first",
                    "after_segment_id": "small-next",
                    "from_diameter_mm": 32.0,
                    "to_diameter_mm": 25.0,
                    "placement": "along_branch",
                }
            ],
            [
                {
                    "before_segment_id": item.get("before_segment_id"),
                    "after_segment_id": item.get("after_segment_id"),
                    "from_diameter_mm": item.get("from_diameter_mm"),
                    "to_diameter_mm": item.get("to_diameter_mm"),
                    "placement": item.get("placement"),
                }
                for item in revised["reducers"]
            ],
        )
        junction = revised["junctions"][0]
        self.assertEqual([32.0, 32.0], junction["branch_outlet_diameters_mm"])
        self.assertEqual("topology_valid", revised["validation"]["status"])

    def test_uniform_plan_reuses_geometry_and_removes_cad_diameter_evidence(self) -> None:
        analysis = _analysis()
        analysis["segments"][0]["diameter_mm"] = None
        analysis["segments"][0]["review_required"] = True
        analysis["unresolved_segment_count"] = 1

        plan = create_uniform_topology_plan(
            analysis,
            diameter_mm=40,
            preview_snapshot_id="uniform-1",
        )

        self.assertEqual("uniform", plan["source_mode"])
        self.assertEqual(40, plan["segments"][0]["diameter_mm"])
        self.assertEqual("uniform_user_setting", plan["segments"][0]["evidence"])
        self.assertFalse(plan["segments"][0]["review_required"])
        self.assertEqual([], plan["reducers"])
        self.assertEqual("valid", validate_topology_plan(plan)["status"])

    def test_uniform_route_adapter_builds_junctions_without_cad_diameter_evidence(self) -> None:
        route = build_uniform_route_analysis(
            route_segments=[
                {
                    "segment_id": "row-0-0",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 2, "y": 0, "z": 0},
                    "end": {"x": 2, "y": 5, "z": 0},
                }
            ],
            main_segments=_analysis()["main_context_segments"],
            diameter_mm=40,
            main_diameter_mm=100,
        )

        self.assertEqual(40, route["segments"][0]["diameter_mm"])
        self.assertEqual("uniform_user_setting", route["segments"][0]["evidence"])
        self.assertEqual("row-0-0", route["junctions"][0]["branch_segment_id"])
        self.assertEqual("main-1", route["junctions"][0]["main_segment_id"])
        self.assertEqual("reducing_tee", route["junctions"][0]["kind"])

    def test_unknown_edit_command_is_rejected(self) -> None:
        plan = create_topology_plan(
            _analysis(), source_mode="cad", preview_snapshot_id="preview-1"
        )

        with self.assertRaisesRegex(ValueError, "不支援的拓樸修正"):
            revise_topology_plan(plan, {"type": "move_sprinkler"})

    def test_edit_with_stale_plan_hash_is_rejected(self) -> None:
        plan = create_topology_plan(
            _analysis(), source_mode="cad", preview_snapshot_id="preview-1"
        )

        with self.assertRaisesRegex(ValueError, "已不是目前版本"):
            revise_topology_plan(
                plan,
                {
                    "type": "set_segment_diameter",
                    "segment_id": "row-0-0",
                    "diameter_mm": 25,
                    "expected_plan_hash": "stale",
                },
            )

    def test_edit_requires_matching_plan_identity_and_revision_when_supplied(self) -> None:
        plan = create_topology_plan(
            _analysis(), source_mode="cad", preview_snapshot_id="preview-1"
        )

        with self.assertRaisesRegex(ValueError, "計畫識別碼"):
            revise_topology_plan(
                plan,
                {
                    "type": "change_segment_diameter",
                    "plan_id": "other-plan",
                    "expected_revision": 1,
                    "expected_hash": plan["plan_hash"],
                    "target_id": "segment:row-0-0",
                    "diameter_mm": 25,
                },
            )

        with self.assertRaisesRegex(ValueError, "版本"):
            revise_topology_plan(
                plan,
                {
                    "type": "change_segment_diameter",
                    "plan_id": plan["plan_id"],
                    "expected_revision": 2,
                    "expected_hash": plan["plan_hash"],
                    "target_id": "segment:row-0-0",
                    "diameter_mm": 25,
                },
            )

    def test_documented_edit_commands_and_review_marker_are_supported(self) -> None:
        plan = create_topology_plan(
            _analysis(), source_mode="cad", preview_snapshot_id="preview-1"
        )
        revised = revise_topology_plan(
            plan,
            {
                "type": "change_segment_diameter",
                "plan_id": plan["plan_id"],
                "expected_revision": plan["revision"],
                "expected_hash": plan["plan_hash"],
                "target_id": "segment:row-0-0",
                "diameter_mm": 25,
                "reason": "CAD 文字確認",
            },
        )
        self.assertEqual(25, revised["segments"][0]["diameter_mm"])
        self.assertEqual("change_segment_diameter", revised["last_command"]["type"])

        reviewed = revise_topology_plan(
            revised,
            {
                "type": "mark_reviewed",
                "plan_id": revised["plan_id"],
                "expected_revision": revised["revision"],
                "expected_hash": revised["plan_hash"],
                "target_id": "junction:main-1:row-0-0",
                "reason": "使用者確認接入點",
            },
        )
        self.assertFalse(reviewed["junctions"][0]["review_required"])

    def test_junction_and_reducer_edits_create_traceable_revisions(self) -> None:
        analysis = _analysis()
        analysis["reducers"] = [
            {
                "after_segment_id": "row-0-0",
                "before_segment_id": "row-0-0",
                "from_diameter_mm": 32,
                "to_diameter_mm": 25,
            }
        ]
        plan = create_topology_plan(analysis, preview_snapshot_id="preview-2")
        junction = revise_topology_plan(
            plan,
            {
                "type": "set_junction_kind",
                "junction_index": 0,
                "kind": "reducing_tee",
                "expected_plan_hash": plan["plan_hash"],
            },
        )
        reducer = revise_topology_plan(
            junction,
            {
                "type": "set_reducer",
                "reducer_index": 0,
                "from_diameter_mm": 40,
                "to_diameter_mm": 25,
                "expected_plan_hash": junction["plan_hash"],
            },
        )

        self.assertEqual("reducing_tee", junction["junctions"][0]["kind"])
        self.assertEqual(40, reducer["reducers"][0]["from_diameter_mm"])
        self.assertEqual(3, reducer["revision"])
        self.assertEqual(junction["plan_hash"], reducer["parent_plan_hash"])

    def test_cross_edit_with_only_one_branch_is_invalid_for_preflight(self) -> None:
        plan = create_topology_plan(
            _analysis(), source_mode="cad", preview_snapshot_id="preview-cross"
        )

        revised = revise_topology_plan(
            plan,
            {
                "type": "set_junction_kind",
                "junction_index": 0,
                "kind": "cross",
                "expected_plan_hash": plan["plan_hash"],
            },
        )

        self.assertEqual("invalid", revised["validation"]["status"])
        self.assertIn(
            "junction_branch_count_mismatch",
            {item["code"] for item in revised["validation"]["issues"]},
        )

    def test_reducer_edit_updates_adjacent_segment_diameters(self) -> None:
        analysis = _analysis()
        analysis["segments"].append(
            {
                "segment_id": "row-0-1",
                "row_index": 0,
                "sequence": 1,
                "start": {"x": 2, "y": 5, "z": 0},
                "end": {"x": 2, "y": 8, "z": 0},
                "diameter_mm": 25,
                "evidence": "direct_text",
            }
        )
        analysis["reducers"] = [
            {
                "before_segment_id": "row-0-0",
                "after_segment_id": "row-0-1",
                "from_diameter_mm": 32,
                "to_diameter_mm": 25,
            }
        ]
        plan = create_topology_plan(
            analysis, source_mode="cad", preview_snapshot_id="preview-reducer"
        )

        revised = revise_topology_plan(
            plan,
            {
                "type": "set_reducer",
                "reducer_index": 0,
                "from_diameter_mm": 40,
                "to_diameter_mm": 20,
                "expected_plan_hash": plan["plan_hash"],
            },
        )

        diameters = {
            item["segment_id"]: item["diameter_mm"] for item in revised["segments"]
        }
        self.assertEqual(40, diameters["row-0-0"])
        self.assertEqual(20, diameters["row-0-1"])
        self.assertEqual("topology_valid", revised["validation"]["status"])


if __name__ == "__main__":
    unittest.main()
