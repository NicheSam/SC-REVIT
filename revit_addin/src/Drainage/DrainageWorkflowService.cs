using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.UI;
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace RfaMetadataAddin.Drainage
{
    internal sealed class DrainageWorkflowService
    {
        public DrainageRoutePlan Plan(
            UIApplication uiApplication,
            DrainageRouteRequest request)
        {
            if (uiApplication == null
                || uiApplication.ActiveUIDocument == null)
            {
                throw new InvalidOperationException(
                    "REVIT_DOCUMENT_REQUIRED");
            }
            ValidateRequest(request);

            Document document =
                uiApplication.ActiveUIDocument.Document;
            Dictionary<string, object> payload =
                BuildPreviewPayload(document, request);
            Dictionary<string, object> preview =
                RfaMetadataApplication.ExecuteDrainageActionInline(
                    uiApplication,
                    "create_drainage_preview",
                    payload);
            var plan = new DrainageRoutePlan
            {
                Request = request,
                PreviewPayload = preview,
                RouteHash = ReadString(
                    preview,
                    "snapshot_hash"),
                ReadyToCreate = ReadBoolean(
                    preview,
                    "ready_to_create")
            };
            ArrayList issues = ReadArray(preview, "issues");
            if (issues != null)
            {
                foreach (object issue in issues)
                {
                    IDictionary<string, object> row =
                        issue as IDictionary<string, object>;
                    plan.Issues.Add(
                        row == null
                            ? Convert.ToString(
                                issue,
                                CultureInfo.InvariantCulture)
                            : ReadString(row, "code"));
                }
            }
            ArrayList plans = ReadArray(preview, "plans");
            ArrayList warnings = ReadArray(preview, "warnings");
            if (warnings != null)
            {
                foreach (object warning in warnings)
                {
                    IDictionary<string, object> row =
                        warning as IDictionary<string, object>;
                    plan.Warnings.Add(
                        row == null
                            ? Convert.ToString(
                                warning,
                                CultureInfo.InvariantCulture)
                            : ReadString(row, "code"));
                }
            }
            if (plans != null && plans.Count > 0)
            {
                IDictionary<string, object> first =
                    plans[0] as IDictionary<string, object>;
                if (first != null)
                {
                    plan.RouteKind = ReadString(
                        first,
                        "route_kind");
                }
            }
            return plan;
        }

        public DrainageExecutionResult Execute(
            UIApplication uiApplication,
            DrainageRoutePlan plan)
        {
            if (plan == null || plan.PreviewPayload == null)
            {
                return DrainageExecutionResult.Failed(
                    DrainageFailureCode.RouteNotFound,
                    "沒有可建立的排水路徑。");
            }
            if (!plan.ReadyToCreate)
            {
                string message = plan.Issues.Count == 0
                    ? "排水路徑未通過 preflight。"
                    : string.Join(
                        Environment.NewLine,
                        plan.Issues);
                DrainageFailureCode failureCode =
                    ClassifyFailure(message);
                if (failureCode
                    == DrainageFailureCode.CommitFailed)
                {
                    failureCode =
                        DrainageFailureCode.RouteBlocked;
                }
                return DrainageExecutionResult.Failed(
                    failureCode,
                    message);
            }

            try
            {
                Document document =
                    uiApplication.ActiveUIDocument.Document;
                string snapshotId = ReadString(
                    plan.PreviewPayload,
                    "snapshot_id");
                string snapshotHash = ReadString(
                    plan.PreviewPayload,
                    "snapshot_hash");
                Dictionary<string, object> confirmation =
                    RfaMetadataApplication
                        .ConfirmDrainageSnapshotInline(
                            document,
                            snapshotId,
                            snapshotHash,
                            "human");
                string operationId =
                    "DOP-" + Guid.NewGuid().ToString("N");
                var commitPayload =
                    new Dictionary<string, object>
                    {
                        { "snapshot_id", snapshotId },
                        { "snapshot_hash", snapshotHash },
                        {
                            "confirmation_id",
                            ReadString(
                                confirmation,
                                "confirmation_id")
                        },
                        { "operation_id", operationId },
                        {
                            "idempotency_key",
                            string.IsNullOrWhiteSpace(
                                plan.Request.IdempotencyKey)
                                ? "DIK-"
                                    + Guid.NewGuid().ToString("N")
                                : plan.Request.IdempotencyKey
                        },
                        {
                            "actor_kind",
                            string.IsNullOrWhiteSpace(
                                plan.Request.ActorKind)
                                ? DrainageActorKinds.HumanGui
                                : plan.Request.ActorKind
                        }
                    };
                Dictionary<string, object> committed =
                    RfaMetadataApplication
                        .ExecuteDrainageActionInline(
                            uiApplication,
                            "create_drainage_pipes",
                            commitPayload);
                var result = new DrainageExecutionResult
                {
                    Succeeded = true,
                    RouteHash = snapshotHash,
                    OperationId = operationId,
                    Message = plan.Warnings.Count == 0
                        ? "\u63a5\u7ba1\u5b8c\u6210\u3002"
                        : "\u63a5\u7ba1\u5b8c\u6210\uff0c\u4f46\u6709\u8def\u5f91\u63d0\u793a\u3002"
                };
                foreach (string warning in plan.Warnings)
                {
                    result.Warnings.Add(warning);
                }
                foreach (ElementId id in ReadCreatedElementIds(
                    committed))
                {
                    result.CreatedElementIds.Add(id);
                }
                return result;
            }
            catch (Exception ex)
            {
                return DrainageExecutionResult.Failed(
                    ClassifyFailure(ex.Message),
                    ex.Message);
            }
        }

        public DrainageExecutionResult Connect(
            UIApplication uiApplication,
            DrainageRouteRequest request)
        {
            try
            {
                return Execute(
                    uiApplication,
                    Plan(uiApplication, request));
            }
            catch (Exception ex)
            {
                return DrainageExecutionResult.Failed(
                    ClassifyFailure(ex.Message),
                    ex.Message);
            }
        }

        public DrainageExecutionResult
            ConnectResolvingAmbiguousDownstream(
                UIApplication uiApplication,
                DrainageRouteRequest request)
        {
            try
            {
                DrainageRoutePlan automaticPlan =
                    Plan(uiApplication, request);
                if (automaticPlan.ReadyToCreate
                    || !HasIssue(
                        automaticPlan,
                        "MAIN_DOWNSTREAM_UNRESOLVED"))
                {
                    return Execute(
                        uiApplication,
                        automaticPlan);
                }

                DrainageRoutePlan end0Plan = Plan(
                    uiApplication,
                    CloneRequest(
                        request,
                        "inferred_end0"));
                DrainageRoutePlan end1Plan = Plan(
                    uiApplication,
                    CloneRequest(
                        request,
                        "inferred_end1"));
                int end0Evidence =
                    ReadEndpointTopologyEvidence(
                        request.Target.MainPipe,
                        0);
                int end1Evidence =
                    ReadEndpointTopologyEvidence(
                        request.Target.MainPipe,
                        1);
                int selectedEndpoint =
                    DrainageEngineeringCore
                        .SelectPreferredDownstreamCandidate(
                            end0Plan.ReadyToCreate,
                            end1Plan.ReadyToCreate,
                            end0Evidence,
                            end1Evidence);
                if (selectedEndpoint < 0)
                {
                    return Execute(
                        uiApplication,
                        ChooseMoreSpecificFailure(
                            end0Plan,
                            end1Plan));
                }

                DrainageRoutePlan selectedPlan = Plan(
                    uiApplication,
                    CloneRequest(
                        request,
                        selectedEndpoint == 0
                            ? "inferred_end0"
                            : "inferred_end1"));
                return Execute(
                    uiApplication,
                    selectedPlan);
            }
            catch (Exception ex)
            {
                return DrainageExecutionResult.Failed(
                    ClassifyFailure(ex.Message),
                    ex.Message);
            }
        }

        private static DrainageRouteRequest CloneRequest(
            DrainageRouteRequest request,
            string downstreamMode)
        {
            return new DrainageRouteRequest
            {
                Source = request.Source,
                Target = request.Target,
                Configuration = request.Configuration,
                DiameterMm = request.DiameterMm,
                MainDiameterMm = request.MainDiameterMm,
                DownstreamMode = downstreamMode,
                ActorKind = request.ActorKind,
                IdempotencyKey = request.IdempotencyKey
            };
        }

        private static bool HasIssue(
            DrainageRoutePlan plan,
            string code)
        {
            return plan != null
                && plan.Issues != null
                && plan.Issues.Any(issue =>
                    string.Equals(
                        issue,
                        code,
                        StringComparison.OrdinalIgnoreCase));
        }

        private static DrainageRoutePlan ChooseMoreSpecificFailure(
            DrainageRoutePlan end0Plan,
            DrainageRoutePlan end1Plan)
        {
            int end0IssueCount = end0Plan == null
                || end0Plan.Issues == null
                    ? int.MaxValue
                    : end0Plan.Issues.Count;
            int end1IssueCount = end1Plan == null
                || end1Plan.Issues == null
                    ? int.MaxValue
                    : end1Plan.Issues.Count;
            return end1IssueCount < end0IssueCount
                ? end1Plan
                : end0Plan;
        }

        private static int ReadEndpointTopologyEvidence(
            Pipe pipe,
            int endpointIndex)
        {
            LocationCurve location = pipe == null
                ? null
                : pipe.Location as LocationCurve;
            if (location == null
                || location.Curve == null
                || pipe.ConnectorManager == null)
            {
                return 0;
            }

            XYZ endpoint = location.Curve.GetEndPoint(
                endpointIndex == 0 ? 0 : 1);
            Connector connector = pipe.ConnectorManager.Connectors
                .Cast<Connector>()
                .Where(item =>
                    item.ConnectorType == ConnectorType.End)
                .OrderBy(item =>
                    item.Origin.DistanceTo(endpoint))
                .FirstOrDefault();
            if (connector == null)
            {
                return 0;
            }

            int evidence = 0;
            var ownerIds = new HashSet<long>();
            foreach (Connector reference in connector.AllRefs)
            {
                if (reference == null
                    || reference.ConnectorType
                        != ConnectorType.End
                    || reference.Owner == null
                    || reference.Owner.Id == pipe.Id
                    || !ownerIds.Add(
                        reference.Owner.Id.Value))
                {
                    continue;
                }

                FamilyInstance fitting =
                    reference.Owner as FamilyInstance;
                if (fitting != null
                    && fitting.MEPModel != null
                    && fitting.MEPModel.ConnectorManager != null)
                {
                    int portCount = fitting.MEPModel
                        .ConnectorManager.Connectors
                        .Cast<Connector>()
                        .Count(item =>
                            item.ConnectorType
                                == ConnectorType.End);
                    evidence = Math.Max(
                        evidence,
                        portCount >= 3 ? 4 : 2);
                    continue;
                }
                if (reference.Owner is Pipe)
                {
                    evidence = Math.Max(evidence, 2);
                }
            }
            return evidence;
        }

        private static Dictionary<string, object> BuildPreviewPayload(
            Document document,
            DrainageRouteRequest request)
        {
            Pipe mainPipe = request.Target.MainPipe;
            PipeType pipeType = document.GetElement(
                mainPipe.GetTypeId()) as PipeType;
            ElementId systemTypeId = ReadSystemTypeId(mainPipe);
            PipingSystemType systemType = document.GetElement(
                systemTypeId) as PipingSystemType;
            ElementId levelId = ReadLevelId(mainPipe);
            Level level = document.GetElement(levelId) as Level;
            if (pipeType == null
                || systemType == null
                || level == null)
            {
                throw new InvalidOperationException(
                    "CONFIGURATION_INVALID: 無法解析幹管的管類型、系統或樓層。");
            }

            Dictionary<string, object> documentRef =
                RfaMetadataApplication
                    .GetDrainageDocumentIdentityInline(document);
            var sourceIds = new ArrayList
            {
                request.Source.ElementId.Value.ToString(
                    CultureInfo.InvariantCulture)
            };
            var sourceUniqueIds = new ArrayList
            {
                request.Source.UniqueId
            };
            return new Dictionary<string, object>
            {
                {
                    "document_fingerprint",
                    ReadString(documentRef, "fingerprint")
                },
                {
                    "document_revision",
                    ReadLong(documentRef, "revision")
                },
                { "main_pipe_id", mainPipe.Id.Value.ToString() },
                { "main_pipe_unique_id", mainPipe.UniqueId },
                { "fixture_ids", sourceIds },
                { "fixture_unique_ids", sourceUniqueIds },
                {
                    "source_connector_origin",
                    new Dictionary<string, object>
                    {
                        {
                            "x",
                            request.Source.SourceConnector.Origin.X
                        },
                        {
                            "y",
                            request.Source.SourceConnector.Origin.Y
                        },
                        {
                            "z",
                            request.Source.SourceConnector.Origin.Z
                        }
                    }
                },
                {
                    "source_connector_key",
                    request.Source.ConnectorRef == null
                        ? ""
                        : request.Source.ConnectorRef.ConnectorKey
                },
                {
                    "profile_id",
                    request.Configuration.ProfileId
                },
                {
                    "profile_kind",
                    request.Configuration.ProfileKind
                },
                { "selection_source", "explicit_user_refs" },
                { "main_candidate_count", 1 },
                { "pipe_type_id", pipeType.Id.Value.ToString() },
                { "pipe_type_unique_id", pipeType.UniqueId },
                { "system_type_id", systemType.Id.Value.ToString() },
                { "system_type_unique_id", systemType.UniqueId },
                { "level_id", level.Id.Value.ToString() },
                { "level_unique_id", level.UniqueId },
                {
                    "junction_type_id",
                    request.Configuration.WyeTypeId.ToString()
                },
                {
                    "junction_type_unique_id",
                    request.Configuration.WyeTypeUniqueId
                },
                {
                    "elbow_type_id",
                    request.Configuration.OffsetElbowTypeId.ToString()
                },
                {
                    "elbow_type_unique_id",
                    request.Configuration.OffsetElbowTypeUniqueId
                },
                {
                    "slope_ratio",
                    request.Configuration.SlopePercent / 100.0
                },
                { "diameter_mm", request.DiameterMm },
                {
                    "main_diameter_mm",
                    request.MainDiameterMm > 0
                        ? request.MainDiameterMm
                        : ReadPipeDiameterMm(request.Target.MainPipe)
                },
                {
                    "downstream_mode",
                    string.IsNullOrWhiteSpace(
                        request.DownstreamMode)
                        ? "auto"
                        : request.DownstreamMode
                },
                {
                    "route_policy",
                    new Dictionary<string, object>
                    {
                        {
                            "route_policy_id",
                            "sc-drainage-route-policy"
                        },
                        {
                            "route_policy_version",
                            "1.4.0"
                        },
                        {
                            "side_entry_angle_degrees",
                            45.0
                        },
                        {
                            "side_entry_tolerance_degrees",
                            5.0
                        },
                        {
                            "radial_minimum_degrees",
                            0.0
                        },
                        {
                            "radial_maximum_degrees",
                            45.0
                        },
                        {
                            "radial_tolerance_degrees",
                            5.0
                        },
                        {
                            "minimum_tangent_mm",
                            request.Configuration
                                .MinimumTangentMm
                        },
                        {
                            "minimum_junction_spacing_mm",
                            Math.Max(
                                300.0,
                                request.DiameterMm * 3.0)
                        },
                        {
                            "collision_clearance_mm",
                            25.0
                        },
                        {
                            "maximum_double45_lateral_offset_mm",
                            25.0
                        },
                        {
                            "maximum_perpendicular_drop_length_mm",
                            Math.Max(
                                1000.0,
                                request.DiameterMm * 10.0)
                        },
                        {
                            "maximum_perpendicular_drop_route_share",
                            0.40
                        }
                    }
                }
            };
        }

        private static void ValidateRequest(
            DrainageRouteRequest request)
        {
            if (request == null
                || request.Source == null
                || request.Source.SourceElement == null
                || request.Source.SourceConnector == null)
            {
                throw new InvalidOperationException(
                    "SOURCE_CONNECTOR_MISSING");
            }
            if (request.Target == null
                || request.Target.MainPipe == null)
            {
                throw new InvalidOperationException(
                    "TARGET_NOT_FOUND");
            }
            if (request.Configuration == null
                || !request.Configuration.SupportsDiameter(
                    request.DiameterMm))
            {
                throw new InvalidOperationException(
                    "PROFILE_NOT_MATCHED");
            }
            if (!string.Equals(
                request.Configuration.ProfileKind,
                "GravityDrainage",
                StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "PROFILE_NOT_MATCHED: 目前只支援 GravityDrainage。");
            }
        }

        private static double ReadPipeDiameterMm(Pipe pipe)
        {
            Parameter parameter = pipe == null
                ? null
                : pipe.get_Parameter(
                    BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
            return parameter == null
                ? 0
                : UnitUtils.ConvertFromInternalUnits(
                    parameter.AsDouble(),
                    UnitTypeId.Millimeters);
        }

        private static ElementId ReadSystemTypeId(Pipe pipe)
        {
            Parameter parameter = pipe.get_Parameter(
                BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM);
            return parameter == null
                ? ElementId.InvalidElementId
                : parameter.AsElementId();
        }

        private static ElementId ReadLevelId(Pipe pipe)
        {
            try
            {
                if (pipe.ReferenceLevel != null)
                {
                    return pipe.ReferenceLevel.Id;
                }
            }
            catch
            {
            }
            Parameter parameter = pipe.get_Parameter(
                BuiltInParameter.RBS_START_LEVEL_PARAM);
            return parameter == null
                ? ElementId.InvalidElementId
                : parameter.AsElementId();
        }

        private static IEnumerable<ElementId> ReadCreatedElementIds(
            IDictionary<string, object> payload)
        {
            ArrayList raw = ReadArray(
                payload,
                "created_element_ids");
            if (raw == null)
            {
                yield break;
            }
            foreach (object item in raw)
            {
                long value;
                if (long.TryParse(
                    Convert.ToString(
                        item,
                        CultureInfo.InvariantCulture),
                    NumberStyles.Integer,
                    CultureInfo.InvariantCulture,
                    out value))
                {
                    yield return new ElementId(value);
                }
            }
        }

        private static DrainageFailureCode ClassifyFailure(
            string message)
        {
            string value = message ?? "";
            if (value.Contains("SOURCE_CONNECTOR_AMBIGUOUS"))
            {
                return DrainageFailureCode
                    .SourceConnectorAmbiguous;
            }
            if (value.Contains("SOURCE_FLOW_INCOMPATIBLE"))
            {
                return DrainageFailureCode
                    .SourceFlowIncompatible;
            }
            if (value.Contains("PROFILE_NOT_MATCHED"))
            {
                return DrainageFailureCode.ProfileNotMatched;
            }
            if (value.Contains("SOURCE_BELOW_TARGET_MAIN"))
            {
                return DrainageFailureCode
                    .SourceBelowTargetMain;
            }
            if (value.Contains("SOURCE_AXIS_ROUTE_UNRESOLVED"))
            {
                return DrainageFailureCode
                    .SourceAxisRouteUnresolved;
            }
            if (value.Contains(
                "SOURCE_GEOMETRY_ADJUSTMENT")
                || value.Contains(
                    "SOURCE_CONNECTED_END_VERIFY_FAILED"))
            {
                return DrainageFailureCode
                    .SourceGeometryAdjustmentBlocked;
            }
            if (value.Contains(
                "TARGET_FITTING_CLEARANCE_CONFLICT"))
            {
                return DrainageFailureCode
                    .TargetFittingClearanceConflict;
            }
            if (value.Contains(
                "TARGET_SEGMENT_CAPACITY_INSUFFICIENT"))
            {
                return DrainageFailureCode
                    .TargetSegmentCapacityInsufficient;
            }
            if (value.Contains("SINGLE45_NOT_FEASIBLE"))
            {
                return DrainageFailureCode
                    .SingleFortyFiveNotFeasible;
            }
            if (value.Contains("NO_FEASIBLE_ROUTE"))
            {
                return DrainageFailureCode.NoFeasibleRoute;
            }
            if (value.Contains("SOURCE_CONNECTOR"))
            {
                return DrainageFailureCode.SourceConnectorMissing;
            }
            if (value.Contains("MAIN_DOWNSTREAM"))
            {
                return DrainageFailureCode.TargetDownstreamUnresolved;
            }
            if (value.Contains("CONFIGURATION")
                || value.Contains("ROUTING_RULE")
                || value.Contains("PROFILE_UNRESOLVED"))
            {
                return DrainageFailureCode.ConfigurationInvalid;
            }
            if (value.Contains("TANGENT_TOO_SHORT"))
            {
                return DrainageFailureCode.MinimumTangentViolation;
            }
            if (value.Contains("JUNCTION_GEOMETRY")
                || value.Contains("JUNCTION_TYPE"))
            {
                return DrainageFailureCode.JunctionDirectionInvalid;
            }
            if (value.Contains("SLOPE"))
            {
                return DrainageFailureCode.SlopeValidationFailed;
            }
            if (value.Contains("TOPOLOGY")
                || value.Contains("DISCONNECTED"))
            {
                return DrainageFailureCode.TopologyValidationFailed;
            }
            return DrainageFailureCode.CommitFailed;
        }

        private static string ReadString(
            IDictionary<string, object> payload,
            string key)
        {
            object value;
            return payload != null
                && payload.TryGetValue(key, out value)
                && value != null
                    ? Convert.ToString(
                        value,
                        CultureInfo.InvariantCulture)
                    : "";
        }

        private static long ReadLong(
            IDictionary<string, object> payload,
            string key)
        {
            long result;
            return long.TryParse(
                ReadString(payload, key),
                NumberStyles.Integer,
                CultureInfo.InvariantCulture,
                out result)
                    ? result
                    : 0;
        }

        private static bool ReadBoolean(
            IDictionary<string, object> payload,
            string key)
        {
            object value;
            if (payload != null
                && payload.TryGetValue(key, out value)
                && value is bool)
            {
                return (bool)value;
            }
            bool result;
            return bool.TryParse(
                ReadString(payload, key),
                out result)
                    && result;
        }

        private static ArrayList ReadArray(
            IDictionary<string, object> payload,
            string key)
        {
            object value;
            return payload != null
                && payload.TryGetValue(key, out value)
                    ? value as ArrayList
                    : null;
        }
    }
}
