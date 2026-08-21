import unittest
from unittest.mock import patch

from sc_revit.fire_branch.hot_analysis import (
    _cad_path_verified,
    _build_cad_route_graph,
    build_preview_summary,
)


class FireBranchHotAnalysisSummaryTests(unittest.TestCase):
    def test_cad_path_verification_requires_a_matched_coordinate_contract(self) -> None:
        self.assertFalse(
            _cad_path_verified(
                {
                    "status": "mismatch",
                    "coordinate_verified": True,
                    "coverage_ratio": 1.0,
                }
            )
        )
        self.assertTrue(
            _cad_path_verified(
                {
                    "status": "matched",
                    "coordinate_verified": True,
                    "coverage_ratio": 0.8,
                }
            )
        )

    def test_mismatch_summary_explains_coverage_and_default_note(self) -> None:
        preview = {
            "row_count": 1,
            "estimated_pipe_count": 2,
            "sprinkler_count": 1,
            "cad_path_check": {
                "status": "mismatch",
                "coverage_ratio": 0.0,
            },
        }
        diameter = {
            "status": "ready",
            "default_diameter_mm": 25.0,
            "default_note_count": 1,
            "source_unit": "毫米",
            "label_count": 1,
            "matched_label_count": 1,
            "main_matched_label_count": 0,
            "anchor_group_count": 0,
            "anchor_max_residual_mm": None,
            "resolved_segment_count": 1,
            "unresolved_segment_count": 0,
            "evidence_counts": {},
            "cad_geometry_exact_count": 0,
            "cad_geometry_review_count": 1,
            "junctions": [],
            "reducers": [],
        }
        with patch(
            "sc_revit.fire_branch.hot_analysis._build_diameter_analysis",
            return_value=diameter,
        ):
            result = build_preview_summary(preview)

        self.assertEqual("needs_attention", result["status"])
        self.assertIn("CAD 路徑：覆蓋率 0%（路徑尚未吻合）", result["summary_lines"])
        self.assertIn("CAD 備註預設：已偵測 1 筆｜未標註管徑 25 mm", result["summary_lines"])

    def test_summary_reports_per_sprinkler_route_candidate_audit(self) -> None:
        preview = {
            "row_count": 1,
            "estimated_pipe_count": 2,
            "sprinkler_count": 1,
            "cad_path_check": {"status": "matched", "coverage_ratio": 1.0},
        }
        diameter = {
            "status": "ready",
            "default_diameter_mm": 25.0,
            "default_note_count": 0,
            "source_unit": "毫米",
            "label_count": 1,
            "matched_label_count": 1,
            "main_matched_label_count": 0,
            "anchor_group_count": 1,
            "anchor_max_residual_mm": 0.0,
            "resolved_segment_count": 1,
            "unresolved_segment_count": 0,
            "evidence_counts": {},
            "cad_geometry_exact_count": 1,
            "cad_geometry_review_count": 0,
            "junctions": [],
            "reducers": [],
            "route_candidate_decisions": [
                {"status": "selected", "selection_consistent": True}
            ],
        }
        with patch(
            "sc_revit.fire_branch.hot_analysis._build_diameter_analysis",
            return_value=diameter,
        ):
            result = build_preview_summary(preview)

        self.assertIn("CAD 路徑候選：1/1 顆已核對", result["summary_lines"])

    def test_cad_route_graph_uses_model_coordinates_and_keeps_components(self) -> None:
        graph = _build_cad_route_graph(
            [
                {
                    "segment_id": "main",
                    "start": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "end": {"x": 10.0, "y": 0.0, "z": 0.0},
                    "layer": "SR-4626撒水100",
                    "color_key": "0,191,255",
                },
                {
                    "segment_id": "branch",
                    "start": {"x": 5.0, "y": -5.0, "z": 0.0},
                    "end": {"x": 5.0, "y": 5.0, "z": 0.0},
                    "layer": "SR-4626撒水32",
                    "color_key": "255,127,0",
                },
            ],
            coordinate_tolerance_mm=150.0,
        )

        self.assertEqual("fire_branch_cad_route_graph.v1", graph["schema_version"])
        self.assertEqual(1, graph["component_count"])
        self.assertEqual(4, graph["edge_count"])
        self.assertTrue(all(edge["component_id"] for edge in graph["edges"]))
        self.assertEqual(
            {"SR-4626撒水100", "SR-4626撒水32"},
            {layer for edge in graph["edges"] for layer in edge["layers"]},
        )


if __name__ == "__main__":
    unittest.main()
