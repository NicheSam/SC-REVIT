import unittest
from unittest.mock import patch

from sc_revit.fire_branch.hot_analysis import (
    _cad_path_verified,
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


if __name__ == "__main__":
    unittest.main()
