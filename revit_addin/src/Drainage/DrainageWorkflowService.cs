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
                return DrainageExecutionResult.Failed(
                    DrainageFailureCode.RouteBlocked,
                    plan.Issues.Count == 0
                        ? "排水路徑未通過 preflight。"
                        : string.Join(
                            Environment.NewLine,
                            plan.Issues));
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
                            "human_interactive");
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
                                ? "human_interactive"
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
                    Message = "接管完成。"
                };
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
                    "downstream_mode",
                    string.IsNullOrWhiteSpace(
                        request.DownstreamMode)
                        ? "auto"
                        : request.DownstreamMode
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
                    "CONFIGURATION_MISSING");
            }
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
