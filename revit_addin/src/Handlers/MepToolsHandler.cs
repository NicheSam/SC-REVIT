using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Electrical;
using Autodesk.Revit.DB.Mechanical;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.UI;
using System;
using System.Collections.Generic;
using System.Collections;
using System.IO;
using System.Linq;
using System.Web.Script.Serialization;

namespace RfaMetadataAddin
{
    public partial class RfaMetadataApplication
    {
        private static readonly HashSet<string> MepToolsActions = new HashSet<string>(StringComparer.Ordinal)
        {
            "inspect_selected_elements",
            "scan_sc_parameters",
            "diagnose_mep_connectors",
            "connect_pipe_fittings",
            "preview_piping_support_points"
        };

        private static bool TryHandleMepToolsAction(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            if (!MepToolsActions.Contains(action))
            {
                return false;
            }

            HandleMepToolsAction(uiApp, payload, action, responseFile, serializer);
            return true;
        }

        private static void HandleMepToolsAction(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            Document doc = GetActiveProjectDocument(uiApp);
            if (action == "inspect_selected_elements")
            {
                List<Element> elements = GetSelectedElements(uiApp, doc);
                File.WriteAllText(
                    responseFile,
                    serializer.Serialize(new
                    {
                        action = action,
                        document = SerializeDocumentIdentity(doc),
                        selected_count = elements.Count,
                        elements = elements.Select(element => SerializeElementInspection(doc, element)).ToList()
                    })
                );
                return;
            }

            if (action == "scan_sc_parameters")
            {
                string scope = ReadPayloadText(payload, "scope", "selection");
                string prefix = ReadPayloadText(payload, "parameter_prefix", "SC_");
                List<string> expected = ReadStringList(payload, "expected_parameters");
                List<Element> elements = scope == "active_view"
                    ? new FilteredElementCollector(doc, doc.ActiveView.Id).WhereElementIsNotElementType().ToElements().ToList()
                    : GetSelectedElements(uiApp, doc);
                List<string> discovered = elements
                    .SelectMany(element => GetParametersByPrefix(element, prefix).Select(item => item.Name))
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .OrderBy(item => item)
                    .ToList();
                List<string> standard = expected.Count > 0 ? expected : discovered;
                File.WriteAllText(
                    responseFile,
                    serializer.Serialize(new
                    {
                        action = action,
                        document = SerializeDocumentIdentity(doc),
                        scope = scope,
                        parameter_prefix = prefix,
                        scanned_count = elements.Count,
                        expected_parameters = standard,
                        elements = elements.Select(element => SerializeParameterAudit(doc, element, prefix, standard)).ToList()
                    })
                );
                return;
            }

            if (action == "diagnose_mep_connectors")
            {
                double maxDistanceFeet = UnitUtils.ConvertToInternalUnits(
                    ReadDouble(payload, "max_distance_mm", 50),
                    UnitTypeId.Millimeters
                );
                List<Element> elements = GetSelectedElements(uiApp, doc)
                    .Where(IsSupportedMepConnectorElement)
                    .ToList();
                List<ConnectorSnapshot> openConnectors = elements
                    .SelectMany(GetConnectorSnapshots)
                    .Where(item => !item.IsConnected)
                    .ToList();
                File.WriteAllText(
                    responseFile,
                    serializer.Serialize(new
                    {
                        action = action,
                        document = SerializeDocumentIdentity(doc),
                        selected_count = elements.Count,
                        elements = elements.Select(SerializeConnectorDiagnosis).ToList(),
                        nearest_open_pairs = FindNearestOpenConnectorPairs(openConnectors, 10, maxDistanceFeet)
                    })
                );
                return;
            }

            if (action == "connect_pipe_fittings")
            {
                double maxDistanceFeet = UnitUtils.ConvertToInternalUnits(
                    ReadDouble(payload, "max_distance_mm", 50),
                    UnitTypeId.Millimeters
                );
                List<Pipe> pipes = GetSelectedElements(uiApp, doc).OfType<Pipe>().ToList();
                List<object> connected = new List<object>();
                List<object> failed = new List<object>();
                List<object> created = new List<object>();
                using (Transaction transaction = new Transaction(doc, "SC connect pipe fittings"))
                {
                    transaction.Start();
                    foreach (ConnectorPair pair in FindPipeConnectorPairs(pipes, maxDistanceFeet))
                    {
                        try
                        {
                            FamilyInstance fitting = doc.Create.NewElbowFitting(pair.A.Connector, pair.B.Connector);
                            if (fitting != null)
                            {
                                created.Add(SerializeCreatedElement(doc, fitting));
                            }
                            connected.Add(SerializeConnectorPair(pair, maxDistanceFeet));
                        }
                        catch (Exception ex)
                        {
                            try
                            {
                                pair.A.Connector.ConnectTo(pair.B.Connector);
                                connected.Add(SerializeConnectorPair(pair, maxDistanceFeet));
                            }
                            catch (Exception connectEx)
                            {
                                failed.Add(new
                                {
                                    status_code = "failed",
                                    a_element_id = pair.A.OwnerId,
                                    b_element_id = pair.B.OwnerId,
                                    distance_mm = UnitUtils.ConvertFromInternalUnits(pair.DistanceFeet, UnitTypeId.Millimeters),
                                    reason_code = "fitting_create_failed",
                                    recommendation_code = "manual_adjust_then_retry",
                                    error = ex.Message + " / " + connectEx.Message
                                });
                            }
                        }
                    }
                    transaction.Commit();
                }
                File.WriteAllText(
                    responseFile,
                    serializer.Serialize(new
                    {
                        action = action,
                        document = SerializeDocumentIdentity(doc),
                        pipe_count = pipes.Count,
                        connected_count = connected.Count,
                        failed_count = failed.Count,
                        connected = connected,
                        failed = failed,
                        created = created
                    })
                );
                return;
            }

            if (action == "preview_piping_support_points")
            {
                double spacingFeet = UnitUtils.ConvertToInternalUnits(ReadDouble(payload, "spacing_cm", 150), UnitTypeId.Centimeters);
                double startOffsetFeet = UnitUtils.ConvertToInternalUnits(ReadDouble(payload, "start_offset_cm", 30), UnitTypeId.Centimeters);
                double endOffsetFeet = UnitUtils.ConvertToInternalUnits(ReadDouble(payload, "end_offset_cm", 30), UnitTypeId.Centimeters);
                double markerSizeFeet = UnitUtils.ConvertToInternalUnits(ReadDouble(payload, "marker_size_cm", 10), UnitTypeId.Centimeters);
                List<Pipe> pipes = GetSelectedElements(uiApp, doc).OfType<Pipe>().ToList();
                List<SupportPoint> points = BuildSupportCandidatePoints(pipes, spacingFeet, startOffsetFeet, endOffsetFeet);
                List<ElementId> createdIds = new List<ElementId>();
                string batchId = DateTime.Now.ToString("yyyyMMdd-HHmmss");
                string groupName = "";
                long groupId = 0;
                using (Transaction transaction = new Transaction(doc, "SC piping support preview"))
                {
                    transaction.Start();
                    OverrideGraphicSettings overrides = new OverrideGraphicSettings();
                    overrides.SetProjectionLineColor(new Autodesk.Revit.DB.Color(255, 190, 60));
                    overrides.SetProjectionLineWeight(7);
                    foreach (SupportPoint point in points)
                    {
                        SketchPlane sketchPlane = SketchPlane.Create(
                            doc,
                            Plane.CreateByNormalAndOrigin(XYZ.BasisZ, point.Point)
                        );
                        ModelCurve curveA = doc.Create.NewModelCurve(
                            Line.CreateBound(point.Point + new XYZ(-markerSizeFeet, 0, 0), point.Point + new XYZ(markerSizeFeet, 0, 0)),
                            sketchPlane
                        );
                        ModelCurve curveB = doc.Create.NewModelCurve(
                            Line.CreateBound(point.Point + new XYZ(0, -markerSizeFeet, 0), point.Point + new XYZ(0, markerSizeFeet, 0)),
                            sketchPlane
                        );
                        createdIds.Add(curveA.Id);
                        createdIds.Add(curveB.Id);
                        try
                        {
                            doc.ActiveView.SetElementOverrides(curveA.Id, overrides);
                            doc.ActiveView.SetElementOverrides(curveB.Id, overrides);
                        }
                        catch
                        {
                        }
                    }
                    if (createdIds.Count > 0)
                    {
                        Autodesk.Revit.DB.Group group = doc.Create.NewGroup(createdIds);
                        groupId = group.Id.Value;
                        groupName = MakeUniqueGroupTypeName(doc, "SC_piping_support_preview_" + batchId);
                        try
                        {
                            group.GroupType.Name = groupName;
                        }
                        catch
                        {
                            groupName = group.GroupType != null ? group.GroupType.Name : groupName;
                        }
                    }
                    transaction.Commit();
                }
                File.WriteAllText(
                    responseFile,
                    serializer.Serialize(new
                    {
                        action = action,
                        document = SerializeDocumentIdentity(doc),
                        pipe_count = pipes.Count,
                        point_count = points.Count,
                        group_id = groupId,
                        group_name = groupName,
                        support_family_id = ReadPayloadText(payload, "support_family_id", ""),
                        support_type_id = ReadPayloadText(payload, "support_type_id", ""),
                        points = points.Select(SerializeSupportPoint).ToList()
                    })
                );
                return;
            }
        }

