using Autodesk.Revit.DB;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;
using Autodesk.Revit.DB.Structure;
using Autodesk.Revit.DB.Plumbing;
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Reflection;
using System.Web.Script.Serialization;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace RfaMetadataAddin
{
    public partial class RfaMetadataApplication
    {
        private static readonly HashSet<string> FireBranchActions = new HashSet<string>(StringComparer.Ordinal)
        {
            "list_fire_branch_context",
            "read_fire_branch_selection",
            "create_fire_branch_preview",
            "create_fire_branch_pipes"
        };
        private const string ScFireBranchCommentPrefix = "SC_FIRE_BRANCH:";

        [ThreadStatic]
        private static string _fireBranchConnectionDiagnostic;

        private sealed class FireBranchConnectorVerificationException : InvalidOperationException
        {
            public object FailureDetails { get; private set; }

            public FireBranchConnectorVerificationException(string message, object failureDetails)
                : base(message)
            {
                FailureDetails = failureDetails;
            }
        }

        private static void ResetFireBranchConnectionDiagnostic()
        {
            _fireBranchConnectionDiagnostic = null;
        }

        private static void SetFireBranchConnectionDiagnostic(string stage, Exception exception)
        {
            string detail = exception == null
                ? "unknown failure"
                : exception.GetType().Name + ": " + exception.Message;
            _fireBranchConnectionDiagnostic = stage + " | " + detail;
        }

        private static void SetFireBranchConnectionDiagnostic(string detail)
        {
            _fireBranchConnectionDiagnostic = detail;
        }

        private static string ReadFireBranchConnectionDiagnostic()
        {
            return string.IsNullOrWhiteSpace(_fireBranchConnectionDiagnostic)
                ? "Revit rejected the fitting without an exception detail."
                : _fireBranchConnectionDiagnostic;
        }

        private enum FireBranchJunctionTopology
        {
            SingleSideSameElevation,
            OppositeSidesSameElevation,
            SingleSideOffsetElevation,
            OppositeSidesOffsetElevation,
            Complex
        }

        private class FireBranchJunctionPlan
        {
            public long MainPipeId { get; set; }
            public double MainParameter { get; set; }
            public FireBranchJunctionTopology Topology { get; set; }
            public List<List<FireBranchItem>> Rows { get; private set; }

            public FireBranchJunctionPlan()
            {
                Rows = new List<List<FireBranchItem>>();
            }
        }

        private class FireMainPipeData
        {
            public Pipe Pipe { get; set; }
            public long PipeId { get; set; }
            public XYZ Start { get; set; }
            public XYZ End { get; set; }
            public XYZ Direction { get; set; }
            public XYZ BaseBranchDirection { get; set; }
            public double Length { get; set; }
            public double Z { get; set; }
            public double DiameterFeet { get; set; }
        }

        private class FireMainGraphNode
        {
            public int Index { get; set; }
            public XYZ Point { get; set; }
            public List<FireMainGraphEdge> Edges { get; private set; }

            public FireMainGraphNode()
            {
                Edges = new List<FireMainGraphEdge>();
            }
        }

        private class FireMainGraphEdge
        {
            public FireMainPipeData Pipe { get; set; }
            public int A { get; set; }
            public int B { get; set; }
            public double Length { get; set; }
        }

        private class FireMainPathState
        {
            public double Distance { get; set; }
            public int PreviousNode { get; set; }
            public FireMainGraphEdge PreviousEdge { get; set; }
            public bool Visited { get; set; }
        }

        private static List<FireMainPipeData> ReadFireMainPipes(Document doc, Dictionary<string, object> payload)
        {
            int candidateCount = 0;
            int excludedCount = 0;
            return ReadFireMainPipes(doc, payload, out candidateCount, out excludedCount);
        }

        private static List<FireMainPipeData> ReadFireMainPipes(
            Document doc,
            Dictionary<string, object> payload,
            out int candidateCount,
            out int excludedCount)
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
                    if (id > 0 && !ids.Contains(id))
                    {
                        ids.Add(id);
                    }
                }
            }

            long singleId = ReadLong(payload, "main_pipe_id", 0);
            if (singleId > 0 && !ids.Contains(singleId))
            {
                ids.Add(singleId);
            }

            double shortPipeFeet = UnitUtils.ConvertToInternalUnits(50, UnitTypeId.Centimeters);
            double riserHorizontalFeet = UnitUtils.ConvertToInternalUnits(30, UnitTypeId.Centimeters);
            double riserVerticalFeet = UnitUtils.ConvertToInternalUnits(30, UnitTypeId.Centimeters);
            var candidates = new List<FireMainPipeData>();
            foreach (long id in ids)
            {
                Pipe pipe = doc.GetElement(new ElementId(id)) as Pipe;
                LocationCurve curve = pipe != null ? pipe.Location as LocationCurve : null;
                if (curve == null)
                {
                    continue;
                }
                XYZ start = curve.Curve.GetEndPoint(0);
                XYZ end = curve.Curve.GetEndPoint(1);
                XYZ direction = NormalizeXY(end - start);
                double length = Math.Sqrt(Math.Pow(end.X - start.X, 2) + Math.Pow(end.Y - start.Y, 2));
                if (length < 0.01)
                {
                    continue;
                }
                candidates.Add(new FireMainPipeData
                {
                    Pipe = pipe,
                    PipeId = id,
                    Start = start,
                    End = end,
                    Direction = direction,
                    BaseBranchDirection = new XYZ(-direction.Y, direction.X, 0),
                    Length = length,
                    Z = (start.Z + end.Z) * 0.5,
                    DiameterFeet = GetPipeDiameterFeet(pipe)
                });
            }
            candidateCount = candidates.Count;
            excludedCount = 0;
            double maxDiameterFeet = candidates.Count > 0 ? candidates.Max(item => item.DiameterFeet) : 0;
            var mains = new List<FireMainPipeData>();
            foreach (FireMainPipeData candidate in candidates)
            {
                double zDelta = Math.Abs(candidate.End.Z - candidate.Start.Z);
                if (IsScFireBranchPipe(candidate.Pipe)
                    || candidate.Length < shortPipeFeet
                    || (candidate.Length < riserHorizontalFeet && zDelta > riserVerticalFeet)
                    || (maxDiameterFeet > 0
                        && candidate.DiameterFeet > 0
                        && candidate.DiameterFeet < maxDiameterFeet * 0.75))
                {
                    excludedCount += 1;
                    continue;
                }
                mains.Add(candidate);
            }
            List<FireMainPipeData> pathMains = KeepMainPathSegments(mains);
            excludedCount += mains.Count - pathMains.Count;
            return pathMains;
        }

        private static List<FireMainPipeData> KeepMainPathSegments(List<FireMainPipeData> candidates)
        {
            if (candidates.Count <= 2)
            {
                return candidates;
            }

            double snapTolerance = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters);
            var nodes = new List<FireMainGraphNode>();
            var edges = new List<FireMainGraphEdge>();
            foreach (FireMainPipeData pipe in candidates)
            {
                int startNode = FindOrAddFireMainNode(nodes, pipe.Start, snapTolerance);
                int endNode = FindOrAddFireMainNode(nodes, pipe.End, snapTolerance);
                if (startNode == endNode)
                {
                    continue;
                }

                var edge = new FireMainGraphEdge
                {
                    Pipe = pipe,
                    A = startNode,
                    B = endNode,
                    Length = pipe.Length
                };
                edges.Add(edge);
                nodes[startNode].Edges.Add(edge);
                nodes[endNode].Edges.Add(edge);
            }

            if (edges.Count <= 2)
            {
                return edges.Select(edge => edge.Pipe).ToList();
            }

            var keepIds = new HashSet<long>();
            foreach (List<int> component in BuildFireMainNodeComponents(nodes))
            {
                List<FireMainGraphEdge> componentEdges = edges
                    .Where(edge => component.Contains(edge.A) || component.Contains(edge.B))
                    .ToList();
                if (componentEdges.Count <= 2)
                {
                    foreach (FireMainGraphEdge edge in componentEdges)
                    {
                        keepIds.Add(edge.Pipe.PipeId);
                    }
                    continue;
                }

                List<FireMainGraphEdge> pathEdges = FindLongestFireMainPath(nodes, component);
                foreach (FireMainGraphEdge edge in pathEdges)
                {
                    keepIds.Add(edge.Pipe.PipeId);
                }
            }

            var result = candidates.Where(item => keepIds.Contains(item.PipeId)).ToList();
            return result.Count > 0 ? result : candidates;
        }

        private static int FindOrAddFireMainNode(List<FireMainGraphNode> nodes, XYZ point, double tolerance)
        {
            for (int index = 0; index < nodes.Count; index++)
            {
                XYZ existing = nodes[index].Point;
                double dx = existing.X - point.X;
                double dy = existing.Y - point.Y;
                if (Math.Sqrt(dx * dx + dy * dy) <= tolerance)
                {
                    return index;
                }
            }

            int newIndex = nodes.Count;
            nodes.Add(new FireMainGraphNode { Index = newIndex, Point = point });
            return newIndex;
        }

        private static List<List<int>> BuildFireMainNodeComponents(List<FireMainGraphNode> nodes)
        {
            var components = new List<List<int>>();
            var visited = new HashSet<int>();
            foreach (FireMainGraphNode node in nodes)
            {
                if (visited.Contains(node.Index))
                {
                    continue;
                }

                var component = new List<int>();
                var queue = new Queue<int>();
                queue.Enqueue(node.Index);
                visited.Add(node.Index);
                while (queue.Count > 0)
                {
                    int current = queue.Dequeue();
                    component.Add(current);
                    foreach (FireMainGraphEdge edge in nodes[current].Edges)
                    {
                        int next = edge.A == current ? edge.B : edge.A;
                        if (!visited.Contains(next))
                        {
                            visited.Add(next);
                            queue.Enqueue(next);
                        }
                    }
                }
                components.Add(component);
            }
            return components;
        }

        private static List<FireMainGraphEdge> FindLongestFireMainPath(List<FireMainGraphNode> nodes, List<int> component)
        {
            double bestDistance = -1;
            var bestPath = new List<FireMainGraphEdge>();
            var componentSet = new HashSet<int>(component);
            foreach (int start in component)
            {
                FireMainPathState[] states = new FireMainPathState[nodes.Count];
                for (int index = 0; index < nodes.Count; index++)
                {
                    states[index] = new FireMainPathState
                    {
                        Distance = double.MaxValue,
                        PreviousNode = -1,
                        PreviousEdge = null,
                        Visited = false
                    };
                }
                states[start].Distance = 0;

                while (true)
                {
                    int current = -1;
                    double currentDistance = double.MaxValue;
                    foreach (int nodeIndex in component)
                    {
                        if (!states[nodeIndex].Visited && states[nodeIndex].Distance < currentDistance)
                        {
                            current = nodeIndex;
                            currentDistance = states[nodeIndex].Distance;
                        }
                    }
                    if (current < 0)
                    {
                        break;
                    }

                    states[current].Visited = true;
                    foreach (FireMainGraphEdge edge in nodes[current].Edges)
                    {
                        int next = edge.A == current ? edge.B : edge.A;
                        if (!componentSet.Contains(next))
                        {
                            continue;
                        }

                        double nextDistance = states[current].Distance + edge.Length;
                        if (nextDistance < states[next].Distance)
                        {
                            states[next].Distance = nextDistance;
                            states[next].PreviousNode = current;
                            states[next].PreviousEdge = edge;
                        }
                    }
                }

                foreach (int target in component)
                {
                    if (states[target].Distance <= bestDistance || states[target].Distance == double.MaxValue)
                    {
                        continue;
                    }

                    bestDistance = states[target].Distance;
                    bestPath = ReconstructFireMainPath(states, start, target);
                }
            }
            return bestPath;
        }

        private static List<FireMainGraphEdge> ReconstructFireMainPath(FireMainPathState[] states, int start, int target)
        {
            var path = new List<FireMainGraphEdge>();
            int current = target;
            while (current != start && current >= 0)
            {
                FireMainPathState state = states[current];
                if (state.PreviousEdge == null)
                {
                    break;
                }
                path.Add(state.PreviousEdge);
                current = state.PreviousNode;
            }
            return path;
        }

        private static FireBranchItem BuildFireBranchItem(FamilyInstance sprinkler, XYZ point, List<FireMainPipeData> mains)
        {
            FireMainPipeData bestMain = null;
            FireMainPipeData secondMain = null;
            double bestDistance = double.MaxValue;
            double secondDistance = double.MaxValue;
            double bestParameter = 0;
            double bestBranchParameter = 0;
            int bestSideSign = 1;
            XYZ bestBranchDirection = XYZ.BasisY;

            foreach (FireMainPipeData main in mains)
            {
                double rawParameter = DotXY(point - main.Start, main.Direction);
                double projectionTolerance = UnitUtils.ConvertToInternalUnits(30, UnitTypeId.Centimeters);
                if (rawParameter < -projectionTolerance || rawParameter > main.Length + projectionTolerance)
                {
                    continue;
                }
                double parameter = Math.Max(0, Math.Min(main.Length, rawParameter));
                XYZ projected = main.Start + main.Direction * parameter;
                double signedBranch = DotXY(point - projected, main.BaseBranchDirection);
                double distance = Math.Abs(signedBranch);
                if (distance < bestDistance)
                {
                    secondMain = bestMain;
                    secondDistance = bestDistance;
                    bestMain = main;
                    bestDistance = distance;
                    bestParameter = parameter;
                    bestBranchParameter = distance;
                    bestSideSign = signedBranch < 0 ? -1 : 1;
                    bestBranchDirection = signedBranch < 0
                        ? main.BaseBranchDirection.Negate()
                        : main.BaseBranchDirection;
                }
                else if (distance < secondDistance)
                {
                    secondMain = main;
                    secondDistance = distance;
                }
            }

            if (bestMain == null)
            {
                throw new InvalidOperationException("撒水頭 " + sprinkler.Id.Value + " 無法投影到選取主管管段上，請選擇實際穿過支管交接位置的主管段。");
            }
            double ambiguityTolerance = UnitUtils.ConvertToInternalUnits(30, UnitTypeId.Centimeters);
            if (secondMain != null && secondMain.PipeId != bestMain.PipeId && secondDistance - bestDistance < ambiguityTolerance)
            {
                throw new InvalidOperationException("撒水頭 " + sprinkler.Id.Value + " 距離兩段主管太接近，請分段建立或縮小主管候選。");
            }

            return new FireBranchItem
            {
                Sprinkler = sprinkler,
                Point = point,
                MainPipe = bestMain.Pipe,
                MainPipeId = bestMain.PipeId,
                MainStart = bestMain.Start,
                MainDirection = bestMain.Direction,
                BranchDirection = bestBranchDirection,
                MainZ = bestMain.Z,
                MainParameter = bestParameter,
                BranchParameter = bestBranchParameter,
                SideSign = bestSideSign
            };
        }

        private static List<FireBranchItem> BuildFireBranchItems(
            List<FamilyInstance> sprinklers,
            List<XYZ> sprinklerPoints,
            List<FireMainPipeData> mainPipes,
            List<object> skipped)
        {
            var result = new List<FireBranchItem>();
            for (int index = 0; index < sprinklers.Count; index++)
            {
                FamilyInstance sprinkler = sprinklers[index];
                try
                {
                    result.Add(BuildFireBranchItem(sprinkler, sprinklerPoints[index], mainPipes));
                }
                catch (Exception ex)
                {
                    skipped.Add(new
                    {
                        sprinkler_id = sprinkler.Id.Value,
                        reason = ex.Message
                    });
                }
            }
            return result.OrderBy(item => item.MainParameter).ToList();
        }

        private static List<List<FireBranchItem>> BuildFireBranchRows(List<FireBranchItem> sprinklerData, double rowTolerance)
        {
            var rows = new List<List<FireBranchItem>>();
            foreach (var sideGroup in sprinklerData
                .GroupBy(item => item.MainPipeId.ToString() + ":" + item.SideSign.ToString())
                .OrderBy(group => group.Min(item => item.MainParameter)))
            {
                foreach (FireBranchItem item in sideGroup.OrderBy(item => item.MainParameter))
                {
                    if (rows.Count == 0
                        || rows.Last()[0].MainPipeId != item.MainPipeId
                        || rows.Last()[0].SideSign != item.SideSign
                        || Math.Abs(item.MainParameter - rows.Last().Average(row => row.MainParameter)) > rowTolerance)
                    {
                        rows.Add(new List<FireBranchItem>());
                    }
                    rows.Last().Add(item);
                }
            }
            return rows;
        }

        private static List<FireBranchJunctionPlan> BuildFireBranchJunctionPlans(
            List<List<FireBranchItem>> rows,
            double junctionTolerance,
            double branchZ)
        {
            var plans = new List<FireBranchJunctionPlan>();
            foreach (var pipeRows in rows
                .GroupBy(row => row[0].MainPipeId)
                .OrderBy(group => group.Key))
            {
                var pipePlans = new List<FireBranchJunctionPlan>();
                foreach (List<FireBranchItem> row in pipeRows.OrderBy(item => item.Average(value => value.MainParameter)))
                {
                    double rowMain = row.Average(item => item.MainParameter);
                    FireBranchJunctionPlan plan = pipePlans.LastOrDefault();
                    if (plan == null || Math.Abs(rowMain - plan.MainParameter) > junctionTolerance)
                    {
                        plan = new FireBranchJunctionPlan
                        {
                            MainPipeId = row[0].MainPipeId,
                            MainParameter = rowMain
                        };
                        pipePlans.Add(plan);
                    }
                    plan.Rows.Add(row);
                    plan.MainParameter = plan.Rows.Average(item => item.Average(value => value.MainParameter));
                }

                foreach (FireBranchJunctionPlan plan in pipePlans)
                {
                    bool offsetElevation = Math.Abs(plan.Rows[0][0].MainZ - branchZ) > 0.01;
                    int[] sides = plan.Rows.Select(row => row[0].SideSign).Distinct().OrderBy(value => value).ToArray();
                    bool hasOppositeSides = plan.Rows.Count == 2
                        && sides.Length == 2
                        && sides[0] == -1
                        && sides[1] == 1;
                    if (hasOppositeSides)
                    {
                        plan.Topology = offsetElevation
                            ? FireBranchJunctionTopology.OppositeSidesOffsetElevation
                            : FireBranchJunctionTopology.OppositeSidesSameElevation;
                    }
                    else if (plan.Rows.Count == 1)
                    {
                        plan.Topology = offsetElevation
                            ? FireBranchJunctionTopology.SingleSideOffsetElevation
                            : FireBranchJunctionTopology.SingleSideSameElevation;
                    }
                    else
                    {
                        plan.Topology = FireBranchJunctionTopology.Complex;
                    }
                    plans.Add(plan);
                }
            }
            return plans;
        }

        private static double GetPipeDiameterFeet(Pipe pipe)
        {
            Parameter diameter = pipe != null ? pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM) : null;
            return diameter != null && diameter.HasValue ? diameter.AsDouble() : 0;
        }

        private static bool IsScFireBranchPipe(Pipe pipe)
        {
            Parameter comments = pipe != null ? pipe.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS) : null;
            string value = comments != null && comments.HasValue ? comments.AsString() ?? "" : "";
            return value.StartsWith(ScFireBranchCommentPrefix, StringComparison.Ordinal);
        }

        private static void TrySetScFireBranchMetadata(Pipe pipe, string kind, string batchId)
        {
            try
            {
                Parameter comments = pipe != null ? pipe.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS) : null;
                if (comments != null && !comments.IsReadOnly)
                {
                    comments.Set(ScFireBranchCommentPrefix + kind + ":" + batchId);
                }
            }
            catch
            {
            }
        }

        private static bool TryChangeConnectorSystemType(Connector connector, ElementId systemTypeId)
        {
            try
            {
                if (connector == null || systemTypeId == null || systemTypeId == ElementId.InvalidElementId)
                {
                    return false;
                }

                MEPSystem system = connector.MEPSystem;
                if (system == null)
                {
                    return false;
                }

                ElementId currentTypeId = system.GetTypeId();
                if (currentTypeId != null && currentTypeId.Value == systemTypeId.Value)
                {
                    return true;
                }

                if (!system.CanHaveTypeAssigned() || !system.IsValidType(systemTypeId))
                {
                    return false;
                }

                system.ChangeTypeId(systemTypeId);
                ElementId updatedTypeId = system.GetTypeId();
                return updatedTypeId != null && updatedTypeId.Value == systemTypeId.Value;
            }
            catch
            {
                return false;
            }
        }

        private static Pipe CreateFireDropForSystem(
            Document doc,
            ElementId systemTypeId,
            ElementId pipeTypeId,
            ElementId levelId,
            Connector startConnector,
            XYZ end,
            double diameterFeet)
        {
            if (startConnector == null || startConnector.Origin.DistanceTo(end) < 0.01)
            {
                SetFireBranchConnectionDiagnostic("CreateFireDropForSystem | sprinkler connector or drop geometry is invalid");
                return null;
            }

            try
            {
                Pipe pipe = CreateFirePipe(doc, systemTypeId, pipeTypeId, levelId, startConnector.Origin, end, diameterFeet);
                if (pipe == null)
                {
                    SetFireBranchConnectionDiagnostic("CreateFireDropForSystem | explicit-system pipe creation returned null");
                    return null;
                }

                Connector pipeConnector = FindConnectorNear(pipe, startConnector.Origin);
                if (pipeConnector == null)
                {
                    SetFireBranchConnectionDiagnostic("CreateFireDropForSystem | pipe connector is missing at sprinkler point");
                    return null;
                }
                if (!pipeConnector.IsConnectedTo(startConnector))
                {
                    pipeConnector.ConnectTo(startConnector);
                }
                doc.Regenerate();
                if (!pipeConnector.IsConnectedTo(startConnector))
                {
                    SetFireBranchConnectionDiagnostic("CreateFireDropForSystem | sprinkler connection did not persist");
                    return null;
                }

                MEPSystem system = pipe.MEPSystem;
                if (system == null || system.GetTypeId().Value != systemTypeId.Value)
                {
                    SetFireBranchConnectionDiagnostic("CreateFireDropForSystem | explicit system type did not persist after sprinkler connection");
                    return null;
                }
                return pipe;
            }
            catch (Exception ex)
            {
                SetFireBranchConnectionDiagnostic("CreateFireDropForSystem", ex);
                return null;
            }
        }

        private static void ValidateFireBranchPlan(
            List<List<FireBranchItem>> rows,
            out int rowCount,
            out int estimatedPipeCount,
            out double maxBranchLengthMeters)
        {
            int sprinklerCount = rows.Sum(row => row.Count);
            rowCount = rows.Count;
            maxBranchLengthMeters = sprinklerCount > 0
                ? rows.SelectMany(row => row).Max(item => item.BranchParameter) * 0.3048
                : 0;
            estimatedPipeCount = sprinklerCount + rowCount * 2;
            if (estimatedPipeCount > 220)
            {
                throw new InvalidOperationException(
                    "這次選取預估會建立約 " + estimatedPipeCount
                    + " 支管段，風險過高。請縮小框選範圍，分區或分主管建立，先用預覽確認路徑後再建立。");
            }
            if (maxBranchLengthMeters > 25)
            {
                throw new InvalidOperationException(
                    "最長支管距離主管約 " + maxBranchLengthMeters.ToString("0.0")
                    + " m，可能選到不屬於這支主管的撒水頭。請縮小框選範圍或改選正確主管。");
            }
        }

        private static double ResolveFireBranchPreviewDisplayZ(
            Document doc,
            View view,
            double modelZ)
        {
            ViewPlan viewPlan = view as ViewPlan;
            if (viewPlan == null)
            {
                return modelZ;
            }
            try
            {
                PlanViewRange viewRange = viewPlan.GetViewRange();
                ElementId cutLevelId = viewRange.GetLevelId(PlanViewPlane.CutPlane);
                Level cutLevel = doc.GetElement(cutLevelId) as Level;
                if (cutLevel != null)
                {
                    return cutLevel.Elevation + viewRange.GetOffset(PlanViewPlane.CutPlane);
                }
            }
            catch
            {
            }
            return viewPlan.GenLevel != null ? viewPlan.GenLevel.Elevation : modelZ;
        }

        private static List<DrainagePreviewSegment> BuildFireBranchPreviewSegments(
            List<List<FireBranchItem>> rows,
            double displayZ,
            double extension)
        {
            var segments = new List<DrainagePreviewSegment>();
            double markerSize = UnitUtils.ConvertToInternalUnits(30, UnitTypeId.Centimeters);
            foreach (List<FireBranchItem> row in rows)
            {
                double rowMain = row.Average(item => item.MainParameter);
                double rowMin = 0 - extension;
                double rowMax = row.Max(item => item.BranchParameter) + extension;
                XYZ mainStart = row[0].MainStart;
                XYZ mainDirection = row[0].MainDirection;
                XYZ branchDirection = row[0].BranchDirection;
                XYZ branchStart = new XYZ(
                    mainStart.X + mainDirection.X * rowMain + branchDirection.X * rowMin,
                    mainStart.Y + mainDirection.Y * rowMain + branchDirection.Y * rowMin,
                    displayZ);
                XYZ branchEnd = new XYZ(
                    mainStart.X + mainDirection.X * rowMain + branchDirection.X * rowMax,
                    mainStart.Y + mainDirection.Y * rowMain + branchDirection.Y * rowMax,
                    displayZ);
                segments.Add(new DrainagePreviewSegment
                {
                    Start = branchStart,
                    End = branchEnd,
                    Kind = "fire_branch_preview"
                });
                foreach (FireBranchItem item in row)
                {
                    XYZ center = new XYZ(
                        mainStart.X + mainDirection.X * rowMain + branchDirection.X * item.BranchParameter,
                        mainStart.Y + mainDirection.Y * rowMain + branchDirection.Y * item.BranchParameter,
                        displayZ);
                    segments.Add(new DrainagePreviewSegment
                    {
                        Start = center + new XYZ(-markerSize, 0, 0),
                        End = center + new XYZ(markerSize, 0, 0),
                        Kind = "fire_branch_preview"
                    });
                    segments.Add(new DrainagePreviewSegment
                    {
                        Start = center + new XYZ(0, -markerSize, 0),
                        End = center + new XYZ(0, markerSize, 0),
                        Kind = "fire_branch_preview"
                    });
                }
            }
            return segments;
        }

        private static bool TryHandleFireBranchAction(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            if (!FireBranchActions.Contains(action))
            {
                return false;
            }

            HandleFireBranchAction(uiApp, payload, action, responseFile, serializer);
            return true;
        }

        private static void HandleFireBranchAction(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            if (action == "list_fire_branch_context")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                var pipeTypes = new List<object>();
                                foreach (PipeType pipeType in new FilteredElementCollector(doc)
                                    .OfClass(typeof(PipeType))
                                    .Cast<PipeType>()
                                    .OrderBy(item => item.Name))
                                {
                                    pipeTypes.Add(new
                                    {
                                        element_id = pipeType.Id.Value,
                                        name = pipeType.Name
                                    });
                                }

                                var systemTypes = new List<object>();
                                foreach (PipingSystemType systemType in new FilteredElementCollector(doc)
                                    .OfClass(typeof(PipingSystemType))
                                    .Cast<PipingSystemType>()
                                    .OrderBy(item => item.Name))
                                {
                                    systemTypes.Add(new
                                    {
                                        element_id = systemType.Id.Value,
                                        name = systemType.Name
                                    });
                                }

                                var levels = new List<object>();
                                foreach (Level level in new FilteredElementCollector(doc)
                                    .OfClass(typeof(Level))
                                    .Cast<Level>()
                                    .OrderBy(item => item.Elevation))
                                {
                                    levels.Add(new
                                    {
                                        element_id = level.Id.Value,
                                        name = level.Name,
                                        elevation = level.Elevation
                                    });
                                }

                                var usedDiameters = GetAvailablePipeDiameters(doc);

                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        pipe_types = pipeTypes,
                                        system_types = systemTypes,
                                        levels = levels,
                                        used_diameters = usedDiameters
                                    })
                                );
                                return;
                            }

            if (action == "read_fire_branch_selection")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                var selectedIds = uiApp.ActiveUIDocument.Selection.GetElementIds();
                                var selectedPipes = selectedIds
                                    .Select(id => doc.GetElement(id))
                                    .OfType<Pipe>()
                                    .ToList();
                                var selectedSprinklers = selectedIds
                                    .Select(id => doc.GetElement(id))
                                    .OfType<FamilyInstance>()
                                    .Where(instance => IsSprinkler(instance))
                                    .ToList();

                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        pipes = selectedPipes.Select(pipe => SerializePipeInfo(doc, pipe)).ToList(),
                                        sprinklers = selectedSprinklers.Select(instance => SerializeSprinklerInfo(instance)).ToList()
                                    })
                                );
                                return;
                            }

            if (action == "create_fire_branch_preview")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                long selectedLevelId = ReadLong(payload, "level_id", 0);
                                double branchOffsetCm = ReadDouble(payload, "branch_offset_cm", 0);
                                string heightReference = payload.ContainsKey("height_reference") && payload["height_reference"] != null
                                    ? payload["height_reference"].ToString()
                                    : "管中心";
                                ArrayList sprinklerIdsRaw = payload.ContainsKey("sprinkler_ids")
                                    ? payload["sprinkler_ids"] as ArrayList
                                    : null;

                                int mainCandidateCount = 0;
                                int excludedMainCount = 0;
                                List<FireMainPipeData> mainPipes = ReadFireMainPipes(doc, payload, out mainCandidateCount, out excludedMainCount);
                                if (mainPipes.Count == 0)
                                {
                                    throw new InvalidOperationException("找不到可用主管，請至少選取一段主管。");
                                }
                                if (sprinklerIdsRaw == null || sprinklerIdsRaw.Count == 0)
                                {
                                    throw new InvalidOperationException("尚未選擇撒水頭");
                                }
                                var sprinklers = new List<FamilyInstance>();
                                foreach (object idValue in sprinklerIdsRaw)
                                {
                                    FamilyInstance instance = doc.GetElement(new ElementId(Convert.ToInt64(idValue))) as FamilyInstance;
                                    if (IsSprinkler(instance))
                                    {
                                        sprinklers.Add(instance);
                                    }
                                }
                                if (sprinklers.Count == 0)
                                {
                                    throw new InvalidOperationException("沒有可用的撒水頭資料");
                                }

                                ElementId levelId = selectedLevelId > 0 ? new ElementId(selectedLevelId) : GetPipeLevelId(doc, mainPipes[0].Pipe);
                                Level branchLevel = doc.GetElement(levelId) as Level;
                                double previewDiameterFeet = UnitUtils.ConvertToInternalUnits(25, UnitTypeId.Millimeters);
                                double branchZ = ResolvePipeCenterZ(branchLevel, mainPipes[0].Z, branchOffsetCm, previewDiameterFeet, heightReference);
                                List<XYZ> sprinklerPoints = sprinklers.Select(item => GetFamilyConnectionPoint(item)).ToList();
                                double rowTolerance = UnitUtils.ConvertToInternalUnits(10, UnitTypeId.Centimeters);
                                double extension = 0;
                                var skipped = new List<object>();
                                List<FireBranchItem> sprinklerData = BuildFireBranchItems(sprinklers, sprinklerPoints, mainPipes, skipped);
                                if (sprinklerData.Count == 0)
                                {
                                    throw new InvalidOperationException("選取撒水頭都無法投影到主管，請改選主管或縮小撒水頭範圍。");
                                }
                                var rows = BuildFireBranchRows(sprinklerData, rowTolerance);
                                int plannedRowCount = 0;
                                int estimatedPipeCount = 0;
                                double maxBranchLengthMeters = 0;
                                ValidateFireBranchPlan(
                                    rows,
                                    out plannedRowCount,
                                    out estimatedPipeCount,
                                    out maxBranchLengthMeters);
                                object cadPathCheck = BuildFireBranchCadPathShadowReport(
                                    doc,
                                    rows,
                                    branchZ,
                                    extension);

                                string batchId = DateTime.Now.ToString("yyyyMMdd-HHmmss");
                                long previewGroupId = 0;
                                string previewGroupName = "";
                                TryDeletePreviewGroupsByPrefix(doc, "SC_fire_branch_preview_");
                                double previewDisplayZ = ResolveFireBranchPreviewDisplayZ(
                                    doc,
                                    doc.ActiveView,
                                    branchZ);
                                List<DrainagePreviewSegment> directPreviewSegments =
                                    BuildFireBranchPreviewSegments(rows, previewDisplayZ, extension);
                                DrainagePreviewServer.SetSegments(
                                    doc,
                                    batchId,
                                    directPreviewSegments);
                                uiApp.ActiveUIDocument.RefreshActiveView();

                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        batch_id = batchId,
                                        segment_count = directPreviewSegments.Count,
                                        sprinkler_count = sprinklers.Count,
                                        main_candidate_count = mainCandidateCount,
                                        valid_main_count = mainPipes.Count,
                                        excluded_main_count = excludedMainCount,
                                        row_count = plannedRowCount,
                                        estimated_pipe_count = estimatedPipeCount,
                                        max_branch_length_m = maxBranchLengthMeters,
                                        cad_path_check = cadPathCheck,
                                        skipped = skipped,
                                        group_id = previewGroupId,
                                        group_name = previewGroupName,
                                        preview_snapshot_id = batchId,
                                        preview_rendering = "direct_context_3d",
                                        preview_server_active = DrainagePreviewServer.IsRegisteredAndActive(),
                                        direct_preview_segment_count = directPreviewSegments.Count,
                                        preview_display_z = previewDisplayZ
                                    })
                                );
                                return;
                            }

            if (action == "create_fire_branch_pipes")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                long pipeTypeId = ReadLong(payload, "pipe_type_id");
                                long systemTypeId = ReadLong(payload, "system_type_id");
                                long selectedLevelId = ReadLong(payload, "level_id", 0);
                                double diameterMm = ReadDouble(payload, "diameter_mm", 25);
                                double branchOffsetCm = ReadDouble(payload, "branch_offset_cm", 0);
                                long previewGroupId = ReadLong(payload, "preview_group_id", 0);
                                bool deletePreviewAfterCreate = true;
                                if (payload.ContainsKey("delete_preview_after_create") && payload["delete_preview_after_create"] != null)
                                {
                                    try
                                    {
                                        deletePreviewAfterCreate = Convert.ToBoolean(payload["delete_preview_after_create"]);
                                    }
                                    catch
                                    {
                                        deletePreviewAfterCreate = true;
                                    }
                                }
                                string heightReference = payload.ContainsKey("height_reference") && payload["height_reference"] != null
                                    ? payload["height_reference"].ToString()
                                    : "管中心";
                                ArrayList sprinklerIdsRaw = payload.ContainsKey("sprinkler_ids")
                                    ? payload["sprinkler_ids"] as ArrayList
                                    : null;

                                int mainCandidateCount = 0;
                                int excludedMainCount = 0;
                                List<FireMainPipeData> mainPipes = ReadFireMainPipes(doc, payload, out mainCandidateCount, out excludedMainCount);
                                PipeType pipeType = doc.GetElement(new ElementId(pipeTypeId)) as PipeType;
                                PipingSystemType systemType = doc.GetElement(new ElementId(systemTypeId)) as PipingSystemType;
                                if (mainPipes.Count == 0)
                                {
                                    throw new InvalidOperationException("找不到可用主管，請至少選取一段主管。");
                                }
                                if (pipeType == null)
                                {
                                    throw new InvalidOperationException("找不到指定管類型");
                                }
                                if (systemType == null)
                                {
                                    throw new InvalidOperationException("找不到指定系統類型");
                                }
                                if (sprinklerIdsRaw == null || sprinklerIdsRaw.Count == 0)
                                {
                                    throw new InvalidOperationException("尚未選擇撒水頭");
                                }

                                var sprinklers = new List<FamilyInstance>();
                                foreach (object idValue in sprinklerIdsRaw)
                                {
                                    FamilyInstance instance = doc.GetElement(new ElementId(Convert.ToInt64(idValue))) as FamilyInstance;
                                    if (IsSprinkler(instance))
                                    {
                                        sprinklers.Add(instance);
                                    }
                                }
                                if (sprinklers.Count == 0)
                                {
                                    throw new InvalidOperationException("沒有可用的撒水頭資料");
                                }

                                double diameterFeet = UnitUtils.ConvertToInternalUnits(diameterMm, UnitTypeId.Millimeters);
                                ElementId levelId = selectedLevelId > 0 ? new ElementId(selectedLevelId) : GetPipeLevelId(doc, mainPipes[0].Pipe);
                                if (levelId == ElementId.InvalidElementId)
                                {
                                    throw new InvalidOperationException("無法建立支管幾何方向");
                                }
                                Level branchLevel = doc.GetElement(levelId) as Level;
                                double branchZ = ResolvePipeCenterZ(branchLevel, mainPipes[0].Z, branchOffsetCm, diameterFeet, heightReference);

                                List<XYZ> sprinklerPoints = sprinklers.Select(item => GetFamilyConnectionPoint(item)).ToList();
                                double extension = 0;
                                double rowTolerance = UnitUtils.ConvertToInternalUnits(10, UnitTypeId.Centimeters);
                                double junctionTolerance = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Millimeters);
                                var skipped = new List<object>();
                                List<FireBranchItem> sprinklerData = BuildFireBranchItems(sprinklers, sprinklerPoints, mainPipes, skipped);
                                if (sprinklerData.Count == 0)
                                {
                                    throw new InvalidOperationException("選取撒水頭都無法投影到主管，請改選主管或縮小撒水頭範圍。");
                                }
                                List<FamilyInstance> plannedSprinklers = sprinklerData
                                    .Select(item => item.Sprinkler)
                                    .Where(instance => instance != null)
                                    .GroupBy(instance => instance.Id.Value)
                                    .Select(group => group.First())
                                    .ToList();
                                var rows = BuildFireBranchRows(sprinklerData, rowTolerance);
                                var junctionPlans = BuildFireBranchJunctionPlans(rows, junctionTolerance, branchZ);
                                int plannedRowCount = 0;
                                int estimatedPipeCount = 0;
                                double maxBranchLengthMeters = 0;
                                ValidateFireBranchPlan(
                                    rows,
                                    out plannedRowCount,
                                    out estimatedPipeCount,
                                    out maxBranchLengthMeters);

                                var createdIds = new List<ElementId>();
                                var additionalCreatedIds = new List<ElementId>();
                                var createdPipeRoles = new Dictionary<long, string>();
                                var created = new List<object>();
                                var failed = new List<object>();
                                var junctions = junctionPlans.Select(plan => new
                                {
                                    main_pipe_id = plan.MainPipeId,
                                    main_parameter = plan.MainParameter,
                                    topology = plan.Topology.ToString(),
                                    row_count = plan.Rows.Count
                                }).ToList();
                                string batchId = DateTime.Now.ToString("yyyyMMdd-HHmmss");
                                long deletedPreviewGroupId = 0;

                                // Revit 2024 transactions become model state only after Commit; a TransactionGroup
                                // can still roll back committed inner transactions or assimilate them into one Undo item.
                                // Source: https://help.autodesk.com/cloudhelp/2024/ENU/Revit-API/files/Revit_API_Developers_Guide/Basic_Interaction_with_Revit_Elements/Revit_API_Revit_API_Developers_Guide_Basic_Interaction_with_Revit_Elements_Transactions_html.html
                                using (TransactionGroup transactionGroup = new TransactionGroup(doc, "SC \u6d88\u9632\u652f\u7ba1\u5efa\u7acb"))
                                {
                                    TransactionStatus groupStartStatus = transactionGroup.Start();
                                    if (groupStartStatus != TransactionStatus.Started)
                                    {
                                        throw new InvalidOperationException("Fire branch transaction group did not start: " + groupStartStatus);
                                    }
                                    try
                                    {
                                    using (Transaction creationTransaction = new Transaction(doc, "SC \u5efa\u7acb\u6d88\u9632\u652f\u7ba1\u5e7e\u4f55"))
                                    {
                                    TransactionStatus creationStartStatus = creationTransaction.Start();
                                    if (creationStartStatus != TransactionStatus.Started)
                                    {
                                        throw new InvalidOperationException("Fire branch geometry transaction did not start: " + creationStartStatus);
                                    }
                                    var mainSegmentsByPipeId = mainPipes.ToDictionary(item => item.PipeId, item => new List<Pipe> { item.Pipe });
                                    var junctionPlanByRow = junctionPlans
                                        .SelectMany(plan => plan.Rows.Select(row => new { row, plan }))
                                        .ToDictionary(item => item.row, item => item.plan);
                                    var crossBranchesByPlan = new Dictionary<FireBranchJunctionPlan, List<Pipe>>();
                                    var attemptedCrossPlans = new HashSet<FireBranchJunctionPlan>();
                                    var offsetFeedersByPlan = new Dictionary<FireBranchJunctionPlan, Pipe>();
                                    var offsetBranchesByPlan = new Dictionary<FireBranchJunctionPlan, List<Pipe>>();
                                    var attemptedOffsetPlans = new HashSet<FireBranchJunctionPlan>();
                                    foreach (var row in rows)
                                    {
                                        FireBranchJunctionPlan junctionPlan = junctionPlanByRow[row];
                                        bool isOppositeSideCross = junctionPlan.Topology == FireBranchJunctionTopology.OppositeSidesSameElevation;
                                        bool isOppositeSideOffset = junctionPlan.Topology == FireBranchJunctionTopology.OppositeSidesOffsetElevation;
                                        double rowMain = isOppositeSideCross || isOppositeSideOffset
                                            ? junctionPlan.MainParameter
                                            : row.Average(item => item.MainParameter);
                                        double rowMin = isOppositeSideCross || isOppositeSideOffset
                                            ? 0
                                            : 0 - extension;
                                        double rowMax = row.Max(item => item.BranchParameter) + extension;
                                        XYZ mainStart = row[0].MainStart;
                                        XYZ mainDirection = row[0].MainDirection;
                                        XYZ branchDirection = row[0].BranchDirection;
                                        double mainZ = row[0].MainZ;
                                        List<Pipe> mainSegments = mainSegmentsByPipeId[row[0].MainPipeId];
                                        XYZ mainTie = new XYZ(
                                            mainStart.X + mainDirection.X * rowMain,
                                            mainStart.Y + mainDirection.Y * rowMain,
                                            mainZ
                                        );
                                        XYZ branchTie = new XYZ(mainTie.X, mainTie.Y, branchZ);
                                        XYZ branchStart = new XYZ(
                                            mainStart.X + mainDirection.X * rowMain + branchDirection.X * rowMin,
                                            mainStart.Y + mainDirection.Y * rowMain + branchDirection.Y * rowMin,
                                            branchZ
                                        );
                                        XYZ branchEnd = new XYZ(
                                            mainStart.X + mainDirection.X * rowMain + branchDirection.X * rowMax,
                                            mainStart.Y + mainDirection.Y * rowMain + branchDirection.Y * rowMax,
                                            branchZ
                                        );

                                        Pipe feeder = null;
                                        if (mainTie.DistanceTo(branchTie) > 0.01)
                                        {
                                            if (isOppositeSideOffset)
                                            {
                                                if (!offsetFeedersByPlan.TryGetValue(junctionPlan, out feeder))
                                                {
                                                    feeder = CreateFirePipe(doc, systemType.Id, pipeType.Id, levelId, mainTie, branchTie, diameterFeet);
                                                    if (feeder != null)
                                                    {
                                                        offsetFeedersByPlan[junctionPlan] = feeder;
                                                        TrySetScFireBranchMetadata(feeder, "feeder", batchId);
                                                        createdIds.Add(feeder.Id);
                                                        createdPipeRoles[feeder.Id.Value] = "feeder";
                                                        created.Add(new { element_id = feeder.Id.Value, kind = "feeder" });
                                                        ResetFireBranchConnectionDiagnostic();
                                                        if (!TryCreateTeeAtPoint(doc, mainSegments, feeder, mainTie))
                                                        {
                                                            failed.Add(new
                                                            {
                                                                row = rowMain,
                                                                topology = junctionPlan.Topology.ToString(),
                                                                reason = "main_to_shared_feeder_connection_failed",
                                                                detail = ReadFireBranchConnectionDiagnostic()
                                                            });
                                                        }
                                                    }
                                                }
                                            }
                                            else
                                            {
                                                feeder = CreateFirePipe(doc, systemType.Id, pipeType.Id, levelId, mainTie, branchTie, diameterFeet);
                                                if (feeder != null)
                                                {
                                                    TrySetScFireBranchMetadata(feeder, "feeder", batchId);
                                                    createdIds.Add(feeder.Id);
                                                    createdPipeRoles[feeder.Id.Value] = "feeder";
                                                    created.Add(new { element_id = feeder.Id.Value, kind = "feeder" });
                                                    ResetFireBranchConnectionDiagnostic();
                                                    if (!TryCreateTeeAtPoint(doc, mainSegments, feeder, mainTie))
                                                    {
                                                        failed.Add(new
                                                        {
                                                            row = rowMain,
                                                            topology = junctionPlan.Topology.ToString(),
                                                            reason = "main_to_feeder_connection_failed",
                                                            detail = ReadFireBranchConnectionDiagnostic()
                                                        });
                                                    }
                                                }
                                            }
                                        }

                                        Pipe branch = CreateFirePipe(doc, systemType.Id, pipeType.Id, levelId, branchStart, branchEnd, diameterFeet);
                                        var branchSegments = new List<Pipe>();
                                        if (branch != null)
                                        {
                                            TrySetScFireBranchMetadata(branch, "branch", batchId);
                                            createdIds.Add(branch.Id);
                                            createdPipeRoles[branch.Id.Value] = "branch";
                                            created.Add(new { element_id = branch.Id.Value, kind = "branch" });
                                            branchSegments.Add(branch);
                                            if (feeder != null && isOppositeSideOffset)
                                            {
                                                List<Pipe> offsetBranches;
                                                if (!offsetBranchesByPlan.TryGetValue(junctionPlan, out offsetBranches))
                                                {
                                                    offsetBranches = new List<Pipe>();
                                                    offsetBranchesByPlan[junctionPlan] = offsetBranches;
                                                }
                                                offsetBranches.Add(branch);
                                                if (offsetBranches.Count == 2)
                                                {
                                                    attemptedOffsetPlans.Add(junctionPlan);
                                                    ResetFireBranchConnectionDiagnostic();
                                                    if (!TryCreateTeeAtPipeEnds(
                                                        doc,
                                                        offsetBranches[0],
                                                        offsetBranches[1],
                                                        feeder,
                                                        branchTie))
                                                    {
                                                        failed.Add(new
                                                        {
                                                            row = rowMain,
                                                            topology = junctionPlan.Topology.ToString(),
                                                            reason = "shared_feeder_to_opposite_branches_connection_failed",
                                                            detail = ReadFireBranchConnectionDiagnostic()
                                                        });
                                                    }
                                                }
                                            }
                                            if (feeder != null && !isOppositeSideOffset)
                                            {
                                                ResetFireBranchConnectionDiagnostic();
                                                bool feederConnectedToBranch = TryConnectPipeToRun(doc, branchSegments, feeder, branchTie);
                                                if (!feederConnectedToBranch)
                                                {
                                                    failed.Add(new
                                                    {
                                                        row = rowMain,
                                                        topology = junctionPlan.Topology.ToString(),
                                                        reason = "支管與主管垂直連接管未能建立有效配件連接",
                                                        detail = ReadFireBranchConnectionDiagnostic()
                                                    });
                                                }
                                            }
                                            if (feeder == null)
                                            {
                                                if (isOppositeSideCross)
                                                {
                                                    List<Pipe> crossBranches;
                                                    if (!crossBranchesByPlan.TryGetValue(junctionPlan, out crossBranches))
                                                    {
                                                        crossBranches = new List<Pipe>();
                                                        crossBranchesByPlan[junctionPlan] = crossBranches;
                                                    }
                                                    crossBranches.Add(branch);
                                                    if (crossBranches.Count == 2)
                                                    {
                                                        attemptedCrossPlans.Add(junctionPlan);
                                                    ResetFireBranchConnectionDiagnostic();
                                                    bool crossCreated = TryCreateCrossAtPipeEnds(
                                                        doc,
                                                        mainSegments,
                                                            crossBranches[0],
                                                            crossBranches[1],
                                                            mainTie);
                                                        if (!crossCreated)
                                                        {
                                                            failed.Add(new
                                                            {
                                                                row = rowMain,
                                                                topology = junctionPlan.Topology.ToString(),
                                                                reason = "opposite_side_cross_creation_failed",
                                                                detail = ReadFireBranchConnectionDiagnostic()
                                                            });
                                                        }
                                                    }
                                                }
                                                else
                                                {
                                                    double branchTieTolerance = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters);
                                                    bool branchEndsAtMain = IsPointAtPipeEnd(branch, mainTie, branchTieTolerance);
                                                    bool connectorCreated = false;
                                                    if (!branchEndsAtMain)
                                                    {
                                                        connectorCreated = TryCreateCrossAtPoint(doc, mainSegments, branchSegments, mainTie);
                                                    }
                                                    if (!connectorCreated)
                                                    {
                                                        ResetFireBranchConnectionDiagnostic();
                                                        connectorCreated = TryCreateTeeAtPoint(doc, mainSegments, branch, mainTie);
                                                    }
                                                    if (!connectorCreated)
                                                    {
                                                        failed.Add(new
                                                        {
                                                            row = rowMain,
                                                            topology = junctionPlan.Topology.ToString(),
                                                            reason = "主管與支管未能建立有效 Tee/Cross 配件連接",
                                                            detail = ReadFireBranchConnectionDiagnostic()
                                                        });
                                                    }
                                                }
                                            }
                                        }

                                        foreach (var item in row)
                                        {
                                            try
                                            {
                                                XYZ sprinklerPoint = item.Point;
                                                XYZ tapPoint = new XYZ(
                                                    mainStart.X + mainDirection.X * rowMain + branchDirection.X * item.BranchParameter,
                                                    mainStart.Y + mainDirection.Y * rowMain + branchDirection.Y * item.BranchParameter,
                                                    branchZ
                                                );
                                                Connector sprinklerConnector = FindConnectorNear(item.Sprinkler, sprinklerPoint);
                                                TryChangeConnectorSystemType(sprinklerConnector, systemType.Id);
                                                if (sprinklerConnector == null)
                                                {
                                                    failed.Add(new { sprinkler_id = item.Sprinkler.Id.Value, reason = "sprinkler_connector_missing" });
                                                    continue;
                                                }
                                                if (tapPoint.DistanceTo(sprinklerPoint) < 0.01)
                                                {
                                                    ResetFireBranchConnectionDiagnostic();
                                                    bool sameElevationConnected = TryConnectSprinklerToRun(
                                                        doc,
                                                        branchSegments,
                                                        sprinklerConnector,
                                                        tapPoint,
                                                        batchId,
                                                        additionalCreatedIds);
                                                    if (!sameElevationConnected)
                                                    {
                                                        failed.Add(new
                                                        {
                                                            sprinkler_id = item.Sprinkler.Id.Value,
                                                            reason = "same_elevation_sprinkler_connection_failed",
                                                            detail = ReadFireBranchConnectionDiagnostic()
                                                        });
                                                    }
                                                    continue;
                                                }

                                                ResetFireBranchConnectionDiagnostic();
                                                Pipe drop = CreateFireDropForSystem(
                                                    doc,
                                                    systemType.Id,
                                                    pipeType.Id,
                                                    levelId,
                                                    sprinklerConnector,
                                                    tapPoint,
                                                    diameterFeet);
                                                if (drop == null)
                                                {
                                                    failed.Add(new
                                                    {
                                                        sprinkler_id = item.Sprinkler.Id.Value,
                                                        reason = "sprinkler_drop_creation_failed",
                                                        detail = ReadFireBranchConnectionDiagnostic()
                                                    });
                                                    continue;
                                                }
                                                if (drop != null)
                                                {
                                                    TrySetScFireBranchMetadata(drop, "drop", batchId);
                                                    createdIds.Add(drop.Id);
                                                    createdPipeRoles[drop.Id.Value] = "drop";
                                                    created.Add(new { element_id = drop.Id.Value, kind = "drop", sprinkler_id = item.Sprinkler.Id.Value });
                                                    if (branchSegments.Count > 0)
                                                    {
                                                        ResetFireBranchConnectionDiagnostic();
                                                        bool dropConnectedToBranch = TryConnectPipeToRun(doc, branchSegments, drop, tapPoint);
                                                        if (!dropConnectedToBranch)
                                                        {
                                                            failed.Add(new
                                                            {
                                                                sprinkler_id = item.Sprinkler.Id.Value,
                                                                reason = "垂直短管未能與水平支管建立有效 Tee/彎頭連接",
                                                                detail = ReadFireBranchConnectionDiagnostic()
                                                            });
                                                        }
                                                    }
                                                    bool connectedToSprinkler = sprinklerConnector != null && sprinklerConnector.IsConnected;
                                                    if (!connectedToSprinkler)
                                                    {
                                                        connectedToSprinkler = TryConnectElements(doc, drop, sprinklerPoint, item.Sprinkler, sprinklerPoint);
                                                    }
                                                    if (!connectedToSprinkler)
                                                    {
                                                        failed.Add(new { sprinkler_id = item.Sprinkler.Id.Value, reason = "垂直短管未能連接到撒水頭 connector" });
                                                    }
                                                }
                                            }
                                            catch (Exception ex)
                                            {
                                                failed.Add(new { sprinkler_id = item.Sprinkler.Id.Value, reason = ex.Message });
                                            }
                                        }
                                    }
                                    foreach (FireBranchJunctionPlan crossPlan in junctionPlans
                                        .Where(plan => plan.Topology == FireBranchJunctionTopology.OppositeSidesSameElevation
                                            && !attemptedCrossPlans.Contains(plan)))
                                    {
                                        failed.Add(new
                                        {
                                            row = crossPlan.MainParameter,
                                            topology = crossPlan.Topology.ToString(),
                                            reason = "opposite_side_cross_missing_branch"
                                        });
                                    }
                                    foreach (FireBranchJunctionPlan offsetPlan in junctionPlans
                                        .Where(plan => plan.Topology == FireBranchJunctionTopology.OppositeSidesOffsetElevation
                                            && !attemptedOffsetPlans.Contains(plan)))
                                    {
                                        failed.Add(new
                                        {
                                            row = offsetPlan.MainParameter,
                                            topology = offsetPlan.Topology.ToString(),
                                            reason = "opposite_side_offset_missing_branch"
                                        });
                                    }

                                    foreach (ElementId additionalId in additionalCreatedIds
                                        .GroupBy(id => id.Value)
                                        .Select(group => group.First()))
                                    {
                                        if (!createdIds.Any(id => id.Value == additionalId.Value))
                                        {
                                            createdIds.Add(additionalId);
                                            Element additionalElement = doc.GetElement(additionalId);
                                            if (additionalElement is Pipe)
                                            {
                                                createdPipeRoles[additionalId.Value] = "branch";
                                            }
                                            created.Add(new
                                            {
                                                element_id = additionalId.Value,
                                                kind = additionalElement is Pipe ? "branch_segment" : "fitting"
                                            });
                                        }
                                    }

                                    doc.Regenerate();
                                    TransactionStatus creationStatus = creationTransaction.Commit();
                                    if (creationStatus != TransactionStatus.Committed)
                                    {
                                        throw new InvalidOperationException("Fire branch geometry transaction did not commit: " + creationStatus);
                                    }
                                    }
                                    List<Pipe> createdPipes = createdIds
                                        .Select(id => doc.GetElement(id) as Pipe)
                                        .Where(pipe => pipe != null && IsScFireBranchPipe(pipe))
                                        .GroupBy(pipe => pipe.Id.Value)
                                        .Select(group => group.First())
                                        .ToList();
                                    List<MEPSystem> connectedSystems = mainPipes.Select(item => item.Pipe.MEPSystem)
                                        .Concat(createdPipes.Select(pipe => pipe.MEPSystem))
                                        .Concat(plannedSprinklers.Select(instance =>
                                        {
                                            Connector connector = FindConnectorNear(
                                                instance,
                                                GetFamilyConnectionPoint(instance));
                                            return connector == null ? null : connector.MEPSystem;
                                        }))
                                        .Where(system => system != null)
                                        .GroupBy(system => system.Id.Value)
                                        .Select(group => group.First())
                                        .ToList();
                                    var systemChangeFailures = new List<object>();
                                    using (Transaction systemTransaction = new Transaction(doc, "SC \u7d71\u4e00\u6d88\u9632\u7cfb\u7d71\u985e\u578b"))
                                    {
                                    TransactionStatus systemStartStatus = systemTransaction.Start();
                                    if (systemStartStatus != TransactionStatus.Started)
                                    {
                                        throw new InvalidOperationException("Fire branch system transaction did not start: " + systemStartStatus);
                                    }
                                    foreach (MEPSystem connectedSystem in connectedSystems)
                                    {
                                        ElementId beforeTypeId = connectedSystem.GetTypeId();
                                        if (beforeTypeId != null && beforeTypeId.Value == systemType.Id.Value)
                                        {
                                            continue;
                                        }
                                        try
                                        {
                                            bool canAssign = connectedSystem.CanHaveTypeAssigned();
                                            bool targetIsValid = connectedSystem.IsValidType(systemType.Id);
                                            if (!canAssign || !targetIsValid)
                                            {
                                                systemChangeFailures.Add(new
                                                {
                                                    system_id = connectedSystem.Id.Value,
                                                    before_system_type_id = beforeTypeId == null ? 0 : beforeTypeId.Value,
                                                    can_have_type_assigned = canAssign,
                                                    target_is_valid = targetIsValid,
                                                    reason = "target_system_type_not_assignable"
                                                });
                                                continue;
                                            }

                                            connectedSystem.ChangeTypeId(systemType.Id);
                                            ElementId afterTypeId = connectedSystem.GetTypeId();
                                            if (afterTypeId == null || afterTypeId.Value != systemType.Id.Value)
                                            {
                                                systemChangeFailures.Add(new
                                                {
                                                    system_id = connectedSystem.Id.Value,
                                                    before_system_type_id = beforeTypeId == null ? 0 : beforeTypeId.Value,
                                                    after_system_type_id = afterTypeId == null ? 0 : afterTypeId.Value,
                                                    reason = "system_change_did_not_persist"
                                                });
                                            }
                                        }
                                        catch (Exception ex)
                                        {
                                            systemChangeFailures.Add(new
                                            {
                                                system_id = connectedSystem.Id.Value,
                                                before_system_type_id = beforeTypeId == null ? 0 : beforeTypeId.Value,
                                                reason = "system_change_exception",
                                                detail = ex.GetType().Name + ": " + ex.Message
                                            });
                                        }
                                    }
                                    doc.Regenerate();
                                    TransactionStatus systemStatus = systemTransaction.Commit();
                                    if (systemStatus != TransactionStatus.Committed)
                                    {
                                        throw new InvalidOperationException("Fire branch system transaction did not commit: " + systemStatus);
                                    }
                                    }
                                    List<long> actualSystemTypeIds = connectedSystems
                                        .Where(system => system != null)
                                        .Select(system => system.GetTypeId())
                                        .Where(typeId => typeId != null)
                                        .Select(typeId => typeId.Value)
                                        .Distinct()
                                        .ToList();
                                    List<long> missingSystemPipeIds = createdPipes
                                        .Where(pipe => pipe.MEPSystem == null)
                                        .Select(pipe => pipe.Id.Value)
                                        .ToList();
                                    List<long> wrongSystemPipeIds = createdPipes
                                        .Where(pipe => pipe.MEPSystem != null
                                            && pipe.MEPSystem.GetTypeId().Value != systemType.Id.Value)
                                        .Select(pipe => pipe.Id.Value)
                                        .ToList();
                                    List<long> missingConnectorSprinklerIds = plannedSprinklers
                                        .Where(instance => FindConnectorNear(
                                            instance,
                                            GetFamilyConnectionPoint(instance)) == null)
                                        .Select(instance => instance.Id.Value)
                                        .ToList();
                                    List<long> missingSystemSprinklerIds = plannedSprinklers
                                        .Where(instance =>
                                        {
                                            Connector connector = FindConnectorNear(
                                                instance,
                                                GetFamilyConnectionPoint(instance));
                                            return connector != null && connector.MEPSystem == null;
                                        })
                                        .Select(instance => instance.Id.Value)
                                        .ToList();
                                    List<long> wrongSystemSprinklerIds = plannedSprinklers
                                        .Where(instance =>
                                        {
                                            Connector connector = FindConnectorNear(
                                                instance,
                                                GetFamilyConnectionPoint(instance));
                                            return connector != null
                                                && connector.MEPSystem != null
                                                && connector.MEPSystem.GetTypeId().Value != systemType.Id.Value;
                                        })
                                        .Select(instance => instance.Id.Value)
                                        .ToList();
                                    if (missingSystemPipeIds.Count > 0
                                        || wrongSystemPipeIds.Count > 0
                                        || missingConnectorSprinklerIds.Count > 0
                                        || missingSystemSprinklerIds.Count > 0
                                        || wrongSystemSprinklerIds.Count > 0
                                        || systemChangeFailures.Count > 0)
                                    {
                                        failed.Add(new
                                        {
                                            reason = "system_type_verification_failed",
                                            target_system_type_id = systemType.Id.Value,
                                            actual_system_type_ids = actualSystemTypeIds,
                                            missing_system_pipe_ids = missingSystemPipeIds,
                                            wrong_system_pipe_ids = wrongSystemPipeIds,
                                            missing_connector_sprinkler_ids = missingConnectorSprinklerIds,
                                            missing_system_sprinkler_ids = missingSystemSprinklerIds,
                                            wrong_system_sprinkler_ids = wrongSystemSprinklerIds,
                                            system_change_failures = systemChangeFailures
                                        });
                                    }
                                    var unconnectedSprinklerIds = plannedSprinklers
                                        .Where(instance =>
                                        {
                                            Connector connector = FindConnectorNear(instance, GetFamilyConnectionPoint(instance));
                                            return connector == null || !connector.IsConnected;
                                        })
                                        .Select(instance => instance.Id.Value)
                                        .ToList();
                                    var unconnectedCreatedPipeIds = createdIds
                                        .Select(id => doc.GetElement(id) as Pipe)
                                        .Where(pipe => pipe != null)
                                        .Where(pipe =>
                                        {
                                            List<Connector> connectors = pipe.ConnectorManager.Connectors
                                                .Cast<Connector>()
                                                .ToList();
                                            string role;
                                            createdPipeRoles.TryGetValue(pipe.Id.Value, out role);
                                            return role == "feeder" || role == "drop"
                                                ? connectors.Any(connector => !connector.IsConnected)
                                                : connectors.All(connector => !connector.IsConnected);
                                        })
                                        .Select(pipe => pipe.Id.Value)
                                        .Distinct()
                                        .ToList();
                                    if (unconnectedSprinklerIds.Count > 0 || unconnectedCreatedPipeIds.Count > 0)
                                    {
                                        failed.Add(new
                                        {
                                            reason = "connector_verification_failed",
                                            unconnected_sprinkler_ids = unconnectedSprinklerIds,
                                            unconnected_pipe_ids = unconnectedCreatedPipeIds
                                        });
                                    }
                                    if (failed.Count > 0)
                                    {
                                        throw new FireBranchConnectorVerificationException(
                                            "Fire branch connector verification failed. No branch elements were committed. Failure count: "
                                            + failed.Count
                                            + ". Detailed junction diagnostics were persisted.",
                                            failed.ToArray());
                                    }
                                    TransactionStatus groupStatus = transactionGroup.Assimilate();
                                    if (groupStatus != TransactionStatus.Committed)
                                    {
                                        throw new InvalidOperationException("Fire branch transaction group did not assimilate: " + groupStatus);
                                    }
                                    }
                                    catch
                                    {
                                        if (transactionGroup.GetStatus() == TransactionStatus.Started)
                                        {
                                            transactionGroup.RollBack();
                                        }
                                        throw;
                                    }
                                }

                                if (deletePreviewAfterCreate)
                                {
                                    Element previewGroup = previewGroupId > 0
                                        ? doc.GetElement(new ElementId(previewGroupId))
                                        : null;
                                    if (previewGroup != null)
                                    {
                                        using (Transaction cleanupTransaction = new Transaction(doc, "SC 刪除消防支管預覽"))
                                        {
                                            cleanupTransaction.Start();
                                            doc.Delete(previewGroup.Id);
                                            cleanupTransaction.Commit();
                                        }
                                        deletedPreviewGroupId = previewGroupId;
                                    }
                                    DrainagePreviewServer.Clear(doc);
                                    uiApp.ActiveUIDocument.RefreshActiveView();
                                }

                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        batch_id = batchId,
                                        created = created,
                                        failed = failed,
                                        skipped = skipped,
                                        verification_status = "verified",
                                        verified_system_type_id = systemType.Id.Value,
                                        verified_system_type_name = systemType.Name,
                                        connected_sprinkler_count = plannedSprinklers.Count,
                                        unconnected_sprinkler_count = 0,
                                        junctions = junctions,
                                        sprinkler_count = sprinklers.Count,
                                        main_candidate_count = mainCandidateCount,
                                        valid_main_count = mainPipes.Count,
                                        excluded_main_count = excludedMainCount,
                                        row_count = plannedRowCount,
                                        estimated_pipe_count = estimatedPipeCount,
                                        max_branch_length_m = maxBranchLengthMeters,
                                        deleted_preview_group_id = deletedPreviewGroupId
                                    })
                                );
                                return;
                            }

            throw new InvalidOperationException("Unsupported fire branch action: " + action);
        }
    }
}
