import unittest

from sc_revit.fire_branch.topology_profile import (
    _extract_route_candidates,
    classify_axis_polyline,
    summarize_fire_branch_snapshot,
)


class FireBranchTopologyProfileTests(unittest.TestCase):
    def test_classifies_linear_l_u_and_double_l_routes(self) -> None:
        self.assertEqual("linear", classify_axis_polyline([(0, 0, 0), (10, 0, 0)])["shape_class"])
        self.assertEqual(
            "L",
            classify_axis_polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)])["shape_class"],
        )
        self.assertEqual(
            "U",
            classify_axis_polyline(
                [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]
            )["shape_class"],
        )
        self.assertEqual(
            "double_L",
            classify_axis_polyline(
                [
                    (0, 0, 0),
                    (10, 0, 0),
                    (10, 10, 0),
                    (20, 10, 0),
                    (20, 20, 0),
                    (30, 20, 0),
                ]
            )["shape_class"],
        )

    def test_snapshot_with_junction_is_compound_network(self) -> None:
        snapshot = {
            "schema_version": "fire_branch_revit_snapshot.v1",
            "snapshot_id": "fixture",
            "main_graph": {
                "elements": [
                    {
                        "element_id": 1,
                        "kind": "pipe",
                        "diameter_mm": 25,
                        "geometry": {
                            "start": {"x": 0, "y": 0, "z": 0},
                            "end": {"x": 10, "y": 0, "z": 0},
                            "length_mm": 10,
                        },
                    },
                    {"element_id": 2, "kind": "pipe_fitting_or_accessory"},
                    {
                        "element_id": 3,
                        "kind": "pipe",
                        "diameter_mm": 25,
                        "geometry": {
                            "start": {"x": 10, "y": 0, "z": 0},
                            "end": {"x": 10, "y": 10, "z": 0},
                            "length_mm": 10,
                        },
                    },
                    {
                        "element_id": 4,
                        "kind": "pipe",
                        "diameter_mm": 25,
                        "geometry": {
                            "start": {"x": 10, "y": 0, "z": 0},
                            "end": {"x": 20, "y": 0, "z": 0},
                            "length_mm": 10,
                        },
                    },
                ],
                "edges": [],
                "connections": [
                    {"from_element_id": 1, "to_element_id": 2},
                    {"from_element_id": 2, "to_element_id": 3},
                    {"from_element_id": 2, "to_element_id": 4},
                ],
                "stopped_connections": [],
            },
        }
        profile = summarize_fire_branch_snapshot(snapshot)
        self.assertEqual("compound_network", profile["shape_class"])
        self.assertEqual(1, profile["junction_element_count"])
        self.assertEqual({"x": 2, "y": 1}, profile["pipe_axis_counts"])
        self.assertEqual(3, profile["diameter_profiles"]["DN25"]["pipe_count"])

    def test_cycle_candidate_does_not_repeat_a_pipe_id(self) -> None:
        candidates = _extract_route_candidates(
            {1, 2, 3},
            {1: {2, 3}, 2: {1, 3}, 3: {1, 2}},
            {
                1: {"geometry": {"start": {"x": 0, "y": 0, "z": 0}, "end": {"x": 10, "y": 0, "z": 0}, "length_mm": 10}},
                2: {"geometry": {"start": {"x": 10, "y": 0, "z": 0}, "end": {"x": 10, "y": 10, "z": 0}, "length_mm": 10}},
                3: {"geometry": {"start": {"x": 10, "y": 10, "z": 0}, "end": {"x": 0, "y": 0, "z": 0}, "length_mm": 10}},
            },
        )
        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertEqual(len(candidate["pipe_ids"]), len(set(candidate["pipe_ids"])))


if __name__ == "__main__":
    unittest.main()
