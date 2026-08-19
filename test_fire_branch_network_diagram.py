import unittest
import xml.etree.ElementTree as ET

from sc_revit.fire_branch.network_diagram import (
    build_fire_branch_network_layout,
    diameter_to_display_color,
    render_fire_branch_network_svg,
)
from sc_revit.fire_branch.network_preview import (
    main_context_render_segments,
    next_zoom_scale,
    semantic_zoom_visibility,
)


class FireBranchNetworkDiagramTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analysis = {
            "cad_path_verified": True,
            "segments": [
                {
                    "segment_id": "row-0-0",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 8, "y": 0},
                    "diameter_mm": 40,
                    "color": "rgb:255,127,0",
                    "evidence": "explicit_color",
                    "planned_length_mm": 2438.4,
                },
                {
                    "segment_id": "row-0-1",
                    "row_index": 0,
                    "sequence": 1,
                    "start": {"x": 8, "y": 0},
                    "end": {"x": 14, "y": 0},
                    "diameter_mm": 32,
                    "color": "rgb:0,191,0",
                    "evidence": "line_color_reference",
                    "planned_length_mm": 1828.8,
                },
                {
                    "segment_id": "row-1-0",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 0, "y": 10},
                    "end": {"x": -6, "y": 10},
                    "diameter_mm": None,
                    "color": "aci:6",
                    "evidence": "conflicting_color",
                    "planned_length_mm": 1828.8,
                },
            ],
            "reducers": [
                {
                    "row_index": 0,
                    "after_segment_id": "row-0-0",
                    "before_segment_id": "row-0-1",
                    "from_diameter_mm": 40,
                    "to_diameter_mm": 32,
                }
            ],
            "junctions": [
                {
                    "row_index": 0,
                    "branch_segment_id": "row-0-0",
                    "main_segment_id": "main-1001",
                    "kind": "reducing_tee",
                    "main_diameter_mm": 100,
                    "branch_diameter_mm": 40,
                    "review_required": False,
                }
            ],
        }

    def test_layout_preserves_segments_colors_labels_and_reducer(self) -> None:
        layout = build_fire_branch_network_layout(self.analysis)

        self.assertEqual(3, len(layout["segments"]))
        self.assertEqual("#ff7f00", layout["segments"][0]["color"])
        self.assertEqual("#e53935", layout["segments"][0]["display_color"])
        self.assertIn('1 1/2"', layout["segments"][0]["diameter_label"])
        self.assertEqual("#bf00bf", layout["segments"][2]["color"])
        self.assertEqual("#8a8a8a", layout["segments"][2]["display_color"])
        self.assertTrue(layout["segments"][2]["review_required"])
        self.assertGreater(
            layout["segments"][0]["stroke_width"],
            layout["segments"][1]["stroke_width"],
        )
        self.assertGreaterEqual(
            layout["segments"][0]["stroke_width"]
            - layout["segments"][1]["stroke_width"],
            2.0,
        )
        self.assertGreater(
            layout["segments"][1]["stroke_width"],
            layout["segments"][2]["stroke_width"],
        )
        self.assertEqual(1, len(layout["reducers"]))
        self.assertEqual("DN40 → DN32", layout["reducers"][0]["label"])
        reducer = layout["reducers"][0]
        upstream = layout["segments"][0]
        downstream = layout["segments"][1]
        self.assertEqual((upstream["x2"], upstream["y2"]), reducer["lead_start"])
        self.assertEqual((reducer["x"], reducer["y"]), reducer["lead_end"])
        self.assertNotEqual((upstream["x2"], upstream["y2"]), reducer["lead_end"])
        self.assertGreater(reducer["x"], downstream["x1"])
        self.assertEqual(upstream["diameter_mm"], reducer["lead_diameter_mm"])
        self.assertAlmostEqual(22.2, reducer["lead_length_px"])
        self.assertEqual("symbol_clearance_only", reducer["spacing_basis"])
        self.assertEqual(
            (upstream["terminal_x"], upstream["terminal_y"]),
            reducer["lead_start"],
        )
        self.assertEqual(
            (upstream["terminal_x"], upstream["terminal_y"]),
            (downstream["x1"], downstream["y1"]),
        )
        self.assertEqual(1, len(layout["junctions"]))
        self.assertEqual("DN100 × DN100 × DN40", layout["junctions"][0]["label"])
        self.assertEqual("reducing_tee", layout["junctions"][0]["kind"])

    def test_unverified_cad_path_is_neutral_and_uses_planned_geometry(self) -> None:
        analysis = {
            "cad_path_check": {
                "status": "mismatch",
                "coordinate_verified": True,
                "coverage_ratio": 0.0,
            },
            "segments": [
                {
                    "segment_id": "unverified-route",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "cad_geometry_start": {"x": 100, "y": 0},
                    "cad_geometry_end": {"x": 200, "y": 0},
                    "diameter_mm": 32,
                    "color": "rgb:255,0,0",
                    "planned_length_mm": 3048,
                }
            ],
        }

        layout = build_fire_branch_network_layout(analysis)
        segment = layout["segments"][0]

        self.assertFalse(layout["cad_verified"])
        self.assertEqual("#8a8a8a", segment["color"])
        self.assertEqual("#8a8a8a", segment["display_color"])
        self.assertEqual("rgb:255,0,0", segment["cad_source_color"])
        self.assertTrue(segment["review_required"])
        self.assertEqual("\u0043\u0041\u0044\u8def\u5f91\u672a\u9a57\u8b49", segment["evidence_label"])
        svg = render_fire_branch_network_svg(analysis)
        self.assertIn('data-cad-verified="false"', svg)
        self.assertIn("CAD 路徑未驗證", svg)
        self.assertIn("不可用於建模", svg)
        self.assertIn('data-cad-source-color="rgb:255,0,0"', svg)

    def test_missing_cad_verification_contract_is_not_treated_as_matched(self) -> None:
        analysis = {
            "segments": [
                {
                    "segment_id": "legacy-or-stale-dll",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "diameter_mm": 25,
                    "color": "rgb:255,0,0",
                }
            ]
        }

        layout = build_fire_branch_network_layout(analysis)
        svg = render_fire_branch_network_svg(analysis)

        self.assertFalse(layout["cad_verified"])
        self.assertEqual("#8a8a8a", layout["segments"][0]["display_color"])
        self.assertIn('data-cad-verified="false"', svg)
        self.assertIn("CAD 路徑未驗證", svg)

    def test_matched_cad_path_can_use_cad_geometry_and_colour(self) -> None:
        analysis = {
            "cad_path_check": {
                "status": "matched",
                "coordinate_verified": True,
                "coverage_ratio": 1.0,
            },
            "segments": [
                {
                    "segment_id": "matched-route",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 1, "y": 0},
                    "cad_geometry_start": {"x": 10, "y": 0},
                    "cad_geometry_end": {"x": 20, "y": 0},
                    "diameter_mm": 32,
                    "color": "rgb:255,127,0",
                }
            ],
        }

        layout = build_fire_branch_network_layout(analysis)
        segment = layout["segments"][0]

        self.assertTrue(layout["cad_verified"])
        self.assertEqual("#ff7f00", segment["color"])
        self.assertEqual("rgb:255,127,0", segment["cad_source_color"])
        self.assertFalse(segment["review_required"])
        svg = render_fire_branch_network_svg(analysis)
        self.assertIn('data-cad-verified="true"', svg)
        self.assertNotIn("CAD 路徑未驗證", svg)

    def test_layout_preserves_l_shaped_main_context_for_svg(self) -> None:
        analysis = {
            "segments": [
                {
                    "segment_id": "row-0-0",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 8, "y": 0},
                    "diameter_mm": 40,
                    "planned_length_mm": 2438.4,
                }
            ],
            "main_context_segments": [
                {
                    "segment_id": "main-1",
                    "start": {"x": 0, "y": -10},
                    "end": {"x": 0, "y": 10},
                },
                {
                    "segment_id": "main-2",
                    "start": {"x": 0, "y": -10},
                    "end": {"x": 12, "y": -10},
                },
            ],
        }

        layout = build_fire_branch_network_layout(analysis, main_diameter_mm=100)

        self.assertEqual("L", layout["main_shape"])
        self.assertEqual(2, len(layout["main_segments"]))
        self.assertEqual({"main-1", "main-2"}, {
            item["segment_id"] for item in layout["main_segments"]
        })
        for item in layout["main_segments"]:
            self.assertGreater(
                ((item["x2"] - item["x1"]) ** 2 + (item["y2"] - item["y1"]) ** 2) ** 0.5,
                0.0,
            )
        self.assertAlmostEqual(
            layout["main_segments"][0]["x1"],
            layout["segments"][0]["x1"],
        )
        svg = render_fire_branch_network_svg(analysis, main_diameter_mm=100)
        self.assertIn('data-main-shape="L"', svg)
        self.assertIn('class="main-context-segment"', svg)

    def test_verified_l_network_uses_one_topology_canvas_coordinate_space(self) -> None:
        analysis = {
            "cad_path_verified": True,
            "view_orientation": {
                "source": "revit_view",
                "right": {"x": 1, "y": 0, "z": 0},
                "up": {"x": 0, "y": 1, "z": 0},
            },
            "main_context_segments": [
                {
                    "segment_id": "main-horizontal",
                    "start": {"x": 0, "y": 10},
                    "end": {"x": 10, "y": 10},
                },
                {
                    "segment_id": "main-vertical",
                    "start": {"x": 0, "y": 10},
                    "end": {"x": 0, "y": 0},
                },
            ],
            "segments": [
                {
                    "segment_id": "north-a",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 2, "y": 10},
                    "end": {"x": 2, "y": 14},
                    "cad_geometry_start": {"x": 2, "y": 10},
                    "cad_geometry_end": {"x": 2, "y": 14},
                    "diameter_mm": 25,
                    "color": "rgb:0,127,127",
                },
                {
                    "segment_id": "north-b",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 7, "y": 10},
                    "end": {"x": 7, "y": 14},
                    "cad_geometry_start": {"x": 7, "y": 10},
                    "cad_geometry_end": {"x": 7, "y": 14},
                    "diameter_mm": 25,
                    "color": "rgb:0,127,127",
                },
                {
                    "segment_id": "east-a",
                    "row_index": 2,
                    "sequence": 0,
                    "start": {"x": 0, "y": 7},
                    "end": {"x": 4, "y": 7},
                    "cad_geometry_start": {"x": 0, "y": 7},
                    "cad_geometry_end": {"x": 4, "y": 7},
                    "diameter_mm": 32,
                    "color": "rgb:255,127,0",
                },
                {
                    "segment_id": "east-b",
                    "row_index": 3,
                    "sequence": 0,
                    "start": {"x": 0, "y": 3},
                    "end": {"x": 4, "y": 3},
                    "cad_geometry_start": {"x": 0, "y": 3},
                    "cad_geometry_end": {"x": 4, "y": 3},
                    "diameter_mm": 32,
                    "color": "rgb:255,127,0",
                },
            ],
        }

        layout = build_fire_branch_network_layout(analysis, main_diameter_mm=100)

        self.assertEqual("topology_canvas", layout["coordinate_space"])
        by_id = {item["segment_id"]: item for item in layout["segments"]}
        self.assertAlmostEqual(by_id["north-a"]["x1"], by_id["north-a"]["x2"])
        self.assertAlmostEqual(by_id["north-b"]["x1"], by_id["north-b"]["x2"])
        self.assertNotAlmostEqual(by_id["north-a"]["x1"], by_id["north-b"]["x1"])
        self.assertAlmostEqual(by_id["east-a"]["y1"], by_id["east-a"]["y2"])
        self.assertAlmostEqual(by_id["east-b"]["y1"], by_id["east-b"]["y2"])
        self.assertNotAlmostEqual(by_id["east-a"]["y1"], by_id["east-b"]["y1"])
        self.assertEqual([], layout["row_lanes"])
        svg = render_fire_branch_network_svg(analysis, main_diameter_mm=100)
        self.assertIn('data-coordinate-space="topology_canvas"', svg)

    def test_layout_projects_connector_points_before_joining_fragmented_main(self) -> None:
        """Revit endpoints and fitting points arrive in model coordinates.

        The selected main pipes are projected into the active view before the
        graph is normalized.  Connector points must use that same projection;
        otherwise an L-shaped main is classified as a disconnected/linear
        route and one leg is sent far outside the SVG canvas.
        """
        analysis = {
            "segments": [
                {
                    "segment_id": "branch",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 80.0, "y": -73.366},
                    "end": {"x": 60.0, "y": -73.366},
                    "diameter_mm": 25,
                }
            ],
            "view_orientation": {
                "source": "revit_view",
                "view_id": 13301161,
                "right": {"x": 1, "y": 0, "z": 0},
                "up": {"x": 0, "y": 1, "z": 0},
            },
            "main_context_segments": [
                {
                    "segment_id": "main-horizontal",
                    "source_element_id": 13740100,
                    "start": {"x": 92.046, "y": -71.735, "z": 0.328},
                    "end": {"x": 73.617, "y": -71.735, "z": 0.328},
                    "connections": [
                        {
                            "key": "13740125",
                            "endpoint": "end",
                            "point": {"x": 73.366, "y": -71.986, "z": 0.328},
                        }
                    ],
                },
                {
                    "segment_id": "main-vertical",
                    "source_element_id": 13740127,
                    "start": {"x": 73.115, "y": -72.237, "z": 0.328},
                    "end": {"x": 73.115, "y": -130.327, "z": 0.328},
                    "connections": [
                        {
                            "key": "13740125",
                            "endpoint": "start",
                            "point": {"x": 73.366, "y": -71.986, "z": 0.328},
                        }
                    ],
                },
            ],
        }

        layout = build_fire_branch_network_layout(analysis, main_diameter_mm=100)

        self.assertEqual("L", layout["main_shape"])
        self.assertEqual(1, layout["main_graph"]["component_count"])
        self.assertEqual(2, layout["main_graph"]["edge_count"])
        main_by_id = {
            item["segment_id"]: item for item in layout["main_segments"]
        }
        horizontal = main_by_id["main-horizontal"]
        vertical = main_by_id["main-vertical"]
        self.assertAlmostEqual(horizontal["y1"], horizontal["y2"])
        self.assertAlmostEqual(vertical["x1"], vertical["x2"])
        horizontal_joint = (
            horizontal["x1"],
            horizontal["y1"],
        ) if abs(horizontal["x1"] - vertical["x1"]) < abs(horizontal["x2"] - vertical["x1"]) else (
            horizontal["x2"],
            horizontal["y2"],
        )
        vertical_joint = (
            vertical["x1"],
            vertical["y1"],
        ) if abs(vertical["y1"] - horizontal_joint[1]) < abs(vertical["y2"] - horizontal_joint[1]) else (
            vertical["x2"],
            vertical["y2"],
        )
        self.assertAlmostEqual(horizontal_joint[0], vertical_joint[0])
        self.assertAlmostEqual(horizontal_joint[1], vertical_joint[1])
        self.assertLess(
            max(
                abs(value)
                for segment in layout["main_segments"]
                for value in (segment["x1"], segment["y1"], segment["x2"], segment["y2"])
            ),
            2000.0,
        )
        render_segments = main_context_render_segments(layout)
        self.assertEqual(2, len(render_segments))
        self.assertEqual(
            [(item["x1"], item["y1"], item["x2"], item["y2"]) for item in render_segments],
            [
                (
                    item["x1"],
                    item["y1"],
                    item["x2"],
                    item["y2"],
                )
                for item in layout["main_segments"]
            ],
        )

    def test_layout_preserves_u_shaped_main_geometry_and_graph_nodes(self) -> None:
        analysis = {
            "segments": [
                {
                    "segment_id": "branch-u",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 5, "y": 0},
                    "diameter_mm": 25,
                }
            ],
            "main_context_segments": [
                {"segment_id": "main-a", "start": {"x": 0, "y": 0}, "end": {"x": 0, "y": 10}},
                {"segment_id": "main-b", "start": {"x": 0, "y": 10}, "end": {"x": 12, "y": 10}},
                {"segment_id": "main-c", "start": {"x": 12, "y": 10}, "end": {"x": 12, "y": 0}},
            ],
        }

        layout = build_fire_branch_network_layout(analysis, main_diameter_mm=100)

        self.assertEqual("U", layout["main_shape"])
        self.assertEqual(3, len(layout["main_segments"]))
        self.assertEqual(4, layout["main_graph"]["node_count"])
        self.assertEqual(3, layout["main_graph"]["edge_count"])
        self.assertEqual(1, layout["main_graph"]["component_count"])
        anchor = layout["main_graph"]["anchors"][0]
        self.assertLessEqual(anchor["distance"], 1e-6)

    def test_layout_keeps_compound_double_l_geometry_without_synthetic_main_line(self) -> None:
        analysis = {
            "segments": [
                {
                    "segment_id": "branch-double-l",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 4, "y": 4},
                    "end": {"x": 8, "y": 4},
                    "diameter_mm": 32,
                }
            ],
            "main_context_segments": [
                {"segment_id": "main-1", "start": {"x": 0, "y": 0}, "end": {"x": 0, "y": 8}},
                {"segment_id": "main-2", "start": {"x": 0, "y": 8}, "end": {"x": 8, "y": 8}},
                {"segment_id": "main-3", "start": {"x": 8, "y": 8}, "end": {"x": 8, "y": 4}},
                {"segment_id": "main-4", "start": {"x": 8, "y": 4}, "end": {"x": 14, "y": 4}},
            ],
        }

        layout = build_fire_branch_network_layout(analysis, main_diameter_mm=100)

        self.assertEqual("compound_bend", layout["main_shape"])
        self.assertEqual(4, len(layout["main_segments"]))
        self.assertEqual(5, layout["main_graph"]["node_count"])
        self.assertEqual(4, layout["main_graph"]["edge_count"])
        self.assertNotEqual(
            (layout["main"]["x1"], layout["main"]["y1"]),
            (layout["main"]["x2"], layout["main"]["y2"]),
        )

    def test_layout_snaps_fragmented_main_endpoints_within_tolerance(self) -> None:
        analysis = {
            "segments": [
                {
                    "segment_id": "branch-fragment",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 5, "y": 0},
                    "end": {"x": 7, "y": 0},
                    "diameter_mm": 25,
                }
            ],
            "main_context_segments": [
                {"segment_id": "main-frag-a", "start": {"x": 0, "y": 0}, "end": {"x": 5, "y": 0}},
                {"segment_id": "main-frag-b", "start": {"x": 5.001, "y": 0}, "end": {"x": 10, "y": 0}},
            ],
        }

        layout = build_fire_branch_network_layout(analysis, main_diameter_mm=100)

        self.assertEqual("linear", layout["main_shape"])
        self.assertEqual(2, layout["main_graph"]["edge_count"])
        self.assertEqual(3, layout["main_graph"]["node_count"])
        self.assertEqual(1, layout["main_graph"]["component_count"])
        self.assertLessEqual(layout["main_graph"]["anchors"][0]["distance"], 1e-6)

    def test_layout_joins_revit_fitting_gap_by_shared_connection_key(self) -> None:
        analysis = {
            "segments": [
                {
                    "segment_id": "branch-fitting-gap",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 1, "y": 0},
                    "diameter_mm": 25,
                }
            ],
            "main_context_segments": [
                {
                    "segment_id": "main-horizontal",
                    "source_element_id": 101,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "connections": [
                        {"key": "fitting-1", "endpoint": "end", "point": {"x": 10.0, "y": 0.0}}
                    ],
                },
                {
                    "segment_id": "main-vertical",
                    "source_element_id": 102,
                    "start": {"x": 10.8, "y": 0.8},
                    "end": {"x": 10.8, "y": 8},
                    "connections": [
                        {"key": "fitting-1", "endpoint": "start", "point": {"x": 10.0, "y": 0.0}}
                    ],
                },
            ],
        }

        layout = build_fire_branch_network_layout(analysis, main_diameter_mm=100)

        self.assertEqual("L", layout["main_shape"])
        self.assertEqual(1, layout["main_graph"]["component_count"])
        self.assertEqual(2, layout["main_graph"]["edge_count"])
        node_ids = {
            (edge["node_start"], edge["node_end"])
            for edge in layout["main_graph"]["segments"]
        }
        self.assertTrue(node_ids)
        self.assertEqual(
            layout["main_graph"]["segments"][0]["end"],
            layout["main_graph"]["segments"][1]["start"],
        )

    def test_opposite_branches_at_same_cad_point_share_one_cross_node(self) -> None:
        analysis = {
            "segments": [
                {
                    "segment_id": "north",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0.2},
                    "end": {"x": 0, "y": 8},
                    "cad_geometry_start": {"x": 0, "y": 0},
                    "cad_geometry_end": {"x": 0, "y": 8},
                    "diameter_mm": 25,
                },
                {
                    "segment_id": "south",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 0, "y": -0.2},
                    "end": {"x": 0, "y": -8},
                    "cad_geometry_start": {"x": 0, "y": 0},
                    "cad_geometry_end": {"x": 0, "y": -8},
                    "diameter_mm": 25,
                },
            ],
            "junctions": [
                {
                    "row_index": 0,
                    "branch_segment_id": "north",
                    "main_segment_id": "main-1",
                    "point": {"x": 0, "y": 0},
                    "kind": "reducing_tee",
                    "main_diameter_mm": 100,
                    "branch_diameter_mm": 25,
                },
                {
                    "row_index": 1,
                    "branch_segment_id": "south",
                    "main_segment_id": "main-1",
                    "point": {"x": 0, "y": 0},
                    "kind": "reducing_tee",
                    "main_diameter_mm": 100,
                    "branch_diameter_mm": 25,
                },
            ],
        }

        layout = build_fire_branch_network_layout(analysis, main_diameter_mm=100)
        by_id = {item["segment_id"]: item for item in layout["segments"]}

        self.assertEqual(
            (by_id["north"]["x1"], by_id["north"]["y1"]),
            (by_id["south"]["x1"], by_id["south"]["y1"]),
        )
        self.assertEqual(1, len(layout["junctions"]))
        self.assertEqual("reducing_cross", layout["junctions"][0]["kind"])
        self.assertEqual("DN100 × DN100 × DN25 × DN25", layout["junctions"][0]["label"])
        svg = render_fire_branch_network_svg(analysis, main_diameter_mm=100)
        self.assertIn("異徑四通", svg)
        self.assertIn("DN100 × DN100 × DN25 × DN25", svg)

    def test_unequal_opposite_branches_use_larger_cross_outlet_and_reduce_outward(self) -> None:
        analysis = {
            "segments": [
                {
                    "segment_id": "north-32",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 0, "y": 8},
                    "cad_geometry_start": {"x": 0, "y": 0},
                    "cad_geometry_end": {"x": 0, "y": 8},
                    "diameter_mm": 32,
                    "color": "magenta",
                },
                {
                    "segment_id": "south-40",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 0, "y": -8},
                    "cad_geometry_start": {"x": 0, "y": 0},
                    "cad_geometry_end": {"x": 0, "y": -8},
                    "diameter_mm": 40,
                    "color": "red",
                },
            ],
            "junctions": [
                {
                    "row_index": 0,
                    "branch_segment_id": "north-32",
                    "main_segment_id": "main-1",
                    "point": {"x": 0, "y": 0},
                    "kind": "reducing_tee",
                    "main_diameter_mm": 100,
                    "branch_diameter_mm": 32,
                },
                {
                    "row_index": 1,
                    "branch_segment_id": "south-40",
                    "main_segment_id": "main-1",
                    "point": {"x": 0, "y": 0},
                    "kind": "reducing_tee",
                    "main_diameter_mm": 100,
                    "branch_diameter_mm": 40,
                },
            ],
        }

        layout = build_fire_branch_network_layout(analysis, main_diameter_mm=100)

        self.assertEqual(1, len(layout["junctions"]))
        self.assertEqual(
            "DN100 × DN100 × DN40 × DN40",
            layout["junctions"][0]["label"],
        )
        cross_reducers = [
            item
            for item in layout["reducers"]
            if item.get("placement") == "after_cross"
        ]
        self.assertEqual(1, len(cross_reducers))
        self.assertEqual("north-32", cross_reducers[0]["source_segment_id"])
        self.assertEqual("DN40 → DN32", cross_reducers[0]["label"])
        self.assertEqual(40, cross_reducers[0]["lead_diameter_mm"])
        svg = render_fire_branch_network_svg(analysis, main_diameter_mm=100)
        self.assertIn("DN100 × DN100 × DN40 × DN40", svg)
        self.assertIn("DN40 → DN32", svg)

    def test_svg_is_valid_simple_engineering_drawing(self) -> None:
        svg = render_fire_branch_network_svg(self.analysis, title="消防支管路網")
        root = ET.fromstring(svg)

        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("row-0-0", svg)
        self.assertIn("#ff7f00", svg)
        self.assertIn("DN40", svg)
        self.assertIn("DN40 → DN32", svg)
        self.assertIn('class="reducer-lead"', svg)
        self.assertIn("異徑三通", svg)
        self.assertIn("DN100 × DN100 × DN40", svg)
        self.assertIn("待確認", svg)
        self.assertIn("#ffffff", svg)
        self.assertIn('data-diameter-mm="40.0"', svg)
        self.assertIn('data-source-color="#ff7f00"', svg)
        self.assertIn("管線色彩依管徑", svg)
        self.assertIn("2.44 m", svg)

    def test_diameter_display_colors_are_stable_and_unknown_is_neutral(self) -> None:
        self.assertEqual("#00a8b5", diameter_to_display_color(25, "#e53935"))
        self.assertEqual("#ff7f00", diameter_to_display_color(32, "#e53935"))
        self.assertEqual("#8a8a8a", diameter_to_display_color(None, "#e53935"))

    def test_svg_draws_only_revit_sprinkler_terminals_not_diameter_boundaries(self) -> None:
        analysis = {
            "segments": [
                {
                    "segment_id": "row-0-0",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 0, "y": 5},
                    "diameter_mm": 40,
                    "is_sprinkler_terminal": False,
                },
                {
                    "segment_id": "row-0-1",
                    "row_index": 0,
                    "sequence": 1,
                    "start": {"x": 0, "y": 5},
                    "end": {"x": 0, "y": 10},
                    "diameter_mm": 32,
                    "is_sprinkler_terminal": True,
                    "sprinkler_id": 101,
                },
            ]
        }

        svg = render_fire_branch_network_svg(analysis)

        self.assertEqual(1, svg.count('class="sprinkler-terminal"'))
        self.assertIn('data-sprinkler-id="101"', svg)

    def test_equal_route_lengths_have_equal_display_extent_after_diameter_splits(self) -> None:
        segments = [
            {
                "segment_id": "row-0-0",
                "row_index": 0,
                "sequence": 0,
                "start": {"x": 0, "y": 0},
                "end": {"x": 10, "y": 0},
                "planned_length_mm": 3048,
                "diameter_mm": 25,
            }
        ]
        for sequence in range(4):
            segments.append(
                {
                    "segment_id": f"row-1-{sequence}",
                    "row_index": 1,
                    "sequence": sequence,
                    "start": {"x": sequence * 2.5, "y": 10},
                    "end": {"x": (sequence + 1) * 2.5, "y": 10},
                    "planned_length_mm": 762,
                    "diameter_mm": 25,
                }
            )

        layout = build_fire_branch_network_layout({"segments": segments})
        rows = {}
        for segment in layout["segments"]:
            rows.setdefault(segment["row_index"], []).append(segment)
        extents = []
        for row in rows.values():
            ordered = sorted(row, key=lambda item: item["sequence"])
            extents.append(abs(ordered[-1]["x2"] - ordered[0]["x1"]))

        self.assertAlmostEqual(extents[0], extents[1], places=6)

    def test_canvas_preview_renders_junction_candidates(self) -> None:
        source = (
            __import__("pathlib").Path(__file__).resolve().parent
            / "sc_revit"
            / "fire_branch"
            / "network_preview.py"
        ).read_text(encoding="utf-8")

        self.assertIn('for junction in self._layout["junctions"]', source)
        self.assertIn('"異徑三通"', source)
        self.assertIn('"junction-label"', source)

    def test_layout_follows_rotated_revit_view_axes(self) -> None:
        analysis = dict(self.analysis)
        analysis["view_orientation"] = {
            "source": "revit_view",
            "view_id": 123,
            "right": {"x": 0, "y": 1, "z": 0},
            "up": {"x": -1, "y": 0, "z": 0},
        }

        layout = build_fire_branch_network_layout(analysis)

        self.assertEqual("horizontal", layout["main"]["orientation"])
        first = layout["segments"][0]
        self.assertAlmostEqual(first["x1"], first["x2"])
        self.assertGreater(first["y2"], first["y1"])
        reducer = layout["reducers"][0]
        downstream = layout["segments"][1]
        self.assertEqual(
            (first["terminal_x"], first["terminal_y"]),
            reducer["lead_start"],
        )
        self.assertGreater(reducer["y"], downstream["y1"])
        self.assertEqual("revit_view", layout["orientation"]["source"])

    def test_svg_records_view_orientation_and_cardinal_compass(self) -> None:
        analysis = dict(self.analysis)
        analysis["view_orientation"] = {
            "source": "revit_view",
            "view_id": 123,
            "right": {"x": 1, "y": 0, "z": 0},
            "up": {"x": 0, "y": 1, "z": 0},
        }

        svg = render_fire_branch_network_svg(analysis)

        self.assertIn('data-orientation-source="revit_view"', svg)
        self.assertIn("方向依目前 Revit 視圖", svg)
        self.assertIn(">北<", svg)
        self.assertIn(">東<", svg)
        self.assertIn(">南<", svg)
        self.assertIn(">西<", svg)

    def test_canvas_preview_uses_semantic_zoom_instead_of_overlapping_details(self) -> None:
        source = (
            __import__("pathlib").Path(__file__).resolve().parent
            / "sc_revit"
            / "fire_branch"
            / "network_preview.py"
        ).read_text(encoding="utf-8")

        self.assertIn("def _apply_semantic_zoom", source)
        self.assertIn("semantic_zoom_visibility(self._scale)", source)
        self.assertIn('"diameter-text"', source)
        self.assertIn('"segment-detail"', source)
        self.assertIn('"junction_label": not overview', source)

    def test_zoom_in_can_escape_a_fit_scale_below_the_minimum(self) -> None:
        self.assertGreater(next_zoom_scale(0.20, 1), 0.20)
        self.assertEqual(0.35, next_zoom_scale(0.20, 1))

    def test_overview_hides_all_detail_labels_including_junction_text(self) -> None:
        visibility = semantic_zoom_visibility(0.30)

        self.assertFalse(visibility["diameter_text"])
        self.assertFalse(visibility["segment_detail"])
        self.assertFalse(visibility["reducer_label"])
        self.assertFalse(visibility["junction_label"])
        self.assertFalse(visibility["main_label"])

    def test_readable_scale_restores_junction_and_diameter_labels(self) -> None:
        visibility = semantic_zoom_visibility(0.80)

        self.assertTrue(visibility["diameter_text"])
        self.assertTrue(visibility["reducer_label"])
        self.assertTrue(visibility["junction_label"])
        self.assertFalse(visibility["segment_detail"])

    def test_preview_opens_at_readable_scale_and_has_explicit_zoom_controls(self) -> None:
        source = (
            __import__("pathlib").Path(__file__).resolve().parent
            / "sc_revit"
            / "fire_branch"
            / "network_preview.py"
        ).read_text(encoding="utf-8")

        self.assertIn("self.after(80, self._show_readable_view)", source)
        self.assertIn('text="－"', source)
        self.assertIn('text="＋"', source)
        self.assertIn("self._zoom_percent_var", source)
        self.assertIn('self.bind("<MouseWheel>"', source)
        self.assertIn("def _refresh_scaled_styles", source)


if __name__ == "__main__":
    unittest.main()
