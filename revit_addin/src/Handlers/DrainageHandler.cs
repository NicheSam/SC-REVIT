using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.DB.Structure;
using Autodesk.Revit.UI;
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using RfaMetadataAddin.Drainage;

namespace RfaMetadataAddin
{
    public partial class RfaMetadataApplication
    {
        private static readonly HashSet<string> DrainageActions = new HashSet<string>(StringComparer.Ordinal)
        {
            "list_drainage_context",
            "read_drainage_selection",
            "search_drainage_targets",
            "create_drainage_preview",
            "confirm_drainage_snapshot",
            "clear_drainage_preview",
            "create_drainage_pipes",
            "validate_drainage_result",
            "get_drainage_operation"
        };

        private const string ScDrainageCommentPrefix = "SC_DRAINAGE:";

        private class DrainagePlan
        {
            public Element SourceElement { get; set; }
            public Connector FixtureConnector { get; set; }
            public XYZ ConnectorPoint { get; set; }
            public XYZ ConnectorStubEnd { get; set; }
            public bool HasConnectorStub { get; set; }
            public bool HasDoubleFortyFive { get; set; }
            public XYZ BranchStart { get; set; }
            public XYZ MainTie { get; set; }
            public double HorizontalLength { get; set; }
            public double VerticalDrop { get; set; }
            public double SlopeRatio { get; set; }
            public XYZ ConnectorAxis { get; set; }
            public string OutletOrientation { get; set; }
            public string RouteKind { get; set; }
            public int DownstreamEndpointIndex { get; set; }
            public XYZ DownstreamPoint { get; set; }
            public string DownstreamResolution { get; set; }
            public double SideEntryAngleDegrees { get; set; }
            public double RadialEntryAngleDegrees { get; set; }
            public double? StubTangentLength { get; set; }
            public double? MiddleTangentLength { get; set; }
            public double? BranchTangentLength { get; set; }
            public double FirstElbowAngleDegrees { get; set; }
            public double SecondElbowAngleDegrees { get; set; }
            public double MiddleLateralOffset { get; set; }
            public int SequenceIndex { get; set; }
            public List<long> CollisionElementIds { get; set; }
            public List<string> Issues { get; set; }
            public bool ReadyToCreate { get { return Issues != null && Issues.Count == 0; } }
        }

        private class DrainageRoutingPart
        {
            public ElementId PartId { get; set; }
            public string PartUniqueId { get; set; }
            public string Name { get; set; }
            public string FamilyName { get; set; }
            public int RuleOrder { get; set; }
            public double? MeasuredTakeoutMm { get; set; }
            public double? MeasuredRunTakeoutMm { get; set; }
            public long? TakeoutEvidenceElementId { get; set; }
            public string TakeoutEvidenceKind { get; set; }
            public string TakeoutGeometryHash { get; set; }
        }

        private class DrainageRoutePolicy
        {
            public string PolicyId { get; set; }
            public string PolicyVersion { get; set; }
            public double SideEntryAngleDegrees { get; set; }
            public double SideEntryToleranceDegrees { get; set; }
            public double RadialMinimumDegrees { get; set; }
            public double RadialMaximumDegrees { get; set; }
            public double RadialToleranceDegrees { get; set; }
            public double MinimumTangentMm { get; set; }
            public double MinimumJunctionSpacingMm { get; set; }
            public double CollisionClearanceMm { get; set; }
            public double MaximumDouble45LateralOffsetMm { get; set; }
        }

        private class DrainageCreatedPipeCheck
        {
            public Pipe Pipe { get; set; }
            public XYZ Source { get; set; }
            public XYZ Sink { get; set; }
            public bool RequiresSignedSlope { get; set; }
            public bool RequiresDescending { get; set; }
            public double MinimumCenterlineLength { get; set; }
        }

        private static bool TryHandleDrainageAction(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            if (!DrainageActions.Contains(action))
            {
                return false;
            }

            HandleDrainageAction(uiApp, payload, action, responseFile, serializer);
            return true;
        }

