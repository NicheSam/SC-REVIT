import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VERIFIER_SOURCE = ROOT / "revit_addin" / "src" / "Handlers" / "CadPathShadowVerifier.cs"
FIRE_BRANCH_SOURCE = ROOT / "revit_addin" / "src" / "Handlers" / "FireBranchHandler.cs"
GUI_SOURCE = ROOT / "gui_app.py"


class FireBranchCadPathContractTests(unittest.TestCase):
    def test_preview_returns_non_blocking_cad_shadow_evidence(self):
        verifier = VERIFIER_SOURCE.read_text(encoding="utf-8")
        handler = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        self.assertIn('mode = "shadow"', verifier)
        self.assertIn("affects_creation = false", verifier)
        self.assertIn("BuildFireBranchCadPathShadowReport", handler)
        self.assertIn("cad_path_check = cadPathCheck", handler)

    def test_verifier_extracts_supported_revit_cad_curves(self):
        source = VERIFIER_SOURCE.read_text(encoding="utf-8")

        self.assertIn("PolyLine polyLine = item as PolyLine", source)
        self.assertIn("Curve curve = item as Curve", source)
        self.assertIn("curve.Tessellate()", source)
        self.assertIn("GraphicsStyleCategory", source)

    def test_verifier_reuses_point_placement_coordinate_evidence(self):
        source = VERIFIER_SOURCE.read_text(encoding="utf-8")

        self.assertIn("ScanCadBlockPoints(", source)
        self.assertIn("HasNonCollinearCadPathAnchors", source)
        self.assertIn("MaximumAnchorResidualMm <= 1.0", source)
        self.assertIn("cad_geometry_to_import_total_transform_to_revit_model", source)
        self.assertIn("cad_anchor_unverified", source)

    def test_path_geometry_uses_same_import_transform_as_point_placement(self):
        source = VERIFIER_SOURCE.read_text(encoding="utf-8")

        self.assertIn("root.GetSymbolGeometry()", source)
        self.assertIn("root.Transform,", source)
        self.assertNotIn("importTransform.Multiply(root.Transform)", source)

    def test_verifier_checks_route_and_topology_with_separate_tolerances(self):
        source = VERIFIER_SOURCE.read_text(encoding="utf-8")

        self.assertIn("CadPathSpatialIndex", source)
        self.assertIn("CadPathExtractionScope", source)
        self.assertIn("selected_sprinkler_route_corridors", source)
        self.assertIn("corridor_buffer_mm = 1000", source)
        self.assertIn("CadPathSegmentIntersectsScope", source)
        self.assertIn("CadPathSegmentsIntersectXY", source)
        self.assertIn("distance_tolerance_mm = 150", source)
        self.assertIn("angle_tolerance_degrees", source)
        self.assertIn("topology_match_ratio", source)
        self.assertIn("BuildFireBranchJunctionPlans", source)
        self.assertIn("DotXY(item, branchDirection) > 0.999", source)

    def test_verifier_does_not_search_unrelated_cad_with_a_global_fallback(self):
        source = VERIFIER_SOURCE.read_text(encoding="utf-8")

        self.assertNotIn("ConvertToInternalUnits(15000", source)
        self.assertNotIn("selected_route_corridors_expanded_after_empty_first_pass", source)
        self.assertNotIn('warningCodes.Add("cad_scope_expanded")', source)

    def test_gui_displays_cad_status_without_new_user_input(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn('cad_path_check = payload.get("cad_path_check") or {}', source)
        self.assertIn('f"CAD {cad_status} {coverage:.0%}｜"', source)
        self.assertNotIn("fire_cad_import_var", source)

    def test_preview_exposes_diameter_probe_geometry_without_new_cad_selection(self):
        source = VERIFIER_SOURCE.read_text(encoding="utf-8")

        self.assertIn("BuildFireBranchDiameterProbeSegments", source)
        self.assertIn("diameter_probe_segments", source)
        self.assertIn("import_transform", source)
        self.assertIn("color_key", source)
        self.assertIn("selected_source_path", source)

    def test_route_geometry_preserves_kind_and_closed_shape_metadata(self):
        source = VERIFIER_SOURCE.read_text(encoding="utf-8")

        self.assertIn("GeometryKind", source)
        self.assertIn("ClosedGeometry", source)
        self.assertIn("geometry_kind = segment.GeometryKind", source)
        self.assertIn("closed_geometry = segment.ClosedGeometry", source)

    def test_diameter_probe_preserves_real_revit_sprinkler_terminals(self):
        source = VERIFIER_SOURCE.read_text(encoding="utf-8")

        self.assertIn("sprinkler_id = target.Sprinkler.Id.Value", source)
        self.assertIn("is_sprinkler_terminal = true", source)

    def test_preview_exposes_selected_main_geometry_for_role_aware_matching(self):
        source = VERIFIER_SOURCE.read_text(encoding="utf-8")

        self.assertIn("BuildFireBranchMainContextSegments", source)
        self.assertIn("main_context_segments", source)
        self.assertIn('topology_role = "main"', source)
        self.assertIn("source_element_id = item.PipeId", source)
        self.assertIn("diameter_mm = UnitUtils.ConvertFromInternalUnits", source)
        self.assertIn("BuildFireBranchMainConnectionRecords", source)
        self.assertIn("endpoint = startDistance <= endDistance ? \"start\" : \"end\"", source)

    def test_multi_main_assignment_uses_cad_route_evidence_before_rows(self):
        handler = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        self.assertIn("BuildFireBranchItemsFromCadEvidence", handler)
        preview_start = handler.index('if (action == "create_fire_branch_preview")')
        create_start = handler.index('if (action == "create_fire_branch_pipes"')
        for action_start in (preview_start, create_start):
            assignment = handler.index("BuildFireBranchItemsFromCadEvidence(", action_start)
            grouping = handler.index("BuildFireBranchRows(", action_start)
            self.assertLess(assignment, grouping)
        self.assertIn("CompareFireBranchCadCandidateEvidence", handler)
        self.assertIn("Candidate.BranchParameter", handler)
        self.assertIn("CAD 路徑證據", handler)


if __name__ == "__main__":
    unittest.main()
