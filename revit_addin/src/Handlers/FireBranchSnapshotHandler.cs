using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.UI;
using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Web.Script.Serialization;

namespace RfaMetadataAddin
{
    public partial class RfaMetadataApplication
    {
        private sealed class FireBranchSnapshotElement
        {
            public Element Element { get; set; }
            public List<Connector> Connectors { get; set; }
            public Dictionary<Connector, string> ConnectorKeys { get; set; }
        }

        private static void WriteFireBranchSnapshotResponse(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            Document doc = GetActiveProjectDocument(uiApp);
            List<long> seedIds = ReadFireBranchSnapshotSeedIds(uiApp, doc, payload);
            if (seedIds.Count == 0)
            {
                throw new InvalidOperationException("請先選取至少一段消防主管作為搜尋起點。");
            }

            List<FireBranchSnapshotElement> graphElements = TraverseFireBranchSnapshot(doc, seedIds);
            if (graphElements.Count == 0)
            {
                throw new InvalidOperationException("選取的元素沒有可展開的消防管路 Connector。");
            }

            var nodes = new List<object>();
            var connections = new List<object>();
            var connectionKeys = new HashSet<string>(StringComparer.Ordinal);
            var stoppedConnections = new List<object>();
            foreach (FireBranchSnapshotElement graphElement in graphElements)
            {
                foreach (Connector connector in graphElement.Connectors)
                {
                    if (!IsFireBranchPipingConnector(connector))
                    {
                        continue;
                    }

                    string key = graphElement.ConnectorKeys[connector];
                    nodes.Add(SerializeFireBranchSnapshotConnector(graphElement.Element, connector, key));
                    AddFireBranchSnapshotConnections(
                        graphElement,
                        connector,
                        key,
                        graphElements,
                        connectionKeys,
                        connections,
                        stoppedConnections);
                }
            }

            var elements = graphElements
                .Select(SerializeFireBranchSnapshotElement)
                .ToList();
            var pipeEdges = graphElements
                .Where(item => item.Element is Pipe)
                .Select(SerializeFireBranchSnapshotPipeEdge)
                .Where(item => item != null)
                .ToList();

            View activeView = doc.ActiveView;
            FileWriteFireBranchSnapshot(
                responseFile,
                serializer,
                new
                {
                    action = "read_fire_branch_snapshot",
                    schema_version = "fire_branch_revit_snapshot.v1",
                    snapshot_id = DateTime.UtcNow.ToString("yyyyMMddTHHmmssfffZ"),
                    document = new
                    {
                        title = doc.Title,
                        path_name_present = !string.IsNullOrWhiteSpace(doc.PathName)
                    },
                    active_view = activeView == null
                        ? null
                        : new
                        {
                            view_id = activeView.Id.Value,
                            name = activeView.Name,
                            right = SerializeCadPathPoint(activeView.RightDirection),
                            up = SerializeCadPathPoint(activeView.UpDirection),
                            direction = SerializeCadPathPoint(activeView.ViewDirection)
                        },
                    seed_main_pipe_ids = seedIds,
                    main_graph = new
                    {
                        elements = elements,
                        nodes = nodes,
                        edges = pipeEdges,
                        connections = connections,
                        stopped_connections = stoppedConnections,
                        visited_element_count = graphElements.Count
                    },
                    mutation = new
                    {
                        mode = "read_only",
                        created_element_count = 0,
                        deleted_element_count = 0
                    }
                });
        }

        private static List<long> ReadFireBranchSnapshotSeedIds(
            UIApplication uiApp,
            Document doc,
            Dictionary<string, object> payload)
        {
            var ids = new List<long>();
            ArrayList rawIds = payload.ContainsKey("main_pipe_ids")
                ? payload["main_pipe_ids"] as ArrayList
                : null;
            if (rawIds != null)
            {
                foreach (object rawId in rawIds)
                {
                    long id = Convert.ToInt64(rawId);
                    Pipe pipe = id > 0 ? doc.GetElement(new ElementId(id)) as Pipe : null;
                    if (pipe != null && !ids.Contains(id))
                    {
                        ids.Add(id);
                    }
                }
            }

            long singleId = ReadLong(payload, "main_pipe_id", 0);
            if (singleId > 0 && doc.GetElement(new ElementId(singleId)) is Pipe && !ids.Contains(singleId))
            {
                ids.Add(singleId);
            }

            if (ids.Count == 0 && uiApp.ActiveUIDocument != null)
            {
                foreach (ElementId elementId in uiApp.ActiveUIDocument.Selection.GetElementIds())
                {
                    if (elementId == null || elementId == ElementId.InvalidElementId)
                    {
                        continue;
                    }
                    Pipe pipe = doc.GetElement(elementId) as Pipe;
                    if (pipe != null && !ids.Contains(pipe.Id.Value))
                    {
                        ids.Add(pipe.Id.Value);
                    }
                }
            }
            return ids;
        }