        private static void HandleDrainageAction(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            Document doc = GetActiveProjectDocument(uiApp);

            if (action == "list_drainage_context")
            {
                var pipeTypes = new FilteredElementCollector(doc)
                    .OfClass(typeof(PipeType))
                    .Cast<PipeType>()
                    .OrderBy(item => item.Name)
                    .Select(item => new
                    {
                        element_id = item.Id.Value,
                        unique_id = item.UniqueId,
                        name = item.Name
                    })
                    .ToList();
                var systemTypes = new FilteredElementCollector(doc)
                    .OfClass(typeof(PipingSystemType))
                    .Cast<PipingSystemType>()
                    .OrderBy(item => item.Name)
                    .Select(item => new
                    {
                        element_id = item.Id.Value,
                        unique_id = item.UniqueId,
                        name = item.Name
                    })
                    .ToList();
                var levels = new FilteredElementCollector(doc)
                    .OfClass(typeof(Level))
                    .Cast<Level>()
                    .OrderBy(item => item.Elevation)
                    .Select(item => new
                    {
                        element_id = item.Id.Value,
                        unique_id = item.UniqueId,
                        name = item.Name,
                        elevation = item.Elevation
                    })
                    .ToList();
                File.WriteAllText(responseFile, serializer.Serialize(new
                {
                    action = action,
                    document = SerializeDrainageDocumentRef(doc),
                    default_slope_ratio = 0.01,
                    default_diameter_mm = 100,
                    default_route_policy = SerializeDrainageRoutePolicy(
                        CreateDefaultDrainageRoutePolicy(100)),
                    pipe_types = pipeTypes,
                    system_types = systemTypes,
                    levels = levels,
                    routing_profiles = new FilteredElementCollector(doc)
                        .OfClass(typeof(PipeType))
                        .Cast<PipeType>()
                        .OrderBy(item => item.Name)
                        .Select(item => new
                        {
                            pipe_type_id = item.Id.Value,
                            pipe_type_unique_id = item.UniqueId,
                            pipe_type_name = item.Name,
                            junctions = SerializeDrainageRoutingRules(
                                doc,
                                item,
                                RoutingPreferenceRuleGroupType.Junctions),
                            elbows = SerializeDrainageRoutingRules(
                                doc,
                                item,
                                RoutingPreferenceRuleGroupType.Elbows)
                        })
                        .ToList()
                }));
                return;
            }

            if (action == "read_drainage_selection")
            {
                ICollection<ElementId> selectedIds = uiApp.ActiveUIDocument.Selection.GetElementIds();
                List<Pipe> pipes = selectedIds.Select(id => doc.GetElement(id)).OfType<Pipe>().ToList();
                List<FamilyInstance> fixtures = selectedIds
                    .Select(id => doc.GetElement(id))
                    .OfType<FamilyInstance>()
                    .Where(IsPlumbingFixture)
                    .ToList();
                File.WriteAllText(responseFile, serializer.Serialize(new
                {
                    action = action,
                    document = SerializeDrainageDocumentRef(doc),
                    pipes = pipes.Select(pipe => SerializePipeInfo(doc, pipe)).ToList(),
                    fixtures = fixtures.Select(SerializeDrainageFixture).ToList()
                }));
                return;
            }

            if (action == "search_drainage_targets")
            {
                RequireDrainageExpectedDocument(doc, payload);
                string scope = ReadDrainageString(payload, "scope");
                if (string.IsNullOrWhiteSpace(scope))
                {
                    scope = "active_view";
                }
                int maxResults = (int)ReadLong(
                    payload,
                    "max_results",
                    200);
                if ((scope != "active_view" && scope != "document")
                    || maxResults < 1
                    || maxResults > 1000)
                {
                    throw new InvalidOperationException(
                        "SEARCH_SCOPE_INVALID");
                }
                FilteredElementCollector pipeCollector =
                    scope == "active_view"
                        ? new FilteredElementCollector(
                            doc,
                            doc.ActiveView.Id)
                        : new FilteredElementCollector(doc);
                FilteredElementCollector fixtureCollector =
                    scope == "active_view"
                        ? new FilteredElementCollector(
                            doc,
                            doc.ActiveView.Id)
                        : new FilteredElementCollector(doc);
                HashSet<long> explicitIds =
                    ReadDrainageLongSet(
                        payload,
                        "explicit_element_ids");
                HashSet<long> pipeTypeIds =
                    ReadDrainageLongSet(payload, "pipe_type_ids");
                HashSet<long> systemTypeIds =
                    ReadDrainageLongSet(
                        payload,
                        "system_type_ids");
                HashSet<long> levelIds =
                    ReadDrainageLongSet(payload, "level_ids");
                List<Pipe> matchingPipes = pipeCollector
                    .OfClass(typeof(Pipe))
                    .Cast<Pipe>()
                    .Where(pipe => explicitIds.Count == 0
                        || explicitIds.Contains(pipe.Id.Value))
                    .Where(pipe => pipeTypeIds.Count == 0
                        || pipeTypeIds.Contains(
                            pipe.GetTypeId().Value))
                    .Where(pipe => systemTypeIds.Count == 0
                        || systemTypeIds.Contains(
                            ReadDrainageElementIdParameter(
                                pipe,
                                BuiltInParameter
                                    .RBS_PIPING_SYSTEM_TYPE_PARAM)))
                    .Where(pipe => levelIds.Count == 0
                        || levelIds.Contains(
                            ReadDrainageElementIdParameter(
                                pipe,
                                BuiltInParameter
                                    .RBS_START_LEVEL_PARAM)))
                    .OrderBy(pipe => pipe.Id.Value)
                    .ToList();
                List<FamilyInstance> matchingFixtures =
                    fixtureCollector
                    .OfClass(typeof(FamilyInstance))
                    .Cast<FamilyInstance>()
                    .Where(IsPlumbingFixture)
                    .Where(item => explicitIds.Count == 0
                        || explicitIds.Contains(item.Id.Value))
                    .Where(item => levelIds.Count == 0
                        || levelIds.Contains(
                            ReadDrainageElementIdParameter(
                                item,
                                BuiltInParameter.FAMILY_LEVEL_PARAM)))
                    .OrderBy(item => item.Id.Value)
                    .ToList();
                List<Pipe> foundPipes = matchingPipes
                    .Take(maxResults)
                    .ToList();
                List<FamilyInstance> foundFixtures =
                    matchingFixtures
                    .Take(maxResults)
                    .ToList();
                var searchIssues = new List<string>();
                if (matchingPipes.Count == 0)
                {
                    searchIssues.Add("MAIN_CANDIDATE_NOT_FOUND");
                }
                else if (matchingPipes.Count > 1)
                {
                    searchIssues.Add("MAIN_CANDIDATE_AMBIGUOUS");
                }
                DrainageCandidateSetGrant candidateSetGrant =
                    IssueDrainageCandidateSetGrant(
                        doc,
                        foundPipes.Cast<Element>().ToList(),
                        foundFixtures.Cast<Element>().ToList(),
                        matchingPipes.Count);
                File.WriteAllText(responseFile, serializer.Serialize(new
                {
                    action = action,
                    document = SerializeDrainageDocumentRef(doc),
                    scope = scope,
                    status = matchingPipes.Count == 1
                        ? "ready"
                        : "blocked",
                    main_candidate_count = matchingPipes.Count,
                    blocking_issues = searchIssues,
                    candidate_set_token = candidateSetGrant.Token,
                    candidate_set_expires_at_utc =
                        candidateSetGrant.ExpiresUtc.ToString("o"),
                    max_results = maxResults,
                    applied_filters = new
                    {
                        explicit_element_ids = explicitIds,
                        pipe_type_ids = pipeTypeIds,
                        system_type_ids = systemTypeIds,
                        level_ids = levelIds
                    },
                    pipes = foundPipes
                        .Select(pipe => SerializePipeInfo(doc, pipe))
                        .ToList(),
                    fixtures = foundFixtures
                        .Select(SerializeDrainageFixture)
                        .ToList(),
                    truncated = matchingPipes.Count > maxResults
                        || matchingFixtures.Count > maxResults
                }));
                return;
            }

            if (action == "clear_drainage_preview")
            {
                string snapshotId =
                    ReadDrainageString(payload, "snapshot_id");
                string snapshotHash =
                    ReadDrainageString(payload, "snapshot_hash");
                long expectedRevision = ReadLong(
                    payload,
                    "document_revision",
                    -1);
                DrainageRouteSnapshot snapshot =
                    RequireDrainageSnapshotForClear(
                        doc,
                        snapshotId,
                        snapshotHash,
                        ReadDrainageString(
                            payload,
                            "document_fingerprint"),
                        expectedRevision);
                if (!DrainagePreviewServer.Clear(
                    doc,
                    snapshot.SnapshotId))
                {
                    throw new InvalidOperationException(
                        "PREVIEW_SNAPSHOT_NOT_ACTIVE");
                }
                RemoveDrainageSnapshot(
                    snapshot.SnapshotId,
                    snapshot.SnapshotHash);
                uiApp.ActiveUIDocument.RefreshActiveView();
                File.WriteAllText(responseFile, serializer.Serialize(new
                {
                    action = action,
                    cleared = true,
                    snapshot_id = snapshot.SnapshotId,
                    snapshot_hash = snapshot.SnapshotHash,
                    note = "DirectContext3D preview cleared; no model elements were created"
                }));
                return;
            }

            if (action == "confirm_drainage_snapshot")
            {
                string snapshotId = ReadDrainageString(payload, "snapshot_id");
                string snapshotHash = ReadDrainageString(payload, "snapshot_hash");
                string actorKind = ReadDrainageString(payload, "actor_kind");
                DrainageRouteSnapshot snapshot = RequireDrainageSnapshot(
                    doc,
                    snapshotId,
                    snapshotHash);
                if (!string.Equals(
                    snapshot.DocumentFingerprint,
                    ReadDrainageString(
                        payload,
                        "document_fingerprint"),
                    StringComparison.Ordinal)
                    || snapshot.DocumentRevision != ReadLong(
                        payload,
                        "document_revision",
                        -1))
                {
                    throw new InvalidOperationException(
                        "SNAPSHOT_DOCUMENT_BINDING_MISMATCH");
                }
                var confirmationDialog = new TaskDialog("SC Drainage Approval")
                {
                    MainInstruction = "Approve this drainage route snapshot?",
                    MainContent = "Snapshot: "
                        + snapshot.SnapshotId
                        + "\nFixtures: "
                        + snapshot.FixtureIds.Count
                        + "\nSlope: "
                        + (snapshot.SlopeRatio * 100.0).ToString(
                            "0.###",
                            System.Globalization.CultureInfo.InvariantCulture)
                        + "%\nDiameter: "
                        + snapshot.DiameterMm.ToString(
                            "0.###",
                            System.Globalization.CultureInfo.InvariantCulture)
                        + " mm",
                    CommonButtons =
                        TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No,
                    DefaultButton = TaskDialogResult.No
                };
                if (confirmationDialog.Show() != TaskDialogResult.Yes)
                {
                    throw new InvalidOperationException(
                        "HUMAN_CONFIRMATION_DECLINED");
                }
                DrainageConfirmation confirmation = ConfirmDrainageSnapshot(
                    snapshot,
                    actorKind);
                File.WriteAllText(responseFile, serializer.Serialize(new
                {
                    action = action,
                    document = SerializeDrainageDocumentRef(doc),
                    snapshot_id = snapshot.SnapshotId,
                    snapshot_hash = snapshot.SnapshotHash,
                    confirmation_id = confirmation.ConfirmationId,
                    actor_kind = confirmation.ActorKind,
                    expires_at_utc = confirmation.ExpiresUtc.ToString("o")
                }));
                return;
            }

            if (action == "get_drainage_operation")
            {
                DrainageOperationRecord operation = RequireDrainageOperationForDocument(
                    doc,
                    ReadDrainageString(payload, "operation_id"));
                operation = ReconcileDrainageOperation(doc, operation);
                File.WriteAllText(responseFile, serializer.Serialize(new
                {
                    action = action,
                    operation_id = operation.OperationId,
                    operation_schema_version =
                        operation.SchemaVersion,
                    idempotency_key = operation.IdempotencyKey,
                    snapshot_id = operation.SnapshotId,
                    snapshot_hash = operation.SnapshotHash,
                    document_fingerprint =
                        operation.DocumentFingerprint,
                    document_revision = operation.DocumentRevision,
                    document_title = operation.DocumentTitle,
                    document_path_kind = operation.DocumentPathKind,
                    dependency_hash = operation.DependencyHash,
                    confirmation_id = operation.ConfirmationId,
                    confirmation_actor_kind =
                        operation.ConfirmationActorKind,
                    initiator_surface = operation.InitiatorSurface,
                    tool_contract_version =
                        operation.ToolContractVersion,
                    assembly_module_version_id =
                        operation.AssemblyModuleVersionId,
                    assembly_sha256 = operation.AssemblySha256,
                    request_tool_name = operation.RequestToolName,
                    addin_version = operation.AddinVersion,
                    status = operation.Status,
                    error = operation.Error,
                    updated_at_utc = operation.UpdatedAtUtc,
                    result = operation.Result,
                    validation_evidence =
                        operation.ValidationEvidence
                }));
                return;
            }

            if (action == "create_drainage_preview" || action == "create_drainage_pipes")
            {
                DrainageRouteSnapshot commitSnapshot = null;
                DrainageConfirmation commitConfirmation = null;
                if (action == "create_drainage_pipes")
                {
                    RequireDrainageCommitDocumentPolicy(doc);
                    commitSnapshot = RequireDrainageSnapshot(
                        doc,
                        ReadDrainageString(payload, "snapshot_id"),
                        ReadDrainageString(payload, "snapshot_hash"));
                    commitConfirmation = RequireDrainageConfirmation(
                        commitSnapshot,
                        ReadDrainageString(payload, "confirmation_id"));
                }
                else
                {
                    RequireDrainageExpectedDocument(doc, payload);
                }

                long mainPipeId = commitSnapshot == null
                    ? ReadLong(payload, "main_pipe_id", 0)
                    : commitSnapshot.MainPipeId;
                double slopeRatio = commitSnapshot == null
                    ? ReadDouble(payload, "slope_ratio", 0.01)
                    : commitSnapshot.SlopeRatio;
                double diameterMm = commitSnapshot == null
                    ? ReadDouble(payload, "diameter_mm", 100)
                    : commitSnapshot.DiameterMm;
                string downstreamMode = commitSnapshot == null
                    ? (payload.ContainsKey("downstream_mode") && payload["downstream_mode"] != null
                        ? payload["downstream_mode"].ToString()
                        : "auto")
                    : commitSnapshot.DownstreamMode;
                DrainageRoutePolicy routePolicy = commitSnapshot == null
                    ? ReadDrainageRoutePolicy(payload, diameterMm)
                    : commitSnapshot.RoutePolicy;
                long requestedPipeTypeId = commitSnapshot == null
                    ? ReadLong(payload, "pipe_type_id", 0)
                    : commitSnapshot.PipeTypeId;
                long systemTypeId = commitSnapshot == null
                    ? ReadLong(payload, "system_type_id", 0)
                    : commitSnapshot.SystemTypeId;
                long levelIdValue = commitSnapshot == null
                    ? ReadLong(payload, "level_id", 0)
                    : commitSnapshot.LevelId;
                Pipe mainPipe = doc.GetElement(new ElementId(mainPipeId)) as Pipe;
                if (mainPipe == null)
                {
                    throw new InvalidOperationException(
                        "MAIN_PIPE_NOT_FOUND: "
                        + "\u627e\u4e0d\u5230\u9078\u53d6\u7684\u6c61\u6c34\u4e3b\u7ba1\u3002");
                }
                ValidateDrainageInputs(slopeRatio, diameterMm);
                ValidateDrainageRoutePolicy(routePolicy);
                List<Element> fixtures = commitSnapshot == null
                    ? ReadDrainageFixtures(doc, payload)
                    : commitSnapshot.FixtureIds
                        .Select(id => doc.GetElement(new ElementId(id)))
                        .Where(item => item != null)
                        .ToList();
                if (fixtures.Count == 0)
                {
                    throw new InvalidOperationException(
                        "FIXTURE_SELECTION_REQUIRED: "
                        + "\u8acb\u5728 Revit \u9078\u53d6\u81f3\u5c11\u4e00\u500b\u885b\u751f\u5668\u5177\u3002");
                }
                if (fixtures.Count > 20)
                {
                    throw new InvalidOperationException(
                        "FIXTURE_BATCH_LIMIT_EXCEEDED: "
                        + "\u55ae\u6b21\u6700\u591a\u8655\u7406 20 \u500b\u885b\u751f\u5668\u5177\uff0c\u8acb\u5206\u5340\u5efa\u7acb\u3002");
                }
                if (commitSnapshot == null)
                {
                    ValidateDrainagePreviewElementIdentities(
                        doc,
                        payload,
                        mainPipe,
                        fixtures);
                }

                PipeType planPipeType = requestedPipeTypeId > 0
                    ? doc.GetElement(new ElementId(requestedPipeTypeId)) as PipeType
                    : doc.GetElement(mainPipe.GetTypeId()) as PipeType;
                if (planPipeType == null)
                {
                    throw new InvalidOperationException(
                        "PIPE_TYPE_NOT_FOUND: "
                        + "\u627e\u4e0d\u5230\u9810\u89bd\u6307\u5b9a\u7684\u7ba1\u985e\u578b\u3002");
                }
                PipingSystemType systemType = doc.GetElement(
                    new ElementId(systemTypeId)) as PipingSystemType;
                ElementId levelId = levelIdValue > 0
                    ? new ElementId(levelIdValue)
                    : GetPipeLevelId(doc, mainPipe);
                Level planLevel = doc.GetElement(levelId) as Level;
                if (systemType == null || planLevel == null)
                {
                    throw new InvalidOperationException(
                        "SYSTEM_OR_LEVEL_INVALID: "
                        + "\u7cfb\u7d71\u985e\u578b\u6216\u6a13\u5c64\u7121\u6548\uff0c\u8acb\u91cd\u65b0\u8b80\u53d6\u5c08\u6848\u8cc7\u6599\u3002");
                }
                if (commitSnapshot == null)
                {
                    ValidateDrainagePreviewTypeIdentities(
                        payload,
                        planPipeType,
                        systemType,
                        planLevel);
                }
                DrainageRoutingPart junctionPart = commitSnapshot == null
                    ? ResolveDrainageRoutingPart(
                        doc,
                        planPipeType,
                        RoutingPreferenceRuleGroupType.Junctions,
                        diameterMm,
                        ReadLong(payload, "junction_type_id", 0),
                        ReadDrainageString(
                            payload,
                            "junction_type_unique_id"))
                    : commitSnapshot.JunctionPart;
                DrainageRoutingPart elbowPart = commitSnapshot == null
                    ? ResolveDrainageRoutingPart(
                        doc,
                        planPipeType,
                        RoutingPreferenceRuleGroupType.Elbows,
                        diameterMm,
                        ReadLong(payload, "elbow_type_id", 0),
                        ReadDrainageString(
                            payload,
                            "elbow_type_unique_id"))
                    : commitSnapshot.ElbowPart;
                List<DrainagePlan> plans = commitSnapshot == null
                    ? fixtures
                        .Select(fixture => BuildDrainagePlan(
                            mainPipe,
                            fixture,
                            ReadDrainagePoint(
                                payload,
                                "source_connector_origin"),
                            slopeRatio,
                            diameterMm,
                            downstreamMode,
                            junctionPart,
                            elbowPart,
                            routePolicy))
                        .ToList()
                    : commitSnapshot.Plans;
                plans = OrderDrainagePlansAlongDownstream(
                    mainPipe,
                    plans);
                ApplyDrainagePlanSetRules(plans, junctionPart, routePolicy);
                ApplyDrainagePlanToPlanClearanceRules(
                    plans,
                    diameterMm,
                    routePolicy);
                ApplyDrainageExistingPipeClearanceRules(
                    doc,
                    mainPipe,
                    plans,
                    diameterMm,
                    routePolicy);

                if (action == "create_drainage_preview")
                {
                    DrainageRouteSnapshot snapshot = CreateDrainageSnapshot(
                        doc,
                        mainPipe.Id.Value,
                        fixtures.Select(item => item.Id.Value),
                        planPipeType.Id.Value,
                        systemType.Id.Value,
                        levelId.Value,
                        slopeRatio,
                        diameterMm,
                        downstreamMode,
                        junctionPart,
                        elbowPart,
                        routePolicy,
                        plans);
                    List<DrainagePreviewSegment> previewSegments = plans
                        .SelectMany(CreateDrainagePreviewSegments)
                        .ToList();
                    previewSegments.AddRange(
                        CreateDrainageMainDirectionPreviewSegments(
                            mainPipe,
                            plans));
                    DrainagePreviewServer.SetSegments(
                        doc,
                        snapshot.SnapshotId,
                        previewSegments);
                    uiApp.ActiveUIDocument.RefreshActiveView();
                    File.WriteAllText(responseFile, serializer.Serialize(new
                    {
                        action = action,
                        document = SerializeDrainageDocumentRef(doc),
                        preview_kind = "revit_canvas_directcontext3d",
                        preview_segment_count = previewSegments.Count,
                        slope_ratio = slopeRatio,
                        slope_percent = slopeRatio * 100.0,
                        diameter_mm = diameterMm,
                        main_pipe_id = mainPipe.Id.Value,
                        pipe_type_id = planPipeType.Id.Value,
                        system_type_id = systemType.Id.Value,
                        level_id = levelId.Value,
                        fixture_count = plans.Count,
                        ready_to_create = plans.All(item => item.ReadyToCreate),
                        downstream_mode = downstreamMode,
                        route_policy = SerializeDrainageRoutePolicy(routePolicy),
                        snapshot_id = snapshot.SnapshotId,
                        snapshot_hash = snapshot.SnapshotHash,
                        snapshot_expires_at_utc = snapshot.ExpiresUtc.ToString("o"),
                        junction_profile = SerializeDrainageRoutingPart(junctionPart),
                        elbow_profile = SerializeDrainageRoutingPart(elbowPart),
                        issues = plans.SelectMany(item => item.Issues.Select(issue => new
                        {
                            fixture_id = item.SourceElement.Id.Value,
                            code = issue
                        })).ToList(),
                        plans = plans.Select(SerializeDrainagePlan).ToList()
                    }));
                    return;
                }

                PipeType pipeType = planPipeType;
                if (pipeType == null || systemType == null || doc.GetElement(levelId) as Level == null)
                {
                    throw new InvalidOperationException(
                        "TYPE_CONTEXT_INVALID: "
                        + "\u7ba1\u985e\u578b\u3001\u7cfb\u7d71\u985e\u578b\u6216\u6a13\u5c64\u7121\u6548\uff0c\u8acb\u91cd\u65b0\u8b80\u53d6\u5c08\u6848\u8cc7\u6599\u3002");
                }
                List<object> blockingIssues = plans
                    .SelectMany(item => item.Issues.Select(issue => (object)new
                    {
                        fixture_id = item.SourceElement.Id.Value,
                        code = issue
                    }))
                    .ToList();
                if (blockingIssues.Count > 0)
                {
                    throw new InvalidOperationException(
                        "PREFLIGHT_BLOCKED: "
                        + "\u6392\u6c34 preflight \u672a\u901a\u904e\uff0c\u7981\u6b62\u5efa\u6a21\uff1a"
                        + string.Join(", ", plans.SelectMany(item => item.Issues).Distinct()));
                }

                double diameterFeet = UnitUtils.ConvertToInternalUnits(diameterMm, UnitTypeId.Millimeters);
                string batchId = DateTime.Now.ToString("yyyyMMdd-HHmmss");
                var mainSegments = new List<Pipe> { mainPipe };
                var created = new List<object>();
                var createdFittings = new List<object>();
                var createdFittingIds = new List<ElementId>();
                var failures = new List<object>();
                var createdIds = new List<ElementId>();
                var createdPipeChecks = new List<DrainageCreatedPipeCheck>();
                string operationActorKind = ReadDrainageString(
                    payload,
                    "actor_kind");
                if (operationActorKind != "agent"
                    && operationActorKind != "human_gui")
                {
                    throw new InvalidOperationException(
                        "OPERATION_ACTOR_INVALID");
                }
                bool createdNewOperation;
                DrainageOperationRecord operation = BeginDrainageOperation(
                    ReadDrainageString(payload, "operation_id"),
                    ReadDrainageString(payload, "idempotency_key"),
                    commitSnapshot,
                    doc,
                    commitConfirmation,
                    operationActorKind,
                    out createdNewOperation);
                if (!createdNewOperation)
                {
                    if (string.Equals(operation.Status, "committed", StringComparison.Ordinal)
                        && operation.Result != null)
                    {
                        File.WriteAllText(
                            responseFile,
                            serializer.Serialize(operation.Result));
                        return;
                    }
                    throw new InvalidOperationException(
                        "OPERATION_STATUS_" + (operation.Status ?? "UNKNOWN").ToUpperInvariant());
                }

                bool modelCommitted = false;
                try
                {
                    using (Transaction transaction = new Transaction(doc, "SC Drainage 1%"))
                    {
                        var failurePreprocessor = new DrainageFailurePreprocessor();
                        FailureHandlingOptions failureOptions =
                            transaction.GetFailureHandlingOptions();
                        failureOptions.SetFailuresPreprocessor(failurePreprocessor);
                        failureOptions.SetClearAfterRollback(true);
                        transaction.SetFailureHandlingOptions(failureOptions);
                        transaction.Start();
                        foreach (DrainagePlan plan in plans)
                        {
                            try
                            {
                                Pipe branch = CreateFirePipe(
                                    doc,
                                    systemType.Id,
                                    pipeType.Id,
                                    levelId,
                                    plan.BranchStart,
                                    plan.MainTie,
                                    diameterFeet);
                                if (branch == null)
                                {
                                    throw new InvalidOperationException(
                                        "BRANCH_TOO_SHORT: "
                                        + "\u659c\u652f\u7ba1\u9577\u5ea6\u4e0d\u8db3\u3002");
                                }
                                SetDrainageMetadata(branch, "branch", batchId, slopeRatio, operation.OperationId);
                                createdIds.Add(branch.Id);
                                createdPipeChecks.Add(new DrainageCreatedPipeCheck
                                {
                                    Pipe = branch,
                                    Source = plan.BranchStart,
                                    Sink = plan.MainTie,
                                    RequiresSignedSlope = true,
                                    RequiresDescending = true,
                                    MinimumCenterlineLength = Math.Max(
                                        diameterFeet,
                                        UnitUtils.ConvertToInternalUnits(
                                            routePolicy.MinimumTangentMm,
                                            UnitTypeId.Millimeters))
                                });
                                created.Add(new
                                {
                                    element_id = branch.Id.Value,
                                    kind = "branch",
                                    fixture_id = plan.SourceElement.Id.Value,
                                    source = SerializePoint(plan.BranchStart),
                                    sink = SerializePoint(plan.MainTie)
                                });

                                Pipe connectorStub = null;
                                Pipe drop = null;
                                if (plan.HasConnectorStub)
                                {
                                connectorStub = CreateFirePipeFromConnector(
                                    doc,
                                    systemType.Id,
                                    pipeType.Id,
                                    levelId,
                                    plan.FixtureConnector,
                                    plan.ConnectorStubEnd,
                                    diameterFeet);
                                if (connectorStub == null)
                                {
                                    throw new InvalidOperationException(
                                        "WALL_CONNECTOR_STUB_CREATE_FAILED");
                                }
                                SetDrainageMetadata(connectorStub, "stub", batchId, slopeRatio, operation.OperationId);
                                createdIds.Add(connectorStub.Id);
                                createdPipeChecks.Add(new DrainageCreatedPipeCheck
                                {
                                    Pipe = connectorStub,
                                    Source = plan.ConnectorPoint,
                                    Sink = plan.ConnectorStubEnd,
                                    RequiresSignedSlope = false,
                                    RequiresDescending = false,
                                    MinimumCenterlineLength = Math.Max(
                                        diameterFeet,
                                        UnitUtils.ConvertToInternalUnits(
                                            routePolicy.MinimumTangentMm,
                                            UnitTypeId.Millimeters))
                                });
                                created.Add(new
                                {
                                    element_id = connectorStub.Id.Value,
                                    kind = "stub",
                                    fixture_id = plan.SourceElement.Id.Value,
                                    source = SerializePoint(plan.ConnectorPoint),
                                    sink = SerializePoint(plan.ConnectorStubEnd)
                                });

                                if (plan.ConnectorStubEnd.DistanceTo(plan.BranchStart) > 0.01)
                                {
                                    drop = CreateFirePipe(
                                        doc,
                                        systemType.Id,
                                        pipeType.Id,
                                        levelId,
                                        plan.ConnectorStubEnd,
                                        plan.BranchStart,
                                        diameterFeet);
                                    if (drop == null)
                                    {
                                        throw new InvalidOperationException(
                                            "WALL_VERTICAL_DROP_CREATE_FAILED");
                                    }
                                    string offsetKind = plan.HasDoubleFortyFive
                                        ? "double45_diagonal"
                                        : "drop";
                                    SetDrainageMetadata(drop, offsetKind, batchId, slopeRatio, operation.OperationId);
                                    createdIds.Add(drop.Id);
                                    createdPipeChecks.Add(new DrainageCreatedPipeCheck
                                    {
                                        Pipe = drop,
                                        Source = plan.ConnectorStubEnd,
                                        Sink = plan.BranchStart,
                                        RequiresSignedSlope = false,
                                        RequiresDescending = true,
                                        MinimumCenterlineLength = Math.Max(
                                            diameterFeet,
                                            UnitUtils.ConvertToInternalUnits(
                                                routePolicy.MinimumTangentMm,
                                                UnitTypeId.Millimeters))
                                    });
                                    created.Add(new
                                    {
                                        element_id = drop.Id.Value,
                                        kind = offsetKind,
                                        fixture_id = plan.SourceElement.Id.Value,
                                        source = SerializePoint(plan.ConnectorStubEnd),
                                        sink = SerializePoint(plan.BranchStart)
                                    });
                                    FamilyInstance stubElbow = CreateAndValidateDrainageElbow(
                                        doc,
                                        connectorStub,
                                        drop,
                                        plan.ConnectorStubEnd,
                                        elbowPart);
                                    createdFittingIds.Add(stubElbow.Id);
                                    SetDrainageElementMetadata(stubElbow, "elbow", batchId, slopeRatio, operation.OperationId);
                                    createdFittings.Add(new
                                    {
                                        element_id = stubElbow.Id.Value,
                                        kind = "elbow",
                                        role = plan.HasDoubleFortyFive
                                            ? "double45_elbow_1"
                                            : "wall_stub_to_drop",
                                        type_id = stubElbow.GetTypeId().Value,
                                        first_pipe_id = connectorStub.Id.Value,
                                        second_pipe_id = drop.Id.Value,
                                        fixture_id = plan.SourceElement.Id.Value
                                    });
                                    FamilyInstance branchElbow = CreateAndValidateDrainageElbow(
                                        doc,
                                        drop,
                                        branch,
                                        plan.BranchStart,
                                        elbowPart);
                                    createdFittingIds.Add(branchElbow.Id);
                                    SetDrainageElementMetadata(branchElbow, "elbow", batchId, slopeRatio, operation.OperationId);
                                    createdFittings.Add(new
                                    {
                                        element_id = branchElbow.Id.Value,
                                        kind = "elbow",
                                        role = plan.HasDoubleFortyFive
                                            ? "double45_elbow_2"
                                            : "drop_to_branch",
                                        type_id = branchElbow.GetTypeId().Value,
                                        first_pipe_id = drop.Id.Value,
                                        second_pipe_id = branch.Id.Value,
                                        fixture_id = plan.SourceElement.Id.Value
                                    });
                                }
                                else
                                {
                                    FamilyInstance stubToBranchElbow = CreateAndValidateDrainageElbow(
                                        doc,
                                        connectorStub,
                                        branch,
                                        plan.BranchStart,
                                        elbowPart);
                                    createdFittingIds.Add(stubToBranchElbow.Id);
                                    SetDrainageElementMetadata(stubToBranchElbow, "elbow", batchId, slopeRatio, operation.OperationId);
                                    createdFittings.Add(new
                                    {
                                        element_id = stubToBranchElbow.Id.Value,
                                        kind = "elbow",
                                        role = "wall_stub_to_branch",
                                        type_id = stubToBranchElbow.GetTypeId().Value,
                                        first_pipe_id = connectorStub.Id.Value,
                                        second_pipe_id = branch.Id.Value,
                                        fixture_id = plan.SourceElement.Id.Value
                                    });
                                }
                                }
                                else if (plan.ConnectorPoint.DistanceTo(plan.BranchStart) > 0.01)
                                {
                                drop = CreateFirePipeFromConnector(
                                    doc,
                                    systemType.Id,
                                    pipeType.Id,
                                    levelId,
                                    plan.FixtureConnector,
                                    plan.BranchStart,
                                    diameterFeet);
                                if (drop == null)
                                {
                                    throw new InvalidOperationException(
                                        "FLOOR_DROP_CREATE_FAILED: "
                                        + "\u7121\u6cd5\u5efa\u7acb\u5668\u5177\u5782\u76f4\u843d\u6c34\u7ba1\u3002");
                                }
                                SetDrainageMetadata(drop, "drop", batchId, slopeRatio, operation.OperationId);
                                createdIds.Add(drop.Id);
                                createdPipeChecks.Add(new DrainageCreatedPipeCheck
                                {
                                    Pipe = drop,
                                    Source = plan.ConnectorPoint,
                                    Sink = plan.BranchStart,
                                    RequiresSignedSlope = false,
                                    RequiresDescending = true,
                                    MinimumCenterlineLength = Math.Max(
                                        diameterFeet,
                                        UnitUtils.ConvertToInternalUnits(
                                            routePolicy.MinimumTangentMm,
                                            UnitTypeId.Millimeters))
                                });
                                created.Add(new
                                {
                                    element_id = drop.Id.Value,
                                    kind = "drop",
                                    fixture_id = plan.SourceElement.Id.Value,
                                    source = SerializePoint(plan.ConnectorPoint),
                                    sink = SerializePoint(plan.BranchStart)
                                });
                                FamilyInstance elbow = CreateAndValidateDrainageElbow(
                                    doc,
                                    branch,
                                    drop,
                                    plan.BranchStart,
                                    elbowPart);
                                createdFittingIds.Add(elbow.Id);
                                SetDrainageElementMetadata(elbow, "elbow", batchId, slopeRatio, operation.OperationId);
                                createdFittings.Add(new
                                {
                                    element_id = elbow.Id.Value,
                                    kind = "elbow",
                                    role = "floor_drop_to_branch",
                                    type_id = elbow.GetTypeId().Value,
                                    first_pipe_id = branch.Id.Value,
                                    second_pipe_id = drop.Id.Value,
                                    fixture_id = plan.SourceElement.Id.Value
                                });
                                }
                                else if (!TryConnectElements(
                                    doc,
                                    branch,
                                    plan.BranchStart,
                                    plan.SourceElement,
                                    plan.ConnectorPoint))
                                {
                                    throw new InvalidOperationException(
                                        "FIXTURE_CONNECT_FAILED: "
                                        + "\u659c\u652f\u7ba1\u7121\u6cd5\u9023\u63a5\u885b\u751f\u5668\u5177 connector\u3002");
                                }

                                FamilyInstance junction = CreateDrainageTeeAtPoint(
                                doc,
                                mainSegments,
                                branch,
                                plan.MainTie,
                                plan.DownstreamPoint,
                                junctionPart,
                                diameterFeet);
                            if (junction == null)
                            {
                                throw new InvalidOperationException(
                                    "JUNCTION_CREATE_FAILED: "
                                    + "\u4e3b\u7ba1\u8207\u659c\u652f\u7ba1\u7121\u6cd5\u5efa\u7acb\u659c\u4e09\u901a\uff1b\u8acb\u6aa2\u67e5 SP \u6c61\u6c34\u7ba1\u8def\u7531\u504f\u597d\u3002");
                            }
                            if (junctionPart == null || junction.GetTypeId().Value != junctionPart.PartId.Value)
                            {
                                throw new InvalidOperationException(
                                    "JUNCTION_TYPE_MISMATCH: expected "
                                    + (junctionPart == null ? 0 : junctionPart.PartId.Value)
                                    + ", actual "
                                    + junction.GetTypeId().Value);
                            }
                            if (!IsDrainageJunctionConnectivityValid(
                                junction,
                                branch,
                                mainSegments))
                            {
                                throw new InvalidOperationException(
                                    "JUNCTION_CONNECTIVITY_INVALID: fitting must connect the branch and two main segments");
                            }
                            double actualJunctionAngle;
                            double actualRadialAngle;
                            string junctionGeometryError;
                            if (!IsDrainageJunctionGeometryValid(
                                junction,
                                branch,
                                mainSegments,
                                plan.MainTie,
                                plan.DownstreamPoint,
                                routePolicy,
                                out actualJunctionAngle,
                                out actualRadialAngle,
                                out junctionGeometryError))
                            {
                                throw new InvalidOperationException(
                                    "JUNCTION_GEOMETRY_INVALID: " + junctionGeometryError);
                            }
                            createdFittingIds.Add(junction.Id);
                            SetDrainageElementMetadata(junction, "junction", batchId, slopeRatio, operation.OperationId);
                                createdFittings.Add(new
                                {
                                element_id = junction.Id.Value,
                                kind = "junction",
                                type_id = junction.GetTypeId().Value,
                                actual_side_entry_angle_degrees = actualJunctionAngle,
                                actual_radial_entry_angle_degrees = actualRadialAngle,
                                fixture_id = plan.SourceElement.Id.Value,
                                branch_id = branch.Id.Value,
                                main_tie = SerializePoint(plan.MainTie),
                                downstream_point = SerializePoint(plan.DownstreamPoint)
                                });
                            }
                            catch (Exception ex)
                            {
                                failures.Add(new
                                {
                                    fixture_id = plan.SourceElement.Id.Value,
                                    reason = ex.Message
                                });
                                throw;
                            }
                        }
                        doc.Regenerate();
                        foreach (DrainageCreatedPipeCheck check in createdPipeChecks)
                        {
                            string validationError = ValidateCreatedDrainagePipe(
                                check,
                                slopeRatio);
                            if (!string.IsNullOrEmpty(validationError))
                            {
                                transaction.RollBack();
                                throw new InvalidOperationException(
                                    "PRECOMMIT_VALIDATION_FAILED: " + validationError);
                            }
                        }
                        double minimumMainSegmentLength = Math.Max(
                            doc.Application.ShortCurveTolerance,
                            Math.Max(
                                diameterFeet,
                                UnitUtils.ConvertToInternalUnits(
                                    routePolicy.MinimumTangentMm,
                                    UnitTypeId.Millimeters)));
                        foreach (Pipe mainSegment in mainSegments)
                        {
                            LocationCurve location =
                                mainSegment.Location as LocationCurve;
                            if (location == null
                                || location.Curve == null
                                || location.Curve.Length
                                    < minimumMainSegmentLength)
                            {
                                transaction.RollBack();
                                throw new InvalidOperationException(
                                    "MAIN_SEGMENT_TANGENT_TOO_SHORT: pipe "
                                    + mainSegment.Id.Value);
                            }
                        }
                        var routeAllowedIds = new HashSet<long>(
                            createdIds.Select(id => id.Value)
                                .Concat(createdFittingIds.Select(id => id.Value))
                                .Concat(mainSegments.Select(pipe => pipe.Id.Value))
                                .Concat(plans.Select(plan => plan.SourceElement.Id.Value)));
                        var mainSegmentIds = new HashSet<long>(
                            mainSegments.Select(pipe => pipe.Id.Value));
                        foreach (DrainagePlan plan in plans)
                        {
                            if (!IsDrainageConnectorGraphReachable(
                                doc,
                                plan.SourceElement.Id.Value,
                                mainSegmentIds,
                                routeAllowedIds))
                            {
                                transaction.RollBack();
                                throw new InvalidOperationException(
                                    "ROUTE_TOPOLOGY_DISCONNECTED: fixture "
                                    + plan.SourceElement.Id.Value
                                    + " does not reach the split main");
                            }
                        }
                        var mainOnlyAllowedIds = new HashSet<long>(
                            mainSegmentIds.Concat(createdFittingIds.Select(id => id.Value)));
                        if (!AreDrainageElementsConnected(
                            doc,
                            mainSegmentIds,
                            mainOnlyAllowedIds))
                        {
                            transaction.RollBack();
                            throw new InvalidOperationException(
                                "MAIN_CONTINUITY_INVALID: split main segments are not one connected graph");
                        }
                        if (HasDrainageConnectorGraphCycle(
                            doc,
                            routeAllowedIds))
                        {
                            transaction.RollBack();
                            throw new InvalidOperationException(
                                "ROUTE_TOPOLOGY_CYCLE: the proposed drainage graph contains a cycle");
                        }
                        TransactionStatus commitStatus = transaction.Commit();
                        if (commitStatus != TransactionStatus.Committed)
                        {
                            throw new InvalidOperationException(
                                "REVIT_FAILURE_ROLLBACK: "
                                + failurePreprocessor.Summarize());
                        }
                        modelCommitted = true;
                    }
                    var committedRouteIds = new HashSet<long>(
                        createdIds.Select(id => id.Value)
                            .Concat(createdFittingIds.Select(id => id.Value))
                            .Concat(mainSegments.Select(pipe => pipe.Id.Value))
                            .Concat(plans.Select(plan => plan.SourceElement.Id.Value)));
                    HashSet<long> routeBridgeFittingIds =
                        FindDrainageBridgingFittingIds(doc, committedRouteIds);
                    var result = new Dictionary<string, object>
                    {
                        { "action", action },
                        { "document", SerializeDrainageDocumentRef(doc) },
                        { "operation_id", operation.OperationId },
                        { "operation_schema_version",
                            operation.SchemaVersion },
                        { "idempotency_key",
                            operation.IdempotencyKey },
                        { "document_fingerprint",
                            operation.DocumentFingerprint },
                        { "initiator_surface", operation.InitiatorSurface },
                        { "confirmation_id", operation.ConfirmationId },
                        { "confirmation_actor_kind", operation.ConfirmationActorKind },
                        { "tool_contract_version", operation.ToolContractVersion },
                        { "assembly_module_version_id", operation.AssemblyModuleVersionId },
                        { "assembly_sha256", operation.AssemblySha256 },
                        { "request_tool_name", operation.RequestToolName },
                        { "dependency_hash", operation.DependencyHash },
                        { "addin_version", operation.AddinVersion },
                        { "snapshot_id", commitSnapshot.SnapshotId },
                        { "snapshot_hash", commitSnapshot.SnapshotHash },
                        { "batch_id", batchId },
                        { "slope_ratio", slopeRatio },
                        { "slope_percent", slopeRatio * 100.0 },
                        { "diameter_mm", diameterMm },
                        { "route_policy", SerializeDrainageRoutePolicy(routePolicy) },
                        { "created", created },
                        { "fittings", createdFittings },
                        { "failed", failures },
                        { "created_element_ids", createdIds.Select(id => id.Value).ToList() },
                        { "created_element_refs", createdIds
                            .Select(id => SerializeDrainageOperationElementRef(
                                doc.GetElement(id)))
                            .ToList() },
                        { "fitting_element_ids", createdFittingIds.Select(id => id.Value).ToList() },
                        { "fitting_element_refs", createdFittingIds
                            .Select(id => SerializeDrainageOperationElementRef(
                                doc.GetElement(id)))
                            .ToList() },
                        { "modified_element_ids", mainSegments
                            .Select(pipe => pipe.Id.Value).ToList() },
                        { "modified_element_refs", mainSegments
                            .Select(pipe =>
                                SerializeDrainageOperationElementRef(pipe))
                            .ToList() },
                        { "deleted_element_ids", new List<long>() },
                        { "before_main_pipe_id",
                            commitSnapshot.MainPipeId },
                        { "failure_severity", failures.Count == 0
                            ? "none"
                            : "error" },
                        { "route_bridge_fitting_ids", routeBridgeFittingIds.ToList() },
                        { "main_segment_ids", mainSegments.Select(pipe => pipe.Id.Value).ToList() },
                        { "fixture_ids", plans.Select(plan => plan.SourceElement.Id.Value).ToList() },
                        { "fixture_refs", plans
                            .Select(plan =>
                                SerializeDrainageOperationElementRef(
                                    plan.SourceElement))
                            .ToList() }
                    };
                    CompleteDrainageOperation(operation, result);
                    File.WriteAllText(responseFile, serializer.Serialize(result));
                    return;
                }
                catch (Exception ex)
                {
                    if (!modelCommitted)
                    {
                        FailDrainageOperation(operation, ex);
                    }
                    throw;
                }
            }

            if (action == "validate_drainage_result")
            {
                double expectedSlope = ReadDouble(
                    payload,
                    "expected_slope_ratio",
                    0.01);
                DrainageOperationRecord validationOperation = null;
                string validationOperationId = ReadDrainageString(payload, "operation_id");
                if (string.IsNullOrWhiteSpace(validationOperationId))
                {
                    throw new InvalidOperationException(
                        "OPERATION_ID_REQUIRED");
                }
                if (!string.IsNullOrWhiteSpace(validationOperationId))
                {
                    validationOperation = RequireDrainageOperationForDocument(
                        doc,
                        validationOperationId);
                    if (!string.Equals(
                        validationOperation.Status,
                        "committed",
                        StringComparison.Ordinal)
                        || validationOperation.Result == null)
                    {
                        throw new InvalidOperationException(
                            "OPERATION_NOT_COMMITTED");
                    }
                }
                Dictionary<string, object> validationSource =
                    validationOperation == null ? payload : validationOperation.Result;
                DrainageRoutePolicy validationRoutePolicy =
                    ReadDrainageRoutePolicy(
                        validationSource,
                        ReadDouble(validationSource, "diameter_mm", 100));
                ValidateDrainageRoutePolicy(validationRoutePolicy);
                if (validationOperation != null)
                {
                    expectedSlope = ReadDouble(
                        validationSource,
                        "slope_ratio",
                        0);
                    if (expectedSlope <= 0)
                    {
                        throw new InvalidOperationException(
                            "OPERATION_SLOPE_EVIDENCE_MISSING");
                    }
                }
                ArrayList rawIds = ReadDrainageArray(validationSource, "created_element_ids");
                if (rawIds == null)
                {
                    rawIds = ReadDrainageArray(payload, "element_ids");
                }
                ArrayList createdElementRefs = ReadDrainageArray(
                    validationSource,
                    "created_element_refs");
                if (validationOperation != null
                    && createdElementRefs == null)
                {
                    throw new InvalidOperationException(
                        "OPERATION_ELEMENT_REFS_MISSING");
                }
                ArrayList routeEvidence = ReadDrainageArray(
                    validationSource,
                    "created");
                if (routeEvidence == null)
                {
                    routeEvidence = ReadDrainageArray(payload, "route_evidence");
                }
                var results = new List<object>();
                if (rawIds != null)
                {
                    foreach (object rawId in rawIds)
                    {
                        long pipeId = Convert.ToInt64(rawId);
                        Pipe pipe = ResolveDrainageOperationElementRef(
                            doc,
                            createdElementRefs,
                            pipeId,
                            validationOperationId,
                            validationOperation != null) as Pipe;
                        if (pipe == null)
                        {
                            results.Add(new { element_id = pipeId, valid = false, reason = "not a pipe" });
                            continue;
                        }
                        LocationCurve location = pipe.Location as LocationCurve;
                        XYZ start = location != null ? location.Curve.GetEndPoint(0) : XYZ.Zero;
                        XYZ end = location != null ? location.Curve.GetEndPoint(1) : XYZ.Zero;
                        string metadata = ReadDrainageMetadata(pipe);
                        string pipeKind =
                            ReadDrainageMetadataKind(metadata);
                        bool isBranch = pipeKind == "branch";
                        Dictionary<string, object> evidence = FindDrainageRouteEvidence(
                            routeEvidence,
                            pipe.Id.Value);
                        XYZ plannedSource = ReadDrainagePoint(evidence, "source");
                        XYZ plannedSink = ReadDrainagePoint(evidence, "sink");
                        XYZ actualSource = start.DistanceTo(plannedSource) <= end.DistanceTo(plannedSource)
                            ? start
                            : end;
                        XYZ actualSink = actualSource.IsAlmostEqualTo(start) ? end : start;
                        double horizontal = Math.Sqrt(
                            Math.Pow(actualSink.X - actualSource.X, 2)
                            + Math.Pow(actualSink.Y - actualSource.Y, 2));
                        double actualSlope = horizontal > 0.000001
                            ? (actualSource.Z - actualSink.Z) / horizontal
                            : 0;
                        int connectedEndCount = CountConnectedEndConnectors(pipe);
                        bool hasEvidence = evidence != null;
                        bool slopeValid = !isBranch
                            || (hasEvidence
                                && actualSlope > 0
                                && Math.Abs(actualSlope - expectedSlope) <= 0.0005);
                        double elevationTolerance = UnitUtils.ConvertToInternalUnits(
                            1,
                            UnitTypeId.Millimeters);
                        bool monotonicValid = hasEvidence
                            && actualSink.Z <= actualSource.Z + elevationTolerance;
                        bool valid = metadata.StartsWith(ScDrainageCommentPrefix, StringComparison.Ordinal)
                            && metadata.Contains(
                                ":operation=" + validationOperationId)
                            && connectedEndCount == 2
                            && slopeValid
                            && monotonicValid;
                        results.Add(new
                        {
                            element_id = pipe.Id.Value,
                            kind = string.IsNullOrWhiteSpace(pipeKind)
                                ? "unknown"
                                : pipeKind,
                            actual_slope_ratio = actualSlope,
                            expected_slope_ratio = expectedSlope,
                            signed_slope = actualSlope,
                            connected_end_count = connectedEndCount,
                            has_route_evidence = hasEvidence,
                            slope_valid = slopeValid,
                            monotonic_valid = monotonicValid,
                            valid = valid
                        });
                    }
                }
                var topologyIssues = new List<string>();
                ArrayList rawFixtureIds = ReadDrainageArray(
                    validationSource,
                    "fixture_ids");
                ArrayList rawMainIds = ReadDrainageArray(
                    validationSource,
                    "main_segment_ids");
                ArrayList rawFittingIds = ReadDrainageArray(
                    validationSource,
                    "fitting_element_ids");
                ArrayList fixtureRefs = ReadDrainageArray(
                    validationSource,
                    "fixture_refs");
                ArrayList mainSegmentRefs = ReadDrainageArray(
                    validationSource,
                    "modified_element_refs");
                ArrayList fittingRefs = ReadDrainageArray(
                    validationSource,
                    "fitting_element_refs");
                var createdPipeIds = new HashSet<long>(
                    (rawIds ?? new ArrayList())
                        .Cast<object>()
                        .Select(Convert.ToInt64));
                var fixtureIds = new HashSet<long>(
                    (rawFixtureIds ?? new ArrayList())
                        .Cast<object>()
                        .Select(Convert.ToInt64));
                var mainIds = new HashSet<long>(
                    (rawMainIds ?? new ArrayList())
                        .Cast<object>()
                        .Select(Convert.ToInt64));
                var fittingIds = new HashSet<long>(
                    (rawFittingIds ?? new ArrayList())
                        .Cast<object>()
                        .Select(Convert.ToInt64));
                if (validationOperation != null)
                {
                    foreach (long fixtureId in fixtureIds)
                    {
                        ResolveDrainageOperationElementRef(
                            doc,
                            fixtureRefs,
                            fixtureId,
                            validationOperationId,
                            false);
                    }
                    foreach (long mainId in mainIds)
                    {
                        ResolveDrainageOperationElementRef(
                            doc,
                            mainSegmentRefs,
                            mainId,
                            validationOperationId,
                            false);
                    }
                    foreach (long fittingId in fittingIds)
                    {
                        ResolveDrainageOperationElementRef(
                            doc,
                            fittingRefs,
                            fittingId,
                            validationOperationId,
                            true);
                    }
                    var allowedIds = new HashSet<long>(
                        createdPipeIds.Concat(fixtureIds).Concat(mainIds).Concat(fittingIds));
                    allowedIds.UnionWith(
                        FindDrainageBridgingFittingIds(doc, allowedIds));
                    foreach (long fixtureId in fixtureIds)
                    {
                        if (!IsDrainageConnectorGraphReachable(
                            doc,
                            fixtureId,
                            mainIds,
                            allowedIds))
                        {
                            topologyIssues.Add(
                                "ROUTE_TOPOLOGY_DISCONNECTED:" + fixtureId);
                        }
                    }
                    if (HasDrainageConnectorGraphCycle(
                        doc,
                        allowedIds))
                    {
                        topologyIssues.Add("ROUTE_TOPOLOGY_CYCLE");
                    }
                    if (!AreDrainageElementsConnected(
                        doc,
                        mainIds,
                        new HashSet<long>(mainIds.Concat(fittingIds))))
                    {
                        topologyIssues.Add("MAIN_CONTINUITY_INVALID");
                    }
                    var mainPipes = mainIds
                        .Select(id => doc.GetElement(new ElementId(id)) as Pipe)
                        .Where(pipe => pipe != null)
                        .ToList();
                    ArrayList fittingEvidence = ReadDrainageArray(
                        validationSource,
                        "fittings");
                    foreach (Dictionary<string, object> fittingRecord in
                        (fittingEvidence ?? new ArrayList())
                            .Cast<object>()
                            .Select(item => item as Dictionary<string, object>)
                            .Where(item => item != null))
                    {
                        string fittingKind = ReadDrainageString(
                            fittingRecord,
                            "kind");
                        long fittingId = Convert.ToInt64(fittingRecord["element_id"]);
                        FamilyInstance fitting =
                            ResolveDrainageOperationElementRef(
                                doc,
                                fittingRefs,
                                fittingId,
                                validationOperationId,
                                true) as FamilyInstance;
                        long expectedTypeId = Convert.ToInt64(fittingRecord["type_id"]);
                        string geometryError;
                        bool geometryValid = fitting != null
                            && fitting.GetTypeId().Value == expectedTypeId;
                        if (geometryValid && fittingKind == "junction")
                        {
                            long branchId = Convert.ToInt64(
                                fittingRecord["branch_id"]);
                            Pipe branch = doc.GetElement(
                                new ElementId(branchId)) as Pipe;
                            double sideAngle;
                            double radialAngle;
                            geometryValid = IsDrainageJunctionGeometryValid(
                                fitting,
                                branch,
                                mainPipes,
                                ReadDrainagePoint(fittingRecord, "main_tie"),
                                ReadDrainagePoint(fittingRecord, "downstream_point"),
                                validationRoutePolicy,
                                out sideAngle,
                                out radialAngle,
                                out geometryError);
                        }
                        else if (geometryValid && fittingKind == "elbow")
                        {
                            Pipe first = doc.GetElement(new ElementId(
                                Convert.ToInt64(
                                    fittingRecord["first_pipe_id"]))) as Pipe;
                            Pipe second = doc.GetElement(new ElementId(
                                Convert.ToInt64(
                                    fittingRecord["second_pipe_id"]))) as Pipe;
                            geometryValid = IsDrainageElbowGeometryValid(
                                fitting,
                                first,
                                second,
                                out geometryError);
                        }
                        if (!geometryValid)
                        {
                            topologyIssues.Add(
                                fittingKind.ToUpperInvariant()
                                + "_GEOMETRY_INVALID:"
                                + fittingId);
                        }
                    }
                }
                bool pipeResultsValid = results.All(item => Convert.ToBoolean(
                    item.GetType().GetProperty("valid").GetValue(item, null)));
                var validationResponse = new Dictionary<string, object>
                {
                    { "action", action },
                    { "document", SerializeDrainageDocumentRef(doc) },
                    { "operation_id", validationOperationId },
                    { "expected_slope_ratio", expectedSlope },
                    { "valid", pipeResultsValid
                        && topologyIssues.Count == 0 },
                    { "topology_issues", topologyIssues },
                    { "results", results },
                    { "validated_at_utc",
                        DateTime.UtcNow.ToString("o") }
                };
                RecordDrainageValidation(
                    validationOperation,
                    validationResponse);
                File.WriteAllText(
                    responseFile,
                    serializer.Serialize(validationResponse));
                return;
            }

            throw new InvalidOperationException(
                "UNSUPPORTED_DRAINAGE_ACTION: " + action);
        }