        private static List<Element> GetSelectedElements(UIApplication uiApp, Document doc)
        {
            return uiApp.ActiveUIDocument.Selection.GetElementIds()
                .Select(id => doc.GetElement(id))
                .Where(element => element != null)
                .ToList();
        }

        private static string ReadPayloadText(Dictionary<string, object> payload, string key, string defaultValue)
        {
            if (!payload.ContainsKey(key) || payload[key] == null)
            {
                return defaultValue;
            }
            string value = payload[key].ToString();
            return string.IsNullOrWhiteSpace(value) ? defaultValue : value;
        }

        private static object SerializeDocumentIdentity(Document doc)
        {
            return new
            {
                title = doc.Title,
                path = doc.PathName
            };
        }

        private static object SerializeElementInspection(Document doc, Element element)
        {
            Element type = doc.GetElement(element.GetTypeId());
            FamilyInstance instance = element as FamilyInstance;
            List<ConnectorSnapshot> connectors = GetConnectorSnapshots(element);
            List<ParameterSnapshot> scParameters = GetParametersByPrefix(element, "SC_");
            string statusCode = scParameters.Count > 0 ? "trackable" : "revit_identity_only";
            return new
            {
                element_id = element.Id.Value,
                unique_id = element.UniqueId,
                category = element.Category != null ? element.Category.Name : "",
                class_name = element.GetType().Name,
                name = element.Name,
                type_name = type != null ? type.Name : "",
                family_name = instance != null && instance.Symbol != null && instance.Symbol.Family != null ? instance.Symbol.Family.Name : "",
                location = SerializePoint(GetElementPoint(element)),
                connector_count = connectors.Count,
                open_connector_count = connectors.Count(item => !item.IsConnected),
                sc_parameter_count = scParameters.Count,
                status_code = statusCode,
                management_code = scParameters.Count > 0 ? "sync_or_report" : "reference_only",
                issue_code = scParameters.Count > 0 ? "none" : "missing_sc_parameters",
                recommendation_code = scParameters.Count > 0 ? "can_sync_or_report" : "add_tracking_parameters_before_management",
                sc_parameters = scParameters.Select(SerializeParameterSnapshot).ToList()
            };
        }

