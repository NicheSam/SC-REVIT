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
            "read_fire_branch_snapshot",
            "create_fire_branch_preview",
            "focus_fire_branch_preview_segment",
            "create_fire_branch_pipes",
            "test_fire_branch_pipes"
        };
        private const string ScFireBranchCommentPrefix = "SC_FIRE_BRANCH:";
        private const double FireSprinklerDropDiameterMillimeters = 25.0;

        private sealed class FireBranchSandboxFailurePreprocessor : IFailuresPreprocessor
        {
            private readonly List<string> _messages = new List<string>();

            public string Summary
            {
                get { return string.Join(" | ", _messages.Distinct()); }
            }

            public FailureProcessingResult PreprocessFailures(FailuresAccessor failuresAccessor)
            {
                bool hasError = false;
                foreach (FailureMessageAccessor message in failuresAccessor.GetFailureMessages())
                {
                    _messages.Add(
                        message.GetFailureDefinitionId().Guid.ToString("D")
                        + ": "
                        + message.GetDescriptionText());
                    if (message.GetSeverity() == FailureSeverity.Warning)
                    {
                        failuresAccessor.DeleteWarning(message);
                    }
                    else
                    {
                        hasError = true;
                    }
                }
                return hasError
                    ? FailureProcessingResult.ProceedWithRollBack
                    : FailureProcessingResult.Continue;
            }
        }

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

        private class FireBranchCadCandidateEvidence
        {
            public FireBranchItem Candidate { get; set; }
            public CadPathSource Source { get; set; }
            public int SampleCount { get; set; }
            public int MatchedSampleCount { get; set; }
            public int LongestMatchedRun { get; set; }
            public bool SprinklerEndMatched { get; set; }
            public double CoverageRatio { get; set; }
            public double ContinuousCoverageRatio { get; set; }
            public double MeanOffsetMm { get; set; }
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

            // The selection is a seed, not necessarily the complete main run.
            // Follow the physical Connector graph through elbows/fittings so an
            // L/U/fishbone main remains one candidate network.
            List<long> networkIds = ExpandFireMainPipeIds(doc, ids);

            double shortPipeFeet = UnitUtils.ConvertToInternalUnits(50, UnitTypeId.Centimeters);
            double riserHorizontalFeet = UnitUtils.ConvertToInternalUnits(30, UnitTypeId.Centimeters);
            double riserVerticalFeet = UnitUtils.ConvertToInternalUnits(30, UnitTypeId.Centimeters);
            var candidates = new List<FireMainPipeData>();
            foreach (long id in networkIds)
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
            // CAD evidence and the topology plan decide the main skeleton.  Do
            // not silently discard connected segments by keeping only a longest
            // or parallel path here.
            return mains;
        }

        private static List<long> ExpandFireMainPipeIds(
            Document doc,
            List<long> seedIds)
        {
            var orderedPipeIds = new List<long>();
            var pending = new Queue<ElementId>();
            var visited = new HashSet<long>();
            foreach (long seedId in seedIds ?? new List<long>())
            {
                if (seedId > 0)
                {
                    pending.Enqueue(new ElementId(seedId));
                }
            }

            while (pending.Count > 0 && visited.Count < 5000)
            {
                ElementId currentId = pending.Dequeue();
                if (currentId == null || !visited.Add(currentId.Value))
                {
                    continue;
                }
                Element current = doc.GetElement(currentId);
                if (current == null || !current.IsValidObject)
                {
                    continue;
                }
                Pipe currentPipe = current as Pipe;
                if (currentPipe != null && !orderedPipeIds.Contains(currentPipe.Id.Value))
                {
                    orderedPipeIds.Add(currentPipe.Id.Value);
                }

                ConnectorSet connectors;
                try
                {
                    connectors = GetFirePhysicalConnectors(current);
                }
                catch
                {
                    continue;
                }
                if (connectors == null)
                {
                    continue;
                }
                foreach (Connector connector in connectors.Cast<Connector>())
                {
                    foreach (Connector reference in connector.AllRefs.Cast<Connector>())
                    {
                        Element owner = reference == null ? null : reference.Owner;
                        if (owner == null
                            || owner is MEPSystem
                            || reference.ConnectorType == ConnectorType.Logical
                            || visited.Contains(owner.Id.Value))
                        {
                            continue;
                        }
                        if (owner is MEPCurve || owner is FamilyInstance)
                        {
                            pending.Enqueue(owner.Id);
                        }
                    }
                }
            }
            return orderedPipeIds;
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

        private static List<FireBranchItem> BuildFireBranchCandidates(
            FamilyInstance sprinkler,
            XYZ point,
            List<FireMainPipeData> mains)
        {
            var result = new List<FireBranchItem>();
            double projectionTolerance = UnitUtils.ConvertToInternalUnits(30, UnitTypeId.Centimeters);
            foreach (FireMainPipeData main in mains)
            {
                double rawParameter = DotXY(point - main.Start, main.Direction);
                if (rawParameter < -projectionTolerance || rawParameter > main.Length + projectionTolerance)
                {
                    continue;
                }
                double parameter = Math.Max(0, Math.Min(main.Length, rawParameter));
                XYZ projected = main.Start + main.Direction * parameter;
                double signedBranch = DotXY(point - projected, main.BaseBranchDirection);
                double distance = Math.Abs(signedBranch);
                if (distance < 0.001)
                {
                    continue;
                }
                int sideSign = signedBranch < 0 ? -1 : 1;
                result.Add(new FireBranchItem
                {
                    Sprinkler = sprinkler,
                    Point = point,
                    MainPipe = main.Pipe,
                    MainPipeId = main.PipeId,
                    MainStart = main.Start,
                    MainDirection = main.Direction,
                    BranchDirection = sideSign < 0
                        ? main.BaseBranchDirection.Negate()
                        : main.BaseBranchDirection,
                    MainZ = main.Z,
                    MainParameter = parameter,
                    BranchParameter = distance,
                    SideSign = sideSign
                });
            }
            return result;
        }

        private static FireBranchItem BuildLegacyUniformFireBranchItem(
            FamilyInstance sprinkler,
            XYZ point,
            List<FireMainPipeData> mains)
        {
            FireMainPipeData bestMain = null;
            FireMainPipeData secondMain = null;
            double bestDistance = double.MaxValue;
            double secondDistance = double.MaxValue;
            double bestParameter = 0;
            double bestBranchParameter = 0;
            int bestSideSign = 1;
            XYZ bestBranchDirection = XYZ.BasisY;
            double projectionTolerance = UnitUtils.ConvertToInternalUnits(30, UnitTypeId.Centimeters);

            foreach (FireMainPipeData main in mains)
            {
                double rawParameter = DotXY(point - main.Start, main.Direction);
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
            if (secondMain != null
                && secondMain.PipeId != bestMain.PipeId
                && secondDistance - bestDistance < ambiguityTolerance)
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

        private static List<FireBranchItem> BuildLegacyUniformFireBranchItems(
            List<FamilyInstance> sprinklers,
            List<XYZ> sprinklerPoints,
            List<FireMainPipeData> mainPipes,
            List<object> skipped,
            out List<object> assignmentAudit)
        {
            var result = new List<FireBranchItem>();
            assignmentAudit = new List<object>();
            for (int index = 0; index < sprinklers.Count; index++)
            {
                FamilyInstance sprinkler = sprinklers[index];
                try
                {
                    FireBranchItem item = BuildLegacyUniformFireBranchItem(
                        sprinkler,
                        sprinklerPoints[index],
                        mainPipes);
                    result.Add(item);
                    assignmentAudit.Add(new
                    {
                        sprinkler_id = sprinkler.Id.Value,
                        status = "selected_by_legacy_nearest_main",
                        main_pipe_id = item.MainPipeId
                    });
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

        private static List<FireBranchItem> BuildFireBranchItemsFromCadEvidence(
            Document doc,
            List<FamilyInstance> sprinklers,
            List<XYZ> sprinklerPoints,
            List<FireMainPipeData> mainPipes,
            double branchZ,
            List<object> skipped,
            out List<object> assignmentAudit)
        {
            var candidatesBySprinkler = new List<List<FireBranchItem>>();
            for (int index = 0; index < sprinklers.Count; index++)
            {
                FamilyInstance sprinkler = sprinklers[index];
                List<FireBranchItem> candidates = BuildFireBranchCandidates(
                    sprinkler,
                    sprinklerPoints[index],
                    mainPipes);
                if (candidates.Count == 0)
                {
                    skipped.Add(new
                    {
                        sprinkler_id = sprinkler.Id.Value,
                        reason = "無法投影到任何主管候選。"
                    });
                }
                candidatesBySprinkler.Add(candidates);
            }
            return SelectFireBranchItemsByCadEvidence(
                doc,
                candidatesBySprinkler,
                mainPipes,
                branchZ,
                skipped,
                out assignmentAudit);
        }

        private static List<FireBranchItem> SelectFireBranchItemsByCadEvidence(
            Document doc,
            List<List<FireBranchItem>> candidatesBySprinkler,
            List<FireMainPipeData> mainPipes,
            double branchZ,
            List<object> skipped,
            out List<object> assignmentAudit)
        {
            assignmentAudit = new List<object>();
            var candidateLines = new List<Line>();
            foreach (FireBranchItem candidate in candidatesBySprinkler.SelectMany(items => items))
            {
                Line line = BuildFireBranchCandidateLine(candidate, branchZ);
                if (line != null)
                {
                    candidateLines.Add(line);
                }
            }
            var extractionScope = new CadPathExtractionScope
            {
                Buffer = UnitUtils.ConvertToInternalUnits(1000, UnitTypeId.Millimeters)
            };
            extractionScope.Corridors.AddRange(candidateLines);
            extractionScope.Corridors.AddRange(BuildFireBranchMainContextLines(mainPipes));
            List<CadPathSource> sources = ReadVisibleCadPathSources(doc, extractionScope);

            var result = new List<FireBranchItem>();
            foreach (List<FireBranchItem> candidates in candidatesBySprinkler)
            {
                if (candidates.Count == 0)
                {
                    continue;
                }
                FamilyInstance sprinkler = candidates[0].Sprinkler;
                var evidence = new List<FireBranchCadCandidateEvidence>();
                foreach (CadPathSource source in sources)
                {
                    var index = new CadPathSpatialIndex(
                        source.Segments,
                        UnitUtils.ConvertToInternalUnits(500, UnitTypeId.Millimeters),
                        UnitUtils.ConvertToInternalUnits(100, UnitTypeId.Millimeters));
                    foreach (FireBranchItem candidate in candidates)
                    {
                        evidence.Add(EvaluateFireBranchCadCandidateEvidence(
                            candidate,
                            source,
                            index,
                            branchZ));
                    }
                }
                FireBranchCadCandidateEvidence best = evidence
                    .OrderByDescending(item => item, Comparer<FireBranchCadCandidateEvidence>.Create(
                        CompareFireBranchCadCandidateEvidence))
                    .FirstOrDefault();
                if (best == null
                    || best.CoverageRatio < 0.55
                    || best.ContinuousCoverageRatio < 0.35)
                {
                    skipped.Add(new
                    {
                        sprinkler_id = sprinkler.Id.Value,
                        reason = sources.Count == 0
                            ? "找不到可用 CAD 路徑，不能決定應連接哪一段主管。"
                            : "CAD 路徑證據不足，未以最近距離猜測主管。"
                    });
                    assignmentAudit.Add(new
                    {
                        sprinkler_id = sprinkler.Id.Value,
                        status = sources.Count == 0 ? "cad_unavailable" : "cad_route_unresolved",
                        candidate_count = candidates.Count
                    });
                    continue;
                }

                result.Add(best.Candidate);
                assignmentAudit.Add(new
                {
                    sprinkler_id = sprinkler.Id.Value,
                    status = "selected_by_cad_route_evidence",
                    main_pipe_id = best.Candidate.MainPipeId,
                    source_import_id = best.Source.ImportInstance.Id.Value,
                    coverage_ratio = best.CoverageRatio,
                    continuous_coverage_ratio = best.ContinuousCoverageRatio,
                    sprinkler_end_matched = best.SprinklerEndMatched,
                    mean_offset_mm = best.MeanOffsetMm,
                    branch_length_mm = best.Candidate.BranchParameter * 304.8,
                    candidate_count = candidates.Count,
                    decision_basis = "CAD 路徑證據優先，距離只作最後同分判斷",
                    candidates = evidence
                        .OrderByDescending(item => item, Comparer<FireBranchCadCandidateEvidence>.Create(
                            CompareFireBranchCadCandidateEvidence))
                        .Select(item => new
                        {
                            main_pipe_id = item.Candidate.MainPipeId,
                            source_import_id = item.Source.ImportInstance.Id.Value,
                            coverage_ratio = item.CoverageRatio,
                            continuous_coverage_ratio = item.ContinuousCoverageRatio,
                            sprinkler_end_matched = item.SprinklerEndMatched,
                            mean_offset_mm = item.MeanOffsetMm,
                            branch_length_mm = item.Candidate.BranchParameter * 304.8
                        })
                        .ToList()
                });
            }
            return result
                .OrderBy(item => item.MainPipeId)
                .ThenBy(item => item.MainParameter)
                .ToList();
        }

        private static Line BuildFireBranchCandidateLine(FireBranchItem candidate, double branchZ)
        {
            XYZ start = new XYZ(
                candidate.MainStart.X + candidate.MainDirection.X * candidate.MainParameter,
                candidate.MainStart.Y + candidate.MainDirection.Y * candidate.MainParameter,
                branchZ);
            XYZ end = new XYZ(candidate.Point.X, candidate.Point.Y, branchZ);
            return DistanceXY(start, end) > 0.001 ? Line.CreateBound(start, end) : null;
        }

        private static FireBranchCadCandidateEvidence EvaluateFireBranchCadCandidateEvidence(
            FireBranchItem candidate,
            CadPathSource source,
            CadPathSpatialIndex index,
            double branchZ)
        {
            var evidence = new FireBranchCadCandidateEvidence
            {
                Candidate = candidate,
                Source = source
            };
            Line line = BuildFireBranchCandidateLine(candidate, branchZ);
            if (line == null)
            {
                return evidence;
            }
            XYZ start = line.GetEndPoint(0);
            XYZ end = line.GetEndPoint(1);
            XYZ direction = NormalizeXY(end - start);
            double length = DistanceXY(start, end);
            double sampleSpacing = UnitUtils.ConvertToInternalUnits(250, UnitTypeId.Millimeters);
            double distanceTolerance = UnitUtils.ConvertToInternalUnits(100, UnitTypeId.Millimeters);
            int sampleCount = Math.Max(5, Math.Min(160, (int)Math.Ceiling(length / sampleSpacing) + 1));
            int currentRun = 0;
            double offsetSum = 0;
            for (int sampleIndex = 0; sampleIndex < sampleCount; sampleIndex++)
            {
                double parameter = (double)sampleIndex / (sampleCount - 1);
                XYZ point = start + (end - start) * parameter;
                CadPathSegment match;
                double distance;
                bool matched = TryFindCadPathMatch(
                    index,
                    point,
                    direction,
                    distanceTolerance,
                    10,
                    out match,
                    out distance);
                evidence.SampleCount += 1;
                if (!matched)
                {
                    currentRun = 0;
                    continue;
                }
                evidence.MatchedSampleCount += 1;
                currentRun += 1;
                evidence.LongestMatchedRun = Math.Max(evidence.LongestMatchedRun, currentRun);
                offsetSum += distance;
                if (sampleIndex == sampleCount - 1)
                {
                    evidence.SprinklerEndMatched = true;
                }
            }
            evidence.CoverageRatio = evidence.SampleCount > 0
                ? (double)evidence.MatchedSampleCount / evidence.SampleCount
                : 0;
            evidence.ContinuousCoverageRatio = evidence.SampleCount > 0
                ? (double)evidence.LongestMatchedRun / evidence.SampleCount
                : 0;
            evidence.MeanOffsetMm = evidence.MatchedSampleCount > 0
                ? offsetSum / evidence.MatchedSampleCount * 304.8
                : double.MaxValue;
            return evidence;
        }

        private static int CompareFireBranchCadCandidateEvidence(
            FireBranchCadCandidateEvidence left,
            FireBranchCadCandidateEvidence right)
        {
            int comparison = left.CoverageRatio.CompareTo(right.CoverageRatio);
            if (Math.Abs(left.CoverageRatio - right.CoverageRatio) > 0.05)
            {
                return comparison;
            }
            comparison = left.ContinuousCoverageRatio.CompareTo(right.ContinuousCoverageRatio);
            if (Math.Abs(left.ContinuousCoverageRatio - right.ContinuousCoverageRatio) > 0.05)
            {
                return comparison;
            }
            comparison = left.SprinklerEndMatched.CompareTo(right.SprinklerEndMatched);
            if (comparison != 0)
            {
                return comparison;
            }
            comparison = left.Source.CoordinateVerified.CompareTo(right.Source.CoordinateVerified);
            if (comparison != 0)
            {
                return comparison;
            }
            if (Math.Abs(left.MeanOffsetMm - right.MeanOffsetMm) > 25)
            {
                return right.MeanOffsetMm.CompareTo(left.MeanOffsetMm);
            }
            // CAD evidence is tied.  Physical distance is deliberately the final tie-breaker.
            comparison = right.Candidate.BranchParameter.CompareTo(left.Candidate.BranchParameter);
            return comparison != 0
                ? comparison
                : right.Candidate.MainPipeId.CompareTo(left.Candidate.MainPipeId);
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

        private static bool IsFireBranchTopologyCrossKind(string kind)
        {
            return kind == "cross"
                || kind == "reducing_cross"
                || kind == "endpoint_tee"
                || kind == "reducing_endpoint_tee";
        }

        private static List<FireBranchJunctionPlan> BuildFireBranchTopologyJunctionPlans(
            List<List<FireBranchItem>> rows,
            List<FireBranchExecutionJunction> topologyPlan)
        {
            var plans = new List<FireBranchJunctionPlan>();
            if (rows == null || topologyPlan == null)
            {
                return plans;
            }
            foreach (FireBranchExecutionJunction execution in topologyPlan)
            {
                if (execution == null
                    || execution.RowIndexes.Count != 2
                    || !IsFireBranchTopologyCrossKind(execution.Kind))
                {
                    continue;
                }
                var plan = new FireBranchJunctionPlan
                {
                    Topology = FireBranchJunctionTopology.OppositeSidesSameElevation
                };
                foreach (int rowIndex in execution.RowIndexes.OrderBy(value => value))
                {
                    if (rowIndex < 0 || rowIndex >= rows.Count)
                    {
                        plan.Rows.Clear();
                        break;
                    }
                    plan.Rows.Add(rows[rowIndex]);
                }
                if (plan.Rows.Count != 2)
                {
                    continue;
                }
                FireBranchItem reference = plan.Rows.SelectMany(row => row).FirstOrDefault();
                if (reference == null)
                {
                    continue;
                }
                plan.MainPipeId = reference.MainPipeId;
                if (execution.Point != null)
                {
                    plan.MainParameter = new XYZ(
                        execution.Point.X - reference.MainStart.X,
                        execution.Point.Y - reference.MainStart.Y,
                        0).DotProduct(reference.MainDirection);
                }
                else
                {
                    plan.MainParameter = plan.Rows.Average(row => row.Average(item => item.MainParameter));
                }
                plans.Add(plan);
            }
            return plans;
        }

        private static List<FireBranchJunctionPlan> MergeFireBranchTopologyJunctionPlans(
            List<FireBranchJunctionPlan> legacyPlans,
            List<FireBranchJunctionPlan> topologyPlans,
            List<List<FireBranchItem>> rows)
        {
            if (topologyPlans == null || topologyPlans.Count == 0)
            {
                return legacyPlans;
            }
            var topologyRowIndexes = new HashSet<int>(
                topologyPlans
                    .SelectMany(plan => plan.Rows)
                    .Select(row => rows.IndexOf(row))
                    .Where(index => index >= 0));
            var merged = (legacyPlans ?? new List<FireBranchJunctionPlan>())
                .Where(plan => !plan.Rows.Any(row => topologyRowIndexes.Contains(rows.IndexOf(row))))
                .ToList();
            merged.AddRange(topologyPlans);
            return merged;
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

        private class FireBranchDiameterPlanSegment
        {
            public string PlanEntityId { get; set; }
            public string SegmentId { get; set; }
            public int RowIndex { get; set; }
            public int Sequence { get; set; }
            public XYZ Start { get; set; }
            public XYZ End { get; set; }
            public double DiameterFeet { get; set; }
            public long SprinklerId { get; set; }
            public bool IsSprinklerTerminal { get; set; }
        }

        private class FireBranchExecutionJunction
        {
            public string PlanEntityId { get; set; }
            public string Kind { get; set; }
            public List<int> RowIndexes { get; private set; }
            public Dictionary<int, string> BranchPlanEntityIdByRow { get; private set; }
            public XYZ Point { get; set; }
            public double MainDiameterFeet { get; set; }
            public double CommonBranchDiameterFeet { get; set; }
            public Dictionary<int, double> SourceBranchDiameterFeetByRow { get; private set; }
            public HashSet<int> RoutingFitReducerRows { get; private set; }
            public HashSet<string> RoutingFitReducerPlanEntityIds { get; private set; }

            public FireBranchExecutionJunction()
            {
                RowIndexes = new List<int>();
                BranchPlanEntityIdByRow = new Dictionary<int, string>();
                SourceBranchDiameterFeetByRow = new Dictionary<int, double>();
                RoutingFitReducerRows = new HashSet<int>();
                RoutingFitReducerPlanEntityIds = new HashSet<string>(StringComparer.Ordinal);
            }
        }

        private class FirePendingCrossTransition
        {
            public int RowIndex { get; set; }
            public ElementId BranchPipeId { get; set; }
            public ElementId CrossFittingId { get; set; }
            public double CommonDiameterFeet { get; set; }
            public double SourceDiameterFeet { get; set; }
            public double ResolvedOffsetFeet { get; set; }
            public List<Pipe> BranchRun { get; set; }
            public HashSet<long> TopologyOverridePipeIds { get; set; }
        }

        private class FireDropAssembly
        {
            public List<Pipe> Pipes { get; private set; }
            public FamilyInstance SprinklerTransition { get; set; }
            public Pipe BranchConnectionPipe { get; set; }
            public Pipe SprinklerConnectionPipe { get; set; }

            public FireDropAssembly()
            {
                Pipes = new List<Pipe>();
            }
        }

        private class FirePendingSprinklerConnection
        {
            public ElementId DropPipeId { get; set; }
            public ElementId SprinklerId { get; set; }
            public XYZ SprinklerPoint { get; set; }
        }

        private static List<FireBranchDiameterPlanSegment> ReadFireBranchDiameterPlan(
            Dictionary<string, object> payload)
        {
            var result = new List<FireBranchDiameterPlanSegment>();
            ArrayList rawSegments = payload.ContainsKey("diameter_plan")
                ? payload["diameter_plan"] as ArrayList
                : null;
            if (rawSegments == null)
            {
                return result;
            }
            foreach (object raw in rawSegments)
            {
                Dictionary<string, object> item = raw as Dictionary<string, object>;
                Dictionary<string, object> start = item != null && item.ContainsKey("start")
                    ? item["start"] as Dictionary<string, object>
                    : null;
                Dictionary<string, object> end = item != null && item.ContainsKey("end")
                    ? item["end"] as Dictionary<string, object>
                    : null;
                if (item == null || start == null || end == null)
                {
                    continue;
                }
                double diameterMm = ReadDouble(item, "diameter_mm", 0);
                if (diameterMm <= 0)
                {
                    continue;
                }
                result.Add(new FireBranchDiameterPlanSegment
                {
                    PlanEntityId = item.ContainsKey("plan_entity_id") ? Convert.ToString(item["plan_entity_id"]) : "",
                    SegmentId = item.ContainsKey("segment_id") ? Convert.ToString(item["segment_id"]) : "",
                    RowIndex = Convert.ToInt32(ReadLong(item, "row_index", 0)),
                    Sequence = Convert.ToInt32(ReadLong(item, "sequence", 0)),
                    Start = new XYZ(ReadDouble(start, "x"), ReadDouble(start, "y"), ReadDouble(start, "z")),
                    End = new XYZ(ReadDouble(end, "x"), ReadDouble(end, "y"), ReadDouble(end, "z")),
                    DiameterFeet = UnitUtils.ConvertToInternalUnits(diameterMm, UnitTypeId.Millimeters),
                    SprinklerId = ReadLong(item, "sprinkler_id", 0),
                    IsSprinklerTerminal = ReadBool(item, "is_sprinkler_terminal", false)
                });
            }
            return result;
        }

        private static Dictionary<string, object> GetFireBranchTopologyPlanPayload(
            Dictionary<string, object> payload)
        {
            return payload.ContainsKey("topology_plan")
                ? payload["topology_plan"] as Dictionary<string, object>
                : null;
        }

        private static string ReadTopologyPlanString(
            Dictionary<string, object> payload,
            string key)
        {
            Dictionary<string, object> topology = GetFireBranchTopologyPlanPayload(payload);
            return topology != null && topology.ContainsKey(key) && topology[key] != null
                ? Convert.ToString(topology[key])
                : "";
        }

        private static long ReadTopologyPlanLong(
            Dictionary<string, object> payload,
            string key,
            long fallback)
        {
            Dictionary<string, object> topology = GetFireBranchTopologyPlanPayload(payload);
            if (topology == null || !topology.ContainsKey(key) || topology[key] == null)
            {
                return fallback;
            }
            try
            {
                return Convert.ToInt64(topology[key]);
            }
            catch
            {
                return fallback;
            }
        }

        private static void ValidateFireBranchTopologyPlanIdentity(
            Dictionary<string, object> payload,
            bool required)
        {
            if (!required)
            {
                return;
            }

            Dictionary<string, object> topology = GetFireBranchTopologyPlanPayload(payload);
            if (topology == null)
            {
                throw new InvalidOperationException("建立要求缺少拓樸計畫，請重新分析。\n");
            }
            string schemaVersion = ReadTopologyPlanString(payload, "schema_version");
            if (schemaVersion != "fire_branch_topology_plan.v5")
            {
                throw new InvalidOperationException(
                    "拓樸計畫版本不支援：" + schemaVersion + "，請重新分析。\n");
            }
            if (string.IsNullOrWhiteSpace(ReadTopologyPlanString(payload, "plan_id")))
            {
                throw new InvalidOperationException("拓樸計畫缺少 plan_id，請重新分析。\n");
            }
            if (!Regex.IsMatch(
                    ReadTopologyPlanString(payload, "plan_hash"),
                    "^[0-9a-fA-F]{64}$"))
            {
                throw new InvalidOperationException("拓樸計畫缺少有效雜湊，請重新分析。\n");
            }

            ArrayList segments = topology.ContainsKey("segments")
                ? topology["segments"] as ArrayList
                : null;
            foreach (object raw in segments ?? new ArrayList())
            {
                Dictionary<string, object> item = raw as Dictionary<string, object>;
                if (item == null || string.IsNullOrWhiteSpace(
                        item.ContainsKey("plan_entity_id") ? Convert.ToString(item["plan_entity_id"]) : ""))
                {
                    throw new InvalidOperationException("拓樸計畫包含缺少識別碼的管段，請重新分析。\n");
                }
            }

            ArrayList junctions = topology.ContainsKey("junctions")
                ? topology["junctions"] as ArrayList
                : null;
            foreach (object raw in junctions ?? new ArrayList())
            {
                Dictionary<string, object> item = raw as Dictionary<string, object>;
                if (item == null || string.IsNullOrWhiteSpace(
                        item.ContainsKey("plan_entity_id") ? Convert.ToString(item["plan_entity_id"]) : ""))
                {
                    throw new InvalidOperationException("拓樸計畫包含缺少識別碼的接頭，請重新分析。\n");
                }
            }

            ArrayList reducers = topology.ContainsKey("reducers")
                ? topology["reducers"] as ArrayList
                : null;
            foreach (object raw in reducers ?? new ArrayList())
            {
                Dictionary<string, object> item = raw as Dictionary<string, object>;
                if (item == null || string.IsNullOrWhiteSpace(
                        item.ContainsKey("plan_entity_id") ? Convert.ToString(item["plan_entity_id"]) : ""))
                {
                    throw new InvalidOperationException("拓樸計畫包含缺少識別碼的異徑，請重新分析。\n");
                }
            }
        }

        private static List<FireBranchExecutionJunction> ReadFireBranchTopologyPlan(
            Dictionary<string, object> payload)
        {
            var result = new List<FireBranchExecutionJunction>();
            Dictionary<string, object> topology = GetFireBranchTopologyPlanPayload(payload);
            ArrayList rawJunctions = topology != null && topology.ContainsKey("junctions")
                ? topology["junctions"] as ArrayList
                : null;
            ArrayList rawReducers = topology != null && topology.ContainsKey("reducers")
                ? topology["reducers"] as ArrayList
                : null;
            if (rawJunctions == null)
            {
                return result;
            }
            foreach (object raw in rawJunctions)
            {
                Dictionary<string, object> item = raw as Dictionary<string, object>;
                ArrayList rows = item != null && item.ContainsKey("row_indexes")
                    ? item["row_indexes"] as ArrayList
                    : null;
                ArrayList diameters = item != null && item.ContainsKey("source_branch_diameters_mm")
                    ? item["source_branch_diameters_mm"] as ArrayList
                    : null;
                if (item == null || rows == null || rows.Count == 0)
                {
                    continue;
                }
                var plan = new FireBranchExecutionJunction
                {
                    PlanEntityId = item.ContainsKey("plan_entity_id") ? Convert.ToString(item["plan_entity_id"]) : "",
                    Kind = item.ContainsKey("kind") ? Convert.ToString(item["kind"]) : "",
                    MainDiameterFeet = UnitUtils.ConvertToInternalUnits(
                        ReadDouble(item, "main_diameter_mm", 0),
                        UnitTypeId.Millimeters),
                    CommonBranchDiameterFeet = UnitUtils.ConvertToInternalUnits(
                        ReadDouble(item, "common_branch_diameter_mm", 0),
                        UnitTypeId.Millimeters)
                };
                Dictionary<string, object> point = item.ContainsKey("point")
                    ? item["point"] as Dictionary<string, object>
                    : null;
                if (point != null)
                {
                    plan.Point = new XYZ(ReadDouble(point, "x"), ReadDouble(point, "y"), 0);
                }
                for (int index = 0; index < rows.Count; index++)
                {
                    int rowIndex = Convert.ToInt32(rows[index]);
                    plan.RowIndexes.Add(rowIndex);
                    ArrayList branchSegmentIds = item.ContainsKey("branch_segment_ids")
                        ? item["branch_segment_ids"] as ArrayList
                        : null;
                    if (branchSegmentIds != null && index < branchSegmentIds.Count)
                    {
                        string branchSegmentId = Convert.ToString(branchSegmentIds[index]);
                        if (!string.IsNullOrWhiteSpace(branchSegmentId))
                        {
                            plan.BranchPlanEntityIdByRow[rowIndex] = "segment:" + branchSegmentId;
                        }
                    }
                    if (diameters != null && index < diameters.Count && diameters[index] != null)
                    {
                        double diameterMm = Convert.ToDouble(diameters[index]);
                        plan.SourceBranchDiameterFeetByRow[rowIndex] = UnitUtils.ConvertToInternalUnits(
                            diameterMm,
                            UnitTypeId.Millimeters);
                    }
                }
                result.Add(plan);
            }
            if (rawReducers != null)
            {
                foreach (object raw in rawReducers)
                {
                    Dictionary<string, object> item = raw as Dictionary<string, object>;
                    string placement = Convert.ToString(
                        item != null && item.ContainsKey("placement") ? item["placement"] : "");
                    if (item == null
                        || (placement != "after_cross" && placement != "after_endpoint_tee"))
                    {
                        continue;
                    }
                    int rowIndex = Convert.ToInt32(ReadLong(item, "row_index", -1));
                    FireBranchExecutionJunction junction = result.FirstOrDefault(candidate =>
                        candidate.RowIndexes.Contains(rowIndex)
                        && candidate.RowIndexes.Count == 2);
                    string placementStrategy = Convert.ToString(
                        item.ContainsKey("placement_strategy") ? item["placement_strategy"] : "");
                    if (junction != null && placementStrategy == "fit_to_routing_parts")
                    {
                        junction.RoutingFitReducerRows.Add(rowIndex);
                        string reducerPlanEntityId = item.ContainsKey("plan_entity_id")
                            ? Convert.ToString(item["plan_entity_id"])
                            : "";
                        if (!string.IsNullOrWhiteSpace(reducerPlanEntityId))
                        {
                            junction.RoutingFitReducerPlanEntityIds.Add(reducerPlanEntityId);
                        }
                    }
                }
            }
            return result;
        }

        private static string FireBranchRowPairKey(IEnumerable<int> rowIndexes)
        {
            return string.Join(":", rowIndexes.OrderBy(value => value));
        }

        private static double ResolveFireBranchDiameterFeet(
            List<FireBranchDiameterPlanSegment> plan,
            int rowIndex,
            XYZ point,
            double fallbackDiameterFeet)
        {
            FireBranchDiameterPlanSegment match = plan
                .Where(item => item.RowIndex == rowIndex)
                .OrderBy(item => DistancePointToSegmentXY(point, item.Start, item.End))
                .ThenBy(item => item.Sequence)
                .FirstOrDefault();
            return match == null ? fallbackDiameterFeet : match.DiameterFeet;
        }

        private static XYZ NormalizeFireBranchPlanPoint(XYZ point, double fallbackZ)
        {
            if (point == null)
            {
                return null;
            }
            double z = Math.Abs(point.Z) <= 1e-9 ? fallbackZ : point.Z;
            return new XYZ(point.X, point.Y, z);
        }

        private static XYZ GetFireBranchPipeEndpoint(Pipe pipe, bool start)
        {
            LocationCurve location = pipe == null ? null : pipe.Location as LocationCurve;
            if (location == null || location.Curve == null)
            {
                return null;
            }
            return location.Curve.GetEndPoint(start ? 0 : 1);
        }

        private static int ResolveFireBranchPlanRowIndex(
            List<FireBranchItem> row,
            List<FireBranchDiameterPlanSegment> diameterPlan,
            int fallbackRowIndex)
        {
            var sprinklerIds = new HashSet<long>((row ?? new List<FireBranchItem>())
                .Where(item => item != null && item.Sprinkler != null)
                .Select(item => item.Sprinkler.Id.Value));
            if (sprinklerIds.Count == 0)
            {
                return fallbackRowIndex;
            }
            var match = (diameterPlan ?? new List<FireBranchDiameterPlanSegment>())
                .Where(item => item.IsSprinklerTerminal && sprinklerIds.Contains(item.SprinklerId))
                .GroupBy(item => item.RowIndex)
                .OrderByDescending(group => group.Count())
                .ThenBy(group => group.Key)
                .FirstOrDefault();
            return match == null ? fallbackRowIndex : match.Key;
        }

        private static List<Pipe> BuildFireBranchPlannedRun(
            Document doc,
            ElementId systemTypeId,
            ElementId pipeTypeId,
            ElementId levelId,
            int rowIndex,
            List<FireBranchDiameterPlanSegment> diameterPlan,
            XYZ fallbackStart,
            XYZ fallbackEnd,
            double fallbackDiameterFeet,
            double branchZ,
            List<ElementId> additionalCreatedIds)
        {
            List<FireBranchDiameterPlanSegment> planned = (diameterPlan ?? new List<FireBranchDiameterPlanSegment>())
                .Where(item => item.RowIndex == rowIndex)
                .OrderBy(item => item.Sequence)
                .ToList();
            var result = new List<Pipe>();
            foreach (FireBranchDiameterPlanSegment segment in planned)
            {
                XYZ start = NormalizeFireBranchPlanPoint(segment.Start, branchZ);
                XYZ end = NormalizeFireBranchPlanPoint(segment.End, branchZ);
                if (start == null || end == null
                    || start.DistanceTo(end) <= doc.Application.ShortCurveTolerance)
                {
                    continue;
                }
                double segmentDiameterFeet = segment.DiameterFeet > 0
                    ? segment.DiameterFeet
                    : fallbackDiameterFeet;
                Pipe pipe = CreateFirePipe(
                    doc,
                    systemTypeId,
                    pipeTypeId,
                    levelId,
                    start,
                    end,
                    segmentDiameterFeet);
                if (pipe == null)
                {
                    SetFireBranchConnectionDiagnostic(
                        "BuildFireBranchPlannedRun | planned segment creation failed | row="
                        + rowIndex + " | sequence=" + segment.Sequence);
                    return new List<Pipe>();
                }
                result.Add(pipe);
            }
            if (result.Count == 0 && fallbackStart != null && fallbackEnd != null)
            {
                Pipe fallback = CreateFirePipe(
                    doc,
                    systemTypeId,
                    pipeTypeId,
                    levelId,
                    fallbackStart,
                    fallbackEnd,
                    fallbackDiameterFeet);
                if (fallback != null)
                {
                    result.Add(fallback);
                }
            }
            if (result.Count == 0)
            {
                SetFireBranchConnectionDiagnostic(
                    "BuildFireBranchPlannedRun | no usable planned segment");
                return result;
            }

            for (int index = 1; index < result.Count; index += 1)
            {
                Pipe previous = result[index - 1];
                Pipe current = result[index];
                XYZ previousEnd = GetFireBranchPipeEndpoint(previous, false);
                XYZ currentStart = GetFireBranchPipeEndpoint(current, true);
                if (previousEnd == null || currentStart == null
                    || previousEnd.DistanceTo(currentStart) > UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Millimeters))
                {
                    SetFireBranchConnectionDiagnostic(
                        "BuildFireBranchPlannedRun | planned segments are not contiguous | row="
                        + rowIndex + " | sequence=" + index);
                    return new List<Pipe>();
                }
                XYZ joint = (previousEnd + currentStart) * 0.5;
                Connector previousConnector = FindConnectorNear(previous, joint);
                Connector currentConnector = FindConnectorNear(current, joint);
                if (previousConnector == null || currentConnector == null)
                {
                    SetFireBranchConnectionDiagnostic(
                        "BuildFireBranchPlannedRun | segment endpoint connector is missing | row="
                        + rowIndex + " | sequence=" + index);
                    return new List<Pipe>();
                }
                Parameter previousDiameter = previous.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
                Parameter currentDiameter = current.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
                double previousFeet = previousDiameter != null ? previousDiameter.AsDouble() : 0;
                double currentFeet = currentDiameter != null ? currentDiameter.AsDouble() : 0;
                try
                {
                    if (Math.Abs(previousFeet - currentFeet) <= 1e-7)
                    {
                        if (!previousConnector.IsConnectedTo(currentConnector))
                        {
                            previousConnector.ConnectTo(currentConnector);
                        }
                        doc.Regenerate();
                        if (!previousConnector.IsConnectedTo(currentConnector))
                        {
                            SetFireBranchConnectionDiagnostic(
                                "BuildFireBranchPlannedRun | same-diameter segment connection did not persist | row="
                                + rowIndex + " | sequence=" + index);
                            return new List<Pipe>();
                        }
                    }
                    else
                    {
                        FamilyInstance transition = doc.Create.NewTransitionFitting(
                            previousConnector,
                            currentConnector);
                        doc.Regenerate();
                        Connector previousTransitionConnector = transition == null
                            ? null
                            : FindConnectorDirectlyReferencingElement(previous, transition.Id);
                        Connector currentTransitionConnector = transition == null
                            ? null
                            : FindConnectorDirectlyReferencingElement(current, transition.Id);
                        if (transition == null
                            || !transition.IsValidObject
                            || previousTransitionConnector == null
                            || currentTransitionConnector == null)
                        {
                            SetFireBranchConnectionDiagnostic(
                                "BuildFireBranchPlannedRun | planned reducer creation failed | row="
                                + rowIndex + " | sequence=" + index);
                            return new List<Pipe>();
                        }
                        if (additionalCreatedIds != null)
                        {
                            additionalCreatedIds.Add(transition.Id);
                        }
                    }
                }
                catch (Exception ex)
                {
                    SetFireBranchConnectionDiagnostic(
                        "BuildFireBranchPlannedRun | segment connection failed | row="
                        + rowIndex + " | sequence=" + index,
                        ex);
                    return new List<Pipe>();
                }
            }
            return result;
        }

        private static int ApplyFireBranchDiameterPlan(
            Document doc,
            List<Pipe> branchSegments,
            List<FireBranchDiameterPlanSegment> plan,
            int rowIndex)
        {
            int applied = 0;
            foreach (Pipe pipe in branchSegments.Where(item => item != null && item.IsValidObject))
            {
                LocationCurve location = pipe.Location as LocationCurve;
                if (location == null || location.Curve == null)
                {
                    continue;
                }
                XYZ midpoint = location.Curve.Evaluate(0.5, true);
                double target = ResolveFireBranchDiameterFeet(plan, rowIndex, midpoint, 0);
                if (target <= 0)
                {
                    continue;
                }
                Parameter diameter = pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
                if (diameter == null || diameter.IsReadOnly)
                {
                    throw new InvalidOperationException("支管管徑參數無法寫入：" + pipe.Id.Value);
                }
                if (!diameter.HasValue || Math.Abs(diameter.AsDouble() - target) > 1e-7)
                {
                    diameter.Set(target);
                    applied += 1;
                }
            }
            if (applied > 0)
            {
                doc.Regenerate();
            }
            return applied;
        }

        private static ElementId PreparePlannedCrossBranchEnd(
            Document doc,
            List<Pipe> branchRun,
            int rowIndex,
            XYZ tiePoint,
            double commonDiameterFeet,
            double sourceDiameterFeet,
            List<ElementId> additionalCreatedIds,
            HashSet<long> topologyOverridePipeIds,
            out FirePendingCrossTransition pendingTransition)
        {
            pendingTransition = null;
            double endpointTolerance = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters);
            Pipe current = FindPipeEndingAtPoint(branchRun, tiePoint, endpointTolerance);
            if (current == null || commonDiameterFeet <= 0 || sourceDiameterFeet <= 0)
            {
                SetFireBranchConnectionDiagnostic("planned cross branch endpoint is missing or has invalid diameter");
                return null;
            }
            ElementId originalPipeId = current.Id;
            Parameter currentDiameter = current.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
            if (currentDiameter == null || currentDiameter.IsReadOnly)
            {
                SetFireBranchConnectionDiagnostic("planned cross branch diameter is not writable");
                return null;
            }
            if (Math.Abs(commonDiameterFeet - sourceDiameterFeet) <= 1e-7)
            {
                currentDiameter.Set(commonDiameterFeet);
                doc.Regenerate();
                return originalPipeId;
            }
            currentDiameter.Set(commonDiameterFeet);
            doc.Regenerate();
            topologyOverridePipeIds.Add(originalPipeId.Value);
            pendingTransition = new FirePendingCrossTransition
            {
                RowIndex = rowIndex,
                BranchPipeId = originalPipeId,
                CrossFittingId = ElementId.InvalidElementId,
                CommonDiameterFeet = commonDiameterFeet,
                SourceDiameterFeet = sourceDiameterFeet,
                BranchRun = branchRun,
                TopologyOverridePipeIds = topologyOverridePipeIds
            };
            return originalPipeId;
        }

        private static bool CompletePlannedCrossTransition(
            Document doc,
            FirePendingCrossTransition pendingTransition,
            List<ElementId> additionalCreatedIds)
        {
            if (pendingTransition == null)
            {
                return true;
            }
            ElementId proximalPipeId;
            ElementId distalPipeId;
            ElementId transitionId;
            double resolvedOffsetFeet;
            if (!TryCommitNearestFeasibleCrossTransition(
                doc,
                pendingTransition,
                out proximalPipeId,
                out distalPipeId,
                out transitionId,
                out resolvedOffsetFeet))
            {
                return false;
            }
            pendingTransition.ResolvedOffsetFeet = resolvedOffsetFeet;
            additionalCreatedIds.Add(proximalPipeId);
            additionalCreatedIds.Add(distalPipeId);
            additionalCreatedIds.Add(transitionId);
            pendingTransition.TopologyOverridePipeIds.Add(proximalPipeId.Value);
            var updatedIds = new HashSet<long> { proximalPipeId.Value, distalPipeId.Value };
            pendingTransition.BranchRun.RemoveAll(pipe =>
                pipe == null
                || !pipe.IsValidObject
                || updatedIds.Contains(pipe.Id.Value));
            Pipe proximal = doc.GetElement(proximalPipeId) as Pipe;
            Pipe distal = doc.GetElement(distalPipeId) as Pipe;
            if (proximal != null && proximal.IsValidObject)
            {
                pendingTransition.BranchRun.Add(proximal);
            }
            if (distal != null && distal.IsValidObject && distal.Id.Value != proximalPipeId.Value)
            {
                pendingTransition.BranchRun.Add(distal);
            }
            return true;
        }

        private static bool TryCommitNearestFeasibleCrossTransition(
            Document doc,
            FirePendingCrossTransition pendingTransition,
            out ElementId proximalPipeId,
            out ElementId distalPipeId,
            out ElementId transitionId,
            out double resolvedOffsetFeet)
        {
            proximalPipeId = ElementId.InvalidElementId;
            distalPipeId = ElementId.InvalidElementId;
            transitionId = ElementId.InvalidElementId;
            resolvedOffsetFeet = 0;
            Pipe branchPipe = doc.GetElement(pendingTransition.BranchPipeId) as Pipe;
            Connector crossConnector = FindConnectorDirectlyReferencingElement(
                branchPipe,
                pendingTransition.CrossFittingId);
            LocationCurve location = branchPipe != null ? branchPipe.Location as LocationCurve : null;
            Line line = location != null ? location.Curve as Line : null;
            if (branchPipe == null
                || !branchPipe.IsValidObject
                || crossConnector == null
                || line == null)
            {
                SetFireBranchConnectionDiagnostic("planned cross transition could not resolve the cross-connected branch pipe");
                return false;
            }
            XYZ farPoint = line.GetEndPoint(0).DistanceTo(crossConnector.Origin)
                >= line.GetEndPoint(1).DistanceTo(crossConnector.Origin)
                ? line.GetEndPoint(0)
                : line.GetEndPoint(1);
            double available = crossConnector.Origin.DistanceTo(farPoint);
            double shortCurveTolerance = doc.Application.ShortCurveTolerance;
            if (available <= shortCurveTolerance * 4.0)
            {
                SetFireBranchConnectionDiagnostic("planned cross transition has insufficient live branch length");
                return false;
            }

            double provisionalDistance = available * 0.5;
            double provisionalPipeLength;
            double provisionalTransitionLength;
            if (!TryCreateCrossTransitionAtDistance(
                doc,
                pendingTransition,
                provisionalDistance,
                false,
                out proximalPipeId,
                out distalPipeId,
                out transitionId,
                out provisionalPipeLength,
                out provisionalTransitionLength))
            {
                SetFireBranchConnectionDiagnostic("planned cross transition could not measure the selected routing parts");
                return false;
            }
            double transitionTakeout = Math.Max(0, provisionalDistance - provisionalPipeLength);
            double requiredStraightLength = Math.Max(
                shortCurveTolerance * 2.0,
                provisionalTransitionLength);
            double requestedDistance = transitionTakeout + requiredStraightLength;
            if (requestedDistance >= available - shortCurveTolerance)
            {
                SetFireBranchConnectionDiagnostic(
                    "planned cross transition has insufficient branch length for the selected transition fitting");
                return false;
            }
            double upperFeasibleDistance = provisionalDistance;
            double lowerFailedDistance = Math.Max(shortCurveTolerance, requestedDistance);
            double committedTransitionLength;
            if (TryCreateCrossTransitionAtDistance(
                doc,
                pendingTransition,
                requestedDistance,
                true,
                out proximalPipeId,
                out distalPipeId,
                out transitionId,
                out resolvedOffsetFeet,
                out committedTransitionLength))
            {
                return true;
            }

            for (int attempt = 0; attempt < 12 && upperFeasibleDistance - lowerFailedDistance > shortCurveTolerance; attempt++)
            {
                double candidate = (lowerFailedDistance + upperFeasibleDistance) * 0.5;
                double candidatePipeLength;
                ElementId candidateProximalId;
                ElementId candidateDistalId;
                ElementId candidateTransitionId;
                double candidateTransitionLength;
                if (TryCreateCrossTransitionAtDistance(
                    doc,
                    pendingTransition,
                    candidate,
                    false,
                    out candidateProximalId,
                    out candidateDistalId,
                    out candidateTransitionId,
                    out candidatePipeLength,
                    out candidateTransitionLength))
                {
                    upperFeasibleDistance = candidate;
                }
                else
                {
                    lowerFailedDistance = candidate;
                }
            }
            return TryCreateCrossTransitionAtDistance(
                doc,
                pendingTransition,
                upperFeasibleDistance,
                true,
                out proximalPipeId,
                out distalPipeId,
                out transitionId,
                out resolvedOffsetFeet,
                out committedTransitionLength);
        }

        private static bool TryCreateCrossTransitionAtDistance(
            Document doc,
            FirePendingCrossTransition pendingTransition,
            double splitDistanceFeet,
            bool commit,
            out ElementId proximalPipeId,
            out ElementId distalPipeId,
            out ElementId transitionId,
            out double resultingProximalLengthFeet,
            out double resultingTransitionLengthFeet)
        {
            proximalPipeId = ElementId.InvalidElementId;
            distalPipeId = ElementId.InvalidElementId;
            transitionId = ElementId.InvalidElementId;
            resultingProximalLengthFeet = 0;
            resultingTransitionLengthFeet = 0;
            using (SubTransaction subTransaction = new SubTransaction(doc))
            {
                try
                {
                    subTransaction.Start();
                    Pipe branchPipe = doc.GetElement(pendingTransition.BranchPipeId) as Pipe;
                    Connector crossConnector = FindConnectorDirectlyReferencingElement(
                        branchPipe,
                        pendingTransition.CrossFittingId);
                    LocationCurve location = branchPipe != null ? branchPipe.Location as LocationCurve : null;
                    Line line = location != null ? location.Curve as Line : null;
                    if (branchPipe == null || crossConnector == null || line == null)
                    {
                        subTransaction.RollBack();
                        return false;
                    }
                    XYZ farPoint = line.GetEndPoint(0).DistanceTo(crossConnector.Origin)
                        >= line.GetEndPoint(1).DistanceTo(crossConnector.Origin)
                        ? line.GetEndPoint(0)
                        : line.GetEndPoint(1);
                    double available = crossConnector.Origin.DistanceTo(farPoint);
                    double shortCurveTolerance = doc.Application.ShortCurveTolerance;
                    if (splitDistanceFeet <= shortCurveTolerance
                        || available - splitDistanceFeet <= shortCurveTolerance)
                    {
                        subTransaction.RollBack();
                        return false;
                    }
                    XYZ splitPoint = crossConnector.Origin
                        + (farPoint - crossConnector.Origin).Normalize() * splitDistanceFeet;
                    ElementId originalPipeId = branchPipe.Id;
                    ElementId newPipeId = PlumbingUtils.BreakCurve(doc, originalPipeId, splitPoint);
                    if (newPipeId == null || newPipeId == ElementId.InvalidElementId)
                    {
                        subTransaction.RollBack();
                        return false;
                    }
                    doc.Regenerate();
                    Pipe originalPipe = doc.GetElement(originalPipeId) as Pipe;
                    Pipe newPipe = doc.GetElement(newPipeId) as Pipe;
                    Pipe proximal = PipeDirectlyReferencesElement(originalPipe, pendingTransition.CrossFittingId)
                        ? originalPipe
                        : PipeDirectlyReferencesElement(newPipe, pendingTransition.CrossFittingId)
                            ? newPipe
                            : null;
                    Pipe distal = proximal != null && proximal.Id.Value == originalPipeId.Value
                        ? newPipe
                        : originalPipe;
                    if (proximal == null || distal == null)
                    {
                        subTransaction.RollBack();
                        return false;
                    }
                    Parameter proximalDiameter = proximal.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
                    Parameter distalDiameter = distal.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
                    if (proximalDiameter == null
                        || proximalDiameter.IsReadOnly
                        || distalDiameter == null
                        || distalDiameter.IsReadOnly)
                    {
                        subTransaction.RollBack();
                        return false;
                    }
                    proximalDiameter.Set(pendingTransition.CommonDiameterFeet);
                    distalDiameter.Set(pendingTransition.SourceDiameterFeet);
                    doc.Regenerate();
                    proximalPipeId = proximal.Id;
                    distalPipeId = distal.Id;
                    Connector proximalConnector = FindConnectorNear(proximal, splitPoint);
                    Connector distalConnector = FindConnectorNear(distal, splitPoint);
                    FamilyInstance transition = doc.Create.NewTransitionFitting(
                        proximalConnector,
                        distalConnector);
                    transitionId = transition != null ? transition.Id : ElementId.InvalidElementId;
                    doc.Regenerate();
                    Pipe refreshedProximal = doc.GetElement(proximalPipeId) as Pipe;
                    Pipe refreshedDistal = doc.GetElement(distalPipeId) as Pipe;
                    FamilyInstance refreshedTransition = doc.GetElement(transitionId) as FamilyInstance;
                    Connector refreshedCrossConnector = FindConnectorDirectlyReferencingElement(
                        refreshedProximal,
                        pendingTransition.CrossFittingId);
                    Connector refreshedProximalTransitionConnector = FindConnectorDirectlyReferencingElement(
                        refreshedProximal,
                        transitionId);
                    Connector refreshedDistalTransitionConnector = FindConnectorDirectlyReferencingElement(
                        refreshedDistal,
                        transitionId);
                    LocationCurve refreshedLocation = refreshedProximal != null
                        ? refreshedProximal.Location as LocationCurve
                        : null;
                    Line refreshedLine = refreshedLocation != null ? refreshedLocation.Curve as Line : null;
                    resultingProximalLengthFeet = refreshedLine != null ? refreshedLine.Length : 0;
                    List<Connector> refreshedTransitionConnectors = refreshedTransition != null
                        && refreshedTransition.MEPModel != null
                        && refreshedTransition.MEPModel.ConnectorManager != null
                        ? refreshedTransition.MEPModel.ConnectorManager.Connectors
                            .Cast<Connector>()
                            .Where(connector => connector.ConnectorType == ConnectorType.End)
                            .ToList()
                        : new List<Connector>();
                    resultingTransitionLengthFeet = refreshedTransitionConnectors.Count >= 2
                        ? refreshedTransitionConnectors
                            .SelectMany((first, firstIndex) => refreshedTransitionConnectors
                                .Skip(firstIndex + 1)
                                .Select(second => first.Origin.DistanceTo(second.Origin)))
                            .DefaultIfEmpty(0)
                            .Max()
                        : 0;
                    bool valid = refreshedTransition != null
                        && refreshedTransition.IsValidObject
                        && refreshedCrossConnector != null
                        && refreshedProximalTransitionConnector != null
                        && refreshedDistalTransitionConnector != null
                        && resultingTransitionLengthFeet > 0
                        && resultingProximalLengthFeet > shortCurveTolerance;
                    if (!valid)
                    {
                        subTransaction.RollBack();
                        return false;
                    }
                    if (commit)
                    {
                        subTransaction.Commit();
                        return true;
                    }
                    subTransaction.RollBack();
                    return true;
                }
                catch
                {
                    if (subTransaction.GetStatus() == TransactionStatus.Started)
                    {
                        subTransaction.RollBack();
                    }
                    return false;
                }
            }
        }

        private static bool PipeDirectlyReferencesElement(Pipe pipe, ElementId targetElementId)
        {
            return FindConnectorDirectlyReferencingElement(pipe, targetElementId) != null;
        }

        private static Connector FindConnectorDirectlyReferencingElement(
            Pipe pipe,
            ElementId targetElementId)
        {
            if (pipe == null
                || !pipe.IsValidObject
                || targetElementId == null
                || targetElementId == ElementId.InvalidElementId)
            {
                return null;
            }
            return pipe.ConnectorManager.Connectors
                .Cast<Connector>()
                .FirstOrDefault(connector => ConnectorDirectlyReferencesElement(connector, targetElementId));
        }

        private static List<long> FindFireBranchDiameterPlanMismatches(
            Dictionary<int, List<Pipe>> branchSegmentsByRow,
            List<FireBranchDiameterPlanSegment> plan,
            HashSet<long> topologyOverridePipeIds)
        {
            var result = new List<long>();
            foreach (KeyValuePair<int, List<Pipe>> row in branchSegmentsByRow)
            {
                foreach (Pipe pipe in row.Value.Where(item => item != null && item.IsValidObject))
                {
                    if (topologyOverridePipeIds.Contains(pipe.Id.Value))
                    {
                        continue;
                    }
                    LocationCurve location = pipe.Location as LocationCurve;
                    Parameter diameter = pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
                    if (location == null || location.Curve == null || diameter == null || !diameter.HasValue)
                    {
                        result.Add(pipe.Id.Value);
                        continue;
                    }
                    XYZ midpoint = location.Curve.Evaluate(0.5, true);
                    double expected = ResolveFireBranchDiameterFeet(plan, row.Key, midpoint, 0);
                    if (expected > 0 && Math.Abs(diameter.AsDouble() - expected) > 1e-7)
                    {
                        result.Add(pipe.Id.Value);
                    }
                }
            }
            return result.Distinct().ToList();
        }

        private static void ValidateFireBranchJunctionRouting(
            PipeType pipeType,
            List<FireBranchDiameterPlanSegment> plan,
            List<FireBranchExecutionJunction> topologyPlan,
            IEnumerable<FamilyInstance> sprinklers)
        {
            if (plan.Count == 0)
            {
                return;
            }
            RoutingPreferenceManager manager = pipeType.RoutingPreferenceManager;
            if (manager == null
                || manager.GetNumberOfRules(RoutingPreferenceRuleGroupType.Junctions) == 0)
            {
                throw new InvalidOperationException(
                    "選取的管類型沒有三通 Routing Preferences，無法建立一般或異徑三通。");
            }
            double sprinklerDropFeet = UnitUtils.ConvertToInternalUnits(
                FireSprinklerDropDiameterMillimeters,
                UnitTypeId.Millimeters);
            bool needsTransition = plan.Any(item => Math.Abs(item.DiameterFeet - sprinklerDropFeet) > 1e-7)
                || (sprinklers ?? Enumerable.Empty<FamilyInstance>()).Any(instance =>
                {
                    Connector connector = FindConnectorNear(instance, GetFamilyConnectionPoint(instance));
                    return connector != null
                        && Math.Abs(connector.Radius * 2.0 - sprinklerDropFeet) > 1e-7;
                });
            if (needsTransition
                && manager.GetNumberOfRules(RoutingPreferenceRuleGroupType.Transitions) == 0)
            {
                throw new InvalidOperationException(
                    "選取的管類型沒有變徑接頭 Routing Preferences，無法由支管管徑轉接至灑水頭 DN25 垂管。");
            }
            Action<double, double, string> requireTransition = (firstDiameterFeet, secondDiameterFeet, context) =>
            {
                if (Math.Abs(firstDiameterFeet - secondDiameterFeet) <= 1e-7)
                {
                    return;
                }
                using (RoutingConditions conditions = new RoutingConditions(
                    RoutingPreferenceErrorLevel.None))
                {
                    conditions.AppendCondition(new RoutingCondition(firstDiameterFeet));
                    conditions.AppendCondition(new RoutingCondition(secondDiameterFeet));
                    ElementId transitionPartId = manager.GetMEPPartId(
                        RoutingPreferenceRuleGroupType.Transitions,
                        conditions);
                    if (transitionPartId == null || transitionPartId == ElementId.InvalidElementId)
                    {
                        throw new InvalidOperationException(
                            "管類型的變徑 Routing Preferences 不支援" + context + "所需的管徑組合。");
                    }
                }
            };
            foreach (IGrouping<int, FireBranchDiameterPlanSegment> row in plan
                .GroupBy(item => item.RowIndex))
            {
                List<FireBranchDiameterPlanSegment> ordered = row
                    .OrderBy(item => item.Sequence)
                    .ToList();
                for (int index = 1; index < ordered.Count; index += 1)
                {
                    requireTransition(
                        ordered[index - 1].DiameterFeet,
                        ordered[index].DiameterFeet,
                        "支管分段");
                }
            }
            foreach (double plannedDiameterFeet in plan
                .Select(item => item.DiameterFeet)
                .Where(value => value > 0)
                .Distinct())
            {
                requireTransition(plannedDiameterFeet, sprinklerDropFeet, "支管至 DN25 垂管");
            }
            foreach (FamilyInstance sprinkler in sprinklers ?? Enumerable.Empty<FamilyInstance>())
            {
                Connector connector = FindConnectorNear(sprinkler, GetFamilyConnectionPoint(sprinkler));
                if (connector != null && connector.Radius > 0)
                {
                    requireTransition(
                        sprinklerDropFeet,
                        connector.Radius * 2.0,
                        "DN25 垂管至灑水頭 Connector");
                }
            }
            List<FireBranchExecutionJunction> crosses = (topologyPlan
                ?? new List<FireBranchExecutionJunction>())
                .Where(item => item.RowIndexes.Count == 2)
                .ToList();
            if (crosses.Count == 0)
            {
                return;
            }
            if (manager.GetNumberOfRules(RoutingPreferenceRuleGroupType.Crosses) == 0)
            {
                throw new InvalidOperationException(
                    "選取的管類型沒有四通 Routing Preferences，無法建立主管與雙側支管交點。");
            }
            foreach (FireBranchExecutionJunction junction in crosses)
            {
                if (junction.MainDiameterFeet <= 0 || junction.CommonBranchDiameterFeet <= 0)
                {
                    throw new InvalidOperationException("四通拓樸計畫缺少主管或支管管徑。");
                }
                using (RoutingConditions conditions = new RoutingConditions(
                    RoutingPreferenceErrorLevel.None))
                {
                    conditions.AppendCondition(new RoutingCondition(junction.MainDiameterFeet));
                    conditions.AppendCondition(new RoutingCondition(junction.MainDiameterFeet));
                    conditions.AppendCondition(new RoutingCondition(junction.CommonBranchDiameterFeet));
                    conditions.AppendCondition(new RoutingCondition(junction.CommonBranchDiameterFeet));
                    ElementId crossPartId = manager.GetMEPPartId(
                        RoutingPreferenceRuleGroupType.Crosses,
                        conditions);
                    if (crossPartId == null || crossPartId == ElementId.InvalidElementId)
                    {
                        throw new InvalidOperationException(
                            "管類型的四通 Routing Preferences 不支援目前主管與支管管徑組合。");
                    }
                }
                foreach (double sourceDiameterFeet in junction.SourceBranchDiameterFeetByRow.Values
                    .Where(value => value > 0
                        && Math.Abs(value - junction.CommonBranchDiameterFeet) > 1e-7)
                    .Distinct())
                {
                    requireTransition(
                        junction.CommonBranchDiameterFeet,
                        sourceDiameterFeet,
                        "四通出口至支管");
                }
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
                Pipe pipe = CreateFirePipe(
                    doc,
                    systemTypeId,
                    pipeTypeId,
                    levelId,
                    startConnector.Origin,
                    end,
                    diameterFeet);
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
                    SetFireBranchConnectionDiagnostic(
                        "CreateFireDropForSystem | explicit system type did not persist after sprinkler connection");
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

        private static bool TryConnectCompletedDropToSprinkler(
            Document doc,
            Pipe drop,
            ElementId sprinklerId,
            XYZ sprinklerPoint)
        {
            if (drop == null || !drop.IsValidObject)
            {
                SetFireBranchConnectionDiagnostic("TryConnectCompletedDropToSprinkler | drop is missing");
                return false;
            }
            try
            {
                ElementId dropId = drop.Id;
                doc.Regenerate();
                Pipe currentDrop = doc.GetElement(dropId) as Pipe;
                FamilyInstance currentSprinkler = doc.GetElement(sprinklerId) as FamilyInstance;
                Connector dropConnector = FindConnectorNear(currentDrop, sprinklerPoint);
                Connector sprinklerConnector = FindConnectorNear(currentSprinkler, sprinklerPoint);
                if (dropConnector == null || sprinklerConnector == null)
                {
                    SetFireBranchConnectionDiagnostic(
                        "TryConnectCompletedDropToSprinkler | endpoint connector is missing");
                    return false;
                }
                bool physicallyReachable = IsPhysicallyReachableFromFireElement(
                    doc,
                    currentSprinkler.Id,
                    new HashSet<long> { currentDrop.Id.Value });
                if (!physicallyReachable)
                {
                    string dropReferenceIds = string.Join(",", dropConnector.AllRefs
                        .Cast<Connector>()
                        .Where(reference => reference != null && reference.Owner != null)
                        .Select(reference => reference.Owner.Id.Value)
                        .Distinct());
                    string sprinklerReferenceIds = string.Join(",", sprinklerConnector.AllRefs
                        .Cast<Connector>()
                        .Where(reference => reference != null && reference.Owner != null)
                        .Select(reference => reference.Owner.Id.Value)
                        .Distinct());
                    SetFireBranchConnectionDiagnostic(
                        "TryConnectCompletedDropToSprinkler | physical connector verification failed"
                        + " | endpoint_distance_mm="
                        + UnitUtils.ConvertFromInternalUnits(
                            dropConnector.Origin.DistanceTo(sprinklerConnector.Origin),
                            UnitTypeId.Millimeters).ToString("0.###")
                        + " | drop_is_connected=" + dropConnector.IsConnected
                        + " | sprinkler_is_connected=" + sprinklerConnector.IsConnected
                        + " | drop_refs=" + dropReferenceIds
                        + " | sprinkler_refs=" + sprinklerReferenceIds);
                    return false;
                }
                return true;
            }
            catch (Exception ex)
            {
                SetFireBranchConnectionDiagnostic("TryConnectCompletedDropToSprinkler", ex);
                return false;
            }
        }

        private static FireDropAssembly CreateFireDropWithTransition(
            Document doc,
            ElementId systemTypeId,
            ElementId pipeTypeId,
            ElementId levelId,
            ElementId sprinklerId,
            XYZ sprinklerPoint,
            XYZ tapPoint,
            double branchDiameterFeet,
            List<Pipe> branchSegments)
        {
            FamilyInstance currentSprinkler = doc.GetElement(sprinklerId) as FamilyInstance;
            Connector sprinklerConnector = FindConnectorNear(currentSprinkler, sprinklerPoint);
            if (sprinklerConnector == null || branchSegments == null || branchSegments.Count == 0)
            {
                SetFireBranchConnectionDiagnostic("CreateFireDropWithTransition | missing sprinkler connector or branch run");
                return null;
            }

            double dropDiameterFeet = UnitUtils.ConvertToInternalUnits(
                FireSprinklerDropDiameterMillimeters,
                UnitTypeId.Millimeters);
            double availableLength = sprinklerPoint.DistanceTo(tapPoint);
            if (availableLength < UnitUtils.ConvertToInternalUnits(30, UnitTypeId.Millimeters))
            {
                SetFireBranchConnectionDiagnostic("CreateFireDropWithTransition | insufficient vertical clearance");
                return null;
            }
            var assembly = new FireDropAssembly();
            XYZ dropStart = tapPoint;
            Pipe drop = CreateFireDropForSystem(
                doc,
                systemTypeId,
                pipeTypeId,
                levelId,
                sprinklerConnector,
                dropStart,
                dropDiameterFeet);
            if (drop == null)
            {
                SetFireBranchConnectionDiagnostic("CreateFireDropWithTransition | DN25 drop creation failed");
                return null;
            }
            assembly.Pipes.Add(drop);

            Pipe branchConnectionPipe = drop;

            Pipe sprinklerConnectionPipe = drop;

            if (!TryConnectPipeToRun(doc, branchSegments, branchConnectionPipe, tapPoint))
            {
                SetFireBranchConnectionDiagnostic("CreateFireDropWithTransition | branch tee verification failed");
                return null;
            }

            doc.Regenerate();
            Pipe currentBranchConnection = doc.GetElement(branchConnectionPipe.Id) as Pipe;
            if (currentBranchConnection == null || !currentBranchConnection.IsValidObject)
            {
                SetFireBranchConnectionDiagnostic(
                    "CreateFireDropWithTransition | explicit-system DN25 drop was deleted during tee creation");
                return null;
            }

            branchConnectionPipe = currentBranchConnection;
            sprinklerConnectionPipe = currentBranchConnection;
            assembly.Pipes.Clear();
            assembly.Pipes.Add(currentBranchConnection);
            assembly.BranchConnectionPipe = branchConnectionPipe;
            assembly.SprinklerConnectionPipe = sprinklerConnectionPipe;
            return assembly;
        }

        private static List<ElementId> ResolveConnectedFireSystemIds(
            Document doc,
            IEnumerable<ElementId> elementIds)
        {
            var systemIds = new List<ElementId>();
            foreach (ElementId elementId in elementIds
                .Where(id => id != null && id != ElementId.InvalidElementId)
                .GroupBy(id => id.Value)
                .Select(group => group.First()))
            {
                Element element = doc.GetElement(elementId);
                Pipe pipe = element as Pipe;
                if (pipe != null)
                {
                    MEPSystem pipeSystem = pipe.MEPSystem;
                    if (pipeSystem != null
                        && pipeSystem.IsValidObject
                        && !systemIds.Any(id => id.Value == pipeSystem.Id.Value))
                    {
                        systemIds.Add(pipeSystem.Id);
                    }
                    continue;
                }

                FamilyInstance instance = element as FamilyInstance;
                ConnectorManager connectorManager = instance != null && instance.MEPModel != null
                    ? instance.MEPModel.ConnectorManager
                    : null;
                if (connectorManager == null)
                {
                    continue;
                }
                foreach (Connector connector in connectorManager.Connectors.Cast<Connector>())
                {
                    MEPSystem connectorSystem = connector.MEPSystem;
                    if (connectorSystem != null
                        && connectorSystem.IsValidObject
                        && !systemIds.Any(id => id.Value == connectorSystem.Id.Value))
                    {
                        systemIds.Add(connectorSystem.Id);
                    }
                }
            }
            return systemIds;
        }

        private static ConnectorSet GetFirePhysicalConnectors(Element element)
        {
            MEPCurve curve = element as MEPCurve;
            if (curve != null)
            {
                return curve.ConnectorManager.Connectors;
            }
            FamilyInstance instance = element as FamilyInstance;
            return instance != null && instance.MEPModel != null
                ? instance.MEPModel.ConnectorManager.Connectors
                : null;
        }

        private static bool IsPhysicallyReachableFromFireElement(
            Document doc,
            ElementId startId,
            HashSet<long> targetPipeIds)
        {
            if (startId == null || startId == ElementId.InvalidElementId || targetPipeIds.Count == 0)
            {
                return false;
            }
            var pending = new Queue<ElementId>();
            var visited = new HashSet<long>();
            pending.Enqueue(startId);
            while (pending.Count > 0 && visited.Count < 2000)
            {
                ElementId currentId = pending.Dequeue();
                if (currentId == null || !visited.Add(currentId.Value))
                {
                    continue;
                }
                if (targetPipeIds.Contains(currentId.Value))
                {
                    return true;
                }
                Element current = doc.GetElement(currentId);
                ConnectorSet connectors = current == null ? null : GetFirePhysicalConnectors(current);
                if (connectors == null)
                {
                    continue;
                }
                foreach (Connector connector in connectors.Cast<Connector>())
                {
                    foreach (Connector reference in connector.AllRefs.Cast<Connector>())
                    {
                        Element owner = reference == null ? null : reference.Owner;
                        if (owner == null
                            || owner is MEPSystem
                            || reference.ConnectorType == ConnectorType.Logical
                            || visited.Contains(owner.Id.Value))
                        {
                            continue;
                        }
                        pending.Enqueue(owner.Id);
                    }
                }
            }
            return false;
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
                                // A new selection invalidates the previous DirectContext preview.
                                DrainagePreviewServer.Clear(doc);
                                if (uiApp.ActiveUIDocument != null)
                                {
                                    uiApp.ActiveUIDocument.RefreshActiveView();
                                }
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

            if (action == "read_fire_branch_snapshot")
                            {
                                WriteFireBranchSnapshotResponse(uiApp, payload, responseFile, serializer);
                                return;
                            }

            if (action == "focus_fire_branch_preview_segment")
                            {
                                UIDocument uiDocument = uiApp.ActiveUIDocument;
                                if (uiDocument == null || uiDocument.ActiveGraphicalView == null)
                                {
                                    throw new InvalidOperationException("目前沒有可定位的 Revit 圖形視圖。");
                                }
                                Dictionary<string, object> startData = payload.ContainsKey("start")
                                    ? payload["start"] as Dictionary<string, object>
                                    : null;
                                Dictionary<string, object> endData = payload.ContainsKey("end")
                                    ? payload["end"] as Dictionary<string, object>
                                    : null;
                                if (startData == null || endData == null)
                                {
                                    throw new InvalidOperationException("預覽管段缺少起點或終點座標。");
                                }
                                double displayZ = ReadDouble(
                                    payload,
                                    "display_z",
                                    ReadDouble(startData, "z"));
                                XYZ start = new XYZ(
                                    ReadDouble(startData, "x"),
                                    ReadDouble(startData, "y"),
                                    displayZ);
                                XYZ end = new XYZ(
                                    ReadDouble(endData, "x"),
                                    ReadDouble(endData, "y"),
                                    displayZ);
                                View activeView = uiDocument.ActiveGraphicalView;
                                UIView uiView = uiDocument.GetOpenUIViews()
                                    .FirstOrDefault(item => item.ViewId.Value == activeView.Id.Value);
                                if (uiView == null)
                                {
                                    throw new InvalidOperationException("目前圖形視圖沒有可用的 Revit 視窗。");
                                }

                                double padding = UnitUtils.ConvertToInternalUnits(
                                    Math.Max(100, ReadDouble(payload, "padding_mm", 750)),
                                    UnitTypeId.Millimeters);
                                XYZ center = (start + end) * 0.5;
                                XYZ delta = end - start;
                                XYZ right = activeView.RightDirection.Normalize();
                                XYZ up = activeView.UpDirection.Normalize();
                                double halfWidth = Math.Max(
                                    padding,
                                    Math.Abs(delta.DotProduct(right)) * 0.5 + padding);
                                double halfHeight = Math.Max(
                                    padding,
                                    Math.Abs(delta.DotProduct(up)) * 0.5 + padding);
                                XYZ corner1 = center - right * halfWidth - up * halfHeight;
                                XYZ corner2 = center + right * halfWidth + up * halfHeight;
                                uiView.ZoomAndCenterRectangle(corner1, corner2);
                                uiDocument.RefreshActiveView();

                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        focused = true,
                                        view_id = activeView.Id.Value,
                                        padding_mm = padding * 304.8
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
                                string sourceMode = payload.ContainsKey("source_mode") && payload["source_mode"] != null
                                    ? payload["source_mode"].ToString().Trim().ToLowerInvariant()
                                    : "cad";
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
                                List<object> cadRouteAssignments;
                                List<FireBranchItem> sprinklerData = sourceMode == "uniform"
                                    ? BuildLegacyUniformFireBranchItems(
                                        sprinklers,
                                        sprinklerPoints,
                                        mainPipes,
                                        skipped,
                                        out cadRouteAssignments)
                                    : BuildFireBranchItemsFromCadEvidence(
                                        doc,
                                        sprinklers,
                                        sprinklerPoints,
                                        mainPipes,
                                        branchZ,
                                        skipped,
                                        out cadRouteAssignments);
                                if (sprinklerData.Count == 0)
                                {
                                    throw new InvalidOperationException(sourceMode == "uniform"
                                        ? "選取撒水頭都無法投影到主管，請改選主管或縮小撒水頭範圍。"
                                        : "沒有任何灑水頭取得足夠的 CAD 路徑證據，請查看主管候選與 CAD 對位診斷。");
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
                                    mainPipes,
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
                                View activeView = doc.ActiveView;
                                XYZ activeViewRight = activeView.RightDirection.Normalize();
                                XYZ activeViewUp = activeView.UpDirection.Normalize();
                                XYZ activeViewDirection = activeView.ViewDirection.Normalize();

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
                                        main_pipe_ids = mainPipes.Select(item => item.PipeId).ToList(),
                                        excluded_main_count = excludedMainCount,
                                        row_count = plannedRowCount,
                                        estimated_pipe_count = estimatedPipeCount,
                                        max_branch_length_m = maxBranchLengthMeters,
                                        cad_path_check = cadPathCheck,
                                        cad_route_assignments = cadRouteAssignments,
                                        skipped = skipped,
                                        group_id = previewGroupId,
                                        group_name = previewGroupName,
                                        preview_snapshot_id = batchId,
                                        preview_rendering = "direct_context_3d",
                                        preview_server_active = DrainagePreviewServer.IsRegisteredAndActive(),
                                        direct_preview_segment_count = directPreviewSegments.Count,
                                        preview_display_z = previewDisplayZ,
                                        view_orientation = new
                                        {
                                            source = "revit_view",
                                            view_id = activeView.Id.Value,
                                            view_name = activeView.Name,
                                            right = SerializeCadPathPoint(activeViewRight),
                                            up = SerializeCadPathPoint(activeViewUp),
                                            direction = SerializeCadPathPoint(activeViewDirection)
                                        }
                                    })
                                );
                                return;
                            }

            if (action == "create_fire_branch_pipes" || action == "test_fire_branch_pipes")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                long pipeTypeId = ReadLong(payload, "pipe_type_id");
                                long systemTypeId = ReadLong(payload, "system_type_id");
                                long selectedLevelId = ReadLong(payload, "level_id", 0);
                                double diameterMm = ReadDouble(payload, "diameter_mm", 25);
                                List<FireBranchDiameterPlanSegment> diameterPlan = ReadFireBranchDiameterPlan(payload);
                                List<FireBranchExecutionJunction> topologyPlan = ReadFireBranchTopologyPlan(payload);
                                double branchOffsetCm = ReadDouble(payload, "branch_offset_cm", 0);
                                long previewGroupId = ReadLong(payload, "preview_group_id", 0);
                                bool isSandboxAction = action == "test_fire_branch_pipes";
                                string sandboxScope = payload.ContainsKey("sandbox_scope") && payload["sandbox_scope"] != null
                                    ? payload["sandbox_scope"].ToString().Trim().ToLowerInvariant()
                                    : "";
                                string previewSnapshotId = payload.ContainsKey("preview_snapshot_id") && payload["preview_snapshot_id"] != null
                                    ? payload["preview_snapshot_id"].ToString().Trim()
                                    : "";
                                int pilotSourceRowIndex = Convert.ToInt32(ReadLong(payload, "pilot_source_row_index", -1));
                                bool requireDiameterPlan = ReadBool(payload, "require_diameter_plan", false);
                                string modelPlanHash = payload.ContainsKey("model_plan_hash") && payload["model_plan_hash"] != null
                                    ? payload["model_plan_hash"].ToString().Trim()
                                    : "";
                                string executionMode = payload.ContainsKey("execution_mode") && payload["execution_mode"] != null
                                    ? payload["execution_mode"].ToString().Trim().ToLowerInvariant()
                                    : (isSandboxAction ? "sandbox" : "commit");
                                string sourceMode = payload.ContainsKey("source_mode") && payload["source_mode"] != null
                                    ? payload["source_mode"].ToString().Trim().ToLowerInvariant()
                                    : "cad";
                                if (executionMode != "commit" && executionMode != "sandbox")
                                {
                                    throw new InvalidOperationException("Unsupported fire branch execution mode: " + executionMode);
                                }
                                if (isSandboxAction != (executionMode == "sandbox"))
                                {
                                    throw new InvalidOperationException("Fire branch action and execution mode do not match.");
                                }
                                bool isSandbox = isSandboxAction;
                                bool topologyOnlySandbox = isSandbox && sandboxScope == "topology_only";
                                if (sandboxScope == "topology_only" && !isSandbox)
                                {
                                    throw new InvalidOperationException(
                                        "拓樸管段檢查只能使用可回復沙盒模式。\n");
                                }
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

                                if (sandboxScope == "single_sprinkler")
                                {
                                    if (!isSandbox
                                        || sprinklerIdsRaw.Count != 1
                                        || sprinklers.Count != 1
                                        || string.IsNullOrWhiteSpace(previewSnapshotId)
                                        || pilotSourceRowIndex < 0
                                        || !requireDiameterPlan
                                        || !Regex.IsMatch(modelPlanHash, "^[0-9a-fA-F]{64}$"))
                                    {
                                        throw new InvalidOperationException(
                                            "單一灑水頭測試資料不完整，請重新分析後再由清單選取一顆灑水頭測試。");
                                    }
                                    if (diameterPlan.Count == 0
                                        || diameterPlan.Any(item => item.RowIndex != pilotSourceRowIndex))
                                    {
                                        throw new InvalidOperationException(
                                            "單一灑水頭測試的管徑規劃與預覽列不一致，請重新分析。");
                                    }
                                }
                                else if (requireDiameterPlan && diameterPlan.Count == 0)
                                {
                                    throw new InvalidOperationException("此建立要求必須包含已確認的管徑規劃。");
                                }
                                if (requireDiameterPlan && !Regex.IsMatch(modelPlanHash, "^[0-9a-fA-F]{64}$"))
                                {
                                    throw new InvalidOperationException("此建立要求缺少完整拓樸計畫雜湊，請重新分析。");
                                }
                                ValidateFireBranchTopologyPlanIdentity(payload, requireDiameterPlan);

                                if (!topologyOnlySandbox)
                                {
                                    ValidateFireBranchJunctionRouting(
                                        pipeType,
                                        diameterPlan,
                                        topologyPlan,
                                        sprinklers);
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
                                List<object> cadRouteAssignments;
                                List<FireBranchItem> sprinklerData = sourceMode == "uniform"
                                    ? BuildLegacyUniformFireBranchItems(
                                        sprinklers,
                                        sprinklerPoints,
                                        mainPipes,
                                        skipped,
                                        out cadRouteAssignments)
                                    : BuildFireBranchItemsFromCadEvidence(
                                        doc,
                                        sprinklers,
                                        sprinklerPoints,
                                        mainPipes,
                                        branchZ,
                                        skipped,
                                        out cadRouteAssignments);
                                if (sprinklerData.Count == 0)
                                {
                                    throw new InvalidOperationException(sourceMode == "uniform"
                                        ? "選取撒水頭都無法投影到主管，請改選主管或縮小撒水頭範圍。"
                                        : "沒有任何灑水頭取得足夠的 CAD 路徑證據，請重新分析主管候選與 CAD 對位。");
                                }
                                List<FamilyInstance> plannedSprinklers = sprinklerData
                                    .Select(item => item.Sprinkler)
                                    .Where(instance => instance != null)
                                    .GroupBy(instance => instance.Id.Value)
                                    .Select(group => group.First())
                                    .ToList();
                                var rows = BuildFireBranchRows(sprinklerData, rowTolerance);
                                var legacyJunctionPlans = BuildFireBranchJunctionPlans(rows, junctionTolerance, branchZ);
                                var topologyJunctionPlans = requireDiameterPlan
                                    ? BuildFireBranchTopologyJunctionPlans(rows, topologyPlan)
                                    : new List<FireBranchJunctionPlan>();
                                var junctionPlans = requireDiameterPlan
                                    ? MergeFireBranchTopologyJunctionPlans(
                                        legacyJunctionPlans,
                                        topologyJunctionPlans,
                                        rows)
                                    : legacyJunctionPlans;
                                var executionCrossPlans = topologyPlan
                                    .Where(item => item.RowIndexes.Count == 2
                                        && (item.Kind == "cross"
                                            || item.Kind == "reducing_cross"
                                            || item.Kind == "endpoint_tee"
                                            || item.Kind == "reducing_endpoint_tee"))
                                    .ToDictionary(item => FireBranchRowPairKey(item.RowIndexes), item => item);
                                var executionCrossByRowIndex = executionCrossPlans.Values
                                    .SelectMany(item => item.RowIndexes.Select(rowIndex => new { rowIndex, item }))
                                    .ToDictionary(pair => pair.rowIndex, pair => pair.item);
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
                                List<long> originalMainPipeIds = mainPipes.Select(item => item.PipeId).Distinct().ToList();
                                var originalSprinklerPoints = sprinklers.ToDictionary(
                                    item => item.Id.Value,
                                    item => GetFamilyConnectionPoint(item));
                                var originalSprinklerConnected = sprinklers.ToDictionary(
                                    item => item.Id.Value,
                                    item =>
                                    {
                                        Connector connector = FindConnectorNear(item, GetFamilyConnectionPoint(item));
                                        return connector != null && connector.IsConnected;
                                    });
                                var originalSprinklerSystemTypeIds = sprinklers.ToDictionary(
                                    item => item.Id.Value,
                                    item =>
                                    {
                                        Connector connector = FindConnectorNear(item, GetFamilyConnectionPoint(item));
                                        return connector != null && connector.MEPSystem != null
                                            ? connector.MEPSystem.GetTypeId().Value
                                            : 0L;
                                    });
                                bool restorationVerified = false;
                                var residualCreatedElementIds = new List<long>();
                                var createdPipeRoles = new Dictionary<long, string>();
                                var created = new List<object>();
                                var resolvedCrossTransitions = new List<object>();
                                var failed = new List<object>();
                                var junctions = junctionPlans.Select(plan => new
                                {
                                    main_pipe_id = plan.MainPipeId,
                                    main_parameter = plan.MainParameter,
                                    topology = plan.Topology.ToString(),
                                    row_count = plan.Rows.Count
                                }).ToList();
                                string batchId = DateTime.Now.ToString("yyyyMMdd-HHmmss");
                                int variableDiameterApplied = 0;
                                long deletedPreviewGroupId = 0;
                                string fireBranchStage = "initialize";
                                bool partialFailureKept = false;
                                bool sandboxRolledBackEarly = false;
                                string retentionDecision = "not_required";
                                int verifiedConnectedSprinklerCount = plannedSprinklers.Count;
                                int verifiedUnconnectedSprinklerCount = 0;
                                var evidenceElementIds = new List<long>();

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
                                    var mainSegmentsByPipeId = mainPipes.ToDictionary(
                                        item => item.PipeId,
                                        item => new List<Pipe> { item.Pipe });
                                    var branchSegmentsByRow = new Dictionary<int, List<Pipe>>();
                                    var topologyOverridePipeIds = new HashSet<long>();
                                    try
                                    {
                                    fireBranchStage = "geometry_creation";
                                    using (Transaction creationTransaction = new Transaction(doc, "SC \u5efa\u7acb\u6d88\u9632\u652f\u7ba1\u5e7e\u4f55"))
                                    {
                                    FireBranchSandboxFailurePreprocessor creationFailurePreprocessor = null;
                                    if (isSandbox)
                                    {
                                        creationFailurePreprocessor = new FireBranchSandboxFailurePreprocessor();
                                        FailureHandlingOptions options = creationTransaction.GetFailureHandlingOptions();
                                        options.SetFailuresPreprocessor(creationFailurePreprocessor);
                                        options.SetClearAfterRollback(true);
                                        creationTransaction.SetFailureHandlingOptions(options);
                                    }
                                    TransactionStatus creationStartStatus = creationTransaction.Start();
                                    if (creationStartStatus != TransactionStatus.Started)
                                    {
                                        throw new InvalidOperationException("Fire branch geometry transaction did not start: " + creationStartStatus);
                                    }
                                    var junctionPlanByRow = junctionPlans
                                        .SelectMany(plan => plan.Rows.Select(row => new { row, plan }))
                                        .ToDictionary(item => item.row, item => item.plan);
                                    var crossBranchSegmentsByPlan = new Dictionary<FireBranchJunctionPlan, List<List<Pipe>>>();
                                    var attemptedCrossPlans = new HashSet<FireBranchJunctionPlan>();
                                    var offsetFeedersByPlan = new Dictionary<FireBranchJunctionPlan, Pipe>();
                                    var offsetBranchesByPlan = new Dictionary<FireBranchJunctionPlan, List<Pipe>>();
                                    var attemptedOffsetPlans = new HashSet<FireBranchJunctionPlan>();
                                    var pendingSprinklerConnections = new List<FirePendingSprinklerConnection>();
                                    for (int fireBranchRowIndex = 0; fireBranchRowIndex < rows.Count; fireBranchRowIndex++)
                                    {
                                        var row = rows[fireBranchRowIndex];
                                        int diameterPlanRowIndex = sandboxScope == "single_sprinkler"
                                            ? pilotSourceRowIndex
                                            : ResolveFireBranchPlanRowIndex(
                                                row,
                                                diameterPlan,
                                                fireBranchRowIndex);
                                        List<FireBranchDiameterPlanSegment> plannedRowSegments = (diameterPlan ?? new List<FireBranchDiameterPlanSegment>())
                                            .Where(item => item.RowIndex == diameterPlanRowIndex)
                                            .OrderBy(item => item.Sequence)
                                            .ToList();
                                        FireBranchJunctionPlan junctionPlan = junctionPlanByRow[row];
                                        bool isOppositeSideCross = junctionPlan.Topology == FireBranchJunctionTopology.OppositeSidesSameElevation;
                                        bool isOppositeSideOffset = junctionPlan.Topology == FireBranchJunctionTopology.OppositeSidesOffsetElevation;
                                        XYZ mainStart = row[0].MainStart;
                                        XYZ mainDirection = row[0].MainDirection;
                                        FireBranchExecutionJunction executionRowCross = null;
                                        executionCrossByRowIndex.TryGetValue(fireBranchRowIndex, out executionRowCross);
                                        double rowMain = isOppositeSideCross
                                            && executionRowCross != null
                                            && executionRowCross.Point != null
                                            ? new XYZ(
                                                executionRowCross.Point.X - mainStart.X,
                                                executionRowCross.Point.Y - mainStart.Y,
                                                0).DotProduct(mainDirection)
                                            : (isOppositeSideCross || isOppositeSideOffset
                                                ? junctionPlan.MainParameter
                                                : row.Average(item => item.MainParameter));
                                        double rowMin = isOppositeSideCross || isOppositeSideOffset
                                            ? 0
                                            : 0 - extension;
                                        double rowMax = row.Max(item => item.BranchParameter) + extension;
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
                                        if (plannedRowSegments.Count > 0)
                                        {
                                            XYZ plannedStart = NormalizeFireBranchPlanPoint(
                                                plannedRowSegments.First().Start,
                                                branchZ);
                                            XYZ plannedEnd = NormalizeFireBranchPlanPoint(
                                                plannedRowSegments.Last().End,
                                                branchZ);
                                            if (plannedStart != null && plannedEnd != null)
                                            {
                                                branchTie = plannedStart;
                                                mainTie = new XYZ(plannedStart.X, plannedStart.Y, mainZ);
                                                branchStart = plannedStart;
                                                branchEnd = plannedEnd;
                                            }
                                        }
                                        double rowDiameterFeet = ResolveFireBranchDiameterFeet(
                                            diameterPlan,
                                            diameterPlanRowIndex,
                                            branchStart,
                                            diameterFeet);

                                        Pipe feeder = null;
                                        if (mainTie.DistanceTo(branchTie) > 0.01)
                                        {
                                            if (isOppositeSideOffset)
                                            {
                                                if (!offsetFeedersByPlan.TryGetValue(junctionPlan, out feeder))
                                                {
                                                    feeder = CreateFirePipe(doc, systemType.Id, pipeType.Id, levelId, mainTie, branchTie, rowDiameterFeet);
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
                                                feeder = CreateFirePipe(doc, systemType.Id, pipeType.Id, levelId, mainTie, branchTie, rowDiameterFeet);
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

                                        var branchSegments = BuildFireBranchPlannedRun(
                                            doc,
                                            systemType.Id,
                                            pipeType.Id,
                                            levelId,
                                            diameterPlanRowIndex,
                                            diameterPlan,
                                            branchStart,
                                            branchEnd,
                                            rowDiameterFeet,
                                            branchZ,
                                            additionalCreatedIds);
                                        Pipe branch = branchSegments.FirstOrDefault();
                                        if (branchSegments.Count > 0)
                                        {
                                            foreach (Pipe plannedBranch in branchSegments)
                                            {
                                                TrySetScFireBranchMetadata(plannedBranch, "branch", batchId);
                                                createdIds.Add(plannedBranch.Id);
                                                createdPipeRoles[plannedBranch.Id.Value] = "branch";
                                                created.Add(new { element_id = plannedBranch.Id.Value, kind = "branch" });
                                            }
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
                                                    ElementId offsetTeeFittingId = ElementId.InvalidElementId;
                                                    if (!TryCreateTeeAtPipeEnds(
                                                        doc,
                                                        offsetBranches[0],
                                                        offsetBranches[1],
                                                        feeder,
                                                        branchTie,
                                                        out offsetTeeFittingId))
                                                    {
                                                        failed.Add(new
                                                        {
                                                            row = rowMain,
                                                            topology = junctionPlan.Topology.ToString(),
                                                            reason = "shared_feeder_to_opposite_branches_connection_failed",
                                                            detail = ReadFireBranchConnectionDiagnostic()
                                                        });
                                                    }
                                                    else if (offsetTeeFittingId != ElementId.InvalidElementId)
                                                    {
                                                        additionalCreatedIds.Add(offsetTeeFittingId);
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
                                                    List<List<Pipe>> crossBranchRuns;
                                                    if (!crossBranchSegmentsByPlan.TryGetValue(junctionPlan, out crossBranchRuns))
                                                    {
                                                        crossBranchRuns = new List<List<Pipe>>();
                                                        crossBranchSegmentsByPlan[junctionPlan] = crossBranchRuns;
                                                    }
                                                    crossBranchRuns.Add(branchSegments);
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
                                                FireBranchDiameterPlanSegment terminalPlan = (diameterPlan ?? new List<FireBranchDiameterPlanSegment>())
                                                    .Where(segment => segment.RowIndex == diameterPlanRowIndex
                                                        && segment.IsSprinklerTerminal
                                                        && segment.SprinklerId == item.Sprinkler.Id.Value)
                                                    .OrderBy(segment => segment.Sequence)
                                                    .LastOrDefault();
                                            XYZ tapPoint = terminalPlan != null
                                                ? NormalizeFireBranchPlanPoint(terminalPlan.End, branchZ)
                                                : new XYZ(
                                                    mainStart.X + mainDirection.X * rowMain + branchDirection.X * item.BranchParameter,
                                                    mainStart.Y + mainDirection.Y * rowMain + branchDirection.Y * item.BranchParameter,
                                                    branchZ
                                                );
                                                if (topologyOnlySandbox)
                                                {
                                                    // M2-M4 sandbox: verify only the plan-driven pipe and junction
                                                    // geometry.  Do not enter the existing sprinkler-drop path;
                                                    // that path has its own independent Connector gate.
                                                    continue;
                                                }
                                                Connector sprinklerConnector = FindConnectorNear(item.Sprinkler, sprinklerPoint);
                                                TryChangeConnectorSystemType(sprinklerConnector, systemType.Id);
                                                if (sprinklerConnector == null)
                                                {
                                                    failed.Add(new { sprinkler_id = item.Sprinkler.Id.Value, reason = "sprinkler_connector_missing" });
                                                    continue;
                                                }
                                                if (tapPoint.DistanceTo(sprinklerPoint) < 0.01)
                                                {
                                                    variableDiameterApplied += ApplyFireBranchDiameterPlan(
                                                        doc,
                                                        branchSegments,
                                                        diameterPlan,
                                                        diameterPlanRowIndex);
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
                                                FireDropAssembly dropAssembly = null;
                                                double branchDropDiameterFeet = ResolveFireBranchDiameterFeet(
                                                    diameterPlan,
                                                    diameterPlanRowIndex,
                                                    tapPoint,
                                                    diameterFeet);
                                                using (SubTransaction dropTransaction = new SubTransaction(doc))
                                                {
                                                    try
                                                    {
                                                        dropTransaction.Start();
                                                        dropAssembly = CreateFireDropWithTransition(
                                                            doc,
                                                            systemType.Id,
                                                            pipeType.Id,
                                                            levelId,
                                                            item.Sprinkler.Id,
                                                            sprinklerPoint,
                                                            tapPoint,
                                                            branchDropDiameterFeet,
                                                            branchSegments);
                                                        if (dropAssembly != null)
                                                        {
                                                            variableDiameterApplied += ApplyFireBranchDiameterPlan(
                                                                doc,
                                                                branchSegments,
                                                                diameterPlan,
                                                                diameterPlanRowIndex);
                                                        }
                                                        if (dropAssembly == null)
                                                        {
                                                            dropTransaction.RollBack();
                                                        }
                                                        else
                                                        {
                                                            dropTransaction.Commit();
                                                        }
                                                    }
                                                    catch (Exception ex)
                                                    {
                                                        SetFireBranchConnectionDiagnostic("CreateFireDropWithTransition.subtransaction", ex);
                                                        if (dropTransaction.GetStatus() == TransactionStatus.Started)
                                                        {
                                                            dropTransaction.RollBack();
                                                        }
                                                        dropAssembly = null;
                                                    }
                                                }
                                                if (dropAssembly == null)
                                                {
                                                    failed.Add(new
                                                    {
                                                        sprinkler_id = item.Sprinkler.Id.Value,
                                                        reason = "sprinkler_drop_creation_failed",
                                                        detail = ReadFireBranchConnectionDiagnostic()
                                                    });
                                                    continue;
                                                }
                                                foreach (Pipe dropPipe in dropAssembly.Pipes)
                                                {
                                                    string role = dropPipe == dropAssembly.BranchConnectionPipe
                                                        ? "drop_upper"
                                                        : "drop_dn25";
                                                    TrySetScFireBranchMetadata(dropPipe, role, batchId);
                                                    createdIds.Add(dropPipe.Id);
                                                    createdPipeRoles[dropPipe.Id.Value] = "drop";
                                                    created.Add(new { element_id = dropPipe.Id.Value, kind = role, sprinkler_id = item.Sprinkler.Id.Value });
                                                }
                                                if (dropAssembly.SprinklerTransition != null)
                                                {
                                                    additionalCreatedIds.Add(dropAssembly.SprinklerTransition.Id);
                                                    created.Add(new
                                                    {
                                                        element_id = dropAssembly.SprinklerTransition.Id.Value,
                                                        kind = "sprinkler_transition",
                                                        sprinkler_id = item.Sprinkler.Id.Value
                                                    });
                                                }
                                                pendingSprinklerConnections.Add(new FirePendingSprinklerConnection
                                                {
                                                    DropPipeId = dropAssembly.SprinklerConnectionPipe.Id,
                                                    SprinklerId = item.Sprinkler.Id,
                                                    SprinklerPoint = sprinklerPoint
                                                });
                                            }
                                            catch (Exception ex)
                                            {
                                                failed.Add(new { sprinkler_id = item.Sprinkler.Id.Value, reason = ex.Message });
                                            }
                                        }
                                        branchSegmentsByRow[diameterPlanRowIndex] = branchSegments;
                                    }
                                    foreach (FireBranchJunctionPlan crossPlan in junctionPlans
                                        .Where(plan => plan.Topology == FireBranchJunctionTopology.OppositeSidesSameElevation)
                                        .OrderBy(plan => plan.MainPipeId)
                                        .ThenBy(plan => plan.MainParameter))
                                    {
                                        List<List<Pipe>> crossBranchRuns;
                                        if (!crossBranchSegmentsByPlan.TryGetValue(crossPlan, out crossBranchRuns)
                                            || crossBranchRuns.Count != 2)
                                        {
                                            continue;
                                        }

                                        attemptedCrossPlans.Add(crossPlan);
                                        FireBranchItem crossReference = crossPlan.Rows
                                            .SelectMany(row => row)
                                            .First();
                                        int[] crossRowIndexes = crossPlan.Rows
                                            .Select(row => rows.IndexOf(row))
                                            .OrderBy(value => value)
                                            .ToArray();
                                        FireBranchExecutionJunction executionCross = null;
                                        executionCrossPlans.TryGetValue(
                                            FireBranchRowPairKey(crossRowIndexes),
                                            out executionCross);
                                        XYZ crossTie = executionCross != null && executionCross.Point != null
                                            ? new XYZ(executionCross.Point.X, executionCross.Point.Y, crossReference.MainZ)
                                            : new XYZ(
                                                crossReference.MainStart.X + crossReference.MainDirection.X * crossPlan.MainParameter,
                                                crossReference.MainStart.Y + crossReference.MainDirection.Y * crossPlan.MainParameter,
                                                crossReference.MainZ);
                                        double crossEndTolerance = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters);
                                        Pipe crossBranchA = FindPipeEndingAtPoint(crossBranchRuns[0], crossTie, crossEndTolerance);
                                        Pipe crossBranchB = FindPipeEndingAtPoint(crossBranchRuns[1], crossTie, crossEndTolerance);
                                        FirePendingCrossTransition pendingTransitionA = null;
                                        FirePendingCrossTransition pendingTransitionB = null;
                                        ResetFireBranchConnectionDiagnostic();
                                        if (executionCross != null)
                                        {
                                            List<Pipe> firstRun = branchSegmentsByRow[crossRowIndexes[0]];
                                            List<Pipe> secondRun = branchSegmentsByRow[crossRowIndexes[1]];
                                            double firstSourceDiameter = executionCross.SourceBranchDiameterFeetByRow[crossRowIndexes[0]];
                                            double secondSourceDiameter = executionCross.SourceBranchDiameterFeetByRow[crossRowIndexes[1]];
                                            ElementId crossBranchAId = PreparePlannedCrossBranchEnd(
                                                doc,
                                                firstRun,
                                                crossRowIndexes[0],
                                                crossTie,
                                                executionCross.CommonBranchDiameterFeet,
                                                firstSourceDiameter,
                                                additionalCreatedIds,
                                                topologyOverridePipeIds,
                                                out pendingTransitionA);
                                            ElementId crossBranchBId = PreparePlannedCrossBranchEnd(
                                                doc,
                                                secondRun,
                                                crossRowIndexes[1],
                                                crossTie,
                                                executionCross.CommonBranchDiameterFeet,
                                                secondSourceDiameter,
                                                additionalCreatedIds,
                                                topologyOverridePipeIds,
                                                out pendingTransitionB);
                                            doc.Regenerate();
                                            crossBranchA = crossBranchAId != null
                                                && crossBranchAId != ElementId.InvalidElementId
                                                ? doc.GetElement(crossBranchAId) as Pipe
                                                : null;
                                            crossBranchB = crossBranchBId != null
                                                && crossBranchBId != ElementId.InvalidElementId
                                                ? doc.GetElement(crossBranchBId) as Pipe
                                                : null;
                                            crossBranchRuns = new List<List<Pipe>> { firstRun, secondRun };
                                        }
                                        bool crossCreated = false;
                                        ElementId createdCrossFittingId = ElementId.InvalidElementId;
                                        if (executionCross != null
                                            && crossBranchA != null
                                            && crossBranchB != null)
                                        {
                                            bool isEndpointTee = executionCross.Kind == "endpoint_tee"
                                                || executionCross.Kind == "reducing_endpoint_tee";
                                            if (isEndpointTee)
                                            {
                                                Pipe mainEnd = FindPipeEndingAtPoint(
                                                    mainSegmentsByPipeId[crossPlan.MainPipeId],
                                                    crossTie,
                                                    crossEndTolerance);
                                                crossCreated = TryCreateTeeAtPipeEnds(
                                                    doc,
                                                    crossBranchA,
                                                    crossBranchB,
                                                    mainEnd,
                                                    crossTie,
                                                    out createdCrossFittingId);
                                                if (crossCreated && createdCrossFittingId != ElementId.InvalidElementId)
                                                {
                                                    additionalCreatedIds.Add(createdCrossFittingId);
                                                }
                                            }
                                            else
                                            {
                                                crossCreated = TryCreateCrossAtPipeEnds(
                                                    doc,
                                                    mainSegmentsByPipeId[crossPlan.MainPipeId],
                                                    crossBranchRuns[0],
                                                    crossBranchRuns[1],
                                                    crossBranchA,
                                                    crossBranchB,
                                                    crossTie,
                                                    executionCross.MainDiameterFeet,
                                                    executionCross.CommonBranchDiameterFeet,
                                                    additionalCreatedIds,
                                                    out createdCrossFittingId);
                                            }
                                        }
                                        if (crossCreated)
                                        {
                                            if (pendingTransitionA != null)
                                            {
                                                pendingTransitionA.CrossFittingId = createdCrossFittingId;
                                            }
                                            if (pendingTransitionB != null)
                                            {
                                                pendingTransitionB.CrossFittingId = createdCrossFittingId;
                                            }
                                            crossCreated = CompletePlannedCrossTransition(
                                                doc,
                                                pendingTransitionA,
                                                additionalCreatedIds)
                                                && CompletePlannedCrossTransition(
                                                    doc,
                                                    pendingTransitionB,
                                                    additionalCreatedIds);
                                            if (crossCreated)
                                            {
                                                foreach (FirePendingCrossTransition resolved in new[]
                                                {
                                                    pendingTransitionA,
                                                    pendingTransitionB
                                                }.Where(item => item != null))
                                                {
                                                    resolvedCrossTransitions.Add(new
                                                    {
                                                        row_index = resolved.RowIndex,
                                                        cross_fitting_id = resolved.CrossFittingId.Value,
                                                        placement_strategy = "fit_to_routing_parts",
                                                        common_diameter_mm = UnitUtils.ConvertFromInternalUnits(
                                                            resolved.CommonDiameterFeet,
                                                            UnitTypeId.Millimeters),
                                                        source_diameter_mm = UnitUtils.ConvertFromInternalUnits(
                                                            resolved.SourceDiameterFeet,
                                                            UnitTypeId.Millimeters),
                                                        resolved_straight_length_mm = UnitUtils.ConvertFromInternalUnits(
                                                            resolved.ResolvedOffsetFeet,
                                                            UnitTypeId.Millimeters)
                                                    });
                                                }
                                            }
                                        }
                                        if (!crossCreated)
                                        {
                                            if (crossBranchA == null || crossBranchB == null)
                                            {
                                                SetFireBranchConnectionDiagnostic(
                                                    "deferred cross endpoint resolution failed | sideA="
                                                    + (crossBranchA == null ? "missing" : crossBranchA.Id.Value.ToString())
                                                    + " | sideB="
                                                    + (crossBranchB == null ? "missing" : crossBranchB.Id.Value.ToString()));
                                            }
                                            failed.Add(new
                                            {
                                                row = crossPlan.MainParameter,
                                                topology = crossPlan.Topology.ToString(),
                                                reason = executionCross != null
                                                    && (executionCross.Kind == "endpoint_tee"
                                                        || executionCross.Kind == "reducing_endpoint_tee")
                                                    ? "opposite_side_endpoint_tee_creation_failed"
                                                    : "opposite_side_cross_creation_failed",
                                                detail = ReadFireBranchConnectionDiagnostic()
                                            });
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

                                    foreach (FirePendingSprinklerConnection pending in pendingSprinklerConnections)
                                    {
                                        Pipe completedDrop = doc.GetElement(pending.DropPipeId) as Pipe;
                                        ResetFireBranchConnectionDiagnostic();
                                        if (!TryConnectCompletedDropToSprinkler(
                                            doc,
                                            completedDrop,
                                            pending.SprinklerId,
                                            pending.SprinklerPoint))
                                        {
                                            failed.Add(new
                                            {
                                                sprinkler_id = pending.SprinklerId.Value,
                                                reason = "DN25 垂管未能連接到灑水頭 connector",
                                                detail = ReadFireBranchConnectionDiagnostic()
                                            });
                                        }
                                    }

                                    doc.Regenerate();
                                    TransactionStatus creationStatus = creationTransaction.Commit();
                                    if (creationStatus != TransactionStatus.Committed)
                                    {
                                        throw new InvalidOperationException(
                                            "消防支管沙盒幾何未通過 Revit 驗證："
                                            + creationStatus
                                            + (creationFailurePreprocessor != null && !string.IsNullOrWhiteSpace(creationFailurePreprocessor.Summary)
                                                ? "｜" + creationFailurePreprocessor.Summary
                                                : ""));
                                    }
                                    }
                                    fireBranchStage = "connected_system_discovery";
                                List<ElementId> fireNetworkElementIds = mainSegmentsByPipeId.Values
                                    .SelectMany(segments => segments)
                                    .Where(pipe => pipe != null && pipe.IsValidObject)
                                    .Select(pipe => pipe.Id)
                                    .Concat(createdIds)
                                    .GroupBy(id => id.Value)
                                    .Select(group => group.First())
                                    .ToList();
                                if (!topologyOnlySandbox)
                                {
                                    fireNetworkElementIds = fireNetworkElementIds
                                        .Concat(plannedSprinklers
                                            .Where(instance => instance != null && instance.IsValidObject)
                                            .Select(instance => instance.Id))
                                        .GroupBy(id => id.Value)
                                        .Select(group => group.First())
                                        .ToList();
                                }
                                    List<ElementId> connectedSystemIds = ResolveConnectedFireSystemIds(
                                        doc,
                                        fireNetworkElementIds);
                                    var systemChangeFailures = new List<object>();
                                    fireBranchStage = "system_type_change";
                                    using (Transaction systemTransaction = new Transaction(doc, "SC \u7d71\u4e00\u6d88\u9632\u7cfb\u7d71\u985e\u578b"))
                                    {
                                    FireBranchSandboxFailurePreprocessor systemFailurePreprocessor = null;
                                    if (isSandbox)
                                    {
                                        systemFailurePreprocessor = new FireBranchSandboxFailurePreprocessor();
                                        FailureHandlingOptions options = systemTransaction.GetFailureHandlingOptions();
                                        options.SetFailuresPreprocessor(systemFailurePreprocessor);
                                        options.SetClearAfterRollback(true);
                                        systemTransaction.SetFailureHandlingOptions(options);
                                    }
                                    TransactionStatus systemStartStatus = systemTransaction.Start();
                                    if (systemStartStatus != TransactionStatus.Started)
                                    {
                                        throw new InvalidOperationException("Fire branch system transaction did not start: " + systemStartStatus);
                                    }
                                    foreach (ElementId connectedSystemId in connectedSystemIds.ToList())
                                    {
                                        long connectedSystemIdValue = connectedSystemId.Value;
                                        MEPSystem connectedSystem = doc.GetElement(connectedSystemId) as MEPSystem;
                                        if (connectedSystem == null)
                                        {
                                            systemChangeFailures.Add(new
                                            {
                                                system_id = connectedSystemIdValue,
                                                reason = "connected_system_not_found"
                                            });
                                            continue;
                                        }
                                        ElementId beforeTypeId = ElementId.InvalidElementId;
                                        try
                                        {
                                            beforeTypeId = connectedSystem.GetTypeId();
                                            if (beforeTypeId != null && beforeTypeId.Value == systemType.Id.Value)
                                            {
                                                continue;
                                            }
                                            bool canAssign = connectedSystem.CanHaveTypeAssigned();
                                            bool targetIsValid = connectedSystem.IsValidType(systemType.Id);
                                            if (!canAssign || !targetIsValid)
                                            {
                                                systemChangeFailures.Add(new
                                                {
                                                    system_id = connectedSystemIdValue,
                                                    before_system_type_id = beforeTypeId == null ? 0 : beforeTypeId.Value,
                                                    can_have_type_assigned = canAssign,
                                                    target_is_valid = targetIsValid,
                                                    reason = "target_system_type_not_assignable"
                                                });
                                                continue;
                                            }

                                            ElementId replacementSystemId = connectedSystem.ChangeTypeId(systemType.Id);
                                            ElementId effectiveSystemId = replacementSystemId != null
                                                && replacementSystemId != ElementId.InvalidElementId
                                                ? replacementSystemId
                                                : connectedSystemId;
                                            MEPSystem changedSystem = doc.GetElement(effectiveSystemId) as MEPSystem;
                                            ElementId afterTypeId = changedSystem == null
                                                ? ElementId.InvalidElementId
                                                : changedSystem.GetTypeId();
                                            if (effectiveSystemId.Value != connectedSystemIdValue)
                                            {
                                                connectedSystemIds.RemoveAll(id => id.Value == connectedSystemIdValue);
                                                if (!connectedSystemIds.Any(id => id.Value == effectiveSystemId.Value))
                                                {
                                                    connectedSystemIds.Add(effectiveSystemId);
                                                }
                                            }
                                            if (afterTypeId == null || afterTypeId.Value != systemType.Id.Value)
                                            {
                                                systemChangeFailures.Add(new
                                                {
                                                    system_id = effectiveSystemId.Value,
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
                                                system_id = connectedSystemIdValue,
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
                                        throw new InvalidOperationException(
                                            "消防支管沙盒系統設定未通過 Revit 驗證："
                                            + systemStatus
                                            + (systemFailurePreprocessor != null && !string.IsNullOrWhiteSpace(systemFailurePreprocessor.Summary)
                                                ? "｜" + systemFailurePreprocessor.Summary
                                                : ""));
                                    }
                                    }
                                    fireBranchStage = "system_and_connector_verification";
                                    List<ElementId> verifiedConnectedSystemIds = ResolveConnectedFireSystemIds(
                                        doc,
                                        fireNetworkElementIds);
                                    List<long> actualSystemTypeIds = verifiedConnectedSystemIds
                                        .Select(id => doc.GetElement(id) as MEPSystem)
                                        .Where(system => system != null && system.IsValidObject)
                                        .Select(system => system.GetTypeId())
                                        .Where(typeId => typeId != null)
                                        .Select(typeId => typeId.Value)
                                        .Distinct()
                                        .ToList();
                                    List<Pipe> createdPipes = createdIds
                                        .Select(id => doc.GetElement(id) as Pipe)
                                        .Where(pipe => pipe != null && pipe.IsValidObject && IsScFireBranchPipe(pipe))
                                        .GroupBy(pipe => pipe.Id.Value)
                                        .Select(group => group.First())
                                        .ToList();
                                    List<long> diameterMismatchPipeIds = FindFireBranchDiameterPlanMismatches(
                                        branchSegmentsByRow,
                                        diameterPlan,
                                        topologyOverridePipeIds);
                                    if (diameterMismatchPipeIds.Count > 0)
                                    {
                                        failed.Add(new
                                        {
                                            reason = "variable_diameter_verification_failed",
                                            pipe_ids = diameterMismatchPipeIds
                                        });
                                    }
                                    List<long> missingSystemPipeIds = createdPipes
                                        .Where(pipe => pipe.MEPSystem == null)
                                        .Select(pipe => pipe.Id.Value)
                                        .ToList();
                                    List<long> wrongSystemPipeIds = createdPipes
                                        .Where(pipe => pipe.MEPSystem != null
                                            && pipe.MEPSystem.GetTypeId().Value != systemType.Id.Value)
                                        .Select(pipe => pipe.Id.Value)
                                        .ToList();
                                    List<long> missingConnectorSprinklerIds = topologyOnlySandbox
                                        ? new List<long>()
                                        : plannedSprinklers
                                            .Where(instance => FindConnectorNear(
                                                instance,
                                                GetFamilyConnectionPoint(instance)) == null)
                                            .Select(instance => instance.Id.Value)
                                            .ToList();
                                    List<long> missingSystemSprinklerIds = topologyOnlySandbox
                                        ? new List<long>()
                                        : plannedSprinklers
                                            .Where(instance =>
                                            {
                                                Connector connector = FindConnectorNear(
                                                    instance,
                                                    GetFamilyConnectionPoint(instance));
                                                return connector != null && connector.MEPSystem == null;
                                            })
                                            .Select(instance => instance.Id.Value)
                                            .ToList();
                                    List<long> wrongSystemSprinklerIds = topologyOnlySandbox
                                        ? new List<long>()
                                        : plannedSprinklers
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
                                    var unconnectedSprinklerIds = topologyOnlySandbox
                                        ? new List<long>()
                                        : plannedSprinklers
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
                                    var missingCreatedPipeIds = createdPipeRoles.Keys
                                        .Where(id => doc.GetElement(new ElementId(id)) == null)
                                        .Distinct()
                                        .ToList();
                                    var verifiedMainPipeIds = new HashSet<long>(
                                        mainSegmentsByPipeId.Values
                                            .SelectMany(segments => segments)
                                            .Where(pipe => pipe != null && pipe.IsValidObject)
                                            .Select(pipe => pipe.Id.Value));
                                    var unreachableSprinklerIds = topologyOnlySandbox
                                        ? new List<long>()
                                        : plannedSprinklers
                                            .Where(instance => !IsPhysicallyReachableFromFireElement(
                                                doc,
                                                instance.Id,
                                                verifiedMainPipeIds))
                                            .Select(instance => instance.Id.Value)
                                            .Distinct()
                                            .ToList();
                                    verifiedUnconnectedSprinklerCount = topologyOnlySandbox
                                        ? 0
                                        : unreachableSprinklerIds.Count;
                                    verifiedConnectedSprinklerCount = topologyOnlySandbox
                                        ? 0
                                        : Math.Max(
                                            0,
                                            plannedSprinklers.Count - verifiedUnconnectedSprinklerCount);
                                    if (unconnectedSprinklerIds.Count > 0
                                        || unconnectedCreatedPipeIds.Count > 0
                                        || missingCreatedPipeIds.Count > 0
                                        || unreachableSprinklerIds.Count > 0)
                                    {
                                        failed.Add(new
                                        {
                                            reason = "connector_verification_failed",
                                            unconnected_sprinkler_ids = unconnectedSprinklerIds,
                                            unconnected_pipe_ids = unconnectedCreatedPipeIds,
                                            missing_created_pipe_ids = missingCreatedPipeIds,
                                            unreachable_sprinkler_ids = unreachableSprinklerIds
                                        });
                                    }
                                    if (failed.Count > 0)
                                    {
                                        int failureCount = failed.Count;
                                        evidenceElementIds = createdIds
                                            .Concat(additionalCreatedIds)
                                            .Where(id => id != null && id != ElementId.InvalidElementId)
                                            .GroupBy(id => id.Value)
                                            .Select(group => group.First())
                                            .Where(id => doc.GetElement(id) != null)
                                            .Select(id => id.Value)
                                            .ToList();

                                        if (isSandbox)
                                        {
                                            fireBranchStage = "sandbox_restore_after_failure";
                                            retentionDecision = "rolled_back";
                                            TransactionStatus rollbackStatus = transactionGroup.RollBack();
                                            if (rollbackStatus != TransactionStatus.RolledBack)
                                            {
                                                throw new InvalidOperationException(
                                                    "消防支管沙盒檢查失敗，且無法完整復原本次變更："
                                                    + rollbackStatus);
                                            }
                                            sandboxRolledBackEarly = true;
                                        }
                                        else
                                        {
                                            fireBranchStage = "partial_failure_decision";
                                            var decisionDialog = new TaskDialog("SC REVIT 消防支管")
                                            {
                                                MainInstruction = "消防支管只有部分建立成功",
                                                MainContent =
                                                    "已建立 " + evidenceElementIds.Count + " 個管段或管件，"
                                                    + "發現 " + failureCount + " 項問題，"
                                                    + verifiedUnconnectedSprinklerCount + " 顆灑水頭尚未連到主管。\n\n"
                                                    + "請選擇要保留成功建立的部分，或將本次建立全部復原。",
                                                ExpandedContent =
                                                    "完整技術診斷與 ElementId 已保存於本次 SC REVIT 工作流程紀錄。",
                                                AllowCancellation = true
                                            };
                                            decisionDialog.AddCommandLink(
                                                TaskDialogCommandLinkId.CommandLink1,
                                                "保留成功部分（可用 Revit 復原）");
                                            decisionDialog.AddCommandLink(
                                                TaskDialogCommandLinkId.CommandLink2,
                                                "全部復原");
                                            TaskDialogResult retentionResult = decisionDialog.Show();

                                            if (retentionResult == TaskDialogResult.CommandLink1)
                                            {
                                                TransactionStatus evidenceStatus = transactionGroup.Assimilate();
                                                if (evidenceStatus != TransactionStatus.Committed)
                                                {
                                                    throw new InvalidOperationException(
                                                        "無法保留消防支管已成功建立的部分："
                                                        + evidenceStatus);
                                                }
                                                partialFailureKept = true;
                                                retentionDecision = "kept";
                                                failed.Add(new
                                                {
                                                    reason = "diagnostic_evidence_kept",
                                                    model_changes_kept = true,
                                                    original_failure_count = failureCount,
                                                    evidence_element_ids = evidenceElementIds,
                                                    undo_transaction = "SC 消防支管建立"
                                                });
                                            }
                                            else
                                            {
                                                retentionDecision = "rolled_back";
                                                TransactionStatus rollbackStatus = transactionGroup.RollBack();
                                                if (rollbackStatus != TransactionStatus.RolledBack)
                                                {
                                                    throw new InvalidOperationException(
                                                        "消防支管建立失敗，且無法完整復原本次變更："
                                                        + rollbackStatus);
                                                }
                                                throw new FireBranchConnectorVerificationException(
                                                    "消防支管未完整建立，使用者已選擇全部復原。問題數量："
                                                    + failureCount
                                                    + "。完整診斷已保存。",
                                                    failed.ToArray());
                                            }
                                            }
                                    }
                                    if (!partialFailureKept && isSandbox)
                                    {
                                        fireBranchStage = "sandbox_restore";
                                    }
                                    else if (!partialFailureKept)
                                    {
                                        fireBranchStage = "commit_group";
                                    }
                                    if (!partialFailureKept && !sandboxRolledBackEarly)
                                    {
                                        TransactionStatus groupStatus = isSandbox
                                            ? transactionGroup.RollBack()
                                            : transactionGroup.Assimilate();
                                        TransactionStatus expectedGroupStatus = isSandbox
                                            ? TransactionStatus.RolledBack
                                            : TransactionStatus.Committed;
                                        if (groupStatus != expectedGroupStatus)
                                        {
                                            throw new InvalidOperationException(
                                                "Fire branch transaction group did not finish in "
                                                + executionMode
                                                + " mode: "
                                                + groupStatus);
                                        }
                                    }
                                    }
                                    catch (FireBranchConnectorVerificationException)
                                    {
                                        if (transactionGroup.GetStatus() == TransactionStatus.Started)
                                        {
                                            transactionGroup.RollBack();
                                        }
                                        throw;
                                    }
                                    catch (Exception ex)
                                    {
                                        if (transactionGroup.GetStatus() == TransactionStatus.Started)
                                        {
                                            transactionGroup.RollBack();
                                        }
                                        throw new InvalidOperationException(
                                            "Fire branch failed at " + fireBranchStage + ": " + ex.Message,
                                            ex);
                                    }
                                }

                                if (isSandbox && !partialFailureKept)
                                {
                                    residualCreatedElementIds = createdIds
                                        .Concat(additionalCreatedIds)
                                        .Where(id => id != null && id != ElementId.InvalidElementId)
                                        .GroupBy(id => id.Value)
                                        .Select(group => group.First())
                                        .Where(id => doc.GetElement(id) != null)
                                        .Select(id => id.Value)
                                        .ToList();
                                    bool mainsRestored = originalMainPipeIds.All(id => doc.GetElement(new ElementId(id)) is Pipe);
                                    bool sprinklersRestored = originalSprinklerPoints.All(pair =>
                                    {
                                        FamilyInstance restored = doc.GetElement(new ElementId(pair.Key)) as FamilyInstance;
                                        if (restored == null || GetFamilyConnectionPoint(restored).DistanceTo(pair.Value) > 1e-7)
                                        {
                                            return false;
                                        }
                                        Connector connector = FindConnectorNear(restored, pair.Value);
                                        bool connected = connector != null && connector.IsConnected;
                                        long restoredSystemTypeId = connector != null && connector.MEPSystem != null
                                            ? connector.MEPSystem.GetTypeId().Value
                                            : 0L;
                                        return connected == originalSprinklerConnected[pair.Key]
                                            && restoredSystemTypeId == originalSprinklerSystemTypeIds[pair.Key];
                                    });
                                    restorationVerified = residualCreatedElementIds.Count == 0
                                        && mainsRestored
                                        && sprinklersRestored;
                                    if (!restorationVerified)
                                    {
                                        throw new InvalidOperationException(
                                            "沙盒已回復，但模型狀態驗證未通過；請勿進行正式建立並查看診斷資料。");
                                    }
                                }

                                if (deletePreviewAfterCreate && !isSandbox && !partialFailureKept)
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
                                        execution_mode = executionMode,
                                        model_restored = restorationVerified,
                                        restoration_verified = restorationVerified,
                                        rollback_status = partialFailureKept
                                            ? "partial_evidence_kept"
                                            : (isSandbox
                                                ? (restorationVerified ? "verified" : "failed")
                                                : "not_applicable"),
                                        residual_created_element_ids = residualCreatedElementIds,
                                        partial_success = partialFailureKept,
                                        retention_decision = retentionDecision,
                                        sandbox_scope = sandboxScope,
                                        sprinkler_connectivity_assessed = !topologyOnlySandbox,
                                        diagnostic_evidence_element_ids = evidenceElementIds,
                                        retained_evidence_element_ids = partialFailureKept
                                            ? evidenceElementIds
                                            : new List<long>(),
                                        model_changes_kept = !isSandbox,
                                        tested_main_pipe_id = mainPipes[0].PipeId,
                                        tested_sprinkler_id = sprinklers.Count == 1 ? sprinklers[0].Id.Value : 0,
                                        source_row_index = sandboxScope == "single_sprinkler" ? pilotSourceRowIndex : -1,
                                        preview_snapshot_id = previewSnapshotId,
                                        model_plan_hash = modelPlanHash,
                                        topology_plan_identity = new
                                        {
                                            schema_version = ReadTopologyPlanString(payload, "schema_version"),
                                            plan_id = ReadTopologyPlanString(payload, "plan_id"),
                                            revision = ReadTopologyPlanLong(payload, "revision", 0),
                                            plan_hash = ReadTopologyPlanString(payload, "plan_hash")
                                        },
                                        applied_diameter_segments = diameterPlan.Select(item => new
                                        {
                                            plan_entity_id = item.PlanEntityId,
                                            segment_id = item.SegmentId,
                                            row_index = item.RowIndex,
                                            sequence = item.Sequence,
                                            diameter_mm = UnitUtils.ConvertFromInternalUnits(
                                                item.DiameterFeet,
                                                UnitTypeId.Millimeters)
                                        }).ToList(),
                                        topology_plan_entities = topologyPlan.Select(item => new
                                        {
                                            plan_entity_id = item.PlanEntityId,
                                            kind = item.Kind,
                                            row_indexes = item.RowIndexes,
                                            branch_plan_entity_ids = item.BranchPlanEntityIdByRow
                                                .Select(pair => new
                                                {
                                                    row_index = pair.Key,
                                                    plan_entity_id = pair.Value
                                                })
                                                .ToList(),
                                            reducer_plan_entity_ids = item.RoutingFitReducerPlanEntityIds.ToList()
                                        }).ToList(),
                                        resolved_cross_transitions = resolvedCrossTransitions,
                                        created = created,
                                        failed = failed,
                                        skipped = skipped,
                                        cad_route_assignments = cadRouteAssignments,
                                        verification_status = failed.Count > 0
                                            ? (partialFailureKept ? "partial" : "failed")
                                            : "verified",
                                        verified_system_type_id = systemType.Id.Value,
                                        verified_system_type_name = systemType.Name,
                                        connected_sprinkler_count = verifiedConnectedSprinklerCount,
                                        unconnected_sprinkler_count = verifiedUnconnectedSprinklerCount,
                                        junctions = junctions,
                                        sprinkler_count = sprinklers.Count,
                                        main_candidate_count = mainCandidateCount,
                                        valid_main_count = mainPipes.Count,
                                        excluded_main_count = excludedMainCount,
                                        row_count = plannedRowCount,
                                        estimated_pipe_count = estimatedPipeCount,
                                        max_branch_length_m = maxBranchLengthMeters,
                                        deleted_preview_group_id = deletedPreviewGroupId,
                                        variable_diameter_applied = variableDiameterApplied,
                                        diameter_plan_segment_count = diameterPlan.Count
                                    })
                                );
                                return;
                            }

            throw new InvalidOperationException("Unsupported fire branch action: " + action);
        }
    }
}
