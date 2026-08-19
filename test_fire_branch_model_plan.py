import unittest

from sc_revit.fire_branch.model_plan import (
    build_fire_branch_execution_plan,
    build_single_sprinkler_model_plan,
    select_single_sprinkler,
)
from sc_revit.fire_branch.diameter_analysis import _nearest_main_connection


class FireBranchModelPlanTests(unittest.TestCase):
    def test_junction_point_is_projected_onto_the_selected_main_centerline(self) -> None:
        branch = {
            "segment_id": "branch-1",
            "start": {"x": 4.0, "y": 0.03},
            "end": {"x": 4.0, "y": 5.0},
        }
        main = {
            "segment_id": "main-1",
            "start": {"x": 0.0, "y": 0.0},
            "end": {"x": 10.0, "y": 0.0},
        }

        _, point = _nearest_main_connection(branch, [main])

        self.assertAlmostEqual(4.0, point["x"])
        self.assertAlmostEqual(0.0, point["y"])

    def test_execution_plan_is_the_shared_source_for_reducing_cross(self) -> None:
        analysis = {
            "status": "ready",
            "unresolved_segment_count": 0,
            "segments": [
                {
                    "segment_id": "row-0-0",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0, "z": 0},
                    "end": {"x": 0, "y": 10, "z": 0},
                    "diameter_mm": 40,
                },
                {
                    "segment_id": "row-1-0",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0, "z": 0},
                    "end": {"x": 0, "y": -10, "z": 0},
                    "diameter_mm": 32,
                },
            ],
            "reducers": [],
            "junctions": [
                {
                    "row_index": 0,
                    "branch_segment_id": "row-0-0",
                    "main_segment_id": "main-0",
                    "point": {"x": 0, "y": 0, "z": 0},
                    "main_diameter_mm": 100,
                    "branch_diameter_mm": 40,
                    "review_required": False,
                },
                {
                    "row_index": 1,
                    "branch_segment_id": "row-1-0",
                    "main_segment_id": "main-0",
                    "point": {"x": 0, "y": 0, "z": 0},
                    "main_diameter_mm": 100,
                    "branch_diameter_mm": 32,
                    "review_required": False,
                },
            ],
        }

        plan = build_fire_branch_execution_plan(
            diameter_analysis=analysis,
            main_pipe_ids=[100],
            sprinkler_ids=[200, 201],
            preview_snapshot_id="preview-123",
            pipe_type_id=300,
            system_type_id=400,
            level_id=500,
        )

        self.assertEqual("fire_branch_execution_plan.v4", plan["schema_version"])
        self.assertEqual(
            "fire_branch_topology_plan.v4",
            plan["topology_plan"]["schema_version"],
        )
        self.assertEqual(2, len(plan["diameter_plan"]))
        self.assertEqual(1, len(plan["topology_plan"]["junctions"]))
        cross = plan["topology_plan"]["junctions"][0]
        self.assertEqual("reducing_cross", cross["kind"])
        self.assertEqual([0, 1], cross["row_indexes"])
        self.assertEqual(40.0, cross["common_branch_diameter_mm"])
        self.assertEqual([40.0, 32.0], cross["source_branch_diameters_mm"])
        self.assertEqual(1, len(plan["topology_plan"]["reducers"]))
        reducer = plan["topology_plan"]["reducers"][0]
        self.assertEqual("after_cross", reducer["placement"])
        self.assertEqual("fit_to_routing_parts", reducer["placement_strategy"])
        self.assertNotIn("offset_mm", reducer)
        self.assertEqual(64, len(plan["plan_hash"]))

    def test_opposite_branches_at_main_endpoint_are_a_tee_not_a_cross(self) -> None:
        analysis = {
            "status": "ready",
            "unresolved_segment_count": 0,
            "main_context_segments": [
                {
                    "segment_id": "main-100",
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
                    "start": {"x": 0, "y": 0, "z": 0},
                    "end": {"x": 0, "y": 10, "z": 0},
                    "diameter_mm": 25,
                },
                {
                    "segment_id": "row-1-0",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0, "z": 0},
                    "end": {"x": 0, "y": -10, "z": 0},
                    "diameter_mm": 25,
                },
            ],
            "reducers": [],
            "junctions": [
                {
                    "row_index": 0,
                    "branch_segment_id": "row-0-0",
                    "main_segment_id": "main-100",
                    "point": {"x": 0, "y": 0, "z": 0},
                    "main_diameter_mm": 100,
                    "branch_diameter_mm": 25,
                    "review_required": False,
                },
                {
                    "row_index": 1,
                    "branch_segment_id": "row-1-0",
                    "main_segment_id": "main-100",
                    "point": {"x": 0, "y": 0, "z": 0},
                    "main_diameter_mm": 100,
                    "branch_diameter_mm": 25,
                    "review_required": False,
                },
            ],
        }

        plan = build_fire_branch_execution_plan(
            diameter_analysis=analysis,
            main_pipe_ids=[100],
            sprinkler_ids=[200, 201],
            preview_snapshot_id="preview-endpoint-tee",
            pipe_type_id=300,
            system_type_id=400,
            level_id=500,
        )

        junction = plan["topology_plan"]["junctions"][0]
        self.assertEqual("reducing_endpoint_tee", junction["kind"])
        self.assertEqual(1, junction["main_run_count"])
        self.assertEqual([0, 1], junction["row_indexes"])

    def test_pilot_requires_exactly_one_explicit_tree_selection(self) -> None:
        sprinklers = [{"element_id": 200}, {"element_id": 201}]

        self.assertEqual(201, select_single_sprinkler(sprinklers, ["201"])["element_id"])
        with self.assertRaisesRegex(ValueError, "選取一顆"):
            select_single_sprinkler(sprinklers, [])
        with self.assertRaisesRegex(ValueError, "選取一顆"):
            select_single_sprinkler(sprinklers, ["200", "201"])

    def test_single_sprinkler_plan_keeps_original_row_and_confirmed_segments(self) -> None:
        analysis = {
            "status": "review_required",
            "segments": [
                {
                    "segment_id": "row-3-0",
                    "row_index": 3,
                    "sequence": 0,
                    "start": {"x": 0, "y": 10, "z": 0},
                    "end": {"x": 5, "y": 10, "z": 0},
                    "diameter_mm": 40,
                    "review_required": False,
                },
                {
                    "segment_id": "row-3-1",
                    "row_index": 3,
                    "sequence": 1,
                    "start": {"x": 5, "y": 10, "z": 0},
                    "end": {"x": 10, "y": 10, "z": 0},
                    "diameter_mm": 32,
                    "review_required": False,
                },
                {
                    "segment_id": "row-8-0",
                    "row_index": 8,
                    "sequence": 0,
                    "start": {"x": 0, "y": 40, "z": 0},
                    "end": {"x": 5, "y": 40, "z": 0},
                    "diameter_mm": None,
                    "review_required": True,
                },
            ],
        }

        plan = build_single_sprinkler_model_plan(
            main_pipe_id=100,
            sprinkler={"element_id": 200, "point": {"x": 9, "y": 10, "z": -2}},
            preview_snapshot_id="preview-123",
            diameter_analysis=analysis,
            pipe_type_id=300,
            system_type_id=400,
            level_id=500,
        )

        self.assertEqual("fire_branch_model_plan.v1", plan["schema_version"])
        self.assertEqual(3, plan["source_row_index"])
        self.assertEqual(200, plan["sprinkler_id"])
        self.assertEqual(["row-3-0", "row-3-1"], [item["segment_id"] for item in plan["diameter_plan"]])
        self.assertTrue(plan["require_diameter_plan"])
        self.assertEqual(64, len(plan["plan_hash"]))

    def test_single_sprinkler_plan_rejects_unconfirmed_selected_row(self) -> None:
        analysis = {
            "segments": [
                {
                    "segment_id": "row-2-0",
                    "row_index": 2,
                    "sequence": 0,
                    "start": {"x": 0, "y": 10},
                    "end": {"x": 10, "y": 10},
                    "diameter_mm": None,
                    "review_required": True,
                }
            ]
        }

        with self.assertRaisesRegex(ValueError, "尚未確認"):
            build_single_sprinkler_model_plan(
                main_pipe_id=100,
                sprinkler={"element_id": 200, "point": {"x": 9, "y": 10, "z": -2}},
                preview_snapshot_id="preview-123",
                diameter_analysis=analysis,
                pipe_type_id=300,
                system_type_id=400,
                level_id=500,
            )


if __name__ == "__main__":
    unittest.main()
