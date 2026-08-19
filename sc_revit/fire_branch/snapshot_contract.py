"""Validation for the read-only Revit fire-branch snapshot contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SNAPSHOT_SCHEMA_VERSION = "fire_branch_revit_snapshot.v1"


def validate_fire_branch_snapshot(snapshot: Mapping[str, Any]) -> list[str]:
    """Return human-readable contract errors without mutating the snapshot."""

    errors: list[str] = []
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        errors.append("快照版本不是 fire_branch_revit_snapshot.v1")

    seed_ids = snapshot.get("seed_main_pipe_ids")
    if not isinstance(seed_ids, list) or not seed_ids:
        errors.append("快照沒有主管種子")

    mutation = snapshot.get("mutation")
    if not isinstance(mutation, Mapping):
        errors.append("快照缺少唯讀變更標記")
    else:
        if mutation.get("mode") != "read_only":
            errors.append("主管快照不是唯讀模式")
        if mutation.get("created_element_count") != 0:
            errors.append("唯讀快照不應建立元素")
        if mutation.get("deleted_element_count") != 0:
            errors.append("唯讀快照不應刪除元素")

    graph = snapshot.get("main_graph")
    if not isinstance(graph, Mapping):
        errors.append("快照缺少 main_graph")
        return errors

    nodes = graph.get("nodes")
    edges = graph.get("edges")
    connections = graph.get("connections")
    if not isinstance(nodes, list):
        errors.append("主管圖缺少 nodes")
        nodes = []
    if not isinstance(edges, list):
        errors.append("主管圖缺少 edges")
        edges = []
    if not isinstance(connections, list):
        errors.append("主管圖缺少 connections")
        connections = []

    node_ids = [node.get("node_id") for node in nodes if isinstance(node, Mapping)]
    if len(node_ids) != len(set(node_ids)):
        errors.append("主管圖含重複 Connector 節點")
    node_set = set(node_ids)
    for index, edge in enumerate(edges):
        if not isinstance(edge, Mapping):
            errors.append(f"主管圖第 {index + 1} 段不是物件")
            continue
        for field in ("start_node", "end_node"):
            if edge.get(field) not in node_set:
                errors.append(f"主管圖第 {index + 1} 段引用不存在的 {field}")
    for index, connection in enumerate(connections):
        if not isinstance(connection, Mapping):
            errors.append(f"主管圖第 {index + 1} 個連接不是物件")
            continue
        for field in ("from_node", "to_node"):
            if connection.get(field) not in node_set:
                errors.append(f"主管圖第 {index + 1} 個連接引用不存在的 {field}")
        if connection.get("connected") is not True:
            errors.append(f"主管圖第 {index + 1} 個連接未標記為實際連通")

    return errors
