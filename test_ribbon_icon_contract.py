import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APPLICATION_SOURCE = ROOT / "revit_addin" / "src" / "RfaMetadataApplication.cs"
ICON_FACTORY_SOURCE = ROOT / "revit_addin" / "src" / "ScIconFactory.cs"


class RibbonIconContractTests(unittest.TestCase):
    def test_each_ribbon_command_uses_its_distinct_sc_icon(self):
        application_source = APPLICATION_SOURCE.read_text(encoding="utf-8")
        stable_icons = {
            "placementButton": "point_placement",
            "backstageButton": "backstage",
            "fireBranchButton": "fire_branch",
            "drainageConnectButton": "drainage_connect",
            "drainageSettingsButton": "drainage_settings",
            "alignPipeCenterlineButton": "align_centerline",
        }
        development_icons = {
            "archiveButton": "family_archive",
            "recoveryButton": "project_recovery",
            "openingButton": "opening_locator",
            "elementInspectorButton": "element_inspector",
            "parameterAuditButton": "parameter_audit",
            "connectFittingButton": "breakpoint_check",
            "pipingSupportButton": "piping_support",
        }

        for button_name, icon_name in stable_icons.items():
            pattern = (
                re.escape(button_name)
                + r'\.LargeImage\s*=\s*ScIconFactory\.Create\("'
                + re.escape(icon_name)
                + r'",\s*32\);'
            )
            self.assertRegex(application_source, pattern)

        for button_name, icon_name in development_icons.items():
            call = f'MarkDevelopmentButton({button_name}, "{icon_name}");'
            self.assertIn(call, application_source)

    def test_development_buttons_have_visible_status_labels(self):
        application_source = APPLICATION_SOURCE.read_text(encoding="utf-8")
        self.assertEqual(application_source.count("\\n\\u958b\\u767c\\u4e2d"), 7)
        self.assertIn("ScIconFactory.CreateDevelopment(iconName, 32)", application_source)
        self.assertIn("\\u3010\\u958b\\u767c\\u4e2d\\u3011", application_source)

    def test_development_badge_is_drawn_by_icon_factory(self):
        factory_source = ICON_FACTORY_SOURCE.read_text(encoding="utf-8")
        self.assertIn("CreateDevelopment", factory_source)
        self.assertIn("DrawDevelopmentBadge", factory_source)
        self.assertIn("Brush(Red)", factory_source)

    def test_icon_factory_defines_every_ribbon_icon(self):
        factory_source = ICON_FACTORY_SOURCE.read_text(encoding="utf-8")
        for icon_name in (
            "family_archive",
            "project_recovery",
            "point_placement",
            "backstage",
            "fire_branch",
            "drainage_connect",
            "drainage_settings",
            "align_centerline",
            "opening_locator",
            "element_inspector",
            "parameter_audit",
            "breakpoint_check",
            "piping_support",
        ):
            self.assertIn(f'name == "{icon_name}"', factory_source)


if __name__ == "__main__":
    unittest.main()
