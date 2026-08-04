import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

import addin_installer


class AddinInstallerTests(unittest.TestCase):
    def test_preserves_usable_existing_manifest(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_dll = temp_root / "bundled.dll"
            source_dll.write_bytes(b"bundled")
            existing_dll = temp_root / "RfaMetadataAddin.existing.dll"
            existing_dll.write_bytes(b"existing")
            environment = {
                "APPDATA": str(temp_root / "Roaming"),
                "LOCALAPPDATA": str(temp_root / "Local"),
            }
            with (
                patch.dict(addin_installer.os.environ, environment),
                patch.object(addin_installer, "SOURCE_DLL", source_dll),
            ):
                manifest_path = (
                    addin_installer.get_user_addins_dir()
                    / addin_installer.ADDIN_FILE_NAME
                )
                manifest_path.parent.mkdir(parents=True)
                manifest_path.write_text(
                    addin_installer.render_manifest(existing_dll),
                    encoding="utf-8",
                )
                before = manifest_path.read_bytes()

                result = addin_installer.ensure_revit_addin_installed()

                self.assertFalse(result.installed)
                self.assertEqual(
                    result.message,
                    "保留現有 Revit 外掛部署",
                )
                self.assertEqual(manifest_path.read_bytes(), before)

    def test_replaces_manifest_that_points_to_missing_dll(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_dll = temp_root / "bundled.dll"
            source_dll.write_bytes(b"bundled")
            environment = {
                "APPDATA": str(temp_root / "Roaming"),
                "LOCALAPPDATA": str(temp_root / "Local"),
            }
            with (
                patch.dict(addin_installer.os.environ, environment),
                patch.object(addin_installer, "SOURCE_DLL", source_dll),
            ):
                manifest_path = (
                    addin_installer.get_user_addins_dir()
                    / addin_installer.ADDIN_FILE_NAME
                )
                manifest_path.parent.mkdir(parents=True)
                manifest_path.write_text(
                    addin_installer.render_manifest(
                        temp_root / "missing.dll"
                    ),
                    encoding="utf-8",
                )

                result = addin_installer.ensure_revit_addin_installed()
                deployed_dll = (
                    addin_installer.get_ascii_deploy_dir()
                    / addin_installer.versioned_dll_name(source_dll)
                )

                self.assertFalse(result.installed)
                self.assertTrue(deployed_dll.is_file())
                self.assertIn(
                    str(deployed_dll.resolve()),
                    manifest_path.read_text(encoding="utf-8"),
                )

    def test_force_replaces_usable_existing_manifest(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_dll = temp_root / "bundled.dll"
            source_dll.write_bytes(b"bundled")
            existing_dll = temp_root / "RfaMetadataAddin.existing.dll"
            existing_dll.write_bytes(b"existing")
            environment = {
                "APPDATA": str(temp_root / "Roaming"),
                "LOCALAPPDATA": str(temp_root / "Local"),
            }
            with (
                patch.dict(addin_installer.os.environ, environment),
                patch.object(addin_installer, "SOURCE_DLL", source_dll),
            ):
                manifest_path = (
                    addin_installer.get_user_addins_dir()
                    / addin_installer.ADDIN_FILE_NAME
                )
                manifest_path.parent.mkdir(parents=True)
                manifest_path.write_text(
                    addin_installer.render_manifest(existing_dll),
                    encoding="utf-8",
                )

                result = addin_installer.ensure_revit_addin_installed(
                    force=True
                )
                deployed_dll = (
                    addin_installer.get_ascii_deploy_dir()
                    / addin_installer.versioned_dll_name(source_dll)
                )

                self.assertFalse(result.installed)
                self.assertIn(
                    str(deployed_dll.resolve()),
                    manifest_path.read_text(encoding="utf-8"),
                )

    def test_frozen_launcher_marker_points_to_executable_directory(
        self,
    ) -> None:
        executable = (
            Path("C:/SCRevit/RevitFamilyClassifier")
            / "RevitFamilyClassifier.exe"
        )
        with (
            patch.object(
                addin_installer.sys,
                "frozen",
                True,
                create=True,
            ),
            patch.object(
                addin_installer.sys,
                "executable",
                str(executable),
            ),
        ):
            root = addin_installer.get_launcher_root()
        self.assertEqual(root, executable.parent.resolve())


if __name__ == "__main__":
    unittest.main()
