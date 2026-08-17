import tempfile
import unittest
from pathlib import Path

from sc_revit.fire_branch.dwg_diameter_reader import _read_text_output, _render_lisp


class FireBranchDwgDiameterReaderTests(unittest.TestCase):
    def test_reads_text_position_color_and_layer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "diameters.tsv"
            output.write_text(
                "#INSUNITS\t4\n"
                "text\tx\ty\tz\tcolor\tlayer\thandle\n"
                "1 1/2\"\t10\t20\t0\t1\tSP-PIPE\tA1\n",
                encoding="utf-8",
            )

            result = _read_text_output(output)

        self.assertEqual(4, result["unit_code"])
        self.assertEqual('1 1/2"', result["texts"][0]["text"])
        self.assertEqual(1, result["texts"][0]["color"])
        self.assertEqual("SP-PIPE", result["texts"][0]["layer"])

    def test_reads_text_bounds_and_direction_for_geometric_matching(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "diameters.tsv"
            output.write_text(
                "#INSUNITS\t4\n"
                "kind\ttext\tblock_name\tx\ty\tz\tcolor\tlayer\thandle\t"
                "min_x\tmin_y\tmax_x\tmax_y\tdirection_x\tdirection_y\n"
                "text\t1 1/4\"\t\t5\t1\t0\t7\tFIRE-ANNO\tA2\t"
                "2\t0.5\t8\t1.5\t1\t0\n",
                encoding="utf-8",
            )

            result = _read_text_output(output)

        text = result["texts"][0]
        self.assertEqual(
            {"min_x": 2.0, "min_y": 0.5, "max_x": 8.0, "max_y": 1.5},
            text["bounds"],
        )
        self.assertEqual({"x": 1.0, "y": 0.0}, text["direction"])

    def test_reads_unicode_default_note_and_completion_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "diameters.tsv"
            output.write_text(
                "#INSUNITS\t4\n"
                "kind\ttext\tblock_name\tx\ty\tz\tcolor\tlayer\thandle\t"
                "min_x\tmin_y\tmax_x\tmax_y\tdirection_x\tdirection_y\n"
                "text\t備註2：未標註之管徑均為1”\t\t5\t1\t0\t7\t7\tA3\t"
                "2\t0.5\t8\t1.5\t1\t0\n"
                "#COMPLETE\t1\n",
                encoding="utf-8",
            )

            result = _read_text_output(output)

        self.assertTrue(result["complete"])
        self.assertEqual("備註2：未標註之管徑均為1”", result["texts"][0]["text"])

    def test_autolisp_uses_utf8_dxf_fallback_and_completion_marker(self):
        source = _render_lisp()

        self.assertIn('(open outputPath "w" "utf8")', source)
        self.assertIn("SC-DXF-TEXT", source)
        self.assertIn("vl-catch-all-apply 'vlax-ename->vla-object", source)
        self.assertIn('(write-line "#COMPLETE\\t1" fh)', source)


if __name__ == "__main__":
    unittest.main()
