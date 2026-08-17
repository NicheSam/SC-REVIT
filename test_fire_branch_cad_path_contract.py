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
        self.assertIn("source_element_id = item.MainPipeId", source)


if __name__ == "__main__":
    unittest.main()
