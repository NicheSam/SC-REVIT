import tempfile
import unittest
from pathlib import Path

from tools.inspect_dwg_paths import _read_output, _render_lisp


class DwgPathReaderTests(unittest.TestCase):
    def test_parser_reports_path_types_and_layers(self):
        content = "\n".join(
            [
                "#INSUNITS\t4",
                "#EXTMIN\t0\t0\t0",
                "#EXTMAX\t1000\t500\t0",
                "entity_type\tlayer\thandle\tx1\ty1\tz1\tx2\ty2\tz2",
                "LINE\tFIRE\tA1\t0\t0\t0\t1000\t0\t0",
                "LWPOLYLINE\tFIRE\tA2\t1000\t0\t0\t1000\t500\t0",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "paths.tsv"
            output.write_text(content, encoding="utf-8")
            result = _read_output(Path("sample.dwg"), output)

        self.assertEqual(result["unit_code"], 4)
        self.assertEqual(result["segment_count"], 2)
        self.assertEqual(result["entity_type_counts"], {"LINE": 1, "LWPOLYLINE": 1})
        self.assertEqual(result["layer_counts"][0], {"layer": "FIRE", "segment_count": 2})

    def test_lisp_is_read_only_path_export(self):
        script = _render_lisp()

        self.assertIn('"LINE,LWPOLYLINE,ARC"', script)
        self.assertIn("SC-WRITE-PATH", script)
        self.assertNotIn("entdel", script.lower())
        self.assertNotIn("command ", script.lower())


if __name__ == "__main__":
    unittest.main()
