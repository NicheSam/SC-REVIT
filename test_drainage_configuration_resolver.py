import json
import tempfile
import unittest
from pathlib import Path

from sc_revit.drainage.configuration_resolver import (
    recommend_drainage_configuration,
)


def _candidate(element_id: str, unique_id: str, order: int) -> dict:
    return {
        "element_id": element_id,
        "unique_id": unique_id,
        "name": unique_id,
        "family_name": "Test",
        "order": order,
        "criteria": [{"minimum_mm": 50, "maximum_mm": 150}],
    }


def _context(junctions: list[dict], elbows: list[dict]) -> dict:
    return {
        "document": {"fingerprint": "sha256:doc", "revision": 7},
        "pipe_types": [
            {"element_id": "30", "unique_id": "pipe-type"}
        ],
        "system_types": [
            {"element_id": "40", "unique_id": "system-type"}
        ],
        "levels": [{"element_id": "50", "unique_id": "level"}],
        "routing_profiles": [
            {
                "pipe_type_id": "30",
                "junctions": junctions,
                "elbows": elbows,
            }
        ],
    }


def _main_pipe() -> dict:
    return {
        "element_id": "10",
        "unique_id": "main",
        "pipe_type_id": "30",
        "system_type_id": "40",
        "level_id": "50",
        "diameter_mm": 100,
    }


class DrainageConfigurationResolverTests(unittest.TestCase):
    def test_single_size_compatible_candidate_can_auto_select(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = recommend_drainage_configuration(
                context=_context(
                    [_candidate("60", "junction-a", 0)],
                    [_candidate("70", "elbow-a", 0)],
                ),
                main_pipe=_main_pipe(),
                diameter_mm=100,
                operation_journal_dir=Path(temp_dir),
            )
        self.assertTrue(result["auto_select_allowed"])
        self.assertEqual(result["selection_policy"]["model_scan"], "none")

    def test_dominant_same_document_history_beats_routing_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_dir = Path(temp_dir)
            for index in range(3):
                record = {
                    "DocumentFingerprint": "sha256:doc",
                    "Status": "committed",
                    "Result": {
                        "diameter_mm": 100,
                        "fittings": [
                            {"element_id": 100 + index, "kind": "junction"},
                            {"element_id": 200 + index, "kind": "elbow"},
                        ],
                        "fitting_element_refs": [
                            {
                                "element_id": 100 + index,
                                "type_unique_id": "junction-b",
                            },
                            {
                                "element_id": 200 + index,
                                "type_unique_id": "elbow-b",
                            },
                        ],
                    },
                }
                (journal_dir / f"DOP-{index}.json").write_text(
                    json.dumps(record),
                    encoding="utf-8",
                )
            result = recommend_drainage_configuration(
                context=_context(
                    [
                        _candidate("60", "junction-a", 0),
                        _candidate("61", "junction-b", 1),
                    ],
                    [
                        _candidate("70", "elbow-a", 0),
                        _candidate("71", "elbow-b", 1),
                    ],
                ),
                main_pipe=_main_pipe(),
                diameter_mm=100,
                operation_journal_dir=journal_dir,
            )
        self.assertTrue(result["auto_select_allowed"])
        self.assertEqual(
            result["recommended_configuration"]["junction"]["unique_id"],
            "junction-b",
        )
        self.assertEqual(
            result["confidence"]["junction"]["reason"],
            "dominant_same_document_usage",
        )

    def test_routing_order_only_requires_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = recommend_drainage_configuration(
                context=_context(
                    [
                        _candidate("60", "junction-a", 0),
                        _candidate("61", "junction-b", 1),
                    ],
                    [
                        _candidate("70", "elbow-a", 0),
                        _candidate("71", "elbow-b", 1),
                    ],
                ),
                main_pipe=_main_pipe(),
                diameter_mm=100,
                operation_journal_dir=Path(temp_dir),
            )
        self.assertFalse(result["auto_select_allowed"])
        self.assertTrue(result["requires_human_choice"])

    def test_saved_human_choice_is_used_only_for_same_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = recommend_drainage_configuration(
                context=_context(
                    [
                        _candidate("60", "junction-a", 0),
                        _candidate("61", "junction-b", 1),
                    ],
                    [
                        _candidate("70", "elbow-a", 0),
                        _candidate("71", "elbow-b", 1),
                    ],
                ),
                main_pipe=_main_pipe(),
                diameter_mm=100,
                saved_settings={
                    "document_fingerprint": "sha256:other",
                    "junction_type_unique_id": "junction-b",
                    "elbow_type_unique_id": "elbow-b",
                },
                operation_journal_dir=Path(temp_dir),
            )
        self.assertFalse(result["saved_human_settings_used"])
        self.assertEqual(
            result["recommended_configuration"]["junction"]["unique_id"],
            "junction-a",
        )


if __name__ == "__main__":
    unittest.main()
