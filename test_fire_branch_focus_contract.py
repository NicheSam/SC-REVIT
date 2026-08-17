import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class FireBranchFocusContractTests(unittest.TestCase):
    def test_queue_and_client_expose_preview_segment_focus(self) -> None:
        queue_source = (ROOT / "queue_protocol.py").read_text(encoding="utf-8")
        client_source = (ROOT / "sc_revit" / "fire_branch" / "client.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("def create_fire_branch_focus_request", queue_source)
        self.assertIn('action="focus_fire_branch_preview_segment"', queue_source)
        self.assertIn("def request_focus_fire_branch_segment", client_source)

    def test_revit_handler_zooms_open_active_view_without_model_mutation(self) -> None:
        source = (
            ROOT / "revit_addin" / "src" / "Handlers" / "FireBranchHandler.cs"
        ).read_text(encoding="utf-8")

        self.assertIn('"focus_fire_branch_preview_segment"', source)
        self.assertIn("GetOpenUIViews()", source)
        self.assertIn("ZoomAndCenterRectangle", source)


if __name__ == "__main__":
    unittest.main()
