import unittest

from sc_revit.fire_branch.cad_route_graph import (
    build_cad_route_graph,
    build_revit_route_candidate_decisions,
    compare_cad_route_candidates,
)


class FireBranchCadRouteGraphTests(unittest.TestCase):
    def test_fragmented_collinear_route_uses_position_not_total_length(self) -> None:
        graph = build_cad_route_graph(
            [
                {"segment_id": "a", "start": (0, 0), "end": (5, 0), "layer": "PIPE"},
                {"segment_id": "b", "start": (5.3, 0), "end": (10, 0), "layer": "PIPE"},
            ],
            coordinate_tolerance=0.5,
        )

        self.assertEqual(1, graph["component_count"])
        self.assertEqual(2, graph["edge_count"])
        self.assertTrue(graph["length_is_diagnostic_only"])
        shared = [node for node in graph["nodes"] if node["degree"] == 2]
        self.assertEqual(1, len(shared))
        self.assertEqual(["a", "b"], shared[0]["source_segment_ids"])
        self.assertGreater(shared[0]["max_snap_residual"], 0)

    def test_crossing_fragments_are_split_into_a_four_way_node(self) -> None:
        graph = build_cad_route_graph(
            [
                {"segment_id": "horizontal", "start": (-5, 0), "end": (5, 0)},
                {"segment_id": "vertical", "start": (0, -5), "end": (0, 5)},
            ],
            coordinate_tolerance=0.01,
        )

        junctions = [node for node in graph["nodes"] if node["degree"] == 4]
        self.assertEqual(1, len(junctions))
        self.assertEqual(4, graph["edge_count"])

    def test_gap_beyond_tolerance_remains_a_disconnected_evidence_break(self) -> None:
        graph = build_cad_route_graph(
            [
                {"segment_id": "left", "start": (0, 0), "end": (5, 0)},
                {"segment_id": "right", "start": (6, 0), "end": (10, 0)},
            ],
            coordinate_tolerance=0.25,
        )

        self.assertEqual(2, graph["component_count"])
        self.assertEqual(2, graph["edge_count"])

    def test_nodes_and_edges_keep_their_component_identity(self) -> None:
        graph = build_cad_route_graph(
            [
                {"segment_id": "main", "start": (0, 0), "end": (10, 0)},
                {"segment_id": "branch", "start": (5, -5), "end": (5, 5)},
                {"segment_id": "isolated", "start": (100, 0), "end": (110, 0)},
            ],
            coordinate_tolerance=0.01,
        )

        self.assertEqual(2, graph["component_count"])
        self.assertTrue(all(edge.get("component_id") for edge in graph["edges"]))
        self.assertTrue(all(node.get("component_id") for node in graph["nodes"]))
        crossing_edges = [
            edge for edge in graph["edges"] if "main" in edge["source_segment_ids"]
        ]
        self.assertEqual(2, len(crossing_edges))
        self.assertEqual(
            {edge["component_id"] for edge in crossing_edges},
            {graph["edges"][0]["component_id"]},
        )

    def test_metadata_and_overlapping_fragments_are_preserved(self) -> None:
        graph = build_cad_route_graph(
            [
                {
                    "segment_id": "line-1",
                    "start": (0, 0, 0),
                    "end": (10, 0, 0),
                    "layer": "FIRE",
                    "color_key": "rgb:255,0,0",
                },
                {
                    "segment_id": "line-2",
                    "start": (0, 0, 0),
                    "end": (10, 0, 0),
                    "layer": "FIRE",
                    "color_key": "rgb:255,0,0",
                },
            ],
            coordinate_tolerance=0.01,
        )

        self.assertEqual(1, graph["edge_count"])
        edge = graph["edges"][0]
        self.assertEqual(["line-1", "line-2"], edge["source_segment_ids"])
        self.assertEqual(2, edge["fragment_count"])
        self.assertEqual(["FIRE"], edge["layers"])
        self.assertEqual(["rgb:255,0,0"], edge["colors"])

    def test_route_candidate_comparison_keeps_reasons_and_prefers_complete_cad_path(self) -> None:
        decision = compare_cad_route_candidates(
            [
                {
                    "candidate_id": "parallel-short",
                    "sprinkler_reached": False,
                    "continuous_coverage_ratio": 1.0,
                    "coverage_ratio": 1.0,
                    "diameter_evidence_ratio": 1.0,
                    "topology_consistency_ratio": 1.0,
                    "turn_count": 0,
                    "length": 4.0,
                    "anchor_distance": 0.1,
                },
                {
                    "candidate_id": "fishbone-route",
                    "sprinkler_reached": True,
                    "continuous_coverage_ratio": 0.8,
                    "coverage_ratio": 0.9,
                    "diameter_evidence_ratio": 0.7,
                    "topology_consistency_ratio": 1.0,
                    "turn_count": 1,
                    "length": 7.0,
                    "anchor_distance": 0.2,
                },
            ]
        )

        self.assertEqual("selected", decision["status"])
        self.assertEqual("fishbone-route", decision["selected_candidate_id"])
        self.assertTrue(decision["candidates"]["fishbone-route"]["selected"])
        self.assertIn("到達目標灑水頭", "；".join(decision["candidates"]["fishbone-route"]["reasons"]))
        self.assertIn("未到達目標灑水頭", "；".join(decision["candidates"]["parallel-short"]["rejected_reasons"]))

    def test_route_candidate_comparison_is_deterministic_on_full_tie(self) -> None:
        candidates = [
            {"candidate_id": "b", "sprinkler_reached": True, "coverage_ratio": 1.0},
            {"candidate_id": "a", "sprinkler_reached": True, "coverage_ratio": 1.0},
        ]
        first = compare_cad_route_candidates(candidates)
        second = compare_cad_route_candidates(list(reversed(candidates)))
        self.assertEqual("a", first["selected_candidate_id"])
        self.assertEqual(first, second)

    def test_revit_assignment_audit_preserves_authoritative_selection(self) -> None:
        decisions = build_revit_route_candidate_decisions(
            [
                {
                    "sprinkler_id": 501,
                    "status": "selected_by_cad_route_evidence",
                    "main_pipe_id": 200,
                    "source_import_id": 9,
                    "candidates": [
                        {
                            "main_pipe_id": 200,
                            "source_import_id": 9,
                            "coverage_ratio": 0.9,
                            "continuous_coverage_ratio": 0.8,
                            "sprinkler_end_matched": True,
                            "mean_offset_mm": 5,
                            "branch_length_mm": 1000,
                        },
                        {
                            "main_pipe_id": 201,
                            "source_import_id": 9,
                            "coverage_ratio": 1.0,
                            "continuous_coverage_ratio": 1.0,
                            "sprinkler_end_matched": False,
                            "mean_offset_mm": 1,
                            "branch_length_mm": 500,
                        },
                    ],
                }
            ]
        )

        self.assertEqual(1, len(decisions))
        decision = decisions[0]
        self.assertEqual("selected", decision["status"])
        self.assertTrue(decision["selection_consistent"])
        self.assertEqual(
            decision["selected_candidate_id"],
            decision["revit_selected_candidate_id"],
        )
        self.assertEqual(2, len(decision["candidates"]))

    def test_revit_assignment_without_candidates_is_review_only(self) -> None:
        decisions = build_revit_route_candidate_decisions(
            [
                {
                    "sprinkler_id": 502,
                    "status": "cad_route_unresolved",
                    "candidate_count": 2,
                    "candidates": [],
                }
            ]
        )

        self.assertEqual("needs_review", decisions[0]["status"])
        self.assertFalse(decisions[0]["selection_consistent"])


if __name__ == "__main__":
    unittest.main()