        private static void ValidateDrainageInputs(double slopeRatio, double diameterMm)
        {
            if (slopeRatio < 0.001 || slopeRatio > 0.10)
            {
                throw new InvalidOperationException(
                    "SLOPE_OUT_OF_RANGE: "
                    + "\u5761\u5ea6\u5fc5\u9808\u4ecb\u65bc 0.1% \u8207 10% \u4e4b\u9593\u3002");
            }
            if (diameterMm < 25 || diameterMm > 300)
            {
                throw new InvalidOperationException(
                    "DIAMETER_OUT_OF_RANGE: "
                    + "\u6e2c\u8a66\u652f\u7ba1\u7ba1\u5f91\u5fc5\u9808\u4ecb\u65bc 25 mm \u8207 300 mm \u4e4b\u9593\u3002");
            }
        }

        private static DrainageRoutePolicy CreateDefaultDrainageRoutePolicy(
            double diameterMm)
        {
            return new DrainageRoutePolicy
            {
                PolicyId = "sc-drainage-route-policy",
                PolicyVersion = "1.1.0",
                SideEntryAngleDegrees = 45,
                SideEntryToleranceDegrees = 5,
                RadialMinimumDegrees = 0,
                RadialMaximumDegrees = 45,
                RadialToleranceDegrees = 5,
                MinimumTangentMm = diameterMm,
                MinimumJunctionSpacingMm = Math.Max(300, diameterMm * 3.0),
                CollisionClearanceMm = 25,
                MaximumDouble45LateralOffsetMm = 25
            };
        }

        private static DrainageRoutePolicy ReadDrainageRoutePolicy(
            Dictionary<string, object> payload,
            double diameterMm)
        {
            DrainageRoutePolicy policy =
                CreateDefaultDrainageRoutePolicy(diameterMm);
            Dictionary<string, object> source = null;
            if (payload != null
                && payload.ContainsKey("route_policy")
                && payload["route_policy"] != null)
            {
                source = payload["route_policy"] as Dictionary<string, object>;
                if (source == null)
                {
                    throw new InvalidOperationException(
                        "ROUTE_POLICY_INVALID");
                }
            }
            if (source == null)
            {
                return policy;
            }
            policy.PolicyId = ReadDrainageString(
                source,
                "route_policy_id");
            policy.PolicyVersion = ReadDrainageString(
                source,
                "route_policy_version");
            policy.SideEntryAngleDegrees = ReadDouble(
                source,
                "side_entry_angle_degrees",
                policy.SideEntryAngleDegrees);
            policy.SideEntryToleranceDegrees = ReadDouble(
                source,
                "side_entry_tolerance_degrees",
                policy.SideEntryToleranceDegrees);
            policy.RadialMinimumDegrees = ReadDouble(
                source,
                "radial_minimum_degrees",
                policy.RadialMinimumDegrees);
            policy.RadialMaximumDegrees = ReadDouble(
                source,
                "radial_maximum_degrees",
                policy.RadialMaximumDegrees);
            policy.RadialToleranceDegrees = ReadDouble(
                source,
                "radial_tolerance_degrees",
                policy.RadialToleranceDegrees);
            policy.MinimumTangentMm = ReadDouble(
                source,
                "minimum_tangent_mm",
                policy.MinimumTangentMm);
            policy.MinimumJunctionSpacingMm = ReadDouble(
                source,
                "minimum_junction_spacing_mm",
                policy.MinimumJunctionSpacingMm);
            policy.CollisionClearanceMm = ReadDouble(
                source,
                "collision_clearance_mm",
                policy.CollisionClearanceMm);
            policy.MaximumDouble45LateralOffsetMm = ReadDouble(
                source,
                "maximum_double45_lateral_offset_mm",
                policy.MaximumDouble45LateralOffsetMm);
            return policy;
        }

        private static void ValidateDrainageRoutePolicy(
            DrainageRoutePolicy policy)
        {
            if (policy == null)
            {
                throw new InvalidOperationException("ROUTE_POLICY_REQUIRED");
            }
            if (!string.Equals(
                    policy.PolicyId,
                    "sc-drainage-route-policy",
                    StringComparison.Ordinal)
                || !string.Equals(
                    policy.PolicyVersion,
                    "1.1.0",
                    StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "ROUTE_POLICY_VERSION_UNSUPPORTED");
            }
            if (Math.Abs(policy.SideEntryAngleDegrees - 45) > 0.001
                || policy.SideEntryToleranceDegrees < 0
                || policy.SideEntryToleranceDegrees > 15)
            {
                throw new InvalidOperationException(
                    "ROUTE_POLICY_SIDE_ENTRY_INVALID");
            }
            if (policy.RadialMinimumDegrees < -15
                || policy.RadialMaximumDegrees > 90
                || policy.RadialMinimumDegrees > policy.RadialMaximumDegrees
                || policy.RadialToleranceDegrees < 0
                || policy.RadialToleranceDegrees > 15)
            {
                throw new InvalidOperationException(
                    "ROUTE_POLICY_RADIAL_INVALID");
            }
            if (policy.MinimumTangentMm < 25
                || policy.MinimumTangentMm > 3000
                || policy.MinimumJunctionSpacingMm < 100
                || policy.MinimumJunctionSpacingMm > 10000
                || policy.CollisionClearanceMm < 0
                || policy.CollisionClearanceMm > 1000
                || policy.MaximumDouble45LateralOffsetMm < 0
                || policy.MaximumDouble45LateralOffsetMm > 1000)
            {
                throw new InvalidOperationException(
                    "ROUTE_POLICY_CLEARANCE_INVALID");
            }
        }

        private static Dictionary<string, object> SerializeDrainageRoutePolicy(
            DrainageRoutePolicy policy)
        {
            return new Dictionary<string, object>
            {
                { "route_policy_id", policy.PolicyId },
                { "route_policy_version", policy.PolicyVersion },
                { "side_entry_angle_degrees", policy.SideEntryAngleDegrees },
                { "side_entry_tolerance_degrees", policy.SideEntryToleranceDegrees },
                { "radial_minimum_degrees", policy.RadialMinimumDegrees },
                { "radial_maximum_degrees", policy.RadialMaximumDegrees },
                { "radial_tolerance_degrees", policy.RadialToleranceDegrees },
                { "minimum_tangent_mm", policy.MinimumTangentMm },
                { "minimum_junction_spacing_mm", policy.MinimumJunctionSpacingMm },
                { "collision_clearance_mm", policy.CollisionClearanceMm },
                { "maximum_double45_lateral_offset_mm",
                    policy.MaximumDouble45LateralOffsetMm }
            };
        }

        private static void ApplyDrainagePlanSetRules(
            List<DrainagePlan> plans,
            DrainageRoutingPart junctionPart,
            DrainageRoutePolicy policy)
        {
            if (plans == null || plans.Count < 2)
            {
                return;
            }
            double runTakeoutMm = junctionPart == null
                ? 0
                : junctionPart.MeasuredRunTakeoutMm.GetValueOrDefault(
                    junctionPart.MeasuredTakeoutMm.GetValueOrDefault(0));
            double requiredMm = Math.Max(
                policy.MinimumJunctionSpacingMm,
                runTakeoutMm * 2.0 + policy.MinimumTangentMm);
            double required = UnitUtils.ConvertToInternalUnits(
                requiredMm,
                UnitTypeId.Millimeters);
            for (int firstIndex = 0;
                firstIndex < plans.Count - 1;
                firstIndex++)
            {
                for (int secondIndex = firstIndex + 1;
                    secondIndex < plans.Count;
                    secondIndex++)
                {
                    DrainagePlan first = plans[firstIndex];
                    DrainagePlan second = plans[secondIndex];
                    if (first.MainTie.DistanceTo(second.MainTie) + 0.000001
                        >= required)
                    {
                        continue;
                    }
                    if (!first.Issues.Contains(
                        "JUNCTION_CLEARANCE_CONFLICT"))
                    {
                        first.Issues.Add("JUNCTION_CLEARANCE_CONFLICT");
                    }
                    if (!second.Issues.Contains(
                        "JUNCTION_CLEARANCE_CONFLICT"))
                    {
                        second.Issues.Add("JUNCTION_CLEARANCE_CONFLICT");
                    }
                }
            }
        }

        private static List<DrainagePlan>
            OrderDrainagePlansAlongDownstream(
                Pipe mainPipe,
                List<DrainagePlan> plans)
        {
            if (mainPipe == null || plans == null || plans.Count == 0)
            {
                return plans ?? new List<DrainagePlan>();
            }
            LocationCurve location = mainPipe.Location as LocationCurve;
            if (location == null)
            {
                return plans;
            }
            XYZ end0 = location.Curve.GetEndPoint(0);
            XYZ end1 = location.Curve.GetEndPoint(1);
            List<int> downstreamIndices = plans
                .Select(item => item.DownstreamEndpointIndex)
                .Where(index => index == 0 || index == 1)
                .Distinct()
                .ToList();
            if (downstreamIndices.Count != 1)
            {
                List<DrainagePlan> stable = plans
                    .OrderBy(item => item.SourceElement.Id.Value)
                    .ToList();
                for (int index = 0; index < stable.Count; index++)
                {
                    stable[index].SequenceIndex = index + 1;
                }
                return stable;
            }
            int downstreamIndex = downstreamIndices[0];
            XYZ upstream = downstreamIndex == 0 ? end1 : end0;
            XYZ downstream = downstreamIndex == 0 ? end0 : end1;
            XYZ direction = downstream - upstream;
            if (direction.IsZeroLength())
            {
                return plans;
            }
            direction = direction.Normalize();
            List<DrainagePlan> ordered = plans
                .OrderBy(item =>
                    (item.MainTie - upstream).DotProduct(direction))
                .ThenBy(item => item.SourceElement.Id.Value)
                .ToList();
            for (int index = 0; index < ordered.Count; index++)
            {
                ordered[index].SequenceIndex = index + 1;
            }
            return ordered;
        }

