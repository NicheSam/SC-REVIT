import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FIRE_BRANCH_SOURCE = ROOT / "revit_addin" / "src" / "Handlers" / "FireBranchHandler.cs"
PREVIEW_SERVER_SOURCE = ROOT / "revit_addin" / "src" / "Drainage" / "DrainagePreviewServer.cs"
APPLICATION_SOURCE = ROOT / "revit_addin" / "src" / "RfaMetadataApplication.cs"
CAD_POINT_SOURCE = ROOT / "revit_addin" / "src" / "Handlers" / "CadPointHandler.cs"


class FireBranchPreviewContractTests(unittest.TestCase):
    def test_fire_branch_preview_uses_direct_context_at_plan_display_z(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        self.assertIn("ResolveFireBranchPreviewDisplayZ", source)
        self.assertIn("BuildFireBranchPreviewSegments", source)
        self.assertIn('Kind = "fire_branch_preview"', source)
        self.assertIn("DrainagePreviewServer.SetSegments", source)
        self.assertIn('preview_rendering = "direct_context_3d"', source)
        self.assertNotIn('preview_rendering = "direct_context_3d_and_model_curves"', source)
        self.assertIn("preview_server_active", source)
        start = source.index('if (action == "create_fire_branch_preview")')
        end = source.index(
            'if (action == "create_fire_branch_pipes" || action == "test_fire_branch_pipes")',
            start,
        )
        self.assertNotIn("NewModelCurve", source[start:end])

    def test_fire_branch_preview_returns_active_view_axes_for_svg_orientation(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        self.assertIn("view_orientation", source)
        self.assertIn("activeView.RightDirection.Normalize()", source)
        self.assertIn("activeView.UpDirection.Normalize()", source)

    def test_point_markers_are_projected_to_the_visible_plan_plane(self):
        source = PREVIEW_SERVER_SOURCE.read_text(encoding="utf-8")

        self.assertIn("CadPointSegmentsByDocument", source)
        self.assertIn("PreviewLifetime", source)
        self.assertIn("IsRegisteredAndActive", source)
        self.assertIn('segment.Kind == "fire_branch_preview"', source)

    def test_failed_create_requests_clear_transient_previews(self):
        application = APPLICATION_SOURCE.read_text(encoding="utf-8")

        self.assertIn("TryCleanupPreviewAfterFailedRequest", application)
        self.assertIn('action == "create_fire_branch_pipes"', application)
        self.assertIn('action == "test_fire_branch_pipes"', application)
        self.assertIn('action == "create_fire_branch_preview"', application)
        self.assertIn('action == "place_dwg_block_points"', application)
        self.assertIn('action == "create_dwg_preview_markers"', application)
        self.assertIn("DrainagePreviewServer.Clear(doc)", application)
        self.assertIn("DrainagePreviewServer.ClearCadPointMarkers(doc)", application)

    def test_point_preview_is_direct_context_only(self):
        source = CAD_POINT_SOURCE.read_text(encoding="utf-8")

        self.assertIn('preview_rendering = "direct_context_3d"', source)
        self.assertNotIn('preview_rendering = "direct_context_3d_and_model_curves"', source)
        self.assertIn("ResolveFireBranchPreviewDisplayZ", source)
        start = source.index('if (action == "create_dwg_preview_markers")')
        end = source.index('if (action == "place_cad_block_points")', start)
        self.assertNotIn("NewModelCurve", source[start:end])


if __name__ == "__main__":
    unittest.main()
