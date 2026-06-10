"""Backward-compatible client exports for CAD point placement and fire branch tools.

New code should import from:
- sc_revit.cad_points
- sc_revit.fire_branch
"""

from sc_revit.cad_points.client import (
    request_cad_block_names,
    request_cad_block_preview,
    request_create_dwg_preview_markers,
    request_place_cad_blocks,
    request_place_dwg_blocks,
    request_point_placement_context,
    request_transform_dwg_points,
)
from sc_revit.fire_branch.client import (
    request_create_fire_branch_pipes,
    request_create_fire_branch_preview,
    request_fire_branch_context,
    request_fire_branch_selection,
)

__all__ = [
    "request_point_placement_context",
    "request_cad_block_preview",
    "request_cad_block_names",
    "request_place_cad_blocks",
    "request_transform_dwg_points",
    "request_place_dwg_blocks",
    "request_create_dwg_preview_markers",
    "request_fire_branch_context",
    "request_fire_branch_selection",
    "request_create_fire_branch_pipes",
    "request_create_fire_branch_preview",
]
