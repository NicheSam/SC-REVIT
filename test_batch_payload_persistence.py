import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from sc_revit.core.batch import BatchStore


class BatchPayloadPersistenceTests(unittest.TestCase):
    def test_full_request_and_response_are_stored_separately_from_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = BatchStore(Path(temp_dir) / "workflow.sqlite3")
            batch = store.start_batch("fire_branch", "create", "fire branch")
            request_payload = {
                "action": "create_fire_branch_pipes",
                "model_plan_hash": "a" * 64,
                "diameter_plan": [
                    {"segment_id": f"segment-{index}", "row_index": index % 12}
                    for index in range(84)
                ],
                "topology_plan": {
                    "schema_version": "fire_branch_topology_plan.v2",
                    "junctions": [
                        {"kind": "reducing_cross", "review_required": False, "index": index}
                        for index in range(6)
                    ],
                    "reducers": [],
                    "diagnostic_padding": "x" * 6000,
                },
            }
            response_payload = {
                "action": "create_fire_branch_pipes",
                "created": [],
                "failed": [{"reason": "cross"} for _ in range(7)],
                "diagnostic_padding": "y" * 6000,
            }

            store.record_request(batch.batch_id, "request-1", "create_fire_branch_pipes", request_payload)
            store.finish_request("request-1", "success", response_payload=response_payload)
            artifact_path = Path(temp_dir) / "cross-diagnostics.json"
            artifact_path.write_text('{"kind":"cross"}', encoding="utf-8")
            store.record_artifact(
                batch.batch_id,
                "fire_branch_diagnostics",
                artifact_path,
                request_id="request-1",
            )

            with store._connect() as connection:
                row = connection.execute(
                    "select * from batch_requests where request_id = ?",
                    ("request-1",),
                ).fetchone()

            expected_request = json.dumps(request_payload, ensure_ascii=False, default=str)
            expected_response = json.dumps(response_payload, ensure_ascii=False, default=str)
            self.assertEqual(
                "消防支管｜12排｜84管段｜6四通｜拓樸已確認｜建模要求\n"
                "計畫：fire_branch_topology_plan.v2\n"
                f"SHA-256：{'a' * 64}",
                row["request_summary"],
            )
            self.assertIn("消防支管｜建模失敗｜建立0項｜失敗7項", row["response_summary"])
            self.assertEqual(expected_request, row["request_payload"])
            self.assertEqual(expected_response, row["response_payload"])
            self.assertEqual(
                hashlib.sha256(expected_request.encode("utf-8")).hexdigest(),
                row["request_payload_sha256"],
            )
            self.assertEqual(
                hashlib.sha256(expected_response.encode("utf-8")).hexdigest(),
                row["response_payload_sha256"],
            )
            self.assertEqual("fire_branch_topology_plan.v2", row["plan_schema_version"])
            self.assertEqual("a" * 64, row["plan_hash"])
            self.assertEqual(84, row["segment_count"])
            self.assertEqual(6, row["junction_count"])
            self.assertEqual(6, row["cross_count"])
            self.assertEqual(7, row["failure_count"])

            with store._connect() as connection:
                topology = connection.execute(
                    "select * from batch_topology_plans where request_id = ?",
                    ("request-1",),
                ).fetchone()
                artifact_columns = {
                    column[1]
                    for column in connection.execute("pragma table_info(batch_artifacts)")
                }
                artifact = connection.execute(
                    "select * from batch_artifacts where request_id = ?",
                    ("request-1",),
                ).fetchone()
            self.assertEqual("fire_branch_topology_plan.v2", topology["schema_version"])
            self.assertEqual(6, topology["cross_count"])
            self.assertEqual(7, topology["failure_count"])
            self.assertEqual(request_payload["topology_plan"], json.loads(topology["topology_payload"]))
            self.assertTrue({"artifact_path", "size_bytes", "sha256"}.issubset(artifact_columns))
            self.assertEqual(artifact_path.resolve(), Path(artifact["artifact_path"]))
            self.assertEqual(16, artifact["size_bytes"])


if __name__ == "__main__":
    unittest.main()
