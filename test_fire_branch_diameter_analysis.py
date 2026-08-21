import unittest

from sc_revit.fire_branch.diameter_analysis import (
    analyze_diameter_evidence,
    parse_diameter_text,
    split_routes_by_cad_geometry,
)


class FireBranchDiameterAnalysisTests(unittest.TestCase):
    def test_single_terminal_route_is_split_by_cad_geometry_changes(self):
        planned = [
            {
                "segment_id": "row-0-0",
                "row_index": 0,
                "sequence": 0,
                "sprinkler_id": 101,
                "is_sprinkler_terminal": True,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 0, "y": 30, "z": 0},
            }
        ]
        cad_geometry = [
            {
                "start": {"x": 0.2, "y": 0},
                "end": {"x": 0.2, "y": 10},
                "layer": "SPRINKLER-40",
                "color": "red",
            },
            {
                "start": {"x": 0.2, "y": 10},
                "end": {"x": 0.2, "y": 20},
                "layer": "SPRINKLER-32",
                "color": "orange",
            },
            {
                "start": {"x": 0.2, "y": 20},
                "end": {"x": 0.2, "y": 30},
                "layer": "SPRINKLER-25",
                "color": "teal",
            },
        ]

        segments = split_routes_by_cad_geometry(
            planned,
            cad_geometry,
            maximum_offset=0.5,
            maximum_angle_degrees=5,
        )

        self.assertEqual(3, len(segments))
        self.assertEqual(
            ["SPRINKLER-40", "SPRINKLER-32", "SPRINKLER-25"],
            [item["layer"] for item in segments],
        )
        self.assertEqual([0, 1, 2], [item["sequence"] for item in segments])
        self.assertEqual(
            [(0.0, 10.0), (10.0, 20.0), (20.0, 30.0)],
            [
                (item["start"]["y"], item["end"]["y"])
                for item in segments
            ],
        )
        self.assertEqual(
            [(0.2, 0.2), (0.2, 0.2), (0.2, 0.2)],
            [
                (
                    item["cad_geometry_start"]["x"],
                    item["cad_geometry_end"]["x"],
                )
                for item in segments
            ],
        )
        self.assertEqual(
            [False, False, True],
            [bool(item.get("is_sprinkler_terminal")) for item in segments],
        )
        self.assertEqual(
            [None, None, 101],
            [item.get("sprinkler_id") for item in segments],
        )

    def test_multiple_planned_spans_in_one_row_keep_unique_monotonic_segments(self):
        planned = [
            {
                "segment_id": "source-a",
                "row_index": 0,
                "sequence": 0,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 0, "y": 10, "z": 0},
            },
            {
                "segment_id": "source-b",
                "row_index": 0,
                "sequence": 1,
                "start": {"x": 0, "y": 10, "z": 0},
                "end": {"x": 0, "y": 20, "z": 0},
            },
        ]
        cad_geometry = [
            {
                "start": {"x": 0, "y": 0},
                "end": {"x": 0, "y": 5},
                "layer": "SPRINKLER-40",
                "color": "red",
            },
            {
                "start": {"x": 0, "y": 5},
                "end": {"x": 0, "y": 10},
                "layer": "SPRINKLER-32",
                "color": "orange",
            },
            {
                "start": {"x": 0, "y": 10},
                "end": {"x": 0, "y": 20},
                "layer": "SPRINKLER-25",
                "color": "teal",
            },
        ]

        segments = split_routes_by_cad_geometry(
            planned,
            cad_geometry,
            maximum_offset=0.5,
            maximum_angle_degrees=5,
        )

        self.assertEqual(3, len(segments))
        self.assertEqual([0, 1, 2], [item["sequence"] for item in segments])
        self.assertEqual(
            ["row-0-0", "row-0-1", "row-0-2"],
            [item["segment_id"] for item in segments],
        )
        self.assertEqual(3, len({item["segment_id"] for item in segments}))

    def test_short_parallel_fragment_does_not_replace_continuous_cad_route(self):
        planned = [
            {
                "segment_id": "row-0-0",
                "row_index": 0,
                "sequence": 0,
                "start": {"x": 0, "y": 0},
                "end": {"x": 0, "y": 10},
            }
        ]
        cad_geometry = [
            {
                "segment_id": "continuous-route",
                "start": {"x": 0.1, "y": 0},
                "end": {"x": 0.1, "y": 10},
                "layer": "SPRINKLER-25",
                "color": "teal",
            },
            {
                "segment_id": "short-yellow-fragment",
                "start": {"x": 0, "y": 3},
                "end": {"x": 0, "y": 4},
                "layer": "ANNOTATION",
                "color": "yellow",
            },
        ]

        segments = split_routes_by_cad_geometry(
            planned,
            cad_geometry,
            maximum_offset=0.5,
            maximum_angle_degrees=5,
        )

        self.assertEqual(1, len(segments))
        self.assertEqual("SPRINKLER-25", segments[0]["layer"])
        self.assertEqual("teal", segments[0]["color"])

    def test_fragmented_route_outranks_repeated_short_symbol_geometry(self):
        planned = [
            {
                "segment_id": "row-0-0",
                "row_index": 0,
                "sequence": 0,
                "start": {"x": 0, "y": 0},
                "end": {"x": 0, "y": 30},
            }
        ]
        cad_geometry = [
            {
                "start": {"x": 0.1, "y": 0},
                "end": {"x": 0.1, "y": 10},
                "layer": "SPRINKLER-40",
                "color": "red",
                "geometry_kind": "line",
            },
            {
                "start": {"x": 0.1, "y": 10},
                "end": {"x": 0.1, "y": 20},
                "layer": "SPRINKLER-32",
                "color": "orange",
                "geometry_kind": "line",
            },
            {
                "start": {"x": 0.1, "y": 20},
                "end": {"x": 0.1, "y": 30},
                "layer": "SPRINKLER-25",
                "color": "teal",
                "geometry_kind": "line",
            },
            {
                "start": {"x": 0, "y": 8.5},
                "end": {"x": 0, "y": 9.5},
                "layer": "SPRINKLER-SYMBOL",
                "color": "yellow",
                "geometry_kind": "polyline",
            },
            {
                "start": {"x": 0, "y": 10.5},
                "end": {"x": 0, "y": 11.5},
                "layer": "SPRINKLER-SYMBOL",
                "color": "yellow",
                "geometry_kind": "polyline",
            },
            {
                "start": {"x": 0, "y": 18.5},
                "end": {"x": 0, "y": 19.5},
                "layer": "SPRINKLER-SYMBOL",
                "color": "yellow",
                "geometry_kind": "polyline",
            },
            {
                "start": {"x": 0, "y": 20.5},
                "end": {"x": 0, "y": 21.5},
                "layer": "SPRINKLER-SYMBOL",
                "color": "yellow",
                "geometry_kind": "polyline",
            },
        ]

        segments = split_routes_by_cad_geometry(
            planned,
            cad_geometry,
            maximum_offset=0.5,
            maximum_angle_degrees=5,
        )

        self.assertEqual(3, len(segments))
        self.assertEqual(
            ["SPRINKLER-40", "SPRINKLER-32", "SPRINKLER-25"],
            [item["layer"] for item in segments],
        )
        self.assertNotIn("yellow", [item["color"] for item in segments])

    def test_closed_cad_geometry_cannot_split_a_pipe_route(self):
        planned = [
            {
                "segment_id": "row-0-0",
                "row_index": 0,
                "sequence": 0,
                "start": {"x": 0, "y": 0},
                "end": {"x": 0, "y": 10},
            }
        ]
        cad_geometry = [
            {
                "start": {"x": 0.1, "y": 0},
                "end": {"x": 0.1, "y": 10},
                "layer": "SPRINKLER-25",
                "color": "teal",
                "geometry_kind": "line",
            },
            {
                "start": {"x": 0, "y": 4},
                "end": {"x": 0, "y": 6},
                "layer": "SPRINKLER-SYMBOL",
                "color": "yellow",
                "geometry_kind": "polyline",
                "closed_geometry": True,
            },
            {
                "start": {"x": 0, "y": 2},
                "end": {"x": 0, "y": 3},
                "layer": "SPRINKLER-SYMBOL",
                "color": "yellow",
                "geometry_kind": "arc",
                "closed_geometry": False,
            },
        ]

        segments = split_routes_by_cad_geometry(
            planned,
            cad_geometry,
            maximum_offset=0.5,
            maximum_angle_degrees=5,
        )

        self.assertEqual(1, len(segments))
        self.assertEqual("SPRINKLER-25", segments[0]["layer"])

    def test_outward_diameter_increase_is_not_accepted_as_valid_reducer(self):
        result = analyze_diameter_evidence(
            texts=[
                {"text": '1"', "x": 2.5, "y": 0.2, "color": 1},
                {"text": '1 1/4"', "x": 7.5, "y": 0.2, "color": 2},
            ],
            segments=[
                {
                    "segment_id": "row-0-0",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 5, "y": 0},
                    "color": 1,
                },
                {
                    "segment_id": "row-0-1",
                    "row_index": 0,
                    "sequence": 1,
                    "start": {"x": 5, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "color": 2,
                },
            ],
            maximum_label_distance=2,
        )

        self.assertEqual(25.0, result["segments"][0]["diameter_mm"])
        self.assertEqual(32.0, result["segments"][1]["diameter_mm"])
        self.assertEqual(
            "diameter_increase_conflict",
            result["segments"][1]["evidence"],
        )
        self.assertEqual([], result["reducers"])
        self.assertIn("outward_diameter_increase", result["warning_codes"])

    def test_parses_explicit_inch_labels_and_default_note(self):
        self.assertEqual(40.0, parse_diameter_text('1 1/2"'))
        self.assertEqual(32.0, parse_diameter_text('1-1/4 吋'))
        self.assertEqual(25.0, parse_diameter_text('未標示者皆以 1" 管計'))
        self.assertEqual(25.0, parse_diameter_text("備註2：未標註之管徑均為1”"))

    def test_stacked_fraction_fragments_are_not_treated_as_whole_inches(self):
        self.assertIsNone(parse_diameter_text('1/2"'))
        self.assertIsNone(parse_diameter_text('1/4"'))

        result = analyze_diameter_evidence(
            texts=[
                {"text": '1 1/2"', "x": 5, "y": 1},
                {"text": '1/2"', "x": 5, "y": 0.2},
            ],
            segments=[
                {
                    "segment_id": "row-0-0",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                }
            ],
            maximum_label_distance=5,
        )

        self.assertEqual(40.0, result["segments"][0]["diameter_mm"])
        self.assertNotEqual("conflicting_label", result["segments"][0]["evidence"])
        self.assertEqual(1, result["label_count"])

    def test_text_color_controls_matching_lines_and_unmarked_lines_use_default(self):
        result = analyze_diameter_evidence(
            texts=[
                {"text": '未標示者皆以 1" 管計', "x": 100, "y": 100, "color": 7},
                {"text": '1 1/2"', "x": 5, "y": 1, "color": 1},
            ],
            segments=[
                {
                    "segment_id": "row-1-0",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "color": 1,
                    "layer": "SP-PIPE",
                },
                {
                    "segment_id": "row-1-1",
                    "row_index": 1,
                    "sequence": 1,
                    "start": {"x": 10, "y": 0},
                    "end": {"x": 20, "y": 0},
                    "color": 7,
                    "layer": "SP-PIPE",
                },
            ],
            maximum_label_distance=5,
        )

        self.assertEqual(25.0, result["default_diameter_mm"])
        self.assertEqual(40.0, result["segments"][0]["diameter_mm"])
        self.assertEqual("explicit_color", result["segments"][0]["evidence"])
        self.assertEqual(25.0, result["segments"][1]["diameter_mm"])
        self.assertEqual("drawing_default", result["segments"][1]["evidence"])
        self.assertEqual(1, len(result["reducers"]))
        self.assertEqual(40.0, result["reducers"][0]["from_diameter_mm"])
        self.assertEqual(25.0, result["reducers"][0]["to_diameter_mm"])
        self.assertEqual("row-1-0", result["reducers"][0]["before_segment_id"])
        self.assertEqual("row-1-1", result["reducers"][0]["after_segment_id"])

    def test_main_to_branch_size_change_is_a_reducing_tee_not_an_inline_reducer(self):
        result = analyze_diameter_evidence(
            texts=[
                {"text": '4"', "x": -4, "y": -0.5, "direction": {"x": 1, "y": 0}},
                {"text": '1 1/2"', "x": 0.5, "y": 5, "direction": {"x": 0, "y": 1}},
            ],
            segments=[
                {
                    "segment_id": "row-0-0",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 0, "y": 10},
                }
            ],
            main_context_segments=[
                {
                    "segment_id": "main-1001",
                    "source_element_id": 1001,
                    "start": {"x": -5, "y": 0},
                    "end": {"x": 5, "y": 0},
                }
            ],
            maximum_label_distance=2,
        )

        self.assertEqual([], result["reducers"])
        self.assertEqual(1, len(result["junctions"]))
        junction = result["junctions"][0]
        self.assertEqual("reducing_tee", junction["kind"])
        self.assertEqual(100.0, junction["main_diameter_mm"])
        self.assertEqual(40.0, junction["branch_diameter_mm"])
        self.assertEqual("main-1001", junction["main_segment_id"])
        self.assertFalse(junction["review_required"])

    def test_selected_main_diameter_resolves_without_repeated_cad_main_label(self):
        result = analyze_diameter_evidence(
            texts=[],
            segments=[
                {
                    "segment_id": "row-0-0",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 0, "y": 8},
                    "diameter_mm": 25,
                    "layer": "SPRINKLER-25",
                }
            ],
            main_context_segments=[
                {
                    "segment_id": "main-1001",
                    "source_element_id": 1001,
                    "start": {"x": -8, "y": 0},
                    "end": {"x": 8, "y": 0},
                    "diameter_mm": 100,
                }
            ],
            maximum_label_distance=2,
        )

        junction = result["junctions"][0]
        self.assertEqual("reducing_tee", junction["kind"])
        self.assertEqual(100.0, junction["main_diameter_mm"])
        self.assertEqual("revit_main_context", junction["evidence"])
        self.assertFalse(junction["review_required"])

    def test_analysis_keeps_main_context_for_svg_and_execution_consumers(self):
        main_context = [
            {
                "segment_id": "main-1",
                "source_element_id": 1001,
                "start": {"x": 0, "y": 0},
                "end": {"x": 0, "y": 10},
            },
            {
                "segment_id": "main-2",
                "source_element_id": 1002,
                "start": {"x": 0, "y": 10},
                "end": {"x": 10, "y": 10},
            },
        ]

        result = analyze_diameter_evidence(
            texts=[],
            segments=[
                {
                    "segment_id": "row-0-0",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 0, "y": 5},
                }
            ],
            main_context_segments=main_context,
            maximum_label_distance=2,
        )

        self.assertEqual(main_context, result["main_context_segments"])

    def test_perpendicular_branch_label_does_not_conflict_with_aligned_main_labels(self):
        result = analyze_diameter_evidence(
            texts=[
                {"text": '4"', "x": -3, "y": 1, "direction": {"x": 1, "y": 0}},
                {"text": '4"', "x": 3, "y": 1, "direction": {"x": 1, "y": 0}},
                {"text": '1 1/4"', "x": 7, "y": 3, "direction": {"x": 0, "y": 1}},
            ],
            segments=[
                {
                    "segment_id": "row-0-0",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 0, "y": 8},
                    "layer": "SR-PIPE-32",
                }
            ],
            main_context_segments=[
                {
                    "segment_id": "main-1001",
                    "source_element_id": 1001,
                    "start": {"x": -8, "y": 0},
                    "end": {"x": 8, "y": 0},
                }
            ],
            maximum_label_distance=4,
        )

        self.assertEqual(1, len(result["junctions"]))
        self.assertEqual("reducing_tee", result["junctions"][0]["kind"])
        self.assertEqual(100.0, result["junctions"][0]["main_diameter_mm"])
        self.assertEqual(32.0, result["junctions"][0]["branch_diameter_mm"])

    def test_perpendicular_main_label_cannot_override_branch_layer_diameter(self):
        result = analyze_diameter_evidence(
            texts=[
                {"text": '4"', "x": 1, "y": 3, "direction": {"x": 1, "y": 0}},
            ],
            segments=[
                {
                    "segment_id": "row-0-0",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 0, "y": 8},
                    "color": "red",
                    "layer": "SR-SPRINKLER-40",
                }
            ],
            main_context_segments=[],
            maximum_label_distance=4,
        )

        self.assertEqual(40.0, result["segments"][0]["diameter_mm"])
        self.assertEqual("line_color_reference", result["segments"][0]["evidence"])

    def test_chinese_unmarked_pipe_note_sets_the_drawing_default(self):
        result = analyze_diameter_evidence(
            texts=[
                {
                    "text": '備註2：未標註之管徑均為1"。',
                    "x": 100,
                    "y": 100,
                    "color": 7,
                }
            ],
            segments=[
                {
                    "segment_id": "unmarked-segment",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "color": 3,
                    "layer": "FIRE-PIPE",
                }
            ],
            maximum_label_distance=5,
        )

        self.assertEqual(25.0, result["default_diameter_mm"])
        self.assertEqual(1, result["default_note_count"])
        self.assertIn("未標註", result["default_notes"][0]["text"])
        self.assertEqual(25.0, result["segments"][0]["diameter_mm"])
        self.assertEqual("drawing_default", result["segments"][0]["evidence"])

    def test_chinese_default_keywords_allow_spacing_and_simplified_text(self):
        from sc_revit.fire_branch.diameter_analysis import _is_default_note

        self.assertTrue(_is_default_note("未 標 註 之 管 徑"))
        self.assertTrue(_is_default_note("未标注之管径"))

    def test_conflicting_labels_on_one_color_require_review(self):
        result = analyze_diameter_evidence(
            texts=[
                {"text": '1"', "x": 2, "y": 1, "color": 3},
                {"text": '1 1/2"', "x": 8, "y": 1, "color": 3},
            ],
            segments=[
                {
                    "segment_id": "row-1-0",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "color": 3,
                    "layer": "SP-PIPE",
                }
            ],
            maximum_label_distance=5,
        )

        self.assertEqual("needs_attention", result["status"])
        self.assertIsNone(result["segments"][0]["diameter_mm"])
        self.assertIn("conflicting_color_labels", result["warning_codes"])

    def test_nearby_block_label_seeds_the_matching_cad_line_color(self):
        result = analyze_diameter_evidence(
            texts=[{"text": '2"', "x": 4, "y": 1, "color": None}],
            segments=[
                {
                    "segment_id": "row-2-0",
                    "row_index": 2,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "color": "rgb:255,0,191",
                    "layer": "SR-SPRINKLER-50",
                },
                {
                    "segment_id": "row-2-1",
                    "row_index": 2,
                    "sequence": 1,
                    "start": {"x": 10, "y": 0},
                    "end": {"x": 20, "y": 0},
                    "color": "rgb:255,0,191",
                    "layer": "SR-SPRINKLER-50",
                },
            ],
            maximum_label_distance=5,
        )

        self.assertEqual([50.0, 50.0], [item["diameter_mm"] for item in result["segments"]])
        self.assertTrue(all(item["evidence"] == "explicit_color" for item in result["segments"]))

    def test_consistent_line_color_reference_precedes_segment_layer_fallback(self):
        result = analyze_diameter_evidence(
            texts=[],
            segments=[
                {
                    "segment_id": "color-reference",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "color": "rgb:255,0,0",
                    "layer": "SR-PIPE-40",
                },
                {
                    "segment_id": "same-color-generic-layer",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 0, "y": 10},
                    "end": {"x": 10, "y": 10},
                    "color": "rgb:255,0,0",
                    "layer": "SR-PIPE-GENERIC",
                },
            ],
            maximum_label_distance=5,
        )

        self.assertEqual([40.0, 40.0], [item["diameter_mm"] for item in result["segments"]])
        self.assertTrue(
            all(item["evidence"] == "line_color_reference" for item in result["segments"])
        )

    def test_conflicting_line_color_reference_does_not_override_layer(self):
        result = analyze_diameter_evidence(
            texts=[],
            segments=[
                {
                    "segment_id": "red-40",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "color": "red",
                    "layer": "SR-PIPE-40",
                },
                {
                    "segment_id": "red-25",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 0, "y": 10},
                    "end": {"x": 10, "y": 10},
                    "color": "red",
                    "layer": "SR-PIPE-25",
                },
            ],
            maximum_label_distance=5,
        )

        self.assertEqual([40.0, 25.0], [item["diameter_mm"] for item in result["segments"]])
        self.assertTrue(all(item["evidence"] == "layer_reference" for item in result["segments"]))
        self.assertIn("conflicting_line_color_references", result["warning_codes"])

    def test_conflicting_direct_color_mapping_falls_back_to_segment_layer(self):
        result = analyze_diameter_evidence(
            texts=[
                {"text": '1 1/2"', "x": 5, "y": 0.5},
                {"text": '1 1/4"', "x": 5, "y": 10.5},
            ],
            segments=[
                {
                    "segment_id": "red-explicit-40",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "color": "red",
                    "layer": "SR-PIPE-40",
                },
                {
                    "segment_id": "red-explicit-32",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 0, "y": 10},
                    "end": {"x": 10, "y": 10},
                    "color": "red",
                    "layer": "SR-PIPE-32",
                },
                {
                    "segment_id": "red-layer-fallback-40",
                    "row_index": 2,
                    "sequence": 0,
                    "start": {"x": 0, "y": 20},
                    "end": {"x": 10, "y": 20},
                    "color": "red",
                    "layer": "SR-PIPE-40",
                },
            ],
            maximum_label_distance=2,
        )

        fallback = result["segments"][2]
        self.assertEqual(40.0, fallback["diameter_mm"])
        self.assertEqual("layer_reference", fallback["evidence"])
        self.assertIn("conflicting_color_labels", result["warning_codes"])

    def test_geometry_audit_blocks_readiness_until_every_segment_is_exact(self):
        result = analyze_diameter_evidence(
            texts=[],
            segments=[
                {
                    "segment_id": "exact",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "color": "red",
                    "layer": "SR-PIPE-40",
                    "cad_geometry_exact": True,
                    "cad_start_offset_mm": 0,
                    "cad_midpoint_offset_mm": 0,
                    "cad_end_offset_mm": 0,
                    "cad_angle_delta_degrees": 0,
                    "length_delta_mm": 0,
                },
                {
                    "segment_id": "review",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 0, "y": 10},
                    "end": {"x": 10, "y": 10},
                    "color": "orange",
                    "layer": "SR-PIPE-32",
                    "cad_geometry_exact": False,
                    "cad_start_offset_mm": 0,
                    "cad_midpoint_offset_mm": 0,
                    "cad_end_offset_mm": 20,
                    "cad_angle_delta_degrees": 0,
                    "length_delta_mm": 20,
                },
            ],
            maximum_label_distance=5,
        )

        self.assertTrue(result["cad_geometry_audit_available"])
        self.assertEqual(1, result["cad_geometry_exact_count"])
        self.assertEqual(1, result["cad_geometry_review_count"])
        self.assertEqual(20, result["cad_max_end_offset_mm"])
        self.assertIn(
            "cad_segment_geometry_review_required",
            result["warning_codes"],
        )

    def test_text_geometry_selects_one_best_pipe_instead_of_every_nearby_line(self):
        result = analyze_diameter_evidence(
            texts=[
                {
                    "text": '1 1/4"',
                    "x": 5,
                    "y": 1,
                    "color": 7,
                    "layer": "FIRE-ANNO",
                    "bounds": {
                        "min_x": 2,
                        "min_y": 0.5,
                        "max_x": 8,
                        "max_y": 1.5,
                    },
                    "direction": {"x": 1, "y": 0},
                }
            ],
            segments=[
                {
                    "segment_id": "horizontal-branch",
                    "row_index": 0,
                    "sequence": 0,
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "color": "orange",
                    "layer": "FIRE-PIPE",
                },
                {
                    "segment_id": "vertical-main",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 7, "y": -5},
                    "end": {"x": 7, "y": 5},
                    "color": "cyan",
                    "layer": "FIRE-MAIN",
                },
            ],
            maximum_label_distance=5,
        )

        self.assertEqual(32.0, result["segments"][0]["diameter_mm"])
        self.assertEqual("explicit_nearby", result["segments"][0]["evidence"])
        self.assertIsNone(result["segments"][1]["diameter_mm"])
        self.assertEqual("horizontal-branch", result["label_matches"][0]["segment_id"])
        self.assertLess(result["label_matches"][0]["distance"], 1.0)
        self.assertEqual(1, result["matched_label_count"])
        self.assertEqual(0, result["unmatched_label_count"])
        self.assertEqual(1, result["evidence_counts"]["explicit_nearby"])

    def test_selected_main_owns_main_label_without_polluting_branch_evidence(self):
        result = analyze_diameter_evidence(
            texts=[
                {
                    "text": '4"',
                    "x": 5,
                    "y": 0.4,
                    "color": "main-red",
                    "layer": "FIRE-ANNO",
                    "direction": {"x": 1, "y": 0},
                },
                {
                    "text": '1 1/2"',
                    "x": 5.4,
                    "y": -5,
                    "color": "branch-orange",
                    "layer": "FIRE-ANNO",
                    "direction": {"x": 0, "y": 1},
                },
            ],
            segments=[
                {
                    "segment_id": "row-1-0",
                    "row_index": 1,
                    "sequence": 0,
                    "start": {"x": 5, "y": 0},
                    "end": {"x": 5, "y": -10},
                    "color": "branch-orange",
                    "layer": "FIRE-BRANCH",
                }
            ],
            main_context_segments=[
                {
                    "segment_id": "main-1001",
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 10, "y": 0},
                    "topology_role": "main",
                    "source_element_id": 1001,
                }
            ],
            maximum_label_distance=5,
        )

        self.assertEqual(40.0, result["segments"][0]["diameter_mm"])
        self.assertNotEqual("conflicting_label", result["segments"][0]["evidence"])
        self.assertEqual(1, result["main_matched_label_count"])
        self.assertEqual(100.0, result["main_label_matches"][0]["diameter_mm"])
        self.assertEqual("main-1001", result["main_label_matches"][0]["segment_id"])
        self.assertEqual("branch", result["label_matches"][0]["topology_role"])
        self.assertEqual([], result["reducers"])


if __name__ == "__main__":
    unittest.main()
