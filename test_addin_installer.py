import unittest
from pathlib import Path
from unittest.mock import patch

import addin_installer


class AddinInstallerTests(unittest.TestCase):
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