        private static void ApplyDrainagePlanToPlanClearanceRules(
            List<DrainagePlan> plans,
            double diameterMm,
            DrainageRoutePolicy policy)
        {
            if (plans == null || plans.Count < 2)
            {
                return;
            }
            double required = UnitUtils.ConvertToInternalUnits(
                diameterMm + policy.CollisionClearanceMm,
                UnitTypeId.Millimeters);
            for (int firstIndex = 0;
                firstIndex < plans.Count - 1;
                firstIndex++)
            {
                List<XYZ> firstPoints =
                    GetDrainagePlanPolyline(plans[firstIndex]);
                for (int secondIndex = firstIndex + 1;
                    secondIndex < plans.Count;
                    secondIndex++)
                {
                    List<XYZ> secondPoints =
                        GetDrainagePlanPolyline(plans[secondIndex]);
                    bool conflict = false;
                    for (int firstSegment = 0;
                        firstSegment < firstPoints.Count - 1
                            && !conflict;
                        firstSegment++)
                    {
                        for (int secondSegment = 0;
                            secondSegment < secondPoints.Count - 1;
                            secondSegment++)
                        {
                            double distance =
                                DrainageEngineeringCore.SegmentDistance3D(
                                    ToDrainageGeometryPoint(
                                        firstPoints[firstSegment]),
                                    ToDrainageGeometryPoint(
                                        firstPoints[firstSegment + 1]),
                                    ToDrainageGeometryPoint(
                                        secondPoints[secondSegment]),
                                    ToDrainageGeometryPoint(
                                        secondPoints[secondSegment + 1]));
                            if (distance + 0.000001 < required)
                            {
                                conflict = true;
                                break;
                            }
                        }
                    }
                    if (!conflict)
                    {
                        continue;
                    }
                    if (!plans[firstIndex].Issues.Contains(
                        "ROUTE_CLEARANCE_CONFLICT"))
                    {
                        plans[firstIndex].Issues.Add(
                            "ROUTE_CLEARANCE_CONFLICT");
                    }
                    if (!plans[secondIndex].Issues.Contains(
                        "ROUTE_CLEARANCE_CONFLICT"))
                    {
                        plans[secondIndex].Issues.Add(
                            "ROUTE_CLEARANCE_CONFLICT");
                    }
                }
            }
        }

        private static List<XYZ> GetDrainagePlanPolyline(
            DrainagePlan plan)
        {
            var points = new List<XYZ> { plan.ConnectorPoint };
            if (plan.HasConnectorStub
                && points.Last().DistanceTo(
                    plan.ConnectorStubEnd) > 0.000001)
            {
                points.Add(plan.ConnectorStubEnd);
            }
            if (points.Last().DistanceTo(
                plan.BranchStart) > 0.000001)
            {
                points.Add(plan.BranchStart);
            }
            if (points.Last().DistanceTo(plan.MainTie) > 0.000001)
            {
                points.Add(plan.MainTie);
            }
            return points;
        }

