import copy
import unittest

from sc_revit.fire_branch.snapshot_contract import validate_fire_branch_snapshot


def _minimal_snapshot() -> dict:
    return {
        "schema_version": "fire_branch_revit_snapshot.v1",
        "seed_main_pipe_ids": [100],
        "main_graph": {
            "elements": [{"element_id": 100, "kind": "pipe"}],
            "nodes": [
                {"node_id": "100:0"},
                {"node_id": "100:1"},
            ],
            "edges": [
                {"start_node": "100:0", "end_node": "100:1"},
            ],
            "connections": [
                {
                    "from_node": "100:0",
                    "to_node": "100:1",
                    "connected": True,
                }
            ],
            "stopped_connections": [],
        },
        "mutation": {
            "mode": "read_only",
            "created_element_count": 0,
            "deleted_element_count": 0,
        },
    }


class FireBranchSnapshotContractTests(unittest.TestCase):
    def test_minimal_read_only_snapshot_is_valid(self) -> None:
        self.assertEqual([], validate_fire_branch_snapshot(_minimal_snapshot()))

    def test_snapshot_validation_does_not_mutate_payload(self) -> None:
        snapshot = _minimal_snapshot()
        before = copy.deepcopy(snapshot)

        validate_fire_branch_snapshot(snapshot)

        self.assertEqual(before, snapshot)

    def test_snapshot_rejects_mutation_and_dangling_edges(self) -> None:
        snapshot = _minimal_snapshot()
        snapshot["mutation"]["created_element_count"] = 1
        snapshot["main_graph"]["edges"][0]["end_node"] = "missing"

        errors = validate_fire_branch_snapshot(snapshot)

        self.assertIn("唯讀快照不應建立元素", errors)
        self.assertIn("主管圖第 1 段引用不存在的 end_node", errors)


if __name__ == "__main__":
    unittest.main()
