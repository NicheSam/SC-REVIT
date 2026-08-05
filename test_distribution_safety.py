import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import listener_status
import queue_protocol


ROOT = Path(__file__).resolve().parent


class AgentListenerControlTests(unittest.TestCase):
    def test_agent_listener_is_disabled_by_default(self) -> None:
        with TemporaryDirectory() as temp_dir:
            queue_dir = Path(temp_dir)
            marker = queue_dir / "agent_listener.enabled"
            heartbeat = queue_dir / "listener_heartbeat.json"
            with (
                patch.object(queue_protocol, "QUEUE_DIR", queue_dir),
                patch.object(queue_protocol, "REQUEST_DIR", queue_dir / "requests"),
                patch.object(queue_protocol, "RESPONSE_DIR", queue_dir / "responses"),
                patch.object(queue_protocol, "ERROR_DIR", queue_dir / "errors"),
                patch.object(queue_protocol, "AGENT_LISTENER_ENABLED_FILE", marker),
                patch.object(queue_protocol, "HEARTBEAT_FILE", heartbeat),
                patch.object(listener_status, "HEARTBEAT_FILE", heartbeat),
            ):
                status = listener_status.get_listener_status()
            self.assertFalse(status["enabled"])
            self.assertEqual(status["label"], "Agent 未啟用")

    def test_enable_and_disable_agent_listener(self) -> None:
        with TemporaryDirectory() as temp_dir:
            queue_dir = Path(temp_dir)
            marker = queue_dir / "agent_listener.enabled"
            heartbeat = queue_dir / "listener_heartbeat.json"
            with (
                patch.object(queue_protocol, "QUEUE_DIR", queue_dir),
                patch.object(queue_protocol, "REQUEST_DIR", queue_dir / "requests"),
                patch.object(queue_protocol, "RESPONSE_DIR", queue_dir / "responses"),
                patch.object(queue_protocol, "ERROR_DIR", queue_dir / "errors"),
                patch.object(queue_protocol, "AGENT_LISTENER_ENABLED_FILE", marker),
                patch.object(queue_protocol, "HEARTBEAT_FILE", heartbeat),
                patch.object(listener_status, "HEARTBEAT_FILE", heartbeat),
            ):
                queue_protocol.set_agent_listener_enabled(True)
                self.assertTrue(marker.is_file())
                heartbeat.write_text(
                    json.dumps({"utc": "2099-01-01T00:00:00+00:00"}),
                    encoding="utf-8",
                )
                queue_protocol.set_agent_listener_enabled(False)
            self.assertFalse(marker.exists())
            self.assertFalse(heartbeat.exists())


class DistributionSafetySourceTests(unittest.TestCase):
    def test_revit_listener_is_opt_in_and_throttled(self) -> None:
        source = (
            ROOT / "revit_addin" / "src" / "RfaMetadataApplication.cs"
        ).read_text(encoding="utf-8")
        self.assertIn("AgentListenerEnabledFile", source)
        self.assertIn("_nextListenerPollUtc", source)
        self.assertIn("now.AddSeconds(1)", source)
        self.assertIn("QuarantinePendingRequests(\"startup\")", source)
        self.assertIn(".FirstOrDefault()", source)
        self.assertNotIn(".Take(3)", source)

    def test_installer_uses_stable_dll_and_single_manifest_entry(self) -> None:
        source = (
            ROOT / "installer" / "install_sc_revit.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn('"SCRevit\\Revit2024"', source)
        self.assertIn('$deployDll = Join-Path $deployDir "RfaMetadataAddin.dll"', source)
        self.assertEqual(source.count('<AddIn Type="Application">'), 1)
        self.assertNotIn('<AddIn Type="Command">', source)
        self.assertIn('throw "Close Revit and SC REVIT before installation."', source)

    def test_agent_helper_uses_cli_safe_mode_parameter(self) -> None:
        source = (
            ROOT / "installer" / "Set_SC_REVIT_Agent.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn('[ValidateSet("enable", "disable")]', source)
        self.assertIn('if ($Mode -eq "enable")', source)


if __name__ == "__main__":
    unittest.main()
