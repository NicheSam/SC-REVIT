"""Action names shared by Python clients and the Revit add-in.

Keep this list as the v0.3 routing contract.  The current C# implementation still
handles these actions inside RfaMetadataApplication.cs, but future C# handler
classes should keep the same names for backward compatibility.
"""

FAMILY_LIBRARY_ACTIONS = {
    "scan_project_families",
    "export_project_families",
    "add_missing_string_parameters",
    "set_string_parameter_values",
}

CAD_POINTS_ACTIONS = {
    "list_point_placement_context",
    "get_cad_import_path",
    "list_cad_block_names",
    "scan_cad_block_points",
    "transform_dwg_block_points",
    "clear_dwg_preview_markers",
    "create_dwg_preview_markers",
    "place_cad_block_points",
    "place_dwg_block_points",
}

FIRE_BRANCH_ACTIONS = {
    "list_fire_branch_context",
    "read_fire_branch_selection",
    "read_fire_branch_snapshot",
    "create_fire_branch_preview",
    "create_fire_branch_pipes",
}

OPENING_ACTIONS = {
    "list_opening_context",
    "scan_opening_candidates",
    "view_opening_candidate",
    "place_opening_markers",
}

BACKSTAGE_ACTIONS = {
    "sync_tracked_elements",
    "delete_tracked_elements",
}

DRAINAGE_ACTIONS = {
    "list_drainage_context",
    "read_drainage_selection",
    "create_drainage_preview",
    "confirm_drainage_snapshot",
    "clear_drainage_preview",
    "create_drainage_pipes",
    "validate_drainage_result",
    "get_drainage_operation",
}

MEP_TOOLS_ACTIONS = {
    "inspect_selected_elements",
    "scan_sc_parameters",
    "diagnose_mep_connectors",
    "connect_pipe_fittings",
    "preview_piping_support_points",
}

ALL_ACTIONS = (
    FAMILY_LIBRARY_ACTIONS
    | CAD_POINTS_ACTIONS
    | FIRE_BRANCH_ACTIONS
    | DRAINAGE_ACTIONS
    | OPENING_ACTIONS
    | BACKSTAGE_ACTIONS
    | MEP_TOOLS_ACTIONS
)