        private static object SerializeParameterAudit(Document doc, Element element, string prefix, List<string> expected)
        {
            List<ParameterSnapshot> found = GetParametersByPrefix(element, prefix);
            HashSet<string> foundNames = new HashSet<string>(found.Select(item => item.Name), StringComparer.OrdinalIgnoreCase);
            List<string> missing = expected.Where(item => !foundNames.Contains(item)).ToList();
            List<string> empty = found
                .Where(item => string.IsNullOrWhiteSpace(item.Value))
                .Select(item => item.Name)
                .ToList();
            string statusCode = "pass";
            if (expected.Count == 0 && found.Count == 0)
            {
                statusCode = "not_managed";
            }
            else if (missing.Count > 0)
            {
                statusCode = "missing_required";
            }
            else if (empty.Count > 0)
            {
                statusCode = "empty_values";
            }
            return new
            {
                element_id = element.Id.Value,
                unique_id = element.UniqueId,
                category = element.Category != null ? element.Category.Name : "",
                name = element.Name,
                sc_parameter_count = found.Count,
                missing_count = missing.Count,
                empty_count = empty.Count,
                status_code = statusCode,
                missing_parameters = missing,
                empty_parameters = empty,
                recommendation_code = GetParameterAuditRecommendation(statusCode),
                parameters = found.Select(SerializeParameterSnapshot).ToList()
            };
        }

