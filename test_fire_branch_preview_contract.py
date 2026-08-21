import unittest
from pathlib import Path

from sc_revit.fire_branch.network_preview import FireBranchNetworkPreview


ROOT = Path(__file__).resolve().parent
FIRE_BRANCH_SOURCE = ROOT / "revit_addin" / "src" / "Handlers" / "FireBranchHandler.cs"
PREVIEW_SERVER_SOURCE = ROOT / "revit_addin" / "src" / "Drainage" / "DrainagePreviewServer.cs"
APPLICATION_SOURCE = ROOT / "revit_addin" / "src" / "RfaMetadataApplication.cs"
CAD_POINT_SOURCE = ROOT / "revit_addin" / "src" / "Handlers" / "CadPointHandler.cs"


class FireBranchPreviewContractTests(unittest.TestCase):
    def test_fittings_are_read_only_in_network_preview(self):
        source = (ROOT / "sc_revit" / "fire_branch" / "network_preview.py").read_text(encoding="utf-8")

        self.assertNotIn('text="修改接頭"', source)
        self.assertNotIn('text="修改異徑"', source)
        self.assertNotIn("command=self._apply_junction_kind", source)
        self.assertNotIn("command=self._apply_reducer", source)
        self.assertNotIn("def _apply_junction_kind", source)
        self.assertNotIn("def _apply_reducer", source)
        self.assertNotIn("_junction_kind_var", source)
        self.assertNotIn("_reducer_from_var", source)
        self.assertNotIn("_reducer_to_var", source)
        self.assertIn("接頭由管段管徑自動推導", source)
        self.assertIn("異徑由前後管段管徑自動推導", source)

    def test_edit_callback_keeps_previous_preview_when_rebuild_raises(self):
        class _Status:
            def __init__(self):
                self.value = ""

            def set(self, value):
                self.value = value

        class _PreviewStub:
            _append_plan_revision = FireBranchNetworkPreview._append_plan_revision

            def __init__(self):
                self._plan_history = [{"revision": 1}]
                self._plan_history_index = 0
                self._status_var = _Status()
                self.calls = []
                self.fail_revision = None

            def _use_plan(self, plan, **_kwargs):
                self.calls.append(plan["revision"])
                if plan["revision"] == self.fail_revision:
                    raise RuntimeError("測試重繪失敗")

        preview = _PreviewStub()
        self.assertTrue(preview._append_plan_revision({"revision": 2}))
        self.assertEqual(1, preview._plan_history_index)
        preview.fail_revision = 3

        self.assertFalse(preview._append_plan_revision({"revision": 3}))
        self.assertEqual(1, preview._plan_history_index)
        self.assertEqual([2, 3, 2], preview.calls)
        self.assertIn("修改未套用", preview._status_var.value)

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
