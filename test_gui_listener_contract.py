import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class GuiListenerContractTests(unittest.TestCase):
    def test_gui_uses_on_demand_revit_connection_without_agent_button(self):
        source = (ROOT / "gui_app.py").read_text(encoding="utf-8")

        self.assertIn("set_gui_request_mode(True)", source)
        self.assertNotIn("set_agent_listener_enabled(True)", source)
        self.assertNotIn('text="啟用 Agent"', source)
        self.assertNotIn('text="停用 Agent"', source)
        self.assertNotIn("def _toggle_agent_listener", source)

    def test_request_queue_uses_atomic_publish_and_revit_external_event_watcher(self):
        queue_source = (ROOT / "queue_protocol.py").read_text(encoding="utf-8")
        addin_source = (
            ROOT / "revit_addin" / "src" / "RfaMetadataApplication.cs"
        ).read_text(encoding="utf-8")

        self.assertIn("os.replace", queue_source)
        self.assertIn("FileSystemWatcher", addin_source)
        self.assertIn("ExternalEvent.Create", addin_source)
        self.assertIn("IExternalEventHandler", addin_source)
        self.assertIn("_queueExternalEvent.Raise()", addin_source)
        self.assertNotIn("SetRaiseWithoutDelay", addin_source)


if __name__ == "__main__":
    unittest.main()