        private static List<FireBranchSnapshotElement> TraverseFireBranchSnapshot(
            Document doc,
            IEnumerable<long> seedIds)
        {
            var result = new List<FireBranchSnapshotElement>();
            var queued = new Queue<Element>();
            var visited = new HashSet<long>();
            foreach (long seedId in seedIds)
            {
                Element seed = doc.GetElement(new ElementId(seedId));
                if (IsFireBranchGraphElement(seed))
                {
                    queued.Enqueue(seed);
                }
            }

            while (queued.Count > 0)
            {
                Element element = queued.Dequeue();
                if (element == null || !element.IsValidObject || !visited.Add(element.Id.Value))
                {
                    continue;
                }
                List<Connector> connectors = GetFireBranchGraphConnectors(element)
                    .Where(IsFireBranchPipingConnector)
                    .ToList();
                if (connectors.Count == 0)
                {
                    continue;
                }
                var record = new FireBranchSnapshotElement
                {
                    Element = element,
                    Connectors = connectors,
                    ConnectorKeys = new Dictionary<Connector, string>()
                };
                for (int index = 0; index < connectors.Count; index++)
                {
                    record.ConnectorKeys[connectors[index]] = element.Id.Value + ":" + index;
                }
                result.Add(record);

                foreach (Connector connector in connectors)
                {
                    ConnectorSet refs = null;
                    try
                    {
                        refs = connector.AllRefs;
                    }
                    catch
                    {
                        refs = null;
                    }
                    if (refs == null)
                    {
                        continue;
                    }
                    foreach (Connector reference in refs)
                    {
                        Element owner = reference != null ? reference.Owner : null;
                        if (owner != null && owner.Id.Value != element.Id.Value && IsFireBranchGraphElement(owner))
                        {
                            queued.Enqueue(owner);
                        }
                    }
                }
            }
            return result;
        }

        private static bool IsFireBranchGraphElement(Element element)
        {
            if (element is Pipe)
            {
                return true;
            }
            FamilyInstance family = element as FamilyInstance;
            if (family == null || family.Category == null)
            {
                return false;
            }
            long categoryId = family.Category.Id.Value;
            return categoryId == (long)BuiltInCategory.OST_PipeFitting
                || categoryId == (long)BuiltInCategory.OST_PipeAccessory;
        }

        private static List<Connector> GetFireBranchGraphConnectors(Element element)
        {
            try
            {
                MEPCurve curve = element as MEPCurve;
                if (curve != null && curve.ConnectorManager != null)
                {
                    return curve.ConnectorManager.Connectors.Cast<Connector>().ToList();
                }
                FamilyInstance family = element as FamilyInstance;
                if (family != null && family.MEPModel != null && family.MEPModel.ConnectorManager != null)
                {
                    return family.MEPModel.ConnectorManager.Connectors.Cast<Connector>().ToList();
                }
            }
            catch
            {
            }
            return new List<Connector>();
        }

        private static bool IsFireBranchPipingConnector(Connector connector)
        {
            try
            {
                return connector != null
                    && connector.IsValidObject
                    && connector.Domain == Domain.DomainPiping;
            }
            catch
            {
                return false;
            }
        }

        private static object SerializeFireBranchSnapshotElement(FireBranchSnapshotElement record)
        {
            Element element = record.Element;
            Pipe pipe = element as Pipe;
            LocationCurve location = pipe != null ? pipe.Location as LocationCurve : null;
            object geometry = null;
            if (location != null && location.Curve != null)
            {
                XYZ start = location.Curve.GetEndPoint(0);
                XYZ end = location.Curve.GetEndPoint(1);
                geometry = new
                {
                    start = SerializeCadPathPoint(start),
                    end = SerializeCadPathPoint(end),
                    length_mm = UnitUtils.ConvertFromInternalUnits(
                        location.Curve.Length,
                        UnitTypeId.Millimeters)
                };
            }
            return new
            {
                element_id = element.Id.Value,
                kind = pipe != null ? "pipe" : "pipe_fitting_or_accessory",
                name = element.Name,
                category = element.Category == null ? "" : element.Category.Name,
                diameter_mm = pipe == null ? (double?)null : ReadFireBranchSnapshotPipeDiameterMm(pipe),
                system_type_id = ReadFireBranchSnapshotSystemTypeId(element),
                geometry = geometry,
                connector_count = record.Connectors.Count
            };
        }

