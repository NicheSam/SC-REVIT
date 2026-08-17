import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class FireBranchCadSegmentAuditContractTests(unittest.TestCase):
    def test_probe_segments_preserve_full_cad_geometry_evidence(self) -> None:
        source = (
            ROOT / "revit_addin" / "src" / "Handlers" / "CadPathShadowVerifier.cs"
        ).read_text(encoding="utf-8")

        for field in (
            "planned_length_mm",
            "cad_length_mm",
            "length_delta_mm",
            "cad_start_offset_mm",
            "cad_midpoint_offset_mm",
            "cad_end_offset_mm",
            "cad_angle_delta_degrees",
            "cad_geometry_exact",
            "cad_start",
            "cad_end",
        ):
            self.assertIn(field, source)


if __name__ == "__main__":
    unittest.main()
