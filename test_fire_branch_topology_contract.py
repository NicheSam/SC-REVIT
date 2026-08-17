import hashlib
import unittest
from pathlib import Path

from sc_revit.core.revit_queue_client import _format_revit_error


ROOT = Path(__file__).resolve().parent
FIRE_BRANCH_SOURCE = ROOT / "revit_addin" / "src" / "Handlers" / "FireBranchHandler.cs"
APPLICATION_SOURCE = ROOT / "revit_addin" / "src" / "RfaMetadataApplication.cs"
GUI_SOURCE = ROOT / "gui_app.py"
QUEUE_CLIENT_SOURCE = ROOT / "sc_revit" / "core" / "revit_queue_client.py"


def method_body(source: str, method_name: str, next_method_name: str) -> str:
    start = source.index(method_name)
    end = source.index(next_method_name, start)
    return source[start:end]


class FireBranchTopologyContractTests(unittest.TestCase):
    def test_tee_endpoint_fallback_accepts_pipe_endpoints(self) -> None:
        source = (ROOT / "revit_addin" / "src" / "RfaMetadataApplication.cs").read_text(
            encoding="utf-8"
        )
        start = source.index("private static bool TryCreateTeeAtPoint")
        end = source.index("private static bool TryCreateElbowAtPipeEnd", start)
        method = source[start:end]

        self.assertIn(
            "pipe => IsPointOnPipeXYIncludingEnds(pipe, tiePoint, tolerance)",
            method,
        )

    def test_junction_planner_distinguishes_current_and_future_topologies(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        for topology in (
            "SingleSideSameElevation",
            "OppositeSidesSameElevation",
            "SingleSideOffsetElevation",
            "OppositeSidesOffsetElevation",
            "Complex",
        ):
            self.assertIn(topology, source)

        self.assertIn("BuildFireBranchJunctionPlans(rows, junctionTolerance, branchZ)", source)
        self.assertIn("ConvertToInternalUnits(5, UnitTypeId.Millimeters)", source)

    def test_opposite_side_rows_share_one_station_and_create_one_cross(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        self.assertIn("double rowMain = isOppositeSideCross", source)
        self.assertIn("? junctionPlan.MainParameter", source)
        self.assertIn("crossBranchSegmentsByPlan", source)
        self.assertIn("crossBranchRuns.Count != 2", source)
        self.assertIn("FindPipeEndingAtPoint(crossBranchRuns[0], crossTie", source)
        self.assertIn("FindPipeEndingAtPoint(crossBranchRuns[1], crossTie", source)
        self.assertIn("TryCreateCrossAtPipeEnds(", source)
        self.assertIn("opposite_side_cross_creation_failed", source)

        row_completion = source.index("branchSegmentsByRow[diameterPlanRowIndex] = branchSegments;")
        deferred_cross = source.index("foreach (FireBranchJunctionPlan crossPlan")
        self.assertGreater(deferred_cross, row_completion)
        cross_loop = source[deferred_cross:source.index("{", deferred_cross)]
        self.assertIn("OrderBy(plan => plan.MainPipeId)", cross_loop)
        self.assertIn("ThenBy(plan => plan.MainParameter)", cross_loop)

    def test_cross_uses_prepared_equal_diameter_ends_and_plain_cross(self):
        source = APPLICATION_SOURCE.read_text(encoding="utf-8")
        endpoint_cross = method_body(
            source,
            "private static bool TryCreateCrossAtPipeEnds",
            "private static bool TryConnectPipeToRun",
        )

        self.assertNotIn("TryPrepareCrossBranchEnd", endpoint_cross)
        self.assertNotIn("TrySetPipeDiameter", endpoint_cross)
        self.assertNotIn("NewTransitionFitting", endpoint_cross)
        self.assertIn("Connector sideA = FindConnectorNear(refreshedBranchA, tiePoint)", endpoint_cross)
        self.assertIn("Connector sideB = FindConnectorNear(refreshedBranchB, tiePoint)", endpoint_cross)
        self.assertIn("Cross inputs do not match the topology plan", endpoint_cross)
        self.assertIn("FamilyInstance fitting = TryNewPlannedCrossFitting(", endpoint_cross)
        self.assertNotIn("TryNewReducingCrossFitting(", endpoint_cross)

    def test_planned_cross_uses_exact_plan_point_and_diameters(self):
        handler = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")
        application = APPLICATION_SOURCE.read_text(encoding="utf-8")
        endpoint_cross = method_body(
            application,
            "private static bool TryCreateCrossAtPipeEnds",
            "private static bool TryConnectPipeToRun",
        )

        self.assertIn("public XYZ Point { get; set; }", handler)
        self.assertIn("executionCross.Point", handler)
        self.assertIn("executionCrossByRowIndex", handler)
        row_geometry = handler[
            handler.index("for (int fireBranchRowIndex"):
            handler.index("foreach (var item in row)", handler.index("for (int fireBranchRowIndex"))
        ]
        self.assertIn("executionRowCross.Point", row_geometry)
        self.assertLess(
            row_geometry.index("executionRowCross.Point"),
            row_geometry.index("XYZ branchStart"),
        )
        self.assertIn("expectedMainDiameterFeet", endpoint_cross)
        self.assertIn("expectedBranchDiameterFeet", endpoint_cross)
        self.assertIn("Cross inputs do not match the topology plan", endpoint_cross)

    def test_planned_cross_is_created_before_external_branch_transitions(self):
        handler = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")
        cross_loop = handler[
            handler.index("foreach (FireBranchJunctionPlan crossPlan"):
            handler.index("foreach (FireBranchJunctionPlan crossPlan", handler.index("foreach (FireBranchJunctionPlan crossPlan") + 1)
        ]

        self.assertIn("FirePendingCrossTransition", handler)
        self.assertIn("CompletePlannedCrossTransition", cross_loop)
        self.assertGreater(
            cross_loop.index("CompletePlannedCrossTransition"),
            cross_loop.index("TryCreateCrossAtPipeEnds("),
        )

    def test_cross_reducer_distance_is_resolved_from_live_routing_parts(self):
        handler = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")
        preparation = method_body(
            handler,
            "private static ElementId PreparePlannedCrossBranchEnd",
            "private static bool CompletePlannedCrossTransition",
        )
        completion = method_body(
            handler,
            "private static bool CompletePlannedCrossTransition",
            "private static List<long> FindFireBranchDiameterPlanMismatches",
        )

        self.assertNotIn("reducerOffsetFeet", preparation)
        self.assertNotIn("PlumbingUtils.BreakCurve", preparation)
        self.assertIn("CrossFittingId", completion)
        self.assertIn("TryCommitNearestFeasibleCrossTransition", completion)
        self.assertIn("Application.ShortCurveTolerance", completion)
        self.assertIn("SubTransaction", completion)
        self.assertIn("provisionalTransitionLength", completion)
        self.assertIn("additionalCreatedIds.Add(proximalPipeId)", completion)
        self.assertNotIn("ReducerOffsetFeetByRow", handler)

    def test_planned_cross_does_not_guess_connector_permutations(self):
        source = APPLICATION_SOURCE.read_text(encoding="utf-8")
        endpoint_cross = method_body(
            source,
            "private static bool TryCreateCrossAtPipeEnds",
            "private static bool TryConnectPipeToRun",
        )

        self.assertIn("TryNewPlannedCrossFitting", endpoint_cross)
        planned_helper = method_body(
            source,
            "private static FamilyInstance TryNewPlannedCrossFitting",
            "private static bool ConnectorDirectlyReferencesElement",
        )
        self.assertEqual(1, planned_helper.count("NewCrossFitting("))
        self.assertNotIn("Connector[][] orders", planned_helper)

    def test_cross_helper_preserves_the_two_collinear_connector_pairs(self):
        source = APPLICATION_SOURCE.read_text(encoding="utf-8")
        endpoint_cross = method_body(
            source,
            "private static bool TryCreateCrossAtPipeEnds",
            "private static bool TryConnectPipeToRun",
        )

        self.assertNotIn("sideA.Radius > sideB.Radius", endpoint_cross)
        self.assertNotIn("Connector swap = sideA", endpoint_cross)
        cross_helper = method_body(
            source,
            "private static FamilyInstance TryNewCrossFitting",
            "private static bool TryCreateCrossAtPoint",
        )
        self.assertIn("new Connector[] { a, b, c, d }", cross_helper)
        self.assertIn("new Connector[] { b, a, c, d }", cross_helper)
        self.assertIn("new Connector[] { a, b, d, c }", cross_helper)
        self.assertIn("new Connector[] { b, a, d, c }", cross_helper)
        self.assertNotIn("new Connector[] { a, c, b, d }", cross_helper)
        self.assertNotIn("new Connector[] { a, d, b, c }", cross_helper)

    def test_preview_and_revit_share_one_hashed_topology_plan(self):
        gui = GUI_SOURCE.read_text(encoding="utf-8")
        handler = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        self.assertIn("build_fire_branch_execution_plan(", gui)
        self.assertIn('topology_plan=topology_plan', gui)
        self.assertIn('model_plan_hash=model_plan_hash', gui)
        self.assertIn("ReadFireBranchTopologyPlan(payload)", handler)
        self.assertIn("executionCrossPlans", handler)
        self.assertIn("PreparePlannedCrossBranchEnd(", handler)
        self.assertLess(
            handler.index("PreparePlannedCrossBranchEnd(", handler.index("foreach (FireBranchJunctionPlan crossPlan")),
            handler.index("TryCreateCrossAtPipeEnds(", handler.index("foreach (FireBranchJunctionPlan crossPlan")),
        )

    def test_planned_cross_reacquires_pipe_references_after_revit_mutations(self):
        handler = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")
        preparation = method_body(
            handler,
            "private static ElementId PreparePlannedCrossBranchEnd",
            "private static bool CompletePlannedCrossTransition",
        )
        completion = method_body(
            handler,
            "private static bool CompletePlannedCrossTransition",
            "private static List<long> FindFireBranchDiameterPlanMismatches",
        )
        cross_loop = handler[
            handler.index("foreach (FireBranchJunctionPlan crossPlan"):
            handler.index("foreach (FireBranchJunctionPlan crossPlan", handler.index("foreach (FireBranchJunctionPlan crossPlan") + 1)
        ]

        self.assertIn("ElementId originalPipeId = current.Id", preparation)
        self.assertNotIn("PlumbingUtils.BreakCurve", preparation)
        self.assertNotIn("NewTransitionFitting", preparation)
        self.assertIn("doc.GetElement(pendingTransition.BranchPipeId) as Pipe", completion)
        self.assertIn("PlumbingUtils.BreakCurve", completion)
        self.assertIn("doc.GetElement(originalPipeId) as Pipe", completion)
        self.assertIn("doc.GetElement(newPipeId) as Pipe", completion)
        self.assertIn("NewTransitionFitting", completion)
        self.assertIn(
            "FindConnectorDirectlyReferencingElement(\n                        refreshedProximal,\n                        transitionId)",
            completion,
        )
        self.assertIn(
            "FindConnectorDirectlyReferencingElement(\n                        refreshedDistal,\n                        transitionId)",
            completion,
        )
        self.assertIn("ElementId crossBranchAId = PreparePlannedCrossBranchEnd", cross_loop)
        self.assertIn("ElementId crossBranchBId = PreparePlannedCrossBranchEnd", cross_loop)
        self.assertIn("doc.GetElement(crossBranchAId) as Pipe", cross_loop)
        self.assertIn("doc.GetElement(crossBranchBId) as Pipe", cross_loop)

    def test_cross_reacquires_main_pipe_after_break_curve(self):
        source = APPLICATION_SOURCE.read_text(encoding="utf-8")
        endpoint_cross = method_body(
            source,
            "private static bool TryCreateCrossAtPipeEnds",
            "private static bool TryConnectPipeToRun",
        )

        self.assertIn("ElementId mainTargetId = mainTarget.Id", endpoint_cross)
        self.assertIn("doc.GetElement(mainTargetId) as Pipe", endpoint_cross)
        self.assertGreater(
            endpoint_cross.index("doc.GetElement(mainTargetId) as Pipe"),
            endpoint_cross.index("PlumbingUtils.BreakCurve"),
        )
        self.assertIn(
            "Connector mainA = FindConnectorNear(refreshedMainTarget, tiePoint)",
            endpoint_cross,
        )
        self.assertNotIn(
            "Connector mainA = FindConnectorNear(mainTarget, tiePoint)",
            endpoint_cross,
        )

    def test_cross_reacquires_all_inputs_after_revit_connection_changes(self):
        source = APPLICATION_SOURCE.read_text(encoding="utf-8")
        endpoint_cross = method_body(
            source,
            "private static bool TryCreateCrossAtPipeEnds",
            "private static bool TryConnectPipeToRun",
        )

        self.assertIn("ElementId branchAId = branchA.Id", endpoint_cross)
        self.assertIn("ElementId branchBId = branchB.Id", endpoint_cross)
        self.assertIn("doc.GetElement(branchAId) as Pipe", endpoint_cross)
        self.assertIn("doc.GetElement(branchBId) as Pipe", endpoint_cross)
        self.assertIn("ElementId fittingId = fitting.Id", endpoint_cross)
        self.assertGreater(
            endpoint_cross.rindex("doc.GetElement(mainTargetId) as Pipe"),
            endpoint_cross.index("ElementId fittingId = fitting.Id"),
        )
        self.assertGreater(
            endpoint_cross.rindex("doc.GetElement(branchAId) as Pipe"),
            endpoint_cross.index("ElementId fittingId = fitting.Id"),
        )
        self.assertIn("ConnectorDirectlyReferencesElement(connector, fittingId)", endpoint_cross)
        self.assertIn('"TryCreateCrossAtPipeEnds | stage=" + stage', endpoint_cross)

    def test_cross_accepts_a_short_fitting_only_path_to_the_planned_cross(self):
        application = APPLICATION_SOURCE.read_text(encoding="utf-8")
        handler = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")
        endpoint_cross = method_body(
            application,
            "private static bool TryCreateCrossAtPipeEnds",
            "private static bool TryFindPipeFittingPathToTarget",
        )

        self.assertIn("ElementId fittingId = fitting.Id", endpoint_cross)
        self.assertIn("additionalCreatedIds.Add(fittingId)", endpoint_cross)
        self.assertIn("TryFindPipeFittingPathToTarget", endpoint_cross)
        self.assertIn("additionalCreatedIds.Add(intermediateId)", endpoint_cross)
        self.assertNotIn("direct planned cross connector verification failed", endpoint_cross)
        self.assertIn("additionalCreatedIds", handler[handler.index("TryCreateCrossAtPipeEnds("):])

    def test_cross_routing_preflight_uses_all_four_planned_diameters(self):
        handler = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")
        routing = method_body(
            handler,
            "private static void ValidateFireBranchJunctionRouting",
            "private static bool TryConnectCompletedDropToSprinkler",
        )

        self.assertIn("RoutingPreferenceRuleGroupType.Crosses", routing)
        self.assertIn("new RoutingCondition(junction.MainDiameterFeet)", routing)
        self.assertGreaterEqual(
            routing.count("new RoutingCondition(junction.CommonBranchDiameterFeet)"),
            2,
        )
        self.assertIn("manager.GetMEPPartId(", routing)
        self.assertIn("RoutingPreferenceRuleGroupType.Transitions", routing)
        self.assertIn("junction.CommonBranchDiameterFeet", routing)
        self.assertIn("sourceDiameterFeet", routing)
        self.assertIn("GroupBy(item => item.RowIndex)", routing)
        self.assertIn("OrderBy(item => item.Sequence)", routing)
        self.assertIn("sprinklerDropFeet", routing)
        self.assertIn("connector.Radius * 2.0", routing)

    def test_confirmed_successful_drop_path_is_frozen_while_cross_is_reworked(self):
        handler = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")
        connect = method_body(
            handler,
            "private static bool TryConnectCompletedDropToSprinkler",
            "private static FireDropAssembly CreateFireDropWithTransition",
        ).replace("\r\n", "\n")
        create = method_body(
            handler,
            "private static FireDropAssembly CreateFireDropWithTransition",
            "private static List<ElementId> ResolveConnectedFireSystemIds",
        ).replace("\r\n", "\n")

        self.assertEqual(
            "706ade85816e82313e19f0072c1951db73fa35f359da6ef248a7571e0d2d1021",
            hashlib.sha256(connect.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            "ff515f9506352f6141b3b39d797ca4db4cbe69c2a1f9149bd36520c66ecf76fe",
            hashlib.sha256(create.encode("utf-8")).hexdigest(),
        )

    def test_failed_fitting_creation_rolls_back_pipe_breaks(self):
        source = APPLICATION_SOURCE.read_text(encoding="utf-8")
        tee = method_body(source, "private static bool TryCreateTeeAtPoint", "private static bool TryCreateElbowAtPipeEnd")
        interior_cross = method_body(source, "private static bool TryCreateCrossAtPoint", "private static bool TryCreateCrossAtPipeEnds")
        endpoint_cross = method_body(source, "private static bool TryCreateCrossAtPipeEnds", "private static bool TryConnectPipeToRun")

        for body in (tee, interior_cross, endpoint_cross):
            self.assertIn("using (SubTransaction", body)
            self.assertIn("subTransaction.RollBack()", body)
            self.assertIn("subTransaction.Commit()", body)

    def test_run_endpoint_is_not_forced_through_break_curve(self):
        source = APPLICATION_SOURCE.read_text(encoding="utf-8")
        tee = method_body(source, "private static bool TryCreateTeeAtPoint", "private static bool TryCreateElbowAtPipeEnd")

        self.assertIn("!IsPointAtPipeEnd(pipe, tiePoint, tolerance)", tee)
        self.assertIn("runConnector.AllRefs", tee)
        self.assertIn("runConnector.DisconnectFrom(adjacentConnector)", tee)
        self.assertIn("NewElbowFitting", tee)
        self.assertLess(tee.index("if (IsPointAtPipeEnd(target"), tee.index("PlumbingUtils.BreakCurve"))

    def test_same_elevation_sprinklers_are_connected_to_the_branch_run(self):
        handler = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")
        application = APPLICATION_SOURCE.read_text(encoding="utf-8")

        self.assertIn("tapPoint.DistanceTo(sprinklerPoint) < 0.01", handler)
        self.assertIn("TryConnectSprinklerToRun(", handler)
        self.assertIn("same_elevation_sprinkler_connection_failed", handler)
        self.assertIn("private static bool TryConnectSprinklerToRun", application)
        self.assertIn("PlumbingUtils.BreakCurve", application)
        self.assertIn("TryNewTeeFitting", application)

    def test_offset_opposite_rows_use_a_shared_feeder_and_branch_tee(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        self.assertIn("offsetFeedersByPlan", source)
        self.assertIn("offsetBranchesByPlan", source)
        self.assertIn("isOppositeSideCross || isOppositeSideOffset", source)
        self.assertIn("TryCreateTeeAtPipeEnds(", source)
        self.assertIn("shared_feeder_to_opposite_branches_connection_failed", source)

    def test_create_requires_connector_readback_and_user_decides_local_failure_retention(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        self.assertIn("connector_verification_failed", source)
        self.assertIn("createdPipeRoles", source)
        self.assertIn("missingCreatedPipeIds", source)
        self.assertIn("unreachableSprinklerIds", source)
        self.assertIn("IsPhysicallyReachableFromFireElement", source)
        self.assertIn("owner is MEPSystem", source)
        self.assertIn("ConnectorType.Logical", source)
        self.assertIn("transactionGroup.RollBack()", source)
        self.assertIn('fireBranchStage = "partial_failure_decision"', source)
        self.assertIn("TaskDialogResult.CommandLink1", source)
        self.assertIn('verification_status = partialFailureKept ? "partial" : "verified"', source)
        self.assertIn("connected_sprinkler_count = verifiedConnectedSprinklerCount", source)

    def test_connector_verification_excludes_intentionally_skipped_sprinklers(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        self.assertIn("List<FamilyInstance> plannedSprinklers = sprinklerData", source)
        self.assertIn("var unconnectedSprinklerIds = plannedSprinklers", source)
        self.assertNotIn("var unconnectedSprinklerIds = sprinklers", source)

    def test_branch_setting_controls_created_pipes_and_connected_sprinklers(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")
        application = APPLICATION_SOURCE.read_text(encoding="utf-8")

        self.assertIn("TryConnectCompletedDropToSprinkler", source)
        self.assertIn("SprinklerConnectionPipe", source)
        self.assertIn("sprinklerConnector.Radius * 2.0", source)
        self.assertIn("NewTransitionFitting(dropConnector, stubConnector)", source)
        self.assertNotIn('"drop_connector_bridge"', source)
        self.assertNotIn("maximumRepairGap", source)
        self.assertLess(
            source.index("foreach (ElementId additionalId in additionalCreatedIds"),
            source.index("foreach (FirePendingSprinklerConnection pending"),
        )
        self.assertIn("CreateFirePipeFromConnector(", source)
        self.assertNotIn("dropConnector.ConnectTo(sprinklerConnector)", source)
        self.assertNotIn("targetPipingSystem.Add(sprinklerConnectorSet)", source)
        self.assertIn("private static Pipe CreateFirePipeFromConnector(", application)
        self.assertIn("ResolveConnectedFireSystemIds(", source)
        self.assertNotIn("mainPipes.Select(item => item.Pipe.MEPSystem)", source)
        self.assertIn("foreach (ElementId connectedSystemId in connectedSystemIds.ToList())", source)
        self.assertIn("connectedSystem.ChangeTypeId(systemType.Id)", source)
        self.assertIn('reason = "system_type_verification_failed"', source)
        self.assertIn("wrong_system_pipe_ids = wrongSystemPipeIds", source)
        self.assertIn("wrong_system_sprinkler_ids = wrongSystemSprinklerIds", source)
        self.assertIn("verified_system_type_id = systemType.Id.Value", source)
        self.assertIn("pipe != null && pipe.IsValidObject && IsScFireBranchPipe(pipe)", source)
        self.assertNotIn('reason = "existing_main_system_changed"', source)

    def test_each_sprinkler_drop_is_isolated_before_the_next_drop_starts(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")
        drop_loop = method_body(
            source,
            "foreach (var item in row)",
            "foreach (FireBranchJunctionPlan crossPlan",
        )

        self.assertIn("using (SubTransaction dropTransaction", drop_loop)
        self.assertIn("dropTransaction.Start()", drop_loop)
        self.assertIn("dropTransaction.Commit()", drop_loop)
        self.assertIn("dropTransaction.RollBack()", drop_loop)

    def test_system_verification_runs_after_committed_transactions_inside_atomic_group(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        group_start = source.index("using (TransactionGroup transactionGroup")
        creation_commit = source.index("creationTransaction.Commit()", group_start)
        system_commit = source.index("systemTransaction.Commit()", creation_commit)
        verification = source.index("List<long> wrongSystemPipeIds", system_commit)
        assimilate = source.index("transactionGroup.Assimilate()", verification)

        self.assertLess(group_start, creation_commit)
        self.assertLess(creation_commit, system_commit)
        self.assertLess(system_commit, verification)
        self.assertLess(verification, assimilate)
        self.assertIn("transactionGroup.RollBack()", source)
        self.assertIn("missing_system_pipe_ids", source)
        self.assertIn("missing_connector_sprinkler_ids", source)
        self.assertIn("missing_system_sprinkler_ids", source)

    def test_branch_setting_changes_each_connected_mep_system_with_diagnostics(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        self.assertIn("List<ElementId> connectedSystemIds", source)
        self.assertIn("ResolveConnectedFireSystemIds(", source)
        self.assertIn("foreach (ElementId connectedSystemId in connectedSystemIds.ToList())", source)
        self.assertIn("connectedSystem.ChangeTypeId(systemType.Id)", source)
        self.assertIn("system_change_failures = systemChangeFailures", source)
        self.assertIn("actual_system_type_ids = actualSystemTypeIds", source)

    def test_system_type_change_never_reuses_a_possibly_invalid_system_wrapper(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")
        change_loop = method_body(
            source,
            "foreach (ElementId connectedSystemId in connectedSystemIds.ToList())",
            "List<long> actualSystemTypeIds",
        )

        self.assertIn("doc.GetElement(connectedSystemId) as MEPSystem", change_loop)
        self.assertIn("ElementId replacementSystemId = connectedSystem.ChangeTypeId", change_loop)
        self.assertNotIn("connectedSystem.Id.Value", change_loop)
        self.assertNotIn("connectedSystem.GetTypeId()", change_loop.split("ChangeTypeId", 1)[1])

    def test_unexpected_revit_lifecycle_errors_report_the_failed_stage(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        for stage in (
            "geometry_creation",
            "connected_system_discovery",
            "system_type_change",
            "system_and_connector_verification",
            "sandbox_restore",
        ):
            self.assertIn(f'fireBranchStage = "{stage}"', source)
        self.assertIn('"Fire branch failed at " + fireBranchStage', source)

    def test_connector_failures_are_persisted_with_revit_details(self):
        handler = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")
        application = APPLICATION_SOURCE.read_text(encoding="utf-8")
        queue_client = QUEUE_CLIENT_SOURCE.read_text(encoding="utf-8")

        self.assertIn("FireBranchConnectorVerificationException", handler)
        self.assertIn("detail = ReadFireBranchConnectionDiagnostic()", handler)
        self.assertIn("failure_details = fireBranchException.FailureDetails", application)
        self.assertIn('payload.get("failure_details")', queue_client)
        self.assertIn('item.get("unconnected_sprinkler_ids")', queue_client)
        self.assertIn('item.get("unconnected_pipe_ids")', queue_client)
        self.assertIn('item.get("missing_created_pipe_ids")', queue_client)
        self.assertIn('item.get("unreachable_sprinkler_ids")', queue_client)
        self.assertIn('item.get("wrong_system_sprinkler_ids")', queue_client)
        self.assertIn('item.get("wrong_system_pipe_ids")', queue_client)
        self.assertIn('item.get("missing_system_pipe_ids")', queue_client)
        self.assertIn('item.get("missing_connector_sprinkler_ids")', queue_client)
        self.assertIn('item.get("missing_system_sprinkler_ids")', queue_client)
        self.assertIn('item.get("actual_system_type_ids")', queue_client)
        self.assertIn('item.get("system_change_failures")', queue_client)

    def test_drop_transition_spool_survives_tee_and_has_real_connections(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")

        self.assertIn(
            "UnitUtils.ConvertToInternalUnits(100, UnitTypeId.Millimeters)",
            source,
        )
        self.assertIn("branchDiameterFeet * 3.0", source)
        self.assertIn("currentBranchConnection", source)
        self.assertIn("branchConnectionConnectors.Any(connector => !connector.IsConnected)", source)

    def test_sprinkler_connection_uses_bidirectional_physical_references(self):
        source = FIRE_BRANCH_SOURCE.read_text(encoding="utf-8")
        verification = method_body(
            source,
            "private static bool TryConnectCompletedDropToSprinkler",
            "private static FireDropAssembly CreateFireDropWithTransition",
        )

        self.assertIn("dropReferencesSprinkler", verification)
        self.assertIn("sprinklerReferencesDrop", verification)
        self.assertIn("reference.ConnectorType != ConnectorType.Logical", verification)
        self.assertIn("endpoint_distance_mm=", verification)
        self.assertNotIn("IsConnectedTo(sprinklerConnector)", verification)

    def test_queue_error_distinguishes_missing_and_wrong_system_state(self):
        message = _format_revit_error(
            {
                "error": "verification failed",
                "failure_details": [
                    {
                        "sprinkler_id": "-",
                        "reason": "system_type_verification_failed",
                        "missing_system_pipe_ids": [101],
                        "wrong_system_pipe_ids": [102],
                        "missing_connector_sprinkler_ids": [201],
                        "missing_system_sprinkler_ids": [202],
                        "wrong_system_sprinkler_ids": [203],
                        "actual_system_type_ids": [301],
                        "system_change_failures": [
                            {
                                "system_id": 401,
                                "reason": "target_system_type_not_assignable",
                            }
                        ],
                    }
                ],
            },
            "fallback",
        )

        self.assertIn("missing-system pipes=101", message)
        self.assertIn("wrong-system pipes=102", message)
        self.assertIn("missing-connector sprinklers=201", message)
        self.assertIn("missing-system sprinklers=202", message)
        self.assertIn("wrong-system sprinklers=203", message)
        self.assertIn("actual system types=301", message)
        self.assertIn("system-change failures=", message)
        self.assertIn("target_system_type_not_assignable", message)

    def test_queue_error_leads_with_plain_chinese_and_keeps_technical_code(self):
        message = _format_revit_error(
            {
                "error": "Fire branch connector verification failed.",
                "failure_details": [
                    {
                        "row": 75.215,
                        "reason": "opposite_side_cross_creation_failed",
                        "detail": (
                            "TryCreateCrossAtPipeEnds | "
                            "tie point is not valid on all four runs"
                        ),
                    },
                    {
                        "reason": "connector_verification_failed",
                        "unreachable_sprinkler_ids": [101, 102, 103],
                    },
                ],
            },
            "Revit 請求失敗",
        )

        self.assertIn("消防支管建立未完成", message)
        self.assertIn("四通建立失敗", message)
        self.assertIn("交點位於主管端點", message)
        self.assertIn("無法由主管到達：3 顆", message)
        self.assertIn("技術代碼：opposite_side_cross_creation_failed", message)
        self.assertNotIn("Connection failure details", message)

    def test_connector_verification_explains_result_inference_and_missing_root_cause(self):
        affected_ids = list(range(101, 119))
        message = _format_revit_error(
            {
                "error": (
                    "Fire branch connector verification failed. "
                    "No branch elements were committed."
                ),
                "failure_details": [
                    {
                        "reason": "connector_verification_failed",
                        "unconnected_sprinkler_ids": [],
                        "unconnected_pipe_ids": [],
                        "missing_created_pipe_ids": [],
                        "unreachable_sprinkler_ids": affected_ids,
                    }
                ],
            },
            "Revit 請求失敗",
        )

        self.assertIn("這是最終連通驗證結果，不是第一個失敗原因", message)
        self.assertIn("灑水頭接頭直接斷線：0 顆", message)
        self.assertIn("新建管線遺失：0 段", message)
        self.assertIn("無法由主管到達：18 顆", message)
        self.assertIn("共用上游接點", message)
        self.assertIn("四通、三通或異徑接頭", message)
        self.assertIn("本次回傳沒有記錄第一個失敗節點", message)
        self.assertIn("受影響灑水頭 ElementId（18 顆）", message)
        self.assertIn("101", message)
        self.assertIn("118", message)
        self.assertIn("本次失敗後已整批復原", message)

    def test_queue_fatal_fire_branch_error_still_leads_with_chinese(self):
        message = _format_revit_error(
            {"error": "Fire branch failed at geometry_creation: invalid object"},
            "Revit 請求失敗",
        )

        self.assertIn("消防支管建立失敗", message)
        self.assertIn("技術資訊：Fire branch failed", message)

    def test_gui_synchronizes_level_to_selected_main_pipe(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn('level_id = str(self.fire_main_pipe.get("level_id") or "")', source)
        self.assertIn("self.fire_level_var.set(name)", source)


if __name__ == "__main__":
    unittest.main()
