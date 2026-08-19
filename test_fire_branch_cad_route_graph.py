import unittest

from sc_revit.fire_branch.cad_route_graph import build_cad_route_graph


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


if __name__ == "__main__":
    unittest.main()