        private static string GetParameterAuditRecommendation(string statusCode)
        {
            if (statusCode == "not_managed")
            {
                return "add_tracking_parameters_if_needed";
            }
            if (statusCode == "missing_required")
            {
                return "add_missing_parameters";
            }
            if (statusCode == "empty_values")
            {
                return "fill_empty_values";
            }
            return "no_action";
        }

        private static List<ParameterSnapshot> GetParametersByPrefix(Element element, string prefix)
        {
            List<ParameterSnapshot> snapshots = new List<ParameterSnapshot>();
            foreach (Parameter parameter in element.Parameters)
            {
                string name = parameter.Definition != null ? parameter.Definition.Name : "";
                if (!name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }
                snapshots.Add(new ParameterSnapshot
                {
                    Name = name,
                    Value = ReadParameterDisplayValue(parameter),
                    StorageType = parameter.StorageType.ToString(),
                    IsReadOnly = parameter.IsReadOnly
                });
            }
            return snapshots.OrderBy(item => item.Name).ToList();
        }

        private static object SerializeParameterSnapshot(ParameterSnapshot snapshot)
        {
            return new
            {
                name = snapshot.Name,
                value = snapshot.Value,
                storage_type = snapshot.StorageType,
                is_read_only = snapshot.IsReadOnly
            };
        }

        private static string ReadParameterDisplayValue(Parameter parameter)
        {
            try
            {
                string formatted = parameter.AsValueString();
                if (!string.IsNullOrWhiteSpace(formatted))
                {
                    return formatted;
                }
            }
            catch
            {
            }
            switch (parameter.StorageType)
            {
                case StorageType.Double:
                    return parameter.AsDouble().ToString();
                case StorageType.Integer:
                    return parameter.AsInteger().ToString();
                case StorageType.ElementId:
                    return parameter.AsElementId().Value.ToString();
                case StorageType.String:
                    return parameter.AsString() ?? "";
                default:
                    return "";
            }
        }

        private static bool IsSupportedMepConnectorElement(Element element)
        {
            return element is Pipe || element is Duct || element is Conduit || element is FamilyInstance;
        }

        private static ConnectorSet GetConnectorSet(Element element)
        {
            MEPCurve curve = element as MEPCurve;
            if (curve != null && curve.ConnectorManager != null)
            {
                return curve.ConnectorManager.Connectors;
            }
            FamilyInstance instance = element as FamilyInstance;
            if (instance != null && instance.MEPModel != null && instance.MEPModel.ConnectorManager != null)
            {
                return instance.MEPModel.ConnectorManager.Connectors;
            }
            return null;
        }

        private static List<ConnectorSnapshot> GetConnectorSnapshots(Element element)
        {
            List<ConnectorSnapshot> snapshots = new List<ConnectorSnapshot>();
            ConnectorSet connectors = GetConnectorSet(element);
            if (connectors == null)
            {
                return snapshots;
            }
            foreach (Connector connector in connectors)
            {
                try
                {
                    snapshots.Add(new ConnectorSnapshot
                    {
                        Connector = connector,
                        OwnerId = element.Id.Value,
                        OwnerName = element.Name,
                        OwnerKind = GetMepKind(element),
                        IsConnected = connector.IsConnected,
                        Point = connector.Origin,
                        Domain = connector.Domain.ToString(),
                        ConnectorType = connector.ConnectorType.ToString()
                    });
                }
                catch
                {
                }
            }
            return snapshots;
        }

