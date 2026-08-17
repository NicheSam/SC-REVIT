import json
import tempfile
import unittest
from pathlib import Path

import queue_protocol
from dwg_block_reader import _read_tsv_output, _render_lisp


class DwgCoordinateMetadataTests(unittest.TestCase):
    def test_reader_preserves_large_insbase_and_extents(self) -> None:
        content = "\n".join(
            [
                "#INSUNITS\t4",
                "#INSBASE\t293603000.125\t44848900.25\t0",
                "#EXTMIN\t293598000\t44843900\t0",
                "#EXTMAX\t293616000\t44857700\t15",
                "name\tx\ty\tz\trotation_degrees\tlayer\thandle",
                "bt23_29\t293613783.119\t44852503.975\t0\t0\t7\t396E",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.dwg"
            output = Path(temp_dir) / "blocks.tsv"
            source.touch()
            output.write_text(content, encoding="utf-8")
            result = _read_tsv_output(source, output)

        self.assertEqual(result["unit_code"], 4)
        self.assertAlmostEqual(result["unit_to_feet"], 1.0 / 304.8)
        self.assertEqual(result["insbase"]["x"], 293603000.125)
        self.assertEqual(result["extmax"]["y"], 44857700.0)
        self.assertEqual(result["points"][0]["block_name"], "bt23_29")

    def test_export_script_includes_coordinate_headers(self) -> None:
        script = _render_lisp()
        self.assertIn("#INSBASE", script)
        self.assertIn("#EXTMIN", script)
        self.assertIn("#EXTMAX", script)
        self.assertIn("SC-POINT-TSV", script)

    def test_reader_handles_zero_base_and_meter_units(self) -> None:
        content = "\n".join(
            [
                "#INSUNITS\t6",
                "#INSBASE\t0\t0\t0",
                "#EXTMIN\t-12.5\t-8\t0",
                "#EXTMAX\t25\t16\t3",
                "name\tx\ty\tz\trotation_degrees\tlayer\thandle",
                "device\t4.5\t2.25\t0\t90\tMEP\tA1",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.dwg"
            output = Path(temp_dir) / "blocks.tsv"
            source.touch()
            output.write_text(content, encoding="utf-8")
            result = _read_tsv_output(source, output)

        self.assertEqual(result["unit_name"], "公尺")
        self.assertAlmostEqual(result["unit_to_feet"], 1.0 / 0.3048)
        self.assertEqual(result["insbase"], {"x": 0.0, "y": 0.0, "z": 0.0})
        self.assertEqual(result["points"][0]["rotation_degrees"], 90.0)


class QueueCoordinateContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_dirs = (
            queue_protocol.REQUEST_DIR,
            queue_protocol.RESPONSE_DIR,
            queue_protocol.ERROR_DIR,
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        queue_protocol.REQUEST_DIR = root / "requests"
        queue_protocol.RESPONSE_DIR = root / "responses"
        queue_protocol.ERROR_DIR = root / "errors"

    def tearDown(self) -> None:
        (
            queue_protocol.REQUEST_DIR,
            queue_protocol.RESPONSE_DIR,
            queue_protocol.ERROR_DIR,
        ) = self.original_dirs
        self.temp_dir.cleanup()

    def test_preview_marks_revit_model_coordinate_space(self) -> None:
        request = queue_protocol.create_dwg_preview_markers_request(
            import_id=10,
            level_id=20,
            points=[{"x": 1.0, "y": 2.0, "z": 0.0}],
            offset_mm=0,
            points_are_model_coordinates=True,
        )
        payload = json.loads(
            (queue_protocol.REQUEST_DIR / f"{request.request_id}.json").read_text(encoding="utf-8")
        )
        self.assertIs(payload["points_are_model_coordinates"], True)

    def test_place_marks_revit_model_coordinate_space(self) -> None:
        request = queue_protocol.create_place_dwg_block_points_request(
            import_id=10,
            symbol_id=30,
            level_id=20,
            points=[{"x": 1.0, "y": 2.0, "z": 0.0}],
            offset_mm=0,
            duplicate_tolerance_mm=10,
            points_are_model_coordinates=True,
        )
        payload = json.loads(
            (queue_protocol.REQUEST_DIR / f"{request.request_id}.json").read_text(encoding="utf-8")
        )
        self.assertIs(payload["points_are_model_coordinates"], True)

    def test_clear_preview_request_has_dedicated_action(self) -> None:
        request = queue_protocol.create_clear_dwg_preview_markers_request()
        payload = json.loads(
            (queue_protocol.REQUEST_DIR / f"{request.request_id}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["action"], "clear_dwg_preview_markers")


class RevitLinkedGeometryContractTests(unittest.TestCase):
    def test_revit_scan_uses_issue_100_transform_chain(self) -> None:
        source = (
            Path(__file__).parent / "revit_addin" / "src" / "RfaMetadataApplication.cs"
        ).read_text(encoding="utf-8")
        self.assertIn("root.GetSymbolGeometry()", source)
        self.assertIn("root.Transform", source)
        self.assertIn("importInstance.GetTotalTransform()", source)
        self.assertIn("anchor_residual_mm", source)
        self.assertIn('blockName.EndsWith("." + filter', source)

    def test_gui_rescans_link_before_preview_and_create(self) -> None:
        source = (Path(__file__).parent / "gui_app.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("request_cad_block_preview("), 2)
        self.assertGreaterEqual(source.count("points_are_model_coordinates=True"), 2)
        self.assertIn("source_signature", source)
        self.assertNotIn("請在 Revit 圖面移動整個預覽群組校正位置", source)

    def test_preview_precomputes_transient_direct_context_markers(self) -> None:
        root = Path(__file__).parent / "revit_addin" / "src"
        handler = (root / "Handlers" / "CadPointHandler.cs").read_text(
            encoding="utf-8"
        )
        renderer = (root / "Drainage" / "DrainagePreviewServer.cs").read_text(
            encoding="utf-8"
        )
        self.assertIn("DrainagePreviewServer.SetCadPointMarkers", handler)
        self.assertIn("DrainagePreviewServer.ClearCadPointMarkers", handler)
        self.assertIn("CadPointSegmentsByDocument", renderer)
        self.assertIn("PreviewExpiresByDocument", renderer)
        self.assertNotIn("view.RightDirection.Normalize()", renderer)
        self.assertNotIn("view.UpDirection.Normalize()", renderer)
        self.assertIn('Kind = "cad_point_preview"', renderer)
        self.assertIn("new ColorWithTransparency(0, 255, 80, 0)", renderer)

    def test_preview_lifecycle_clears_direct_and_legacy_artifacts(self) -> None:
        root = Path(__file__).parent / "revit_addin" / "src"
        application = (root / "RfaMetadataApplication.cs").read_text(encoding="utf-8")
        handler = (root / "Handlers" / "CadPointHandler.cs").read_text(encoding="utf-8")
        gui = (Path(__file__).parent / "gui_app.py").read_text(encoding="utf-8")

        self.assertIn('"clear_dwg_preview_markers"', handler)
        self.assertIn("ClearCadPointMarkers", handler)
        self.assertIn("TryDeletePreviewGroupsByPrefix", handler)
        self.assertIn("candidate_group_types", application)
        self.assertIn("deleted_group_types", application)
        self.assertNotIn("if (previewGroupIds.Count == 0)\n                {\n                    return;", application)
        self.assertIn('self.protocol("WM_DELETE_WINDOW", self._on_app_close)', gui)
        self.assertIn("request_clear_dwg_preview_markers", gui)

    def test_preview_rejects_points_outside_import_bounds(self) -> None:
        source = (
            Path(__file__).parent / "revit_addin" / "src" / "RfaMetadataApplication.cs"
        ).read_text(encoding="utf-8")
        handler = (
            Path(__file__).parent / "revit_addin" / "src" / "Handlers" / "CadPointHandler.cs"
        ).read_text(encoding="utf-8")
        self.assertIn("ValidateCadPreviewPointsAgainstImport", source)
        self.assertIn("outside the linked CAD bounds by more than 30 m", source)
        self.assertIn("ValidateCadPreviewPointsAgainstImport(importInstance, points)", handler)

    def test_updater_deploys_and_verifies_the_runtime_gui(self) -> None:
        source = (Path(__file__).parent / "install_or_update.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("[switch]$GuiOnly", source)
        self.assertIn("SC_REVIT_HOME", source)
        self.assertIn("Deploy GUI executable", source)
        self.assertIn("Deploy GUI hash does not match source GUI", source)
        self.assertIn("Start-Process -FilePath $deployGuiExe", source)
        self.assertIn("--mode=[A-Za-z0-9-]+", source)
        self.assertIn("-ArgumentList $restartGuiMode", source)
        self.assertIn(
            '$runningGuiCommandLineText = if ($null -eq $runningGuiCommandLine)',
            source,
        )
        self.assertIn("$runningGuiCommandLineText,", source)

    def test_legacy_revit_updater_delegates_to_full_dll_and_gui_update(self) -> None:
        source = (Path(__file__).parent / "update_revit_addin.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('Join-Path $root "install_or_update.ps1"', source)
        self.assertIn('-File $installer', source)
        self.assertNotIn('addin_installer.py', source)
        self.assertNotIn('revit_addin\\build.ps1', source)

if __name__ == "__main__":
    unittest.main()