        private static object SerializeFireBranchSnapshotPipeEdge(FireBranchSnapshotElement record)
        {
            Pipe pipe = record.Element as Pipe;
            LocationCurve location = pipe != null ? pipe.Location as LocationCurve : null;
            if (pipe == null || location == null || location.Curve == null || record.Connectors.Count < 2)
            {
                return null;
            }
            Connector start = record.Connectors.OrderBy(item => item.Origin.DistanceTo(location.Curve.GetEndPoint(0))).First();
            Connector end = record.Connectors.OrderBy(item => item.Origin.DistanceTo(location.Curve.GetEndPoint(1))).First();
            return new
            {
                element_id = pipe.Id.Value,
                start_node = record.ConnectorKeys[start],
                end_node = record.ConnectorKeys[end],
                diameter_mm = ReadFireBranchSnapshotPipeDiameterMm(pipe),
                length_mm = UnitUtils.ConvertFromInternalUnits(location.Curve.Length, UnitTypeId.Millimeters)
            };
        }

        private static object SerializeFireBranchSnapshotConnector(
            Element element,
            Connector connector,
            string key)
        {
            XYZ direction = XYZ.BasisZ;
            try
            {
                if (connector.CoordinateSystem != null)
                {
                    direction = connector.CoordinateSystem.BasisZ;
                }
            }
            catch
            {
            }
            return new
            {
                node_id = key,
                owner_element_id = element.Id.Value,
                origin = SerializeCadPathPoint(connector.Origin),
                direction = SerializeCadPathPoint(direction),
                connector_type = connector.ConnectorType.ToString(),
                domain = connector.Domain.ToString(),
                is_connected = connector.IsConnected,
                system_type_id = ReadFireBranchSnapshotConnectorSystemTypeId(connector)
            };
        }

        private static void AddFireBranchSnapshotConnections(
            FireBranchSnapshotElement record,
            Connector connector,
            string connectorKey,
            List<FireBranchSnapshotElement> graphElements,
            HashSet<string> connectionKeys,
            List<object> connections,
            List<object> stoppedConnections)
        {
            ConnectorSet refs = null;
            try
            {
                refs = connector.AllRefs;
            }
            catch
            {
            }
            if (refs == null)
            {
                return;
            }
            foreach (Connector reference in refs)
            {
                Element owner = reference != null ? reference.Owner : null;
                if (owner == null || owner.Id.Value == record.Element.Id.Value)
                {
                    continue;
                }
                FireBranchSnapshotElement target = graphElements.FirstOrDefault(item => item.Element.Id.Value == owner.Id.Value);
                if (target == null)
                {
                    stoppedConnections.Add(new
                    {
                        from_node = connectorKey,
                        target_element_id = owner.Id.Value,
                        target_name = owner.Name,
                        reason = "連接到非主管圖元素，於此停止展開"
                    });
                    continue;
                }
                Connector targetConnector = target.Connectors
                    .OrderBy(item => item.Origin.DistanceTo(reference.Origin))
                    .FirstOrDefault();
                if (targetConnector == null)
                {
                    continue;
                }
                string targetKey = target.ConnectorKeys[targetConnector];
                string orderedKey = String.CompareOrdinal(connectorKey, targetKey) < 0
                    ? connectorKey + "|" + targetKey
                    : targetKey + "|" + connectorKey;
                if (connectionKeys.Add(orderedKey))
                {
                    connections.Add(new
                    {
                        from_node = connectorKey,
                        to_node = targetKey,
                        from_element_id = record.Element.Id.Value,
                        to_element_id = target.Element.Id.Value,
                        connected = true
                    });
                }
            }
        }

        private static double? ReadFireBranchSnapshotPipeDiameterMm(Pipe pipe)
        {
            double feet = GetPipeDiameterFeet(pipe);
            return feet > 0
                ? (double?)UnitUtils.ConvertFromInternalUnits(feet, UnitTypeId.Millimeters)
                : null;
        }

        private static long ReadFireBranchSnapshotSystemTypeId(Element element)
        {
            try
            {
                Pipe pipe = element as Pipe;
                MEPSystem system = pipe != null ? pipe.MEPSystem : null;
                return system == null || system.GetTypeId() == null ? 0 : system.GetTypeId().Value;
            }
            catch
            {
                return 0;
            }
        }

        private static long ReadFireBranchSnapshotConnectorSystemTypeId(Connector connector)
        {
            try
            {
                MEPSystem system = connector.MEPSystem;
                return system == null || system.GetTypeId() == null ? 0 : system.GetTypeId().Value;
            }
            catch
            {
                return 0;
            }
        }

        private static void FileWriteFireBranchSnapshot(
            string responseFile,
            JavaScriptSerializer serializer,
            object response)
        {
            System.IO.File.WriteAllText(responseFile, serializer.Serialize(response));
        }
    }
}