        private static string GetMepKind(Element element)
        {
            if (element is Pipe)
            {
                return "pipe";
            }
            if (element is Duct)
            {
                return "duct";
            }
            if (element is Conduit)
            {
                return "conduit";
            }
            return "family";
        }

        private static object SerializeConnectorDiagnosis(Element element)
        {
            List<ConnectorSnapshot> connectors = GetConnectorSnapshots(element);
            int openCount = connectors.Count(item => !item.IsConnected);
            string statusCode = "normal";
            string reasonCode = "all_connected";
            string recommendationCode = "no_action";
            if (connectors.Count == 0)
            {
                statusCode = "no_connectors";
                reasonCode = "element_has_no_connectors";
                recommendationCode = "skip_or_select_mep_curve";
            }
            else if (openCount > 0 && element is Pipe)
            {
                statusCode = "has_pipe_break";
                reasonCode = "pipe_has_open_connectors";
                recommendationCode = "review_repairable_pairs";
            }
            else if (openCount > 0)
            {
                statusCode = "diagnostic_only";
                reasonCode = "non_pipe_has_open_connectors";
                recommendationCode = "manual_repair_only";
            }
            return new
            {
                element_id = element.Id.Value,
                unique_id = element.UniqueId,
                kind = GetMepKind(element),
                category = element.Category != null ? element.Category.Name : "",
                name = element.Name,
                connector_count = connectors.Count,
                open_connector_count = openCount,
                status = connectors.Count == 0 ? "no_connectors" : (openCount > 0 ? "has_open_connectors" : "connected"),
                status_code = statusCode,
                reason_code = reasonCode,
                recommendation_code = recommendationCode
            };
        }

        private static List<object> FindNearestOpenConnectorPairs(List<ConnectorSnapshot> openConnectors, int limit, double maxDistanceFeet)
        {
            return openConnectors
                .SelectMany((a, index) => openConnectors.Skip(index + 1).Select(b => new ConnectorPair(a, b)))
                .Where(pair => pair.A.OwnerId != pair.B.OwnerId)
                .OrderBy(pair => pair.DistanceFeet)
                .Take(limit)
                .Select(pair => SerializeConnectorPair(pair, maxDistanceFeet))
                .ToList();
        }

        private static List<ConnectorPair> FindPipeConnectorPairs(List<Pipe> pipes, double maxDistanceFeet)
        {
            List<ConnectorSnapshot> connectors = pipes
                .SelectMany(GetConnectorSnapshots)
                .Where(item => !item.IsConnected)
                .ToList();
            List<ConnectorPair> candidates = connectors
                .SelectMany((a, index) => connectors.Skip(index + 1).Select(b => new ConnectorPair(a, b)))
                .Where(pair => pair.A.OwnerId != pair.B.OwnerId && pair.DistanceFeet <= maxDistanceFeet)
                .OrderBy(pair => pair.DistanceFeet)
                .ToList();
            HashSet<string> used = new HashSet<string>();
            List<ConnectorPair> selected = new List<ConnectorPair>();
            foreach (ConnectorPair pair in candidates)
            {
                string aKey = ConnectorKey(pair.A);
                string bKey = ConnectorKey(pair.B);
                if (used.Contains(aKey) || used.Contains(bKey))
                {
                    continue;
                }
                selected.Add(pair);
                used.Add(aKey);
                used.Add(bKey);
            }
            return selected;
        }

        private static string ConnectorKey(ConnectorSnapshot connector)
        {
            return connector.OwnerId + ":" + Math.Round(connector.Point.X, 6) + ":" + Math.Round(connector.Point.Y, 6) + ":" + Math.Round(connector.Point.Z, 6);
        }