        private static void ApplyDrainageExistingPipeClearanceRules(
            Document document,
            Pipe mainPipe,
            List<DrainagePlan> plans,
            double plannedDiameterMm,
            DrainageRoutePolicy policy)
        {
            if (document == null || mainPipe == null || plans == null)
            {
                return;
            }
            double plannedRadius = UnitUtils.ConvertToInternalUnits(
                plannedDiameterMm / 2.0,
                UnitTypeId.Millimeters);
            double clearance = UnitUtils.ConvertToInternalUnits(
                policy.CollisionClearanceMm,
                UnitTypeId.Millimeters);
            List<Pipe> obstacles = new FilteredElementCollector(document)
                .OfClass(typeof(Pipe))
                .Cast<Pipe>()
                .Where(pipe => pipe.Id.Value != mainPipe.Id.Value)
                .ToList();
            foreach (DrainagePlan plan in plans)
            {
                List<XYZ> routePoints = GetDrainagePlanPolyline(plan);
                foreach (Pipe obstacle in obstacles)
                {
                    LocationCurve location =
                        obstacle.Location as LocationCurve;
                    if (location == null)
                    {
                        continue;
                    }
                    Parameter diameterParameter = obstacle.get_Parameter(
                        BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
                    double obstacleRadius = diameterParameter == null
                        ? 0
                        : diameterParameter.AsDouble() / 2.0;
                    IList<XYZ> obstaclePoints =
                        location.Curve.Tessellate();
                    bool conflicts = false;
                    for (int routeIndex = 0;
                        routeIndex < routePoints.Count - 1 && !conflicts;
                        routeIndex++)
                    {
                        for (int obstacleIndex = 0;
                            obstacleIndex < obstaclePoints.Count - 1;
                            obstacleIndex++)
                        {
                            double distance =
                                DrainageEngineeringCore.SegmentDistance3D(
                                    ToDrainageGeometryPoint(
                                        routePoints[routeIndex]),
                                    ToDrainageGeometryPoint(
                                        routePoints[routeIndex + 1]),
                                    ToDrainageGeometryPoint(
                                        obstaclePoints[obstacleIndex]),
                                    ToDrainageGeometryPoint(
                                        obstaclePoints[obstacleIndex + 1]));
                            if (!double.IsNaN(distance)
                                && distance + 0.000001
                                    < plannedRadius
                                        + obstacleRadius
                                        + clearance)
                            {
                                conflicts = true;
                                break;
                            }
                        }
                    }
                    if (!conflicts)
                    {
                        continue;
                    }
                    plan.CollisionElementIds.Add(obstacle.Id.Value);
                    if (!plan.Issues.Contains(
                        "EXISTING_PIPE_CLEARANCE_CONFLICT"))
                    {
                        plan.Issues.Add(
                            "EXISTING_PIPE_CLEARANCE_CONFLICT");
                    }
                }
            }
        }

        private static ArrayList ReadDrainageArray(
            Dictionary<string, object> source,
            string key)
        {
            if (source == null || !source.ContainsKey(key) || source[key] == null)
            {
                return null;
            }
            ArrayList array = source[key] as ArrayList;
            if (array != null)
            {
                return array;
            }
            IEnumerable values = source[key] as IEnumerable;
            return values == null || source[key] is string
                ? null
                : new ArrayList(values.Cast<object>().ToList());
        }

        private static HashSet<long> ReadDrainageLongSet(
            Dictionary<string, object> source,
            string key)
        {
            ArrayList values = ReadDrainageArray(source, key);
            return new HashSet<long>(
                (values ?? new ArrayList())
                    .Cast<object>()
                    .Where(value => value != null)
                    .Select(Convert.ToInt64));
        }

        private static long ReadDrainageElementIdParameter(
            Element element,
            BuiltInParameter builtInParameter)
        {
            Parameter parameter = element == null
                ? null
                : element.get_Parameter(builtInParameter);
            return parameter == null
                ? ElementId.InvalidElementId.Value
                : parameter.AsElementId().Value;
        }

        private static List<object> SerializeDrainageRoutingRules(
            Document doc,
            PipeType pipeType,
            RoutingPreferenceRuleGroupType groupType)
        {
            var result = new List<object>();
            if (pipeType == null || pipeType.RoutingPreferenceManager == null)
            {
                return result;
            }
            RoutingPreferenceManager manager = pipeType.RoutingPreferenceManager;
            int count = manager.GetNumberOfRules(groupType);
            for (int index = 0; index < count; index++)
            {
                RoutingPreferenceRule rule = manager.GetRule(groupType, index);
                Element part = doc.GetElement(rule.MEPPartId);
                FamilySymbol symbol = part as FamilySymbol;
                var criteria = new List<object>();
                for (int criterionIndex = 0; criterionIndex < rule.NumberOfCriteria; criterionIndex++)
                {
                    PrimarySizeCriterion size = rule.GetCriterion(criterionIndex) as PrimarySizeCriterion;
                    criteria.Add(new
                    {
                        minimum_mm = size == null
                            ? (double?)null
                            : UnitUtils.ConvertFromInternalUnits(size.MinimumSize, UnitTypeId.Millimeters),
                        maximum_mm = size == null
                            ? (double?)null
                            : UnitUtils.ConvertFromInternalUnits(size.MaximumSize, UnitTypeId.Millimeters)
                    });
                }
                result.Add(new
                {
                    order = index,
                    element_id = rule.MEPPartId.Value,
                    unique_id = part == null ? "" : part.UniqueId,
                    name = part == null ? "" : part.Name,
                    family_name = symbol == null ? "" : symbol.FamilyName,
                    criteria = criteria
                });
            }
            return result;
        }

        private static DrainageRoutingPart ResolveDrainageRoutingPart(
            Document doc,
            PipeType pipeType,
            RoutingPreferenceRuleGroupType groupType,
            double diameterMm,
            long requestedPartId,
            string requestedPartUniqueId)
        {
            // RoutingPreferenceManager resolves Junctions/Elbows by ordered rules
            // and PrimarySizeCriterion ranges.
            // Source: https://help.autodesk.com/cloudhelp/2024/ESP/Revit-API/files/Revit_API_Developers_Guide/Discipline_Specific_Functionality/MEP_Engineering/Revit_API_Revit_API_Developers_Guide_Discipline_Specific_Functionality_MEP_Engineering_Routing_Preferences_html.html
            if (pipeType == null || pipeType.RoutingPreferenceManager == null)
            {
                return null;
            }
            double diameterFeet = UnitUtils.ConvertToInternalUnits(diameterMm, UnitTypeId.Millimeters);
            RoutingPreferenceManager manager = pipeType.RoutingPreferenceManager;
            int count = manager.GetNumberOfRules(groupType);
            for (int index = 0; index < count; index++)
            {
                RoutingPreferenceRule rule = manager.GetRule(groupType, index);
                if (requestedPartId <= 0
                    || string.IsNullOrWhiteSpace(
                        requestedPartUniqueId))
                {
                    throw new InvalidOperationException(
                        "FITTING_PROFILE_REQUIRED");
                }
                if (rule.MEPPartId.Value != requestedPartId)
                {
                    continue;
                }
                bool matches = rule.NumberOfCriteria == 0;
                for (int criterionIndex = 0; criterionIndex < rule.NumberOfCriteria; criterionIndex++)
                {
                    PrimarySizeCriterion size = rule.GetCriterion(criterionIndex) as PrimarySizeCriterion;
                    if (size != null
                        && diameterFeet >= size.MinimumSize
                        && diameterFeet <= size.MaximumSize)
                    {
                        matches = true;
                    }
                }
                if (!matches)
                {
                    continue;
                }
                Element part = doc.GetElement(rule.MEPPartId);
                if (part == null
                    || !string.Equals(
                        part.UniqueId,
                        requestedPartUniqueId,
                        StringComparison.Ordinal))
                {
                    throw new InvalidOperationException(
                        "FITTING_PROFILE_IDENTITY_MISMATCH");
                }
                FamilySymbol symbol = part as FamilySymbol;
                var resolved = new DrainageRoutingPart
                {
                    PartId = rule.MEPPartId,
                    PartUniqueId = part == null ? "" : part.UniqueId,
                    Name = part == null ? "" : part.Name,
                    FamilyName = symbol == null ? "" : symbol.FamilyName,
                    RuleOrder = index,
                    TakeoutEvidenceKind = "unresolved"
                };
                double measuredTakeoutMm;
                double measuredRunTakeoutMm;
                long evidenceElementId;
                string evidenceKind;
                string geometryHash;
                if (TryMeasureDrainageRoutingPartTakeout(
                    doc,
                    resolved.PartId,
                    groupType,
                    diameterMm,
                    out measuredTakeoutMm,
                    out measuredRunTakeoutMm,
                    out evidenceElementId,
                    out evidenceKind,
                    out geometryHash))
                {
                    resolved.MeasuredTakeoutMm = measuredTakeoutMm;
                    resolved.MeasuredRunTakeoutMm =
                        measuredRunTakeoutMm;
                    resolved.TakeoutEvidenceElementId = evidenceElementId;
                    resolved.TakeoutEvidenceKind = evidenceKind;
                    resolved.TakeoutGeometryHash = geometryHash;
                    return resolved;
                }
            }
            return null;
        }

        private static object SerializeDrainageRoutingPart(DrainageRoutingPart part)
        {
            if (part == null)
            {
                return null;
            }
            return new
            {
                element_id = part.PartId.Value,
                unique_id = part.PartUniqueId,
                name = part.Name,
                family_name = part.FamilyName,
                rule_order = part.RuleOrder,
                measured_takeout_mm = part.MeasuredTakeoutMm,
                measured_run_takeout_mm = part.MeasuredRunTakeoutMm,
                takeout_evidence_element_id = part.TakeoutEvidenceElementId,
                takeout_evidence_kind = part.TakeoutEvidenceKind,
                takeout_geometry_hash = part.TakeoutGeometryHash
            };
        }

        private static bool TryMeasureDrainageRoutingPartTakeout(
            Document doc,
            ElementId partTypeId,
            RoutingPreferenceRuleGroupType groupType,
            double diameterMm,
            out double measuredTakeoutMm,
            out double measuredRunTakeoutMm,
            out long evidenceElementId,
            out string evidenceKind,
            out string geometryHash)
        {
            measuredTakeoutMm = double.NaN;
            measuredRunTakeoutMm = double.NaN;
            evidenceElementId = 0;
            evidenceKind = "unresolved";
            geometryHash = "";
            double diameterToleranceMm = 1.0;
            double intersectionTolerance = UnitUtils.ConvertToInternalUnits(
                2,
                UnitTypeId.Millimeters);
            foreach (FamilyInstance instance in new FilteredElementCollector(doc)
                .OfClass(typeof(FamilyInstance))
                .Cast<FamilyInstance>()
                .Where(item => item.GetTypeId() == partTypeId))
            {
                if (instance.MEPModel == null
                    || instance.MEPModel.ConnectorManager == null)
                {
                    continue;
                }
                List<Connector> connectors = instance.MEPModel.ConnectorManager
                    .Connectors
                    .Cast<Connector>()
                    .Where(connector =>
                        connector.ConnectorType == ConnectorType.End
                        && SafeConnectorDiameterMm(connector).HasValue
                        && Math.Abs(
                            SafeConnectorDiameterMm(connector).Value
                            - diameterMm) <= diameterToleranceMm)
                    .ToList();
                double takeoutFeet = double.NaN;
                double runTakeoutFeet = double.NaN;
                bool measured = groupType == RoutingPreferenceRuleGroupType.Elbows
                    ? TryMeasureElbowTakeout(
                        connectors,
                        intersectionTolerance,
                        out takeoutFeet)
                    : groupType == RoutingPreferenceRuleGroupType.Junctions
                        && TryMeasureJunctionBranchTakeout(
                            connectors,
                            intersectionTolerance,
                            out takeoutFeet,
                            out runTakeoutFeet);
                if (!measured || takeoutFeet <= 0)
                {
                    continue;
                }
                measuredTakeoutMm = UnitUtils.ConvertFromInternalUnits(
                    takeoutFeet,
                    UnitTypeId.Millimeters);
                measuredRunTakeoutMm = groupType
                    == RoutingPreferenceRuleGroupType.Junctions
                    ? UnitUtils.ConvertFromInternalUnits(
                        runTakeoutFeet,
                        UnitTypeId.Millimeters)
                    : measuredTakeoutMm;
                evidenceElementId = instance.Id.Value;
                evidenceKind = "existing_instance";
                geometryHash = ComputeDrainageFittingGeometryHash(
                    instance,
                    connectors,
                    measuredTakeoutMm,
                    measuredRunTakeoutMm);
                return true;
            }
            return TryProbeDrainageRoutingPartTakeout(
                doc,
                partTypeId,
                groupType,
                diameterMm,
                out measuredTakeoutMm,
                out measuredRunTakeoutMm,
                out evidenceKind,
                out geometryHash);
        }

        private static bool TryProbeDrainageRoutingPartTakeout(
            Document doc,
            ElementId partTypeId,
            RoutingPreferenceRuleGroupType groupType,
            double diameterMm,
            out double measuredTakeoutMm,
            out double measuredRunTakeoutMm,
            out string evidenceKind,
            out string geometryHash)
        {
            measuredTakeoutMm = double.NaN;
            measuredRunTakeoutMm = double.NaN;
            evidenceKind = "unresolved";
            geometryHash = "";
            FamilySymbol symbol = doc == null
                ? null
                : doc.GetElement(partTypeId) as FamilySymbol;
            if (symbol == null
                || symbol.Category == null
                || symbol.Category.Id.Value
                    != (long)BuiltInCategory.OST_PipeFitting
                || (groupType != RoutingPreferenceRuleGroupType.Elbows
                    && groupType
                        != RoutingPreferenceRuleGroupType.Junctions)
                || doc.IsModifiable)
            {
                return false;
            }
            // Autodesk requires all temporary model changes to be enclosed in
            // a Transaction; rolling it back discards the probe completely.
            // Source: https://help.autodesk.com/cloudhelp/2024/ESP/Revit-API/files/Revit_API_Developers_Guide/Basic_Interaction_with_Revit_Elements/Revit_API_Revit_API_Developers_Guide_Basic_Interaction_with_Revit_Elements_Transactions_html.html
            using (Transaction probe = new Transaction(
                doc,
                "SC Drainage fitting profile probe"))
            {
                try
                {
                    if (probe.Start() != TransactionStatus.Started)
                    {
                        return false;
                    }
                    if (!symbol.IsActive)
                    {
                        symbol.Activate();
                        doc.Regenerate();
                    }
                    FamilyInstance instance = doc.Create.NewFamilyInstance(
                        XYZ.Zero,
                        symbol,
                        StructuralType.NonStructural);
                    doc.Regenerate();
                    List<Connector> connectors =
                        GetDrainageFittingEndConnectors(instance);
                    int expectedConnectorCount =
                        groupType
                            == RoutingPreferenceRuleGroupType.Elbows
                            ? 2
                            : 3;
                    if (connectors.Count != expectedConnectorCount
                        || connectors.Any(connector =>
                            connector.Domain != Domain.DomainPiping
                            || connector.Shape
                                != ConnectorProfileType.Round))
                    {
                        return false;
                    }
                    double radius = UnitUtils.ConvertToInternalUnits(
                        diameterMm / 2.0,
                        UnitTypeId.Millimeters);
                    foreach (Connector connector in connectors)
                    {
                        connector.Radius = radius;
                    }
                    doc.Regenerate();
                    connectors = GetDrainageFittingEndConnectors(instance);
                    double takeoutFeet;
                    double runTakeoutFeet = double.NaN;
                    double intersectionTolerance =
                        UnitUtils.ConvertToInternalUnits(
                            2,
                            UnitTypeId.Millimeters);
                    bool measured =
                        groupType
                            == RoutingPreferenceRuleGroupType.Elbows
                            ? TryMeasureElbowTakeout(
                                connectors,
                                intersectionTolerance,
                                out takeoutFeet)
                            : TryMeasureJunctionBranchTakeout(
                                connectors,
                                intersectionTolerance,
                                out takeoutFeet,
                                out runTakeoutFeet);
                    if (!measured || takeoutFeet <= 0)
                    {
                        return false;
                    }
                    measuredTakeoutMm =
                        UnitUtils.ConvertFromInternalUnits(
                            takeoutFeet,
                            UnitTypeId.Millimeters);
                    measuredRunTakeoutMm =
                        groupType
                            == RoutingPreferenceRuleGroupType.Junctions
                            ? UnitUtils.ConvertFromInternalUnits(
                                runTakeoutFeet,
                                UnitTypeId.Millimeters)
                            : measuredTakeoutMm;
                    geometryHash =
                        ComputeDrainageFittingGeometryHash(
                            instance,
                            connectors,
                            measuredTakeoutMm,
                            measuredRunTakeoutMm);
                    evidenceKind = "rollback_probe";
                    return true;
                }
                catch
                {
                    return false;
                }
                finally
                {
                    if (probe.GetStatus() == TransactionStatus.Started)
                    {
                        probe.RollBack();
                    }
                }
            }
        }

        private static string ComputeDrainageFittingGeometryHash(
            FamilyInstance instance,
            IEnumerable<Connector> connectors,
            double measuredTakeoutMm,
            double measuredRunTakeoutMm)
        {
            var material = new StringBuilder();
            material.Append(instance.GetTypeId().Value).Append('|');
            material.Append(measuredTakeoutMm.ToString(
                "R",
                System.Globalization.CultureInfo.InvariantCulture)).Append('|');
            material.Append(measuredRunTakeoutMm.ToString(
                "R",
                System.Globalization.CultureInfo.InvariantCulture)).Append('|');
            foreach (Connector connector in connectors
                .OrderBy(item => item.Id))
            {
                XYZ axis = SafeConnectorAxis(connector);
                material.Append(
                    SafeConnectorDiameterMm(connector).GetValueOrDefault()
                        .ToString(
                            "R",
                            System.Globalization.CultureInfo.InvariantCulture))
                    .Append(':')
                    .Append(axis.X.ToString(
                        "R",
                        System.Globalization.CultureInfo.InvariantCulture))
                    .Append(',')
                    .Append(axis.Y.ToString(
                        "R",
                        System.Globalization.CultureInfo.InvariantCulture))
                    .Append(',')
                    .Append(axis.Z.ToString(
                        "R",
                        System.Globalization.CultureInfo.InvariantCulture))
                    .Append('|');
            }
            using (SHA256 sha = SHA256.Create())
            {
                byte[] digest = sha.ComputeHash(
                    Encoding.UTF8.GetBytes(material.ToString()));
                return "sha256:"
                    + BitConverter.ToString(digest)
                        .Replace("-", "")
                        .ToLowerInvariant();
            }
        }

        private static bool TryMeasureElbowTakeout(
            IList<Connector> connectors,
            double intersectionTolerance,
            out double takeout)
        {
            takeout = double.NaN;
            if (connectors == null || connectors.Count != 2)
            {
                return false;
            }
            XYZ firstAxis = SafeConnectorAxis(connectors[0]);
            XYZ secondAxis = SafeConnectorAxis(connectors[1]);
            double elbowAngle = DrainageEngineeringCore.AxialAngleDegrees(
                firstAxis.X,
                firstAxis.Y,
                firstAxis.Z,
                secondAxis.X,
                secondAxis.Y,
                secondAxis.Z);
            if (!DrainageEngineeringCore.IsSideEntryAngleAllowed(
                elbowAngle,
                45,
                2))
            {
                return false;
            }
            XYZ vertex;
            if (!TryIntersectConnectorAxes(
                connectors[0],
                connectors[1],
                intersectionTolerance,
                out vertex))
            {
                return false;
            }
            takeout = Math.Max(
                connectors[0].Origin.DistanceTo(vertex),
                connectors[1].Origin.DistanceTo(vertex));
            return takeout > 0;
        }

        private static bool TryMeasureJunctionBranchTakeout(
            IList<Connector> connectors,
            double intersectionTolerance,
            out double takeout,
            out double runTakeout)
        {
            takeout = double.NaN;
            runTakeout = double.NaN;
            if (connectors == null || connectors.Count != 3)
            {
                return false;
            }
            for (int first = 0; first < connectors.Count; first++)
            {
                for (int second = first + 1; second < connectors.Count; second++)
                {
                    XYZ firstAxis = SafeConnectorAxis(connectors[first]);
                    XYZ secondAxis = SafeConnectorAxis(connectors[second]);
                    double axialAngle = DrainageEngineeringCore.AxialAngleDegrees(
                        firstAxis.X,
                        firstAxis.Y,
                        firstAxis.Z,
                        secondAxis.X,
                        secondAxis.Y,
                        secondAxis.Z);
                    if (double.IsNaN(axialAngle) || axialAngle > 5)
                    {
                        continue;
                    }
                    int branchIndex = 3 - first - second;
                    XYZ vertex;
                    if (!TryIntersectConnectorAxes(
                        connectors[first],
                        connectors[branchIndex],
                        intersectionTolerance,
                        out vertex))
                    {
                        continue;
                    }
                    XYZ branchAxis = SafeConnectorAxis(
                        connectors[branchIndex]);
                    double branchAngle = DrainageEngineeringCore
                        .AxialAngleDegrees(
                            firstAxis.X,
                            firstAxis.Y,
                            firstAxis.Z,
                            branchAxis.X,
                            branchAxis.Y,
                            branchAxis.Z);
                    if (!DrainageEngineeringCore.IsSideEntryAngleAllowed(
                        branchAngle,
                        45,
                        2))
                    {
                        continue;
                    }
                    takeout = connectors[branchIndex].Origin.DistanceTo(vertex);
                    runTakeout = Math.Max(
                        connectors[first].Origin.DistanceTo(vertex),
                        connectors[second].Origin.DistanceTo(vertex));
                    return takeout > 0 && runTakeout > 0;
                }
            }
            return false;
        }

        private static bool TryIntersectConnectorAxes(
            Connector first,
            Connector second,
            double tolerance,
            out XYZ vertex)
        {
            vertex = XYZ.Zero;
            XYZ firstAxis = SafeConnectorAxis(first);
            XYZ secondAxis = SafeConnectorAxis(second);
            if (firstAxis.IsZeroLength() || secondAxis.IsZeroLength())
            {
                return false;
            }
            XYZ delta = first.Origin - second.Origin;
            double axisDot = firstAxis.DotProduct(secondAxis);
            double firstDelta = firstAxis.DotProduct(delta);
            double secondDelta = secondAxis.DotProduct(delta);
            double denominator = 1.0 - axisDot * axisDot;
            if (Math.Abs(denominator) <= 0.000001)
            {
                return false;
            }
            double firstParameter = (
                axisDot * secondDelta - firstDelta)
                / denominator;
            double secondParameter = (
                secondDelta - axisDot * firstDelta)
                / denominator;
            XYZ firstPoint =
                first.Origin + firstAxis * firstParameter;
            XYZ secondPoint =
                second.Origin + secondAxis * secondParameter;
            if (firstPoint.DistanceTo(secondPoint) > tolerance)
            {
                return false;
            }
            vertex = (firstPoint + secondPoint) / 2.0;
            return true;
        }

        private static List<Element> ReadDrainageFixtures(
            Document doc,
            Dictionary<string, object> payload)
        {
            ArrayList rawIds = payload.ContainsKey("fixture_ids") ? payload["fixture_ids"] as ArrayList : null;
            var fixtures = new List<Element>();
            if (rawIds == null)
            {
                return fixtures;
            }
            foreach (object rawId in rawIds)
            {
                Element source = doc.GetElement(
                    new ElementId(Convert.ToInt64(rawId)));
                if (IsPlumbingFixture(source as FamilyInstance)
                    || IsDrainagePipeSource(source as Pipe))
                {
                    fixtures.Add(source);
                }
            }
            return fixtures;
        }

        private static void ValidateDrainagePreviewElementIdentities(
            Document doc,
            Dictionary<string, object> payload,
            Pipe mainPipe,
            IList<Element> fixtures)
        {
            string selectionSource = ReadDrainageString(
                payload,
                "selection_source");
            long mainCandidateCount = ReadLong(
                payload,
                "main_candidate_count",
                0);
            if ((selectionSource != "current_selection"
                    && selectionSource != "search_result"
                    && selectionSource != "explicit_user_refs")
                || mainCandidateCount != 1)
            {
                throw new InvalidOperationException(
                    "MAIN_CANDIDATE_AMBIGUOUS");
            }
            if (selectionSource == "search_result")
            {
                RequireDrainageCandidateSetGrant(
                    doc,
                    ReadDrainageString(
                        payload,
                        "candidate_set_token"),
                    mainPipe,
                    fixtures);
            }
            string requestedMainUniqueId = ReadDrainageString(
                payload,
                "main_pipe_unique_id");
            if (string.IsNullOrWhiteSpace(requestedMainUniqueId)
                || !string.Equals(
                    requestedMainUniqueId,
                    mainPipe.UniqueId,
                    StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "MAIN_PIPE_IDENTITY_MISMATCH");
            }
            ArrayList rawFixtureUniqueIds = payload != null
                && payload.ContainsKey("fixture_unique_ids")
                ? payload["fixture_unique_ids"] as ArrayList
                : null;
            if (rawFixtureUniqueIds == null
                || rawFixtureUniqueIds.Count != fixtures.Count)
            {
                throw new InvalidOperationException(
                    "FIXTURE_IDENTITY_COUNT_MISMATCH");
            }
            for (int index = 0; index < fixtures.Count; index++)
            {
                string requestedUniqueId =
                    rawFixtureUniqueIds[index] == null
                        ? ""
                        : rawFixtureUniqueIds[index].ToString();
                if (!string.Equals(
                    requestedUniqueId,
                    fixtures[index].UniqueId,
                    StringComparison.Ordinal))
                {
                    throw new InvalidOperationException(
                        "FIXTURE_IDENTITY_MISMATCH:"
                        + fixtures[index].Id.Value);
                }
            }
        }

        private static void ValidateDrainagePreviewTypeIdentities(
            Dictionary<string, object> payload,
            PipeType pipeType,
            PipingSystemType systemType,
            Level level)
        {
            ValidateDrainagePreviewTypeIdentity(
                payload,
                "pipe_type_unique_id",
                pipeType,
                "PIPE_TYPE_IDENTITY_MISMATCH");
            ValidateDrainagePreviewTypeIdentity(
                payload,
                "system_type_unique_id",
                systemType,
                "SYSTEM_TYPE_IDENTITY_MISMATCH");
            ValidateDrainagePreviewTypeIdentity(
                payload,
                "level_unique_id",
                level,
                "LEVEL_IDENTITY_MISMATCH");
        }

        private static void ValidateDrainagePreviewTypeIdentity(
            Dictionary<string, object> payload,
            string payloadKey,
            Element element,
            string errorCode)
        {
            string expectedUniqueId =
                ReadDrainageString(payload, payloadKey);
            if (element == null
                || string.IsNullOrWhiteSpace(expectedUniqueId)
                || !string.Equals(
                    expectedUniqueId,
                    element.UniqueId,
                    StringComparison.Ordinal))
            {
                throw new InvalidOperationException(errorCode);
            }
        }

        private static bool IsPlumbingFixture(FamilyInstance instance)
        {
            return instance != null
                && instance.Category != null
                && instance.Category.Id.Value == (long)BuiltInCategory.OST_PlumbingFixtures;
        }

        private static bool IsDrainagePipeSource(Pipe pipe)
        {
            if (pipe == null
                || pipe.ConnectorManager == null
                || !DrainageSourceResolver.IsVerticalPipe(pipe))
            {
                return false;
            }
            return pipe.ConnectorManager.Connectors
                .Cast<Connector>()
                .Any(connector =>
                    connector.Domain == Domain.DomainPiping
                    && connector.ConnectorType == ConnectorType.End
                    && !connector.IsConnected);
        }

        private static List<Connector> GetDrainageConnectors(FamilyInstance fixture)
        {
            var result = new List<Connector>();
            if (fixture == null
                || fixture.MEPModel == null
                || fixture.MEPModel.ConnectorManager == null)
            {
                return result;
            }
            foreach (Connector connector in fixture.MEPModel.ConnectorManager.Connectors)
            {
                if (connector.Domain == Domain.DomainPiping
                    && connector.ConnectorType == ConnectorType.End)
                {
                    result.Add(connector);
                }
            }
            return result;
        }

        private static Connector ResolveDrainageConnector(FamilyInstance fixture)
        {
            List<Connector> candidates = GetDrainageConnectors(fixture);
            if (candidates.Count == 0)
            {
                throw new InvalidOperationException(
                    "FIXTURE_PIPING_CONNECTOR_MISSING: "
                    + "\u885b\u751f\u5668\u5177 " + fixture.Id.Value
                    + " \u6c92\u6709\u53ef\u7528\u7684 piping end connector\u3002");
            }
            List<Connector> sanitary = candidates.Where(connector =>
            {
                try { return connector.PipeSystemType == PipeSystemType.Sanitary; }
                catch { return false; }
            }).ToList();
            if (sanitary.Count == 1)
            {
                if (sanitary[0].IsConnected)
                {
                    throw new InvalidOperationException(
                        "FIXTURE_SANITARY_CONNECTOR_ALREADY_CONNECTED: "
                        + "\u885b\u751f\u5668\u5177 " + fixture.Id.Value
                        + " \u7684\u6c61\u6c34 connector \u5df2\u9023\u63a5\uff0c\u4e0d\u5141\u8a31\u91cd\u8907\u63a5\u7ba1\u3002");
                }
                return sanitary[0];
            }
            if (sanitary.Count > 1)
            {
                List<Connector> openSanitary = sanitary.Where(connector => !connector.IsConnected).ToList();
                if (openSanitary.Count == 1)
                {
                    return openSanitary[0];
                }
                throw new InvalidOperationException(
                    "FIXTURE_SANITARY_CONNECTOR_AMBIGUOUS: "
                    + "\u885b\u751f\u5668\u5177 " + fixture.Id.Value
                    + " \u6709\u591a\u500b\u6c61\u6c34 connector\uff0c\u7121\u6cd5\u5b89\u5168\u81ea\u52d5\u5224\u5b9a\u3002");
            }
            throw new InvalidOperationException(
                "FIXTURE_SANITARY_CONNECTOR_REQUIRED: "
                + "\u885b\u751f\u5668\u5177 " + fixture.Id.Value
                + " \u6c92\u6709\u552f\u4e00\u3001\u672a\u9023\u63a5\u7684 Sanitary connector\uff1b\u4e0d\u5141\u8a31\u4ee5\u5176\u4ed6 piping connector \u731c\u6e2c\u3002");
        }

        private static Connector ResolveDrainageSourceConnector(
            Element source,
            XYZ preferredOrigin)
        {
            FamilyInstance fixture = source as FamilyInstance;
            if (fixture != null)
            {
                return ResolveDrainageConnector(fixture);
            }
            Pipe pipe = source as Pipe;
            if (!IsDrainagePipeSource(pipe))
            {
                throw new InvalidOperationException(
                    "SOURCE_CONNECTOR_MISSING");
            }
            List<Connector> candidates = pipe.ConnectorManager.Connectors
                .Cast<Connector>()
                .Where(connector =>
                    connector.Domain == Domain.DomainPiping
                    && connector.ConnectorType == ConnectorType.End
                    && !connector.IsConnected)
                .ToList();
            if (candidates.Count == 1)
            {
                return candidates[0];
            }
            if (preferredOrigin != null
                && !preferredOrigin.IsAlmostEqualTo(XYZ.Zero))
            {
                List<Connector> ordered = candidates
                    .OrderBy(connector =>
                        connector.Origin.DistanceTo(preferredOrigin))
                    .ToList();
                double tolerance = UnitUtils.ConvertToInternalUnits(
                    50.0,
                    UnitTypeId.Millimeters);
                if (ordered.Count >= 2
                    && ordered[1].Origin.DistanceTo(preferredOrigin)
                        - ordered[0].Origin.DistanceTo(preferredOrigin)
                        > tolerance)
                {
                    return ordered[0];
                }
            }
            throw new InvalidOperationException(
                "SOURCE_CONNECTOR_AMBIGUOUS");
        }

        private static DrainagePlan BuildDrainagePlan(
            Pipe mainPipe,
            Element source,
            XYZ preferredConnectorOrigin,
            double slopeRatio,
            double diameterMm,
            string downstreamMode,
            DrainageRoutingPart junctionPart,
            DrainageRoutingPart elbowPart,
            DrainageRoutePolicy routePolicy)
        {
            LocationCurve location = mainPipe.Location as LocationCurve;
            if (location == null)
            {
                throw new InvalidOperationException(
                    "MAIN_CENTERLINE_MISSING: "
                    + "\u4e3b\u7ba1\u6c92\u6709\u53ef\u7528\u7684\u4e2d\u5fc3\u7dda\u3002");
            }
            Curve curve = location.Curve;
            XYZ mainStart = curve.GetEndPoint(0);
            XYZ mainEnd = curve.GetEndPoint(1);
            double mainHorizontal = Math.Sqrt(
                Math.Pow(mainEnd.X - mainStart.X, 2)
                + Math.Pow(mainEnd.Y - mainStart.Y, 2));
            if (mainHorizontal < 0.1 || Math.Abs(mainEnd.Z - mainStart.Z) / mainHorizontal > 0.20)
            {
                throw new InvalidOperationException(
                    "MAIN_PIPE_GEOMETRY_INVALID: "
                    + "\u4e3b\u7ba1\u5fc5\u9808\u662f\u975e\u5782\u76f4\u7ba1\u6bb5\u3002");
            }

            Connector connector = ResolveDrainageSourceConnector(
                source,
                preferredConnectorOrigin);
            XYZ connectorPoint = connector.Origin;
            XYZ connectorAxis = XYZ.Zero;
            try
            {
                connectorAxis = connector.CoordinateSystem.BasisZ.Normalize();
            }
            catch
            {
                connectorAxis = XYZ.Zero;
            }
            string outletOrientation = DrainageEngineeringCore.ClassifyConnectorAxis(
                connectorAxis.X,
                connectorAxis.Y,
                connectorAxis.Z);
            var issues = new List<string>();
            string flowDirection = SafeConnectorFlowDirection(connector);
            if (flowDirection == "In")
            {
                issues.Add("CONNECTOR_FLOW_POINTS_INTO_FIXTURE");
            }
            else if (flowDirection != "Out")
            {
                issues.Add("CONNECTOR_FLOW_UNRESOLVED");
            }
            if (connector.Shape != ConnectorProfileType.Round)
            {
                issues.Add("CONNECTOR_SHAPE_NOT_ROUND");
            }
            double? connectorDiameterMm =
                SafeConnectorDiameterMm(connector);
            if (!connectorDiameterMm.HasValue)
            {
                issues.Add("CONNECTOR_DIAMETER_UNRESOLVED");
            }
            else if (Math.Abs(connectorDiameterMm.Value - diameterMm)
                > Math.Max(1.0, diameterMm * 0.01))
            {
                issues.Add("CONNECTOR_DIAMETER_MISMATCH");
            }
            if (outletOrientation == "unknown")
            {
                issues.Add("CONNECTOR_AXIS_UNRESOLVED");
            }
            if (outletOrientation == "vertical"
                && !DrainageEngineeringCore.IsDownwardConnectorAxis(
                    connectorAxis.X,
                    connectorAxis.Y,
                    connectorAxis.Z))
            {
                issues.Add("CONNECTOR_AXIS_POINTS_UPWARD");
            }

            int downstreamEndpointIndex;
            string downstreamResolution;
            if (downstreamMode == "end0" || downstreamMode == "end1")
            {
                downstreamEndpointIndex =
                    downstreamMode == "end0" ? 0 : 1;
                downstreamResolution = "UserConfirmed";
            }
            else if (TryResolvePipeDownstreamFromConnectorFlow(
                mainPipe,
                mainStart,
                mainEnd,
                out downstreamEndpointIndex))
            {
                downstreamResolution = "ConnectorFlow";
            }
            else
            {
                downstreamEndpointIndex =
                    DrainageEngineeringCore.ResolveDownstreamEndpoint(
                        mainStart.Z,
                        mainEnd.Z,
                        mainHorizontal,
                        downstreamMode,
                        0.001);
                downstreamResolution = downstreamEndpointIndex >= 0
                    ? "GeometricSlope"
                    : "Unresolved";
            }
            if (downstreamEndpointIndex < 0)
            {
                issues.Add("MAIN_DOWNSTREAM_UNRESOLVED");
            }
            if (junctionPart == null)
            {
                issues.Add("JUNCTION_ROUTING_RULE_MISSING");
            }
            if (elbowPart == null)
            {
                issues.Add("ELBOW_ROUTING_RULE_MISSING");
            }
            XYZ routeOrigin = connectorPoint;
            XYZ connectorStubEnd = connectorPoint;
            bool hasConnectorStub = false;
            IntersectionResult connectorProjection = curve.Project(connectorPoint);
            if (connectorProjection == null)
            {
                throw new InvalidOperationException(
                    "FIXTURE_PROJECTION_FAILED: "
                    + "\u7121\u6cd5\u5c07\u885b\u751f\u5668\u5177\u6295\u5f71\u5230\u4e3b\u7ba1\u3002");
            }
            if (outletOrientation == "horizontal")
            {
                XYZ towardMain = new XYZ(
                    connectorProjection.XYZPoint.X - connectorPoint.X,
                    connectorProjection.XYZPoint.Y - connectorPoint.Y,
                    0);
                XYZ horizontalAxis = new XYZ(connectorAxis.X, connectorAxis.Y, 0);
                if (!DrainageEngineeringCore.IsConnectorAxisDirectedTowardTarget(
                    horizontalAxis.X,
                    horizontalAxis.Y,
                    towardMain.X,
                    towardMain.Y,
                    0.1))
                {
                    issues.Add("CONNECTOR_AXIS_POINTS_AWAY_FROM_MAIN");
                }
                else
                {
                    double stubLengthMm = DrainageEngineeringCore.ComputeConnectorStubLength(
                        diameterMm,
                        150,
                        2.0);
                    double stubLength = UnitUtils.ConvertToInternalUnits(
                        stubLengthMm,
                        UnitTypeId.Millimeters);
                    connectorStubEnd = connectorPoint + horizontalAxis.Normalize() * stubLength;
                    routeOrigin = connectorStubEnd;
                    hasConnectorStub = true;
                }
            }

            IntersectionResult projection = curve.Project(routeOrigin);
            if (projection == null)
            {
                throw new InvalidOperationException(
                    "FIXTURE_PROJECTION_FAILED: "
                    + "\u7121\u6cd5\u5c07\u885b\u751f\u5668\u5177\u6295\u5f71\u5230\u4e3b\u7ba1\u3002");
            }
            XYZ mainTie = projection.XYZPoint;
            string routeKind = outletOrientation == "vertical"
                ? "direct_45_side_entry"
                : outletOrientation == "horizontal"
                    ? "wall_outlet_double_45_pending"
                    : "unresolved_connector_route";
            DrainageWallRouteSolution wallSolution = null;
            bool hasDoubleFortyFive = false;
            double firstElbowAngle = double.NaN;
            double secondElbowAngle = double.NaN;
            double middleLateralOffset = 0;
            if (downstreamEndpointIndex >= 0)
            {
                XYZ downstreamPoint = downstreamEndpointIndex == 0 ? mainStart : mainEnd;
                XYZ downstreamVector = new XYZ(
                    downstreamPoint.X - mainTie.X,
                    downstreamPoint.Y - mainTie.Y,
                    0);
                double downstreamLength = downstreamVector.GetLength();
                double lateralDistance = Math.Sqrt(
                    Math.Pow(routeOrigin.X - mainTie.X, 2)
                    + Math.Pow(routeOrigin.Y - mainTie.Y, 2));
                if (downstreamLength > 0.000001 && lateralDistance > 0.000001)
                {
                    XYZ downstreamUnit = downstreamVector / downstreamLength;
                    double downstreamShift = DrainageEngineeringCore
                        .ComputeDownstreamShiftForFortyFive(lateralDistance);
                    XYZ shiftedGuess = new XYZ(
                        mainTie.X + downstreamUnit.X * downstreamShift,
                        mainTie.Y + downstreamUnit.Y * downstreamShift,
                        mainTie.Z);
                    IntersectionResult shiftedProjection = curve.Project(shiftedGuess);
                    if (shiftedProjection != null)
                    {
                        mainTie = shiftedProjection.XYZPoint;
                    }
                }
            }
            if ((outletOrientation == "horizontal"
                    || outletOrientation == "vertical")
                && downstreamEndpointIndex >= 0)
            {
                if (elbowPart == null
                    || !elbowPart.MeasuredTakeoutMm.HasValue)
                {
                    issues.Add("ELBOW_45_PROFILE_UNRESOLVED");
                }
                if (junctionPart == null
                    || !junctionPart.MeasuredTakeoutMm.HasValue)
                {
                    issues.Add("JUNCTION_45_PROFILE_UNRESOLVED");
                }
                if (elbowPart != null
                    && elbowPart.MeasuredTakeoutMm.HasValue
                    && junctionPart != null
                    && junctionPart.MeasuredTakeoutMm.HasValue)
                {
                    double minimumTangent = Math.Max(
                        mainPipe.Document.Application.ShortCurveTolerance,
                        UnitUtils.ConvertToInternalUnits(
                            routePolicy.MinimumTangentMm,
                            UnitTypeId.Millimeters));
                    double junctionRunTakeout = junctionPart
                            .MeasuredRunTakeoutMm
                            .GetValueOrDefault(
                                junctionPart.MeasuredTakeoutMm.Value);
                    double mainEndClearance = Math.Max(
                        UnitUtils.ConvertToInternalUnits(
                            150,
                            UnitTypeId.Millimeters),
                        UnitUtils.ConvertToInternalUnits(
                            junctionRunTakeout,
                            UnitTypeId.Millimeters)
                            + minimumTangent);
                    wallSolution = DrainageEngineeringCore
                        .SolveWallOutletGeneralDoubleFortyFive(
                            new DrainageWallRouteInput
                            {
                                Source = ToDrainageGeometryPoint(
                                    connectorPoint),
                                OutletX = connectorAxis.X,
                                OutletY = connectorAxis.Y,
                                OutletZ = connectorAxis.Z,
                                MainStart = ToDrainageGeometryPoint(mainStart),
                                MainEnd = ToDrainageGeometryPoint(mainEnd),
                                DownstreamEndpointIndex =
                                    downstreamEndpointIndex,
                                SlopeRatio = slopeRatio,
                                StubLength = UnitUtils
                                    .ConvertToInternalUnits(
                                        Math.Max(150, diameterMm * 2.0),
                                        UnitTypeId.Millimeters),
                                ElbowTakeout = UnitUtils
                                    .ConvertToInternalUnits(
                                        elbowPart.MeasuredTakeoutMm.Value,
                                        UnitTypeId.Millimeters),
                                JunctionBranchTakeout = UnitUtils
                                    .ConvertToInternalUnits(
                                        junctionPart.MeasuredTakeoutMm.Value,
                                        UnitTypeId.Millimeters),
                                MinimumTangentLength = minimumTangent,
                                MainEndClearance = mainEndClearance,
                                MaximumOutletAdvance = UnitUtils
                                    .ConvertToInternalUnits(
                                        25,
                                        UnitTypeId.Meters),
                                MaximumDouble45LateralOffset = UnitUtils
                                    .ConvertToInternalUnits(
                                        routePolicy
                                            .MaximumDouble45LateralOffsetMm,
                                        UnitTypeId.Millimeters),
                                SearchStep = UnitUtils.ConvertToInternalUnits(
                                    5,
                                    UnitTypeId.Millimeters)
                            });
                    if (wallSolution.IsFeasible)
                    {
                        connectorStubEnd = ToXyz(wallSolution.StubEnd);
                        routeOrigin = ToXyz(wallSolution.OffsetEnd);
                        mainTie = ToXyz(wallSolution.MainTie);
                        hasConnectorStub = true;
                        hasDoubleFortyFive = true;
                        XYZ firstDirection =
                            connectorStubEnd - connectorPoint;
                        XYZ middleDirection =
                            routeOrigin - connectorStubEnd;
                        XYZ terminalDirection = mainTie - routeOrigin;
                        firstElbowAngle =
                            DrainageEngineeringCore.AxialAngleDegrees(
                                firstDirection.X,
                                firstDirection.Y,
                                firstDirection.Z,
                                middleDirection.X,
                                middleDirection.Y,
                                middleDirection.Z);
                        secondElbowAngle =
                            DrainageEngineeringCore.AxialAngleDegrees(
                                middleDirection.X,
                                middleDirection.Y,
                                middleDirection.Z,
                                terminalDirection.X,
                                terminalDirection.Y,
                                terminalDirection.Z);
                        middleLateralOffset =
                            wallSolution.MiddleLateralOffset;
                        double lateralOffsetMm =
                            UnitUtils.ConvertFromInternalUnits(
                                middleLateralOffset,
                                UnitTypeId.Millimeters);
                        if (lateralOffsetMm
                            > routePolicy
                                .MaximumDouble45LateralOffsetMm
                                + 0.001)
                        {
                            issues.Add(
                                "DOUBLE45_OUT_OF_PLANE_LIMIT");
                        }
                        routeKind = outletOrientation == "vertical"
                            ? "floor_outlet_double_45"
                            : "wall_outlet_double_45";
                    }
                    else
                    {
                        issues.Add(wallSolution.FailureCode);
                    }
                }
            }
            double endTolerance = UnitUtils.ConvertToInternalUnits(15, UnitTypeId.Centimeters);
            if (mainTie.DistanceTo(mainStart) < endTolerance || mainTie.DistanceTo(mainEnd) < endTolerance)
            {
                throw new InvalidOperationException(
                    "MAIN_END_CLEARANCE: "
                    + "\u652f\u7ba1\u4ea4\u63a5\u9ede\u592a\u9760\u8fd1\u4e3b\u7ba1\u7aef\u9ede\uff0c\u8acb\u6539\u9078\u66f4\u9577\u7684\u4e3b\u7ba1\u6bb5\u3002");
            }
            double horizontal = Math.Sqrt(
                Math.Pow(routeOrigin.X - mainTie.X, 2)
                + Math.Pow(routeOrigin.Y - mainTie.Y, 2));
            if (horizontal < UnitUtils.ConvertToInternalUnits(30, UnitTypeId.Centimeters))
            {
                throw new InvalidOperationException(
                    "FIXTURE_TOO_CLOSE_TO_MAIN: "
                    + "\u5668\u5177\u8ddd\u96e2\u4e3b\u7ba1\u4e0d\u8db3 30 cm\uff0c\u7121\u6cd5\u5efa\u7acb\u53ef\u9a57\u8b49\u7684\u659c\u652f\u7ba1\u3002");
            }
            if (horizontal > UnitUtils.ConvertToInternalUnits(25, UnitTypeId.Meters))
            {
                throw new InvalidOperationException(
                    "FIXTURE_TOO_FAR_FROM_MAIN: "
                    + "\u5668\u5177\u8ddd\u96e2\u4e3b\u7ba1\u8d85\u904e 25 m\uff0c\u8acb\u6aa2\u67e5\u9078\u53d6\u7bc4\u570d\u3002");
            }

            XYZ branchStart = new XYZ(
                routeOrigin.X,
                routeOrigin.Y,
                mainTie.Z + horizontal * slopeRatio);
            if (hasDoubleFortyFive && wallSolution != null)
            {
                branchStart = ToXyz(wallSolution.OffsetEnd);
            }
            double sideEntryAngle = double.NaN;
            double radialEntryAngle = double.NaN;
            if (downstreamEndpointIndex >= 0)
            {
                XYZ downstreamPoint = downstreamEndpointIndex == 0 ? mainStart : mainEnd;
                sideEntryAngle = DrainageEngineeringCore.AngleBetween2D(
                    mainTie.X - branchStart.X,
                    mainTie.Y - branchStart.Y,
                    downstreamPoint.X - mainTie.X,
                    downstreamPoint.Y - mainTie.Y);
                if (!DrainageEngineeringCore.IsSideEntryAngleAllowed(
                    sideEntryAngle,
                    routePolicy.SideEntryAngleDegrees,
                    routePolicy.SideEntryToleranceDegrees))
                {
                    issues.Add("SIDE_ENTRY_ANGLE_OUTSIDE_45_PROFILE");
                }
                radialEntryAngle = DrainageEngineeringCore.RadialElevationAngleDegrees(
                    downstreamPoint.X - mainTie.X,
                    downstreamPoint.Y - mainTie.Y,
                    branchStart.X - mainTie.X,
                    branchStart.Y - mainTie.Y,
                    branchStart.Z - mainTie.Z);
                if (!DrainageEngineeringCore.IsRadialElevationAllowed(
                    radialEntryAngle,
                    routePolicy.RadialMinimumDegrees,
                    routePolicy.RadialMaximumDegrees,
                    routePolicy.RadialToleranceDegrees))
                {
                    issues.Add("RADIAL_ENTRY_OUTSIDE_SIDE_TO_45_PROFILE");
                    issues.Add("VENT_PATH_RISK");
                }
            }
            if (routeOrigin.Z + UnitUtils.ConvertToInternalUnits(1, UnitTypeId.Millimeters) < branchStart.Z)
            {
                issues.Add("FIXTURE_CONNECTOR_BELOW_ROUTE");
            }
            if (!DrainageEngineeringCore.IsExpectedDescendingSlope(
                branchStart.Z,
                mainTie.Z,
                horizontal,
                slopeRatio,
                0.000001))
            {
                issues.Add("SIGNED_SLOPE_INVALID");
            }
            double minimumCenterlineLength = Math.Max(
                mainPipe.Document.Application.ShortCurveTolerance,
                UnitUtils.ConvertToInternalUnits(diameterMm, UnitTypeId.Millimeters));
            var plannedLengths = new List<double>
            {
                branchStart.DistanceTo(mainTie)
            };
            if (hasConnectorStub)
            {
                plannedLengths.Add(connectorPoint.DistanceTo(connectorStubEnd));
                double dropLength = connectorStubEnd.DistanceTo(branchStart);
                if (dropLength > 0.000001)
                {
                    plannedLengths.Add(dropLength);
                }
            }
            else
            {
                double dropLength = connectorPoint.DistanceTo(branchStart);
                if (dropLength > 0.000001)
                {
                    plannedLengths.Add(dropLength);
                }
            }
            if (plannedLengths.Any(length => length < minimumCenterlineLength))
            {
                issues.Add("PLANNED_PIPE_CENTERLINE_TOO_SHORT");
            }
            if (!hasDoubleFortyFive
                && junctionPart != null
                && junctionPart.MeasuredTakeoutMm.HasValue)
            {
                double minimumTangent = UnitUtils.ConvertToInternalUnits(
                    routePolicy.MinimumTangentMm,
                    UnitTypeId.Millimeters);
                double junctionTakeout =
                    UnitUtils.ConvertToInternalUnits(
                        junctionPart.MeasuredTakeoutMm.Value,
                        UnitTypeId.Millimeters);
                double dropLength =
                    connectorPoint.DistanceTo(branchStart);
                double elbowTakeout =
                    dropLength > 0.000001
                        && elbowPart != null
                        && elbowPart.MeasuredTakeoutMm.HasValue
                    ? UnitUtils.ConvertToInternalUnits(
                        elbowPart.MeasuredTakeoutMm.Value,
                        UnitTypeId.Millimeters)
                    : 0;
                if (!DrainageEngineeringCore.IsPipeSegmentLengthAllowed(
                    branchStart.DistanceTo(mainTie),
                    elbowTakeout,
                    junctionTakeout,
                    minimumTangent))
                {
                    issues.Add("PLANNED_PIPE_TANGENT_TOO_SHORT");
                }
                if (dropLength > 0.000001
                    && !DrainageEngineeringCore.IsPipeSegmentLengthAllowed(
                        dropLength,
                        0,
                        elbowTakeout,
                        minimumTangent))
                {
                    if (!issues.Contains(
                        "PLANNED_PIPE_TANGENT_TOO_SHORT"))
                    {
                        issues.Add(
                            "PLANNED_PIPE_TANGENT_TOO_SHORT");
                    }
                }
            }
            var routeElevations = new List<double> { connectorPoint.Z };
            if (hasConnectorStub)
            {
                routeElevations.Add(connectorStubEnd.Z);
            }
            routeElevations.Add(branchStart.Z);
            routeElevations.Add(mainTie.Z);
            if (!DrainageEngineeringCore.IsMonotonicDescending(
                routeElevations,
                UnitUtils.ConvertToInternalUnits(1, UnitTypeId.Millimeters)))
            {
                issues.Add("LOCAL_RISE");
                issues.Add("VENT_PATH_RISK");
            }
            return new DrainagePlan
            {
                SourceElement = source,
                FixtureConnector = connector,
                ConnectorPoint = connectorPoint,
                ConnectorStubEnd = connectorStubEnd,
                HasConnectorStub = hasConnectorStub,
                HasDoubleFortyFive = hasDoubleFortyFive,
                BranchStart = branchStart,
                MainTie = mainTie,
                HorizontalLength = horizontal,
                VerticalDrop = hasDoubleFortyFive
                    ? connectorStubEnd.Z - branchStart.Z
                    : routeOrigin.Z - branchStart.Z,
                SlopeRatio = slopeRatio,
                ConnectorAxis = connectorAxis,
                OutletOrientation = outletOrientation,
                RouteKind = routeKind,
                DownstreamEndpointIndex = downstreamEndpointIndex,
                DownstreamPoint = downstreamEndpointIndex == 0 ? mainStart
                    : downstreamEndpointIndex == 1 ? mainEnd
                    : XYZ.Zero,
                DownstreamResolution = downstreamResolution,
                SideEntryAngleDegrees = sideEntryAngle,
                RadialEntryAngleDegrees = radialEntryAngle,
                StubTangentLength = hasDoubleFortyFive
                    ? wallSolution.OutletAdvance
                        - UnitUtils.ConvertToInternalUnits(
                            elbowPart.MeasuredTakeoutMm.Value,
                            UnitTypeId.Millimeters)
                    : (double?)null,
                MiddleTangentLength = hasDoubleFortyFive
                    ? wallSolution.DiagonalTangentLength
                    : (double?)null,
                BranchTangentLength = hasDoubleFortyFive
                    ? wallSolution.BranchTangentLength
                    : (double?)null,
                FirstElbowAngleDegrees = firstElbowAngle,
                SecondElbowAngleDegrees = secondElbowAngle,
                MiddleLateralOffset = middleLateralOffset,
                CollisionElementIds = new List<long>(),
                Issues = issues
            };
        }

        private static object SerializeDrainageFixture(FamilyInstance fixture)
        {
            List<Connector> connectors = GetDrainageConnectors(fixture);
            return new
            {
                element_id = fixture.Id.Value,
                unique_id = fixture.UniqueId,
                family_name = fixture.Symbol != null ? fixture.Symbol.FamilyName : "",
                type_name = fixture.Symbol != null ? fixture.Symbol.Name : "",
                connector_count = connectors.Count,
                connectors = connectors.Select(connector => new
                {
                    origin = SerializePoint(connector.Origin),
                    axis = SerializePoint(SafeConnectorAxis(connector)),
                    is_connected = connector.IsConnected,
                    pipe_system_type = SafePipeSystemType(connector),
                    flow_direction = SafeConnectorFlowDirection(connector),
                    shape = connector.Shape.ToString(),
                    diameter_mm = SafeConnectorDiameterMm(connector)
                }).ToList()
            };
        }

        private static void RequireDrainageExpectedDocument(
            Document document,
            Dictionary<string, object> payload)
        {
            string expectedFingerprint = ReadDrainageString(
                payload,
                "document_fingerprint");
            long expectedRevision = ReadLong(
                payload,
                "document_revision",
                -1);
            if (string.IsNullOrWhiteSpace(expectedFingerprint)
                || expectedRevision < 0)
            {
                throw new InvalidOperationException(
                    "EXPECTED_DOCUMENT_REQUIRED");
            }
            DrainageDocumentBinding actual =
                GetDrainageDocumentBinding(document);
            if (!string.Equals(
                    actual.Fingerprint,
                    expectedFingerprint,
                    StringComparison.Ordinal)
                || actual.Revision != expectedRevision)
            {
                throw new InvalidOperationException(
                    "EXPECTED_DOCUMENT_MISMATCH");
            }
        }

        private static void RequireDrainageExpectedDocumentIdentity(
            Document document,
            Dictionary<string, object> payload)
        {
            string expectedFingerprint = ReadDrainageString(
                payload,
                "document_fingerprint");
            long expectedRevision = ReadLong(
                payload,
                "document_revision",
                -1);
            DrainageDocumentBinding actual =
                GetDrainageDocumentBinding(document);
            if (string.IsNullOrWhiteSpace(expectedFingerprint)
                || expectedRevision < 0
                || !string.Equals(
                    actual.Fingerprint,
                    expectedFingerprint,
                    StringComparison.Ordinal)
                || actual.Revision < expectedRevision)
            {
                throw new InvalidOperationException(
                    "EXPECTED_DOCUMENT_MISMATCH");
            }
        }

        private static double? SafeConnectorDiameterMm(Connector connector)
        {
            try
            {
                if (connector.Shape != ConnectorProfileType.Round)
                {
                    return null;
                }
                return UnitUtils.ConvertFromInternalUnits(
                    connector.Radius * 2.0,
                    UnitTypeId.Millimeters);
            }
            catch
            {
                return null;
            }
        }

        private static XYZ SafeConnectorAxis(Connector connector)
        {
            try { return connector.CoordinateSystem.BasisZ.Normalize(); }
            catch { return XYZ.Zero; }
        }

        private static string SafePipeSystemType(Connector connector)
        {
            try { return connector.PipeSystemType.ToString(); }
            catch { return ""; }
        }

        private static string SafeConnectorFlowDirection(Connector connector)
        {
            try { return connector.Direction.ToString(); }
            catch { return ""; }
        }

        private static bool TryResolvePipeDownstreamFromConnectorFlow(
            Pipe pipe,
            XYZ end0,
            XYZ end1,
            out int downstreamEndpointIndex)
        {
            downstreamEndpointIndex = -1;
            if (pipe == null || pipe.ConnectorManager == null)
            {
                return false;
            }
            List<Connector> endConnectors = pipe.ConnectorManager.Connectors
                .Cast<Connector>()
                .Where(connector =>
                    connector.ConnectorType == ConnectorType.End)
                .ToList();
            if (endConnectors.Count != 2)
            {
                return false;
            }
            Connector connector0 = endConnectors
                .OrderBy(connector => connector.Origin.DistanceTo(end0))
                .First();
            Connector connector1 = endConnectors
                .First(connector => connector != connector0);
            if (connector1.Origin.DistanceTo(end1)
                > connector1.Origin.DistanceTo(end0))
            {
                return false;
            }
            string flow0 = SafeConnectorFlowDirection(connector0);
            string flow1 = SafeConnectorFlowDirection(connector1);
            if (string.Equals(flow0, "Out", StringComparison.OrdinalIgnoreCase)
                && string.Equals(flow1, "In", StringComparison.OrdinalIgnoreCase))
            {
                downstreamEndpointIndex = 0;
                return true;
            }
            if (string.Equals(flow1, "Out", StringComparison.OrdinalIgnoreCase)
                && string.Equals(flow0, "In", StringComparison.OrdinalIgnoreCase))
            {
                downstreamEndpointIndex = 1;
                return true;
            }
            return false;
        }

        private static object SerializeDrainagePlan(DrainagePlan plan)
        {
            return new
            {
                fixture_id = plan.SourceElement.Id.Value,
                connector = SerializePoint(plan.ConnectorPoint),
                connector_stub_end = plan.HasConnectorStub
                    ? SerializePoint(plan.ConnectorStubEnd)
                    : null,
                has_connector_stub = plan.HasConnectorStub,
                has_double_45 = plan.HasDoubleFortyFive,
                branch_start = SerializePoint(plan.BranchStart),
                main_tie = SerializePoint(plan.MainTie),
                horizontal_length_m = plan.HorizontalLength * 0.3048,
                vertical_drop_mm = UnitUtils.ConvertFromInternalUnits(plan.VerticalDrop, UnitTypeId.Millimeters),
                slope_ratio = plan.SlopeRatio,
                slope_percent = plan.SlopeRatio * 100.0,
                connector_axis = SerializePoint(plan.ConnectorAxis),
                outlet_orientation = plan.OutletOrientation,
                route_kind = plan.RouteKind,
                downstream_endpoint_index = plan.DownstreamEndpointIndex,
                downstream_resolution = plan.DownstreamResolution,
                side_entry_angle_degrees = double.IsNaN(plan.SideEntryAngleDegrees)
                    ? (double?)null
                    : plan.SideEntryAngleDegrees,
                radial_entry_angle_degrees = double.IsNaN(plan.RadialEntryAngleDegrees)
                    ? (double?)null
                    : plan.RadialEntryAngleDegrees,
                stub_tangent_mm = plan.StubTangentLength.HasValue
                    ? (double?)UnitUtils.ConvertFromInternalUnits(
                        plan.StubTangentLength.Value,
                        UnitTypeId.Millimeters)
                    : null,
                middle_tangent_mm = plan.MiddleTangentLength.HasValue
                    ? (double?)UnitUtils.ConvertFromInternalUnits(
                        plan.MiddleTangentLength.Value,
                        UnitTypeId.Millimeters)
                    : null,
                branch_tangent_mm = plan.BranchTangentLength.HasValue
                    ? (double?)UnitUtils.ConvertFromInternalUnits(
                        plan.BranchTangentLength.Value,
                        UnitTypeId.Millimeters)
                    : null,
                first_elbow_angle_degrees =
                    double.IsNaN(plan.FirstElbowAngleDegrees)
                        ? (double?)null
                        : plan.FirstElbowAngleDegrees,
                second_elbow_angle_degrees =
                    double.IsNaN(plan.SecondElbowAngleDegrees)
                        ? (double?)null
                        : plan.SecondElbowAngleDegrees,
                middle_lateral_offset_mm =
                    UnitUtils.ConvertFromInternalUnits(
                        plan.MiddleLateralOffset,
                        UnitTypeId.Millimeters),
                sequence_index = plan.SequenceIndex,
                collision_element_ids = plan.CollisionElementIds,
                ready_to_create = plan.ReadyToCreate,
                issues = plan.Issues
            };
        }

        private static object SerializeDrainageOperationElementRef(
            Element element)
        {
            Element type = element == null
                ? null
                : element.Document.GetElement(element.GetTypeId());
            return new
            {
                element_id = element == null ? 0 : element.Id.Value,
                unique_id = element == null ? "" : element.UniqueId,
                type_id = type == null ? 0 : type.Id.Value,
                type_unique_id = type == null ? "" : type.UniqueId,
                category = element == null || element.Category == null
                    ? ""
                    : element.Category.Name
            };
        }

        private static Element ResolveDrainageOperationElementRef(
            Document document,
            ArrayList elementRefs,
            long expectedElementId,
            string operationId,
            bool requireOperationLineage)
        {
            Dictionary<string, object> elementRef =
                (elementRefs ?? new ArrayList())
                    .Cast<object>()
                    .Select(item => item as Dictionary<string, object>)
                    .FirstOrDefault(item => item != null
                        && Convert.ToInt64(item["element_id"])
                            == expectedElementId);
            if (elementRef == null)
            {
                throw new InvalidOperationException(
                    "OPERATION_ELEMENT_REF_MISSING: "
                    + expectedElementId);
            }
            string uniqueId = ReadDrainageString(
                elementRef,
                "unique_id");
            Element element = string.IsNullOrWhiteSpace(uniqueId)
                ? null
                : document.GetElement(uniqueId);
            if (element == null
                || element.Id.Value != expectedElementId
                || !string.Equals(
                    element.UniqueId,
                    uniqueId,
                    StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "OPERATION_ELEMENT_IDENTITY_MISMATCH: "
                    + expectedElementId);
            }
            long expectedTypeId = ReadLong(
                elementRef,
                "type_id",
                0);
            string expectedTypeUniqueId = ReadDrainageString(
                elementRef,
                "type_unique_id");
            Element type = document.GetElement(element.GetTypeId());
            if (type == null
                || type.Id.Value != expectedTypeId
                || !string.Equals(
                    type.UniqueId,
                    expectedTypeUniqueId,
                    StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "OPERATION_ELEMENT_TYPE_MISMATCH: "
                    + expectedElementId);
            }
            if (requireOperationLineage)
            {
                Parameter comments = element.get_Parameter(
                    BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
                string metadata = comments != null && comments.HasValue
                    ? comments.AsString() ?? ""
                    : "";
                if (string.IsNullOrWhiteSpace(operationId)
                    || !metadata.Contains(
                        ":operation=" + operationId))
                {
                    throw new InvalidOperationException(
                        "OPERATION_ELEMENT_LINEAGE_MISMATCH: "
                        + expectedElementId);
                }
            }
            return element;
        }

        private static DrainageGeometryPoint ToDrainageGeometryPoint(XYZ point)
        {
            return new DrainageGeometryPoint
            {
                X = point.X,
                Y = point.Y,
                Z = point.Z
            };
        }

        private static XYZ ToXyz(DrainageGeometryPoint point)
        {
            return point == null
                ? XYZ.Zero
                : new XYZ(point.X, point.Y, point.Z);
        }

        private static IEnumerable<DrainagePreviewSegment> CreateDrainagePreviewSegments(
            DrainagePlan plan)
        {
            List<XYZ> points = GetDrainagePlanPolyline(plan);
            for (int index = 0; index < points.Count - 1; index++)
            {
                XYZ start = points[index];
                XYZ end = points[index + 1];
                bool blocked = !plan.ReadyToCreate;
                yield return new DrainagePreviewSegment
                {
                    Start = start,
                    End = end,
                    IsBlocked = blocked,
                    Kind = "route"
                };
                foreach (DrainagePreviewSegment arrow in
                    CreateDrainagePreviewArrow(start, end, blocked))
                {
                    yield return arrow;
                }
            }
            double markerSize = UnitUtils.ConvertToInternalUnits(
                75,
                UnitTypeId.Millimeters);
            yield return new DrainagePreviewSegment
            {
                Start = plan.MainTie
                    + new XYZ(-markerSize, 0, 0),
                End = plan.MainTie
                    + new XYZ(markerSize, 0, 0),
                IsBlocked = !plan.ReadyToCreate,
                Kind = "junction"
            };
            yield return new DrainagePreviewSegment
            {
                Start = plan.MainTie
                    + new XYZ(0, -markerSize, 0),
                End = plan.MainTie
                    + new XYZ(0, markerSize, 0),
                IsBlocked = !plan.ReadyToCreate,
                Kind = "junction"
            };
        }

        private static IEnumerable<DrainagePreviewSegment>
            CreateDrainageMainDirectionPreviewSegments(
                Pipe mainPipe,
                IList<DrainagePlan> plans)
        {
            LocationCurve location = mainPipe == null
                ? null
                : mainPipe.Location as LocationCurve;
            List<int> downstreamIndices = (plans
                    ?? new List<DrainagePlan>())
                .Select(item => item.DownstreamEndpointIndex)
                .Where(index => index == 0 || index == 1)
                .Distinct()
                .ToList();
            if (location == null || downstreamIndices.Count != 1)
            {
                yield break;
            }
            XYZ end0 = location.Curve.GetEndPoint(0);
            XYZ end1 = location.Curve.GetEndPoint(1);
            XYZ upstream = downstreamIndices[0] == 0 ? end1 : end0;
            XYZ downstream = downstreamIndices[0] == 0 ? end0 : end1;
            XYZ vector = downstream - upstream;
            if (vector.IsZeroLength())
            {
                yield break;
            }
            XYZ direction = vector.Normalize();
            XYZ midpoint = (upstream + downstream) * 0.5;
            double halfLength = Math.Min(
                vector.GetLength() * 0.25,
                UnitUtils.ConvertToInternalUnits(
                    500,
                    UnitTypeId.Millimeters));
            XYZ start = midpoint - direction * halfLength;
            XYZ end = midpoint + direction * halfLength;
            yield return new DrainagePreviewSegment
            {
                Start = start,
                End = end,
                IsBlocked = false,
                Kind = "main_downstream"
            };
            foreach (DrainagePreviewSegment arrow in
                CreateDrainagePreviewArrow(
                    start,
                    end,
                    false,
                    "main_downstream"))
            {
                yield return arrow;
            }
        }

        private static IEnumerable<DrainagePreviewSegment>
            CreateDrainagePreviewArrow(
                XYZ start,
                XYZ end,
                bool blocked,
                string kind = "route")
        {
            XYZ vector = end - start;
            if (vector.GetLength() < 0.000001)
            {
                yield break;
            }
            XYZ direction = vector.Normalize();
            XYZ perpendicular = XYZ.BasisZ.CrossProduct(direction);
            if (perpendicular.GetLength() < 0.000001)
            {
                perpendicular = XYZ.BasisX;
            }
            else
            {
                perpendicular = perpendicular.Normalize();
            }
            double arrowSize = Math.Min(
                vector.GetLength() * 0.20,
                UnitUtils.ConvertToInternalUnits(
                    100,
                    UnitTypeId.Millimeters));
            if (arrowSize
                < UnitUtils.ConvertToInternalUnits(
                    15,
                    UnitTypeId.Millimeters))
            {
                yield break;
            }
            XYZ tip = start + vector * 0.72;
            XYZ basePoint = tip - direction * arrowSize;
            XYZ wing = perpendicular * arrowSize * 0.45;
            yield return new DrainagePreviewSegment
            {
                Start = basePoint + wing,
                End = tip,
                IsBlocked = blocked,
                Kind = kind
            };
            yield return new DrainagePreviewSegment
            {
                Start = basePoint - wing,
                End = tip,
                IsBlocked = blocked,
                Kind = kind
            };
        }

        private static void SetDrainageMetadata(
            Pipe pipe,
            string kind,
            string batchId,
            double slopeRatio,
            string operationId)
        {
            SetDrainageElementMetadata(
                pipe,
                kind,
                batchId,
                slopeRatio,
                operationId);
        }

        private static void SetDrainageElementMetadata(
            Element element,
            string kind,
            string batchId,
            double slopeRatio,
            string operationId)
        {
            Parameter comments = element == null
                ? null
                : element.get_Parameter(
                    BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
            if (comments != null && !comments.IsReadOnly)
            {
                comments.Set(
                    ScDrainageCommentPrefix
                    + kind + ":"
                    + batchId + ":slope="
                    + slopeRatio.ToString(
                        "0.####",
                        System.Globalization.CultureInfo.InvariantCulture)
                    + ":operation="
                    + operationId);
            }
        }

        private static string ReadDrainageMetadata(Pipe pipe)
        {
            Parameter comments = pipe.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
            return comments != null && comments.HasValue ? comments.AsString() ?? "" : "";
        }

        private static Dictionary<string, object> FindDrainageRouteEvidence(
            ArrayList routeEvidence,
            long elementId)
        {
            if (routeEvidence == null)
            {
                return null;
            }
            foreach (object raw in routeEvidence)
            {
                Dictionary<string, object> item = raw as Dictionary<string, object>;
                if (item != null
                    && item.ContainsKey("element_id")
                    && Convert.ToInt64(item["element_id"]) == elementId)
                {
                    return item;
                }
            }
            return null;
        }

        private static XYZ ReadDrainagePoint(
            Dictionary<string, object> evidence,
            string key)
        {
            if (evidence == null || !evidence.ContainsKey(key))
            {
                return XYZ.Zero;
            }
            Dictionary<string, object> point = evidence[key] as Dictionary<string, object>;
            if (point == null)
            {
                return XYZ.Zero;
            }
            return new XYZ(
                point.ContainsKey("x") ? Convert.ToDouble(point["x"]) : 0,
                point.ContainsKey("y") ? Convert.ToDouble(point["y"]) : 0,
                point.ContainsKey("z") ? Convert.ToDouble(point["z"]) : 0);
        }

        private static FamilyInstance CreateDrainageElbowAtPipeEnd(
            Document doc,
            Pipe branch,
            Pipe drop,
            XYZ tiePoint)
        {
            try
            {
                doc.Regenerate();
                Connector branchConnector = FindConnectorNear(branch, tiePoint);
                Connector dropConnector = FindConnectorNear(drop, tiePoint);
                if (branchConnector == null || dropConnector == null)
                {
                    return null;
                }
                FamilyInstance fitting = doc.Create.NewElbowFitting(branchConnector, dropConnector);
                doc.Regenerate();
                return fitting;
            }
            catch
            {
                return null;
            }
        }

        private static FamilyInstance CreateAndValidateDrainageElbow(
            Document doc,
            Pipe first,
            Pipe second,
            XYZ point,
            DrainageRoutingPart elbowPart)
        {
            FamilyInstance elbow = CreateDrainageElbowAtPipeEnd(
                doc,
                first,
                second,
                point);
            if (elbow == null)
            {
                throw new InvalidOperationException(
                    "ELBOW_CREATE_FAILED: fitting could not connect both planned segments");
            }
            if (elbowPart == null || elbow.GetTypeId().Value != elbowPart.PartId.Value)
            {
                throw new InvalidOperationException(
                    "ELBOW_TYPE_MISMATCH: expected "
                    + (elbowPart == null ? 0 : elbowPart.PartId.Value)
                    + ", actual "
                    + elbow.GetTypeId().Value);
            }
            if (!IsFittingConnectedToElements(
                elbow,
                new List<ElementId> { first.Id, second.Id }))
            {
                throw new InvalidOperationException(
                    "ELBOW_CONNECTIVITY_INVALID: fitting is not connected to both planned segments");
            }
            string geometryError;
            if (!IsDrainageElbowGeometryValid(
                elbow,
                first,
                second,
                out geometryError))
            {
                throw new InvalidOperationException(
                    "ELBOW_GEOMETRY_INVALID: " + geometryError);
            }
            return elbow;
        }

        private static bool IsDrainageElbowGeometryValid(
            FamilyInstance elbow,
            Pipe first,
            Pipe second,
            out string error)
        {
            error = "";
            if (elbow == null
                || first == null
                || second == null
                || elbow.MEPModel == null
                || elbow.MEPModel.ConnectorManager == null)
            {
                error = "missing elbow, pipe, or connector manager";
                return false;
            }
            List<Connector> fittingConnectors = elbow.MEPModel.ConnectorManager
                .Connectors
                .Cast<Connector>()
                .Where(connector => connector.ConnectorType == ConnectorType.End)
                .ToList();
            if (fittingConnectors.Count != 2)
            {
                error = "expected two end connectors";
                return false;
            }
            LocationCurve firstLocation = first.Location as LocationCurve;
            LocationCurve secondLocation = second.Location as LocationCurve;
            if (firstLocation == null || secondLocation == null)
            {
                error = "pipe centerline is unavailable";
                return false;
            }
            XYZ firstVector = firstLocation.Curve.GetEndPoint(1)
                - firstLocation.Curve.GetEndPoint(0);
            XYZ secondVector = secondLocation.Curve.GetEndPoint(1)
                - secondLocation.Curve.GetEndPoint(0);
            XYZ fittingAxisA = SafeConnectorAxis(fittingConnectors[0]);
            XYZ fittingAxisB = SafeConnectorAxis(fittingConnectors[1]);
            double expectedAngle = DrainageEngineeringCore.AxialAngleDegrees(
                firstVector.X,
                firstVector.Y,
                firstVector.Z,
                secondVector.X,
                secondVector.Y,
                secondVector.Z);
            double actualAngle = DrainageEngineeringCore.AxialAngleDegrees(
                fittingAxisA.X,
                fittingAxisA.Y,
                fittingAxisA.Z,
                fittingAxisB.X,
                fittingAxisB.Y,
                fittingAxisB.Z);
            if (double.IsNaN(expectedAngle)
                || double.IsNaN(actualAngle)
                || !DrainageEngineeringCore.IsSideEntryAngleAllowed(
                    expectedAngle,
                    45,
                    3)
                || !DrainageEngineeringCore.IsSideEntryAngleAllowed(
                    actualAngle,
                    45,
                    3)
                || Math.Abs(expectedAngle - actualAngle) > 3.0)
            {
                error = "elbow is not a verified 45-degree fitting";
                return false;
            }
            return true;
        }

        private static FamilyInstance CreateDrainageTeeAtPoint(
            Document doc,
            List<Pipe> mainSegments,
            Pipe branch,
            XYZ tiePoint,
            XYZ downstreamPoint,
            DrainageRoutingPart junctionPart,
            double diameterFeet)
        {
            double tolerance = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters);
            Pipe target = mainSegments.FirstOrDefault(pipe => IsPointOnPipeXY(pipe, tiePoint, tolerance));
            if (target == null)
            {
                return null;
            }
            try
            {
                doc.Regenerate();
                ElementId newSegmentId = PlumbingUtils.BreakCurve(doc, target.Id, tiePoint);
                Pipe newSegment = doc.GetElement(newSegmentId) as Pipe;
                if (newSegment == null)
                {
                    return null;
                }
                mainSegments.Add(newSegment);
                doc.Regenerate();
                Connector mainA = FindConnectorNear(target, tiePoint);
                Connector mainB = FindConnectorNear(newSegment, tiePoint);
                Connector branchConnector = FindConnectorNear(branch, tiePoint);
                Connector downstreamMain = GetPipeFarEndpoint(
                    mainA.Owner as Pipe,
                    tiePoint).DistanceTo(downstreamPoint)
                    <= GetPipeFarEndpoint(
                        mainB.Owner as Pipe,
                        tiePoint).DistanceTo(downstreamPoint)
                        ? mainA
                        : mainB;
                Connector upstreamMain =
                    downstreamMain == mainA ? mainB : mainA;
                FamilyInstance fitting =
                    TryPlaceAndConnectDrainageJunction(
                        doc,
                        junctionPart,
                        diameterFeet,
                        downstreamMain,
                        upstreamMain,
                        branchConnector,
                        tiePoint);
                if (fitting != null)
                {
                    return fitting;
                }
                // The controlled placement ran inside a SubTransaction. After
                // rollback, Connector wrappers captured before that attempt
                // may be stale even though their owners still exist.
                doc.Regenerate();
                mainA = FindConnectorNear(target, tiePoint);
                mainB = FindConnectorNear(newSegment, tiePoint);
                branchConnector = FindConnectorNear(branch, tiePoint);
                if (mainA == null
                    || mainB == null
                    || branchConnector == null)
                {
                    return null;
                }
                downstreamMain = GetPipeFarEndpoint(
                    mainA.Owner as Pipe,
                    tiePoint).DistanceTo(downstreamPoint)
                    <= GetPipeFarEndpoint(
                        mainB.Owner as Pipe,
                        tiePoint).DistanceTo(downstreamPoint)
                        ? mainA
                        : mainB;
                upstreamMain =
                    downstreamMain == mainA ? mainB : mainA;
                return TryNewTeeFitting(
                    doc,
                    downstreamMain,
                    upstreamMain,
                    branchConnector);
            }
            catch
            {
                return null;
            }
        }

        private static FamilyInstance TryPlaceAndConnectDrainageJunction(
            Document doc,
            DrainageRoutingPart junctionPart,
            double diameterFeet,
            Connector mainA,
            Connector mainB,
            Connector branch,
            XYZ tiePoint)
        {
            using (var subTransaction = new SubTransaction(doc))
            {
                subTransaction.Start();
                try
                {
                    FamilyInstance fitting =
                        TryPlaceAndConnectDrainageJunctionCore(
                            doc,
                            junctionPart,
                            diameterFeet,
                            mainA,
                            mainB,
                            branch,
                            tiePoint);
                    if (fitting == null)
                    {
                        subTransaction.RollBack();
                        return null;
                    }
                    if (subTransaction.Commit()
                        != TransactionStatus.Committed)
                    {
                        return null;
                    }
                    return fitting;
                }
                catch
                {
                    if (subTransaction.GetStatus()
                        == TransactionStatus.Started)
                    {
                        subTransaction.RollBack();
                    }
                    return null;
                }
            }
        }

        private static FamilyInstance
            TryPlaceAndConnectDrainageJunctionCore(
            Document doc,
            DrainageRoutingPart junctionPart,
            double diameterFeet,
            Connector mainA,
            Connector mainB,
            Connector branch,
            XYZ tiePoint)
        {
            if (junctionPart == null
                || mainA == null
                || mainB == null
                || branch == null
                || !junctionPart.MeasuredTakeoutMm.HasValue
                || !junctionPart.MeasuredRunTakeoutMm.HasValue)
            {
                return null;
            }
            FamilySymbol symbol = doc.GetElement(junctionPart.PartId) as FamilySymbol;
            Pipe mainAPipe = mainA.Owner as Pipe;
            Pipe mainBPipe = mainB.Owner as Pipe;
            Pipe branchPipe = branch.Owner as Pipe;
            if (symbol == null
                || mainAPipe == null
                || mainBPipe == null
                || branchPipe == null
                || symbol.Category == null
                || symbol.Category.Id.Value
                    != (long)BuiltInCategory.OST_PipeFitting
                || (!string.IsNullOrWhiteSpace(junctionPart.PartUniqueId)
                    && !string.Equals(
                        symbol.UniqueId,
                        junctionPart.PartUniqueId,
                        StringComparison.Ordinal)))
            {
                return null;
            }
            double? mainADiameterMm = SafeConnectorDiameterMm(mainA);
            double? mainBDiameterMm = SafeConnectorDiameterMm(mainB);
            double? branchDiameterMm = SafeConnectorDiameterMm(branch);
            if (!mainADiameterMm.HasValue
                || !mainBDiameterMm.HasValue
                || !branchDiameterMm.HasValue
                || Math.Abs(mainADiameterMm.Value - mainBDiameterMm.Value) > 1
                || Math.Abs(mainADiameterMm.Value - branchDiameterMm.Value) > 1)
            {
                return null;
            }
            if (!symbol.IsActive)
            {
                symbol.Activate();
                doc.Regenerate();
            }

            XYZ mainAAxis = SafeConnectorAxis(mainA);
            XYZ mainBAxis = SafeConnectorAxis(mainB);
            XYZ branchAxis = SafeConnectorAxis(branch);
            if (mainAAxis.IsZeroLength()
                || mainBAxis.IsZeroLength()
                || branchAxis.IsZeroLength())
            {
                return null;
            }
            mainAAxis = mainAAxis.Normalize();
            mainBAxis = mainBAxis.Normalize();
            branchAxis = branchAxis.Normalize();

            FamilyInstance fitting = doc.Create.NewFamilyInstance(
                tiePoint,
                symbol,
                StructuralType.NonStructural);
            doc.Regenerate();
            List<Connector> ports = GetDrainageFittingEndConnectors(fitting);
            if (ports.Count != 3
                || ports.Any(port =>
                    port.Domain != Domain.DomainPiping
                    || port.Shape != ConnectorProfileType.Round
                    || port.IsConnected))
            {
                return null;
            }
            double radius = diameterFeet / 2.0;
            foreach (Connector port in ports)
            {
                port.Radius = radius;
            }
            doc.Regenerate();
            ports = GetDrainageFittingEndConnectors(fitting);
            if (ports.Count != 3
                || ports.Any(port => Math.Abs(port.Radius - radius)
                    > UnitUtils.ConvertToInternalUnits(
                        0.5,
                        UnitTypeId.Millimeters)))
            {
                return null;
            }

            Connector branchPort;
            List<Connector> runPorts;
            if (!TryResolveDrainageJunctionPorts(
                ports,
                out branchPort,
                out runPorts))
            {
                return null;
            }
            Connector sourceRun = runPorts
                .OrderByDescending(port =>
                    SafeConnectorAxis(port).DotProduct(
                        -SafeConnectorAxis(branchPort)))
                .First();
            XYZ targetRun = -mainAAxis;
            XYZ vertex;
            if (!TryIntersectConnectorAxes(
                sourceRun,
                branchPort,
                UnitUtils.ConvertToInternalUnits(2, UnitTypeId.Millimeters),
                out vertex))
            {
                return null;
            }
            RotateDrainageFittingFromTo(
                doc,
                fitting.Id,
                vertex,
                SafeConnectorAxis(sourceRun),
                targetRun);
            doc.Regenerate();

            ports = GetDrainageFittingEndConnectors(fitting);
            if (!TryResolveDrainageJunctionPorts(
                ports,
                out branchPort,
                out runPorts))
            {
                return null;
            }
            XYZ currentBranch = SafeConnectorAxis(branchPort);
            XYZ targetBranch = -branchAxis;
            XYZ currentPerpendicular = currentBranch
                - targetRun * currentBranch.DotProduct(targetRun);
            XYZ targetPerpendicular = targetBranch
                - targetRun * targetBranch.DotProduct(targetRun);
            if (currentPerpendicular.IsZeroLength()
                || targetPerpendicular.IsZeroLength())
            {
                return null;
            }
            currentPerpendicular = currentPerpendicular.Normalize();
            targetPerpendicular = targetPerpendicular.Normalize();
            double twist = Math.Atan2(
                targetRun.DotProduct(
                    currentPerpendicular.CrossProduct(targetPerpendicular)),
                currentPerpendicular.DotProduct(targetPerpendicular));
            if (!TryIntersectConnectorAxes(
                runPorts[0],
                branchPort,
                UnitUtils.ConvertToInternalUnits(2, UnitTypeId.Millimeters),
                out vertex))
            {
                return null;
            }
            if (Math.Abs(twist) > 0.000001)
            {
                ElementTransformUtils.RotateElement(
                    doc,
                    fitting.Id,
                    Line.CreateUnbound(vertex, targetRun),
                    twist);
                doc.Regenerate();
            }

            ports = GetDrainageFittingEndConnectors(fitting);
            if (!TryResolveDrainageJunctionPorts(
                ports,
                out branchPort,
                out runPorts)
                || !TryIntersectConnectorAxes(
                    runPorts[0],
                    branchPort,
                    UnitUtils.ConvertToInternalUnits(
                        2,
                        UnitTypeId.Millimeters),
                    out vertex))
            {
                return null;
            }
            ElementTransformUtils.MoveElement(
                doc,
                fitting.Id,
                tiePoint - vertex);
            doc.Regenerate();

            ports = GetDrainageFittingEndConnectors(fitting);
            if (!TryResolveDrainageJunctionPorts(
                ports,
                out branchPort,
                out runPorts))
            {
                return null;
            }
            Connector fittingA = runPorts
                .OrderBy(port =>
                    SafeConnectorAxis(port).DotProduct(mainAAxis))
                .First();
            Connector fittingB = runPorts.First(port => port.Id != fittingA.Id);
            if (SafeConnectorAxis(fittingB).DotProduct(mainBAxis)
                > SafeConnectorAxis(fittingA).DotProduct(mainBAxis))
            {
                Connector swap = fittingA;
                fittingA = fittingB;
                fittingB = swap;
            }

            SetDrainagePipeEnd(mainAPipe, tiePoint, fittingA.Origin);
            SetDrainagePipeEnd(mainBPipe, tiePoint, fittingB.Origin);
            SetDrainagePipeEnd(branchPipe, tiePoint, branchPort.Origin);
            doc.Regenerate();

            ports = GetDrainageFittingEndConnectors(fitting);
            if (!TryResolveDrainageJunctionPorts(
                ports,
                out branchPort,
                out runPorts))
            {
                return null;
            }
            fittingA = runPorts
                .OrderBy(port =>
                    SafeConnectorAxis(port).DotProduct(mainAAxis))
                .First();
            fittingB = runPorts.First(port => port.Id != fittingA.Id);
            if (SafeConnectorAxis(fittingB).DotProduct(mainBAxis)
                > SafeConnectorAxis(fittingA).DotProduct(mainBAxis))
            {
                Connector swap = fittingA;
                fittingA = fittingB;
                fittingB = swap;
            }
            Connector freshMainA = FindConnectorNear(
                mainAPipe,
                fittingA.Origin);
            Connector freshMainB = FindConnectorNear(
                mainBPipe,
                fittingB.Origin);
            Connector freshBranch = FindConnectorNear(
                branchPipe,
                branchPort.Origin);
            freshMainA.ConnectTo(fittingA);
            freshMainB.ConnectTo(fittingB);
            freshBranch.ConnectTo(branchPort);
            doc.Regenerate();
            return GetDrainageFittingEndConnectors(fitting)
                .All(port => port.IsConnected)
                ? fitting
                : null;
        }

        private static List<Connector> GetDrainageFittingEndConnectors(
            FamilyInstance fitting)
        {
            if (fitting == null
                || fitting.MEPModel == null
                || fitting.MEPModel.ConnectorManager == null)
            {
                return new List<Connector>();
            }
            return fitting.MEPModel.ConnectorManager.Connectors
                .Cast<Connector>()
                .Where(port => port.ConnectorType == ConnectorType.End)
                .ToList();
        }

        private static bool TryResolveDrainageJunctionPorts(
            IList<Connector> ports,
            out Connector branchPort,
            out List<Connector> runPorts)
        {
            branchPort = null;
            runPorts = new List<Connector>();
            if (ports == null || ports.Count != 3)
            {
                return false;
            }
            double bestAlignment = double.MinValue;
            int firstIndex = -1;
            int secondIndex = -1;
            for (int first = 0; first < ports.Count; first++)
            {
                for (int second = first + 1; second < ports.Count; second++)
                {
                    double alignment = Math.Abs(
                        SafeConnectorAxis(ports[first]).DotProduct(
                            SafeConnectorAxis(ports[second])));
                    if (alignment > bestAlignment)
                    {
                        bestAlignment = alignment;
                        firstIndex = first;
                        secondIndex = second;
                    }
                }
            }
            if (bestAlignment < Math.Cos(5.0 * Math.PI / 180.0))
            {
                return false;
            }
            runPorts.Add(ports[firstIndex]);
            runPorts.Add(ports[secondIndex]);
            branchPort = ports.First(
                port => port.Id != ports[firstIndex].Id
                    && port.Id != ports[secondIndex].Id);
            return true;
        }

        private static void RotateDrainageFittingFromTo(
            Document doc,
            ElementId fittingId,
            XYZ origin,
            XYZ from,
            XYZ to)
        {
            XYZ source = from.Normalize();
            XYZ target = to.Normalize();
            double dot = Math.Max(
                -1.0,
                Math.Min(1.0, source.DotProduct(target)));
            double angle = Math.Acos(dot);
            if (angle <= 0.000001)
            {
                return;
            }
            XYZ axis = source.CrossProduct(target);
            if (axis.IsZeroLength())
            {
                axis = source.CrossProduct(
                    Math.Abs(source.Z) < 0.9
                        ? XYZ.BasisZ
                        : XYZ.BasisX);
            }
            ElementTransformUtils.RotateElement(
                doc,
                fittingId,
                Line.CreateUnbound(origin, axis.Normalize()),
                angle);
        }

        private static void SetDrainagePipeEnd(
            Pipe pipe,
            XYZ oldEnd,
            XYZ newEnd)
        {
            LocationCurve location = pipe == null
                ? null
                : pipe.Location as LocationCurve;
            if (location == null)
            {
                throw new InvalidOperationException(
                    "Pipe has no editable location curve.");
            }
            Curve curve = location.Curve;
            XYZ start = curve.GetEndPoint(0);
            XYZ end = curve.GetEndPoint(1);
            location.Curve = start.DistanceTo(oldEnd) <= end.DistanceTo(oldEnd)
                ? Line.CreateBound(newEnd, end)
                : Line.CreateBound(start, newEnd);
        }

        private static bool IsFittingConnectedToElements(
            FamilyInstance fitting,
            ICollection<ElementId> requiredElementIds)
        {
            if (fitting == null
                || fitting.MEPModel == null
                || fitting.MEPModel.ConnectorManager == null)
            {
                return false;
            }
            var connectedOwnerIds = new HashSet<long>();
            foreach (Connector connector in fitting.MEPModel.ConnectorManager.Connectors)
            {
                foreach (Connector reference in connector.AllRefs)
                {
                    if (reference != null
                        && reference.Owner != null
                        && reference.Owner.Id.Value != fitting.Id.Value)
                    {
                        connectedOwnerIds.Add(reference.Owner.Id.Value);
                    }
                }
            }
            return requiredElementIds.All(id => connectedOwnerIds.Contains(id.Value));
        }

        private static bool IsDrainageJunctionConnectivityValid(
            FamilyInstance junction,
            Pipe branch,
            ICollection<Pipe> mainSegments)
        {
            if (junction == null
                || branch == null
                || junction.MEPModel == null
                || junction.MEPModel.ConnectorManager == null)
            {
                return false;
            }
            var connectedOwnerIds = new HashSet<long>();
            foreach (Connector connector in junction.MEPModel.ConnectorManager.Connectors)
            {
                foreach (Connector reference in connector.AllRefs)
                {
                    if (reference != null
                        && reference.Owner != null
                        && reference.Owner.Id.Value != junction.Id.Value)
                    {
                        connectedOwnerIds.Add(reference.Owner.Id.Value);
                    }
                }
            }
            int connectedMainCount = mainSegments.Count(pipe => connectedOwnerIds.Contains(pipe.Id.Value));
            return connectedOwnerIds.Contains(branch.Id.Value) && connectedMainCount >= 2;
        }

        private static bool IsDrainageJunctionGeometryValid(
            FamilyInstance junction,
            Pipe branch,
            ICollection<Pipe> mainSegments,
            XYZ tiePoint,
            XYZ downstreamPoint,
            DrainageRoutePolicy routePolicy,
            out double actualSideEntryAngle,
            out double actualRadialAngle,
            out string error)
        {
            actualSideEntryAngle = double.NaN;
            actualRadialAngle = double.NaN;
            error = "";
            if (junction == null
                || branch == null
                || junction.MEPModel == null
                || junction.MEPModel.ConnectorManager == null
                || downstreamPoint == null
                || downstreamPoint.IsAlmostEqualTo(XYZ.Zero))
            {
                error = "missing fitting, branch, connector manager, or downstream point";
                return false;
            }

            var branchConnectors = new List<Connector>();
            var mainConnectors = new List<Connector>();
            var mainConnectorOwners = new Dictionary<Connector, Pipe>();
            var mainIds = new HashSet<long>(mainSegments.Select(pipe => pipe.Id.Value));
            foreach (Connector fittingConnector in junction.MEPModel.ConnectorManager.Connectors)
            {
                if (fittingConnector.ConnectorType
                    != ConnectorType.End)
                {
                    continue;
                }
                bool connectsBranch = false;
                bool connectsMain = false;
                foreach (Connector reference in fittingConnector.AllRefs)
                {
                    if (reference == null
                        || reference.Owner == null
                        || reference.ConnectorType
                            != ConnectorType.End
                        || !fittingConnector.IsConnectedTo(reference))
                    {
                        continue;
                    }
                    connectsBranch |= reference.Owner.Id.Value == branch.Id.Value;
                    connectsMain |= mainIds.Contains(reference.Owner.Id.Value);
                }
                if (connectsBranch)
                {
                    branchConnectors.Add(fittingConnector);
                }
                if (connectsMain)
                {
                    mainConnectors.Add(fittingConnector);
                    Pipe owner = fittingConnector.AllRefs
                        .Cast<Connector>()
                        .Where(reference =>
                            reference != null
                            && reference.Owner != null
                            && reference.ConnectorType
                                == ConnectorType.End
                            && fittingConnector.IsConnectedTo(
                                reference))
                        .Select(reference => reference.Owner as Pipe)
                        .FirstOrDefault(pipe => pipe != null && mainIds.Contains(pipe.Id.Value));
                    if (owner != null)
                    {
                        mainConnectorOwners[fittingConnector] = owner;
                    }
                }
            }
            if (branchConnectors.Count != 1
                || mainConnectors.Count != 2
                || mainConnectorOwners.Count != 2)
            {
                error = "expected one branch connector and two main connectors";
                return false;
            }

            XYZ branchAxis = SafeConnectorAxis(branchConnectors[0]);
            XYZ mainAxisA = SafeConnectorAxis(mainConnectors[0]);
            XYZ mainAxisB = SafeConnectorAxis(mainConnectors[1]);
            if (branchAxis.IsZeroLength()
                || mainAxisA.IsZeroLength()
                || mainAxisB.IsZeroLength())
            {
                error = "connector axis is unavailable";
                return false;
            }
            double mainAxialAngle = DrainageEngineeringCore.AxialAngleDegrees(
                mainAxisA.X, mainAxisA.Y, mainAxisA.Z,
                mainAxisB.X, mainAxisB.Y, mainAxisB.Z);
            double branchAngleA = DrainageEngineeringCore.AxialAngleDegrees(
                branchAxis.X, branchAxis.Y, branchAxis.Z,
                mainAxisA.X, mainAxisA.Y, mainAxisA.Z);
            double branchAngleB = DrainageEngineeringCore.AxialAngleDegrees(
                branchAxis.X, branchAxis.Y, branchAxis.Z,
                mainAxisB.X, mainAxisB.Y, mainAxisB.Z);
            if (mainAxialAngle > 5.0)
            {
                error = "main run connectors are not collinear";
                return false;
            }
            if (!DrainageEngineeringCore.IsSideEntryAngleAllowed(branchAngleA, 45, 5)
                || !DrainageEngineeringCore.IsSideEntryAngleAllowed(branchAngleB, 45, 5))
            {
                error = "fitting branch connector is not 45 degrees from both run connectors";
                return false;
            }

            Connector downstreamConnector = mainConnectors
                .OrderBy(connector => GetPipeFarEndpoint(
                    mainConnectorOwners[connector],
                    tiePoint).DistanceTo(downstreamPoint))
                .First();
            Connector upstreamConnector = mainConnectors
                .First(connector => connector != downstreamConnector);
            XYZ downstreamAxis = SafeConnectorAxis(downstreamConnector);
            XYZ upstreamAxis = SafeConnectorAxis(upstreamConnector);
            XYZ towardDownstream = downstreamPoint - downstreamConnector.Origin;
            XYZ awayFromDownstream = (GetPipeFarEndpoint(
                mainConnectorOwners[upstreamConnector],
                tiePoint) - upstreamConnector.Origin);
            if (!DrainageEngineeringCore.IsAxisDirectedTowardTarget3D(
                downstreamAxis.X,
                downstreamAxis.Y,
                downstreamAxis.Z,
                towardDownstream.X,
                towardDownstream.Y,
                towardDownstream.Z,
                0.95)
                || !DrainageEngineeringCore.IsAxisDirectedTowardTarget3D(
                    upstreamAxis.X,
                    upstreamAxis.Y,
                    upstreamAxis.Z,
                    awayFromDownstream.X,
                    awayFromDownstream.Y,
                    awayFromDownstream.Z,
                    0.95))
            {
                error = "main fitting connectors cannot be mapped to upstream/downstream";
                return false;
            }

            Connector actualBranchConnector = branchConnectors[0];
            XYZ branchSource = GetPipeFarEndpoint(
                branch,
                actualBranchConnector.Origin);
            XYZ branchFlow = actualBranchConnector.Origin - branchSource;
            XYZ downstreamFar = GetPipeFarEndpoint(
                mainConnectorOwners[downstreamConnector],
                downstreamConnector.Origin);
            XYZ downstreamFlow =
                downstreamFar - downstreamConnector.Origin;
            double branchFlowLength2D = Math.Sqrt(
                branchFlow.X * branchFlow.X
                + branchFlow.Y * branchFlow.Y);
            double downstreamFlowLength2D = Math.Sqrt(
                downstreamFlow.X * downstreamFlow.X
                + downstreamFlow.Y * downstreamFlow.Y);
            if (branchFlowLength2D <= 0.000001
                || downstreamFlowLength2D <= 0.000001)
            {
                error = "directed branch or downstream vector is unavailable";
                return false;
            }
            actualSideEntryAngle = DrainageEngineeringCore.AngleBetween2D(
                branchFlow.X,
                branchFlow.Y,
                downstreamFlow.X,
                downstreamFlow.Y);
            if (!DrainageEngineeringCore.IsDirectedSideEntryAllowed(
                branchFlow.X,
                branchFlow.Y,
                downstreamFlow.X,
                downstreamFlow.Y,
                routePolicy.SideEntryAngleDegrees,
                routePolicy.SideEntryToleranceDegrees))
            {
                error = "junction branch is not a directed downstream 45-degree entry";
                return false;
            }
            XYZ branchOutward =
                branchSource - actualBranchConnector.Origin;
            if (!DrainageEngineeringCore.IsAxisDirectedTowardTarget3D(
                branchAxis.X,
                branchAxis.Y,
                branchAxis.Z,
                branchOutward.X,
                branchOutward.Y,
                branchOutward.Z,
                0.95))
            {
                error = "junction branch port axis is mirrored";
                return false;
            }
            actualRadialAngle = DrainageEngineeringCore.RadialElevationAngleDegrees(
                downstreamFlow.X,
                downstreamFlow.Y,
                branchSource.X - actualBranchConnector.Origin.X,
                branchSource.Y - actualBranchConnector.Origin.Y,
                branchSource.Z - actualBranchConnector.Origin.Z);
            if (!DrainageEngineeringCore.IsRadialElevationAllowed(
                actualRadialAngle,
                routePolicy.RadialMinimumDegrees,
                routePolicy.RadialMaximumDegrees,
                routePolicy.RadialToleranceDegrees))
            {
                error = "actual branch radial orientation is outside side-to-45-degree policy";
                return false;
            }
            return true;
        }

        private static XYZ GetPipeFarEndpoint(Pipe pipe, XYZ nearPoint)
        {
            LocationCurve location = pipe == null ? null : pipe.Location as LocationCurve;
            if (location == null)
            {
                return XYZ.Zero;
            }
            XYZ end0 = location.Curve.GetEndPoint(0);
            XYZ end1 = location.Curve.GetEndPoint(1);
            return end0.DistanceTo(nearPoint) > end1.DistanceTo(nearPoint)
                ? end0
                : end1;
        }

        private static bool HasDrainageConnectorGraphCycle(
            Document document,
            HashSet<long> allowedElementIds)
        {
            var adjacency = allowedElementIds.ToDictionary(
                id => id,
                id => new HashSet<long>());
            foreach (long elementId in allowedElementIds)
            {
                Element element = document.GetElement(
                    new ElementId(elementId));
                foreach (Connector connector in
                    GetDrainageElementConnectors(element))
                {
                    if (connector.ConnectorType != ConnectorType.End)
                    {
                        continue;
                    }
                    foreach (Connector reference in connector.AllRefs)
                    {
                        if (reference == null
                            || reference.Owner == null
                            || reference.ConnectorType
                                != ConnectorType.End
                            || !connector.IsConnectedTo(reference))
                        {
                            continue;
                        }
                        long neighborId = reference.Owner.Id.Value;
                        if (neighborId == elementId
                            || !adjacency.ContainsKey(neighborId))
                        {
                            continue;
                        }
                        adjacency[elementId].Add(neighborId);
                        adjacency[neighborId].Add(elementId);
                    }
                }
            }
            var visited = new HashSet<long>();
            foreach (long start in allowedElementIds)
            {
                if (visited.Contains(start))
                {
                    continue;
                }
                var stack = new Stack<Tuple<long, long>>();
                stack.Push(Tuple.Create(start, long.MinValue));
                while (stack.Count > 0)
                {
                    Tuple<long, long> item = stack.Pop();
                    if (!visited.Add(item.Item1))
                    {
                        continue;
                    }
                    foreach (long neighbor in adjacency[item.Item1])
                    {
                        if (neighbor == item.Item2)
                        {
                            continue;
                        }
                        if (visited.Contains(neighbor))
                        {
                            return true;
                        }
                        stack.Push(Tuple.Create(neighbor, item.Item1));
                    }
                }
            }
            return false;
        }

        private static List<Connector> GetDrainageElementConnectors(Element element)
        {
            var connectors = new List<Connector>();
            Pipe pipe = element as Pipe;
            if (pipe != null)
            {
                foreach (Connector connector in pipe.ConnectorManager.Connectors)
                {
                    connectors.Add(connector);
                }
                return connectors;
            }
            FamilyInstance familyInstance = element as FamilyInstance;
            ConnectorManager connectorManager = null;
            if (familyInstance != null && familyInstance.MEPModel != null)
            {
                connectorManager = familyInstance.MEPModel.ConnectorManager;
            }
            if (connectorManager == null)
            {
                return connectors;
            }
            foreach (Connector connector in connectorManager.Connectors)
            {
                connectors.Add(connector);
            }
            return connectors;
        }

        private static HashSet<long> FindDrainageBridgingFittingIds(
            Document doc,
            HashSet<long> routeElementIds)
        {
            var result = new HashSet<long>();
            if (doc == null || routeElementIds == null || routeElementIds.Count == 0)
            {
                return result;
            }
            var candidateIds = new HashSet<long>();
            foreach (long routeElementId in routeElementIds)
            {
                Element routeElement = doc.GetElement(
                    new ElementId(routeElementId));
                if (routeElement == null)
                {
                    continue;
                }
                foreach (Connector connector in
                    GetDrainageElementConnectors(routeElement))
                {
                    if (connector.ConnectorType != ConnectorType.End)
                    {
                        continue;
                    }
                    foreach (Connector connected in connector.AllRefs)
                    {
                        FamilyInstance candidate =
                            connected.Owner as FamilyInstance;
                        if (candidate == null
                            || candidate.Category == null
                            || candidate.Category.Id.Value
                                != (long)BuiltInCategory.OST_PipeFitting
                            || routeElementIds.Contains(candidate.Id.Value)
                            || !connector.IsConnectedTo(connected))
                        {
                            continue;
                        }
                        candidateIds.Add(candidate.Id.Value);
                    }
                }
            }
            foreach (long candidateId in candidateIds)
            {
                FamilyInstance candidate = doc.GetElement(
                    new ElementId(candidateId)) as FamilyInstance;
                var connectedRouteIds = new HashSet<long>();
                foreach (Connector connector in
                    GetDrainageElementConnectors(candidate))
                {
                    if (connector.ConnectorType != ConnectorType.End)
                    {
                        continue;
                    }
                    foreach (Connector connected in connector.AllRefs)
                    {
                        long ownerId = connected.Owner.Id.Value;
                        if (routeElementIds.Contains(ownerId)
                            && connector.IsConnectedTo(connected))
                        {
                            connectedRouteIds.Add(ownerId);
                        }
                    }
                }
                if (connectedRouteIds.Count >= 2)
                {
                    result.Add(candidateId);
                }
            }
            return result;
        }

        private static HashSet<long> TraverseDrainageConnectorGraph(
            Document doc,
            long startElementId,
            HashSet<long> allowedElementIds)
        {
            var visited = new HashSet<long>();
            if (doc == null
                || allowedElementIds == null
                || !allowedElementIds.Contains(startElementId))
            {
                return visited;
            }
            var pending = new Queue<long>();
            pending.Enqueue(startElementId);
            visited.Add(startElementId);
            while (pending.Count > 0)
            {
                long currentId = pending.Dequeue();
                Element current = doc.GetElement(new ElementId(currentId));
                if (current == null)
                {
                    continue;
                }
                foreach (Connector connector in GetDrainageElementConnectors(current))
                {
                    if (connector.ConnectorType != ConnectorType.End)
                    {
                        continue;
                    }
                    foreach (Connector connected in connector.AllRefs)
                    {
                        if (connected == null
                            || connected.Owner == null
                            || connected.ConnectorType
                                != ConnectorType.End
                            || !connector.IsConnectedTo(connected))
                        {
                            continue;
                        }
                        long connectedOwnerId = connected.Owner.Id.Value;
                        if (connectedOwnerId == currentId
                            || !allowedElementIds.Contains(connectedOwnerId)
                            || !visited.Add(connectedOwnerId))
                        {
                            continue;
                        }
                        pending.Enqueue(connectedOwnerId);
                    }
                }
            }
            return visited;
        }

        private static bool IsDrainageConnectorGraphReachable(
            Document doc,
            long startElementId,
            HashSet<long> targetElementIds,
            HashSet<long> allowedElementIds)
        {
            if (targetElementIds == null || targetElementIds.Count == 0)
            {
                return false;
            }
            HashSet<long> visited = TraverseDrainageConnectorGraph(
                doc,
                startElementId,
                allowedElementIds);
            return targetElementIds.Any(visited.Contains);
        }

        private static bool AreDrainageElementsConnected(
            Document doc,
            HashSet<long> requiredElementIds,
            HashSet<long> allowedElementIds)
        {
            if (requiredElementIds == null || requiredElementIds.Count <= 1)
            {
                return true;
            }
            HashSet<long> visited = TraverseDrainageConnectorGraph(
                doc,
                requiredElementIds.First(),
                allowedElementIds);
            return requiredElementIds.All(visited.Contains);
        }

        private static int CountConnectedEndConnectors(Pipe pipe)
        {
            int count = 0;
            foreach (Connector connector in pipe.ConnectorManager.Connectors)
            {
                if (connector.ConnectorType == ConnectorType.End && connector.IsConnected)
                {
                    count++;
                }
            }
            return count;
        }

        private static string ReadDrainageMetadataKind(string metadata)
        {
            if (string.IsNullOrWhiteSpace(metadata)
                || !metadata.StartsWith(
                    ScDrainageCommentPrefix,
                    StringComparison.Ordinal))
            {
                return "";
            }
            int start = ScDrainageCommentPrefix.Length;
            int separator = metadata.IndexOf(':', start);
            return separator > start
                ? metadata.Substring(start, separator - start)
                : "";
        }

        private static string ValidateCreatedDrainagePipe(
            DrainageCreatedPipeCheck check,
            double expectedSlope)
        {
            if (check == null || check.Pipe == null)
            {
                return "created pipe is unavailable";
            }
            string metadata = ReadDrainageMetadata(check.Pipe);
            if (!metadata.StartsWith(ScDrainageCommentPrefix, StringComparison.Ordinal))
            {
                return "pipe " + check.Pipe.Id.Value + " has no SC drainage metadata";
            }
            int connectedEndCount = CountConnectedEndConnectors(check.Pipe);
            if (connectedEndCount != 2)
            {
                return "pipe " + check.Pipe.Id.Value
                    + " has " + connectedEndCount + " connected ends; expected 2";
            }
            LocationCurve location = check.Pipe.Location as LocationCurve;
            if (location == null)
            {
                return "pipe " + check.Pipe.Id.Value + " has no centerline";
            }
            if (location.Curve.Length + 0.000001 < check.MinimumCenterlineLength)
            {
                return "pipe " + check.Pipe.Id.Value
                    + " centerline is shorter than the configured post-build tangent minimum";
            }
            XYZ end0 = location.Curve.GetEndPoint(0);
            XYZ end1 = location.Curve.GetEndPoint(1);
            XYZ actualSource = end0.DistanceTo(check.Source) <= end1.DistanceTo(check.Source)
                ? end0
                : end1;
            XYZ actualSink = actualSource.IsAlmostEqualTo(end0) ? end1 : end0;
            double elevationTolerance = UnitUtils.ConvertToInternalUnits(
                1,
                UnitTypeId.Millimeters);
            if (check.RequiresDescending
                && actualSink.Z > actualSource.Z + elevationTolerance)
            {
                return "pipe " + check.Pipe.Id.Value
                    + " rises along the planned flow direction";
            }
            if (!check.RequiresSignedSlope)
            {
                return "";
            }
            double horizontal = Math.Sqrt(
                Math.Pow(actualSink.X - actualSource.X, 2)
                + Math.Pow(actualSink.Y - actualSource.Y, 2));
            double actualSlope = DrainageEngineeringCore.ComputeSignedSlope(
                actualSource.Z,
                actualSink.Z,
                horizontal);
            if (double.IsNaN(actualSlope)
                || actualSlope <= 0
                || Math.Abs(actualSlope - expectedSlope) > 0.0005)
            {
                return "pipe " + check.Pipe.Id.Value
                    + " signed slope " + actualSlope.ToString(
                        "0.######",
                        System.Globalization.CultureInfo.InvariantCulture)
                    + " does not match "
                    + expectedSlope.ToString(
                        "0.######",
                        System.Globalization.CultureInfo.InvariantCulture);
            }
            return "";
        }
    }
}