        private static object SerializeConnectorPair(ConnectorPair pair, double maxDistanceFeet)
        {
            bool bothPipes = pair.A.OwnerKind == "pipe" && pair.B.OwnerKind == "pipe";
            string statusCode = "diagnostic_only";
            string reasonCode = "non_pipe_pair";
            string recommendationCode = "manual_repair_only";
            if (bothPipes && (maxDistanceFeet <= 0 || pair.DistanceFeet <= maxDistanceFeet))
            {
                statusCode = "repairable";
                reasonCode = "pipe_pair_within_threshold";
                recommendationCode = "can_auto_repair_pipe";
            }
            else if (bothPipes)
            {
                statusCode = "too_far";
                reasonCode = "pipe_pair_over_threshold";
                recommendationCode = "check_selection_or_adjust_manually";
            }
            return new
            {
                status_code = statusCode,
                a_element_id = pair.A.OwnerId,
                b_element_id = pair.B.OwnerId,
                a_kind = pair.A.OwnerKind,
                b_kind = pair.B.OwnerKind,
                distance_mm = Math.Round(UnitUtils.ConvertFromInternalUnits(pair.DistanceFeet, UnitTypeId.Millimeters), 2),
                reason_code = reasonCode,
                recommendation_code = recommendationCode,
                a_point = SerializePoint(pair.A.Point),
                b_point = SerializePoint(pair.B.Point)
            };
        }

        private static object SerializeCreatedElement(Document doc, Element element)
        {
            return new
            {
                element_id = element.Id.Value,
                unique_id = element.UniqueId,
                category = element.Category != null ? element.Category.Name : "",
                name = element.Name,
                document_title = doc.Title,
                document_path = doc.PathName
            };
        }

        private static List<SupportPoint> BuildSupportCandidatePoints(
            List<Pipe> pipes,
            double spacingFeet,
            double startOffsetFeet,
            double endOffsetFeet)
        {
            List<SupportPoint> points = new List<SupportPoint>();
            if (spacingFeet <= 0)
            {
                return points;
            }
            foreach (Pipe pipe in pipes)
            {
                LocationCurve location = pipe.Location as LocationCurve;
                if (location == null)
                {
                    continue;
                }
                Curve curve = location.Curve;
                double usableLength = curve.Length - startOffsetFeet - endOffsetFeet;
                if (usableLength < 0)
                {
                    continue;
                }
                int index = 1;
                double distance = startOffsetFeet;
                while (distance <= curve.Length - endOffsetFeet + 0.000001)
                {
                    double normalized = curve.Length <= 0 ? 0 : distance / curve.Length;
                    points.Add(new SupportPoint
                    {
                        PipeId = pipe.Id.Value,
                        Index = index,
                        DistanceFeet = distance,
                        Point = curve.Evaluate(normalized, true)
                    });
                    index++;
                    distance += spacingFeet;
                }
            }
            return points;
        }

        private static object SerializeSupportPoint(SupportPoint point)
        {
            return new
            {
                pipe_id = point.PipeId,
                index = point.Index,
                distance_cm = Math.Round(UnitUtils.ConvertFromInternalUnits(point.DistanceFeet, UnitTypeId.Centimeters), 2),
                point = SerializePoint(point.Point)
            };
        }

        private class ParameterSnapshot
        {
            public string Name { get; set; }
            public string Value { get; set; }
            public string StorageType { get; set; }
            public bool IsReadOnly { get; set; }
        }

        private class ConnectorSnapshot
        {
            public Connector Connector { get; set; }
            public long OwnerId { get; set; }
            public string OwnerName { get; set; }
            public string OwnerKind { get; set; }
            public bool IsConnected { get; set; }
            public XYZ Point { get; set; }
            public string Domain { get; set; }
            public string ConnectorType { get; set; }
        }

        private class ConnectorPair
        {
            public ConnectorPair(ConnectorSnapshot a, ConnectorSnapshot b)
            {
                A = a;
                B = b;
                DistanceFeet = a.Point.DistanceTo(b.Point);
            }

            public ConnectorSnapshot A { get; private set; }
            public ConnectorSnapshot B { get; private set; }
            public double DistanceFeet { get; private set; }
        }

        private class SupportPoint
        {
            public long PipeId { get; set; }
            public int Index { get; set; }
            public double DistanceFeet { get; set; }
            public XYZ Point { get; set; }
        }
    }
}
