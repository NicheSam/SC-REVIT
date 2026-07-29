using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.UI.Selection;
using System;
using System.Collections.Generic;
using System.Linq;

namespace RfaMetadataAddin.Drainage
{
    internal sealed class DrainageSourceSelectionFilter :
        ISelectionFilter
    {
        public bool AllowElement(Element element)
        {
            return DrainageSourceResolver.HasOpenPipingEnd(
                element);
        }

        public bool AllowReference(Reference reference, XYZ position)
        {
            return true;
        }
    }

    internal sealed class DrainageMainSelectionFilter :
        ISelectionFilter
    {
        private readonly ElementId _excludedElementId;

        public DrainageMainSelectionFilter(
            ElementId excludedElementId)
        {
            _excludedElementId = excludedElementId;
        }

        public bool AllowElement(Element element)
        {
            Pipe pipe = element as Pipe;
            if (pipe == null)
            {
                return false;
            }
            if (_excludedElementId != null
                && _excludedElementId
                    != ElementId.InvalidElementId
                && pipe.Id.Value
                    == _excludedElementId.Value)
            {
                return false;
            }
            LocationCurve location = pipe.Location as LocationCurve;
            if (location == null || location.Curve == null)
            {
                return false;
            }
            XYZ start = location.Curve.GetEndPoint(0);
            XYZ end = location.Curve.GetEndPoint(1);
            double horizontal = Math.Sqrt(
                Math.Pow(end.X - start.X, 2)
                + Math.Pow(end.Y - start.Y, 2));
            return horizontal > 0.1
                && Math.Abs(end.Z - start.Z)
                    / horizontal <= 0.20;
        }

        public bool AllowReference(Reference reference, XYZ position)
        {
            return true;
        }
    }

    internal sealed class DrainageSpecificPipeSelectionFilter :
        ISelectionFilter
    {
        private readonly ElementId _pipeId;

        public DrainageSpecificPipeSelectionFilter(ElementId pipeId)
        {
            _pipeId = pipeId;
        }

        public bool AllowElement(Element element)
        {
            return element is Pipe
                && _pipeId != null
                && element.Id.Value == _pipeId.Value;
        }

        public bool AllowReference(Reference reference, XYZ position)
        {
            return reference != null
                && _pipeId != null
                && reference.ElementId.Value == _pipeId.Value;
        }
    }

    internal static class DrainageSourceResolver
    {
        public static DrainageSourceRef Resolve(
            Element sourceElement,
            XYZ pickPoint)
        {
            if (sourceElement == null)
            {
                throw new InvalidOperationException(
                    "SOURCE_NOT_SUPPORTED");
            }

            IList<DrainageConnectorRef> candidates =
                BuildConnectorRefs(
                    sourceElement,
                    pickPoint);
            if (candidates.Count == 0)
            {
                throw new InvalidOperationException(
                    "SOURCE_CONNECTOR_MISSING: 選取物件沒有可用的開放 piping end connector。");
            }

            IList<DrainageConfigurationProfile> profiles =
                DrainageConfigurationStore
                    .Load(sourceElement.Document)
                    .Profiles;
            foreach (DrainageConnectorRef candidate in candidates)
            {
                ScoreCandidate(
                    candidate,
                    pickPoint,
                    profiles);
            }
            Pipe sourcePipe = sourceElement as Pipe;
            if (sourcePipe != null
                && IsVerticalPipe(sourcePipe))
            {
                foreach (DrainageConnectorRef candidate in candidates)
                {
                    if (candidate.Axis != null
                        && candidate.Axis.Z < -0.90)
                    {
                        candidate.Score += 1000.0;
                        candidate.Evidence.Add(
                            "垂直 Pipe 優先使用向下開放端");
                    }
                }
            }
            candidates = candidates
                .OrderByDescending(item => item.Score)
                .ThenBy(item => item.Origin.X)
                .ThenBy(item => item.Origin.Y)
                .ThenBy(item => item.Origin.Z)
                .ThenBy(item => item.ConnectorIndex)
                .ToList();

            DrainageConnectorRef selected = candidates[0];
            if (selected.FlowDirectionKnown
                && selected.FlowDirection == FlowDirectionType.In
                && !profiles.Any(item => item != null
                    && item.Enabled
                    && item.AllowInFlow
                    && ProfileAllowsSystem(item, selected)))
            {
                throw new InvalidOperationException(
                    "SOURCE_FLOW_INCOMPATIBLE: connector 的 FlowDirection 為 In，且沒有允許此方向的 Connection Profile。");
            }
            if (candidates.Count > 1)
            {
                double pickTolerance =
                    UnitUtils.ConvertToInternalUnits(
                        50,
                        UnitTypeId.Millimeters);
                double firstDistance = pickPoint == null
                    ? 0
                    : selected.Origin.DistanceTo(pickPoint);
                double secondDistance = pickPoint == null
                    ? 0
                    : candidates[1].Origin.DistanceTo(pickPoint);
                if (selected.Score - candidates[1].Score < 8.0
                    && (pickPoint == null
                        || Math.Abs(
                            secondDistance - firstDistance)
                            < pickTolerance))
                {
                    throw new InvalidOperationException(
                        "SOURCE_CONNECTOR_AMBIGUOUS: 多個 connector 的系統、方向與距離接近，請靠近要使用的接口點選。");
                }
            }

            return new DrainageSourceRef
            {
                SourceElement = sourceElement,
                SourceConnector = selected.Connector,
                ConnectorRef = selected,
                Kind = sourceElement is Pipe
                    ? DrainageSourceKind.PipeOpenEnd
                    : DrainageSourceKind.FamilyConnector,
                PickPoint = pickPoint
            };
        }

        internal static bool HasOpenPipingEnd(Element element)
        {
            return GetConnectors(element)
                .Any(connector =>
                    connector.Domain == Domain.DomainPiping
                    && connector.ConnectorType
                        == ConnectorType.End
                    && !connector.IsConnected);
        }

        internal static bool IsVerticalPipe(Pipe pipe)
        {
            LocationCurve location =
                pipe == null ? null : pipe.Location as LocationCurve;
            if (location == null || location.Curve == null)
            {
                return false;
            }
            XYZ start = location.Curve.GetEndPoint(0);
            XYZ end = location.Curve.GetEndPoint(1);
            double vertical = Math.Abs(end.Z - start.Z);
            double horizontal = Math.Sqrt(
                Math.Pow(end.X - start.X, 2)
                + Math.Pow(end.Y - start.Y, 2));
            return vertical > UnitUtils.ConvertToInternalUnits(
                    100,
                    UnitTypeId.Millimeters)
                && horizontal / vertical <= 0.02;
        }

        public static double ReadDiameterMm(
            DrainageSourceRef source)
        {
            if (source == null || source.SourceConnector == null)
            {
                return 0;
            }
            try
            {
                if (source.SourceConnector.Shape
                    != ConnectorProfileType.Round)
                {
                    return 0;
                }
                return UnitUtils.ConvertFromInternalUnits(
                    source.SourceConnector.Radius * 2.0,
                    UnitTypeId.Millimeters);
            }
            catch
            {
                return 0;
            }
        }

        private static IList<DrainageConnectorRef> BuildConnectorRefs(
            Element sourceElement,
            XYZ pickPoint)
        {
            List<Connector> connectors = GetConnectors(
                    sourceElement)
                .Where(connector =>
                    connector.Domain == Domain.DomainPiping
                    && connector.ConnectorType
                        == ConnectorType.End
                    && !connector.IsConnected)
                .OrderBy(connector => connector.Origin.X)
                .ThenBy(connector => connector.Origin.Y)
                .ThenBy(connector => connector.Origin.Z)
                .ToList();
            var result = new List<DrainageConnectorRef>();
            for (int index = 0;
                index < connectors.Count;
                index++)
            {
                Connector connector = connectors[index];
                XYZ axis = SafeAxis(connector);
                FlowDirectionType direction;
                bool directionKnown = TryReadDirection(
                    connector,
                    out direction);
                string classification =
                    SafeSystemClassification(connector);
                result.Add(new DrainageConnectorRef
                {
                    Connector = connector,
                    ConnectorIndex = index,
                    ConnectorKey = sourceElement.UniqueId
                        + ":PIPING_END:"
                        + index.ToString("D2")
                        + ":"
                        + StablePointKey(connector.Origin),
                    Origin = connector.Origin,
                    Axis = axis,
                    DiameterMm = ReadDiameterMm(connector),
                    Shape = connector.Shape,
                    FlowDirection = direction,
                    FlowDirectionKnown = directionKnown,
                    SystemClassification = classification,
                    SystemTypeUniqueId =
                        ReadSystemTypeUniqueId(connector),
                    IsConnected = connector.IsConnected,
                    Evidence = new List<string>
                    {
                        "DomainPiping",
                        "ConnectorType.End",
                        "未連接",
                        directionKnown
                            ? "FlowDirection="
                                + direction
                            : "FlowDirection=Undefined",
                        string.IsNullOrWhiteSpace(classification)
                            ? "SystemClassification=Unknown"
                            : "SystemClassification="
                                + classification
                    }
                });
            }
            return result;
        }

        private static IEnumerable<Connector> GetConnectors(
            Element element)
        {
            Pipe pipe = element as Pipe;
            if (pipe != null
                && pipe.ConnectorManager != null)
            {
                return pipe.ConnectorManager.Connectors
                    .Cast<Connector>();
            }
            FamilyInstance instance =
                element as FamilyInstance;
            if (instance != null
                && instance.MEPModel != null
                && instance.MEPModel.ConnectorManager != null)
            {
                return instance.MEPModel.ConnectorManager
                    .Connectors
                    .Cast<Connector>();
            }
            return Enumerable.Empty<Connector>();
        }

        private static void ScoreCandidate(
            DrainageConnectorRef candidate,
            XYZ pickPoint,
            IList<DrainageConfigurationProfile> profiles)
        {
            double score = 100.0;
            if (candidate.Shape == ConnectorProfileType.Round
                && candidate.DiameterMm > 0)
            {
                score += 25.0;
                candidate.Evidence.Add("圓形且可讀取尺寸");
            }
            else
            {
                score -= 200.0;
                candidate.Evidence.Add("非圓形或尺寸無效");
            }
            if (candidate.FlowDirectionKnown)
            {
                if (candidate.FlowDirection
                    == FlowDirectionType.Out)
                {
                    score += 35.0;
                }
                else if (candidate.FlowDirection
                    == FlowDirectionType.Bidirectional)
                {
                    score += 15.0;
                }
                else
                {
                    score -= 100.0;
                }
            }
            else
            {
                score += 10.0;
            }
            if (candidate.Axis != null
                && candidate.Axis.GetLength() > 0.99)
            {
                score += 10.0;
            }
            if ((profiles ?? new List<DrainageConfigurationProfile>())
                .Any(item => item != null
                    && item.Enabled
                    && ProfileAllowsSystem(item, candidate)))
            {
                score += 30.0;
                candidate.Evidence.Add("符合專案 Connection Profile");
            }
            if (pickPoint != null)
            {
                score -= Math.Min(
                    30.0,
                    candidate.Origin.DistanceTo(pickPoint) * 6.0);
            }
            candidate.Score = score;
        }

        private static bool ProfileAllowsSystem(
            DrainageConfigurationProfile profile,
            DrainageConnectorRef connector)
        {
            string allowed = profile
                .AllowedSourceSystemClassifications ?? "";
            if (string.IsNullOrWhiteSpace(allowed))
            {
                return true;
            }
            return allowed
                .Split(new[] { ',', ';', '\r', '\n' },
                    StringSplitOptions.RemoveEmptyEntries)
                .Select(item => item.Trim())
                .Any(item => string.Equals(
                    item,
                    connector.SystemClassification,
                    StringComparison.OrdinalIgnoreCase));
        }

        private static double ReadDiameterMm(
            Connector connector)
        {
            try
            {
                return connector.Shape
                        == ConnectorProfileType.Round
                    ? UnitUtils.ConvertFromInternalUnits(
                        connector.Radius * 2.0,
                        UnitTypeId.Millimeters)
                    : 0;
            }
            catch
            {
                return 0;
            }
        }

        private static XYZ SafeAxis(Connector connector)
        {
            try
            {
                XYZ axis = connector.CoordinateSystem.BasisZ;
                return axis == null
                    || axis.GetLength() < 0.000001
                        ? XYZ.Zero
                        : axis.Normalize();
            }
            catch
            {
                return XYZ.Zero;
            }
        }

        private static bool TryReadDirection(
            Connector connector,
            out FlowDirectionType direction)
        {
            try
            {
                direction = connector.Direction;
                return true;
            }
            catch
            {
                direction = FlowDirectionType.Bidirectional;
                return false;
            }
        }

        private static string ReadSystemTypeUniqueId(
            Connector connector)
        {
            try
            {
                MEPSystem system = connector.MEPSystem;
                if (system == null)
                {
                    return "";
                }
                Element type = system.Document.GetElement(
                    system.GetTypeId());
                return type == null ? "" : type.UniqueId;
            }
            catch
            {
                return "";
            }
        }

        private static string StablePointKey(XYZ point)
        {
            return string.Join(
                ",",
                Math.Round(point.X, 6),
                Math.Round(point.Y, 6),
                Math.Round(point.Z, 6));
        }

        private static string SafeSystemClassification(
            Connector connector)
        {
            try
            {
                return connector.PipeSystemType.ToString();
            }
            catch
            {
                return "";
            }
        }
    }

    internal sealed class DrainageTargetResolver
    {
        private const double SearchRadiusFeet = 32.8083989501;

        public IList<DrainageTargetRef> RankCandidates(
            Document document,
            View activeView,
            DrainageSourceRef source,
            Pipe pinnedMain)
        {
            if (pinnedMain != null)
            {
                return new List<DrainageTargetRef>
                {
                    new DrainageTargetRef
                    {
                        MainPipe = pinnedMain,
                        Score = 1000,
                        DistanceFeet = DistanceToPipe(
                            pinnedMain,
                            source.SourceConnector.Origin),
                        Resolution = "Preselected",
                        RequiresUserConfirmation = false,
                        Evidence = new List<string>
                        {
                            "使用者預選唯一幹管"
                        }
                    }
                };
            }

            IList<Pipe> activeViewPipes = activeView != null
                ? new FilteredElementCollector(
                    document,
                    activeView.Id)
                    .OfClass(typeof(Pipe))
                    .Cast<Pipe>()
                    .ToList()
                : new List<Pipe>();
            ISet<long> activeViewIds = new HashSet<long>(
                activeViewPipes.Select(item => item.Id.Value));
            XYZ sourceOrigin = source.SourceConnector.Origin;
            XYZ delta = new XYZ(
                SearchRadiusFeet,
                SearchRadiusFeet,
                SearchRadiusFeet);
            var spatialFilter =
                new BoundingBoxIntersectsFilter(
                    new Outline(
                        sourceOrigin - delta,
                        sourceOrigin + delta));
            IEnumerable<Pipe> pipes = activeViewPipes
                .Concat(
                    new FilteredElementCollector(document)
                        .OfClass(typeof(Pipe))
                        .WherePasses(spatialFilter)
                        .Cast<Pipe>())
                .GroupBy(item => item.Id.Value)
                .Select(group => group.First());
            double sourceDiameterMm =
                DrainageSourceResolver.ReadDiameterMm(source);
            var ranked = new List<DrainageTargetRef>();
            foreach (Pipe pipe in pipes)
            {
                if (pipe.Id == source.ElementId
                    || !IsEligibleMain(pipe))
                {
                    continue;
                }
                double distance = DistanceToPipe(
                    pipe,
                    source.SourceConnector.Origin);
                if (distance > SearchRadiusFeet)
                {
                    continue;
                }
                DrainageConfigurationProfile configuration =
                    DrainageConfigurationStore.ResolveForPipe(
                        document,
                        pipe,
                        sourceDiameterMm,
                        source);
                double score = 100.0 - distance * 2.0;
                var evidence = new List<string>();
                bool isActiveView =
                    activeViewIds.Contains(pipe.Id.Value);
                if (isActiveView)
                {
                    score += 8.0;
                    evidence.Add("位於目前視圖");
                }
                if (configuration != null)
                {
                    score += 60.0;
                    evidence.Add("目標與來源符合 Connection Profile");
                }
                else
                {
                    score -= 80.0;
                    evidence.Add("PROFILE_NOT_MATCHED");
                }
                if (IsBelowSource(pipe, source.SourceConnector.Origin))
                {
                    score += 15.0;
                    evidence.Add("幹管位於接入端下方");
                }
                ranked.Add(new DrainageTargetRef
                {
                    MainPipe = pipe,
                    Score = score,
                    DistanceFeet = distance,
                    Resolution = isActiveView
                        ? "BoundedActiveViewSearch"
                        : "BoundedSpatialSearch",
                    Evidence = evidence
                });
            }

            ranked = ranked
                .OrderByDescending(item => item.Score)
                .ThenBy(item => item.DistanceFeet)
                .ThenBy(item => item.MainPipe.Id.Value)
                .Take(20)
                .ToList();
            if (ranked.Count > 0)
            {
                double margin = ranked.Count == 1
                    ? double.MaxValue
                    : ranked[0].Score - ranked[1].Score;
                ranked[0].RequiresUserConfirmation =
                    ranked[0].Score < 90.0 || margin < 12.0;
            }
            return ranked;
        }

        private static bool IsEligibleMain(Pipe pipe)
        {
            LocationCurve location = pipe.Location as LocationCurve;
            if (location == null || location.Curve == null)
            {
                return false;
            }
            XYZ start = location.Curve.GetEndPoint(0);
            XYZ end = location.Curve.GetEndPoint(1);
            double horizontal = Math.Sqrt(
                Math.Pow(end.X - start.X, 2)
                + Math.Pow(end.Y - start.Y, 2));
            return horizontal > 0.1
                && Math.Abs(end.Z - start.Z)
                    / horizontal <= 0.20;
        }

        private static double DistanceToPipe(
            Pipe pipe,
            XYZ point)
        {
            LocationCurve location = pipe.Location as LocationCurve;
            if (location == null || location.Curve == null)
            {
                return double.MaxValue;
            }
            IntersectionResult projection =
                location.Curve.Project(point);
            return projection == null
                ? double.MaxValue
                : projection.XYZPoint.DistanceTo(point);
        }

        private static bool IsBelowSource(
            Pipe pipe,
            XYZ source)
        {
            LocationCurve location = pipe.Location as LocationCurve;
            IntersectionResult projection =
                location == null || location.Curve == null
                    ? null
                    : location.Curve.Project(source);
            return projection != null
                && projection.XYZPoint.Z
                    <= source.Z
                        + UnitUtils.ConvertToInternalUnits(
                            25,
                            UnitTypeId.Millimeters);
        }

        private static bool HasCompatibleSystem(
            Element source,
            Pipe target)
        {
            Pipe sourcePipe = source as Pipe;
            if (sourcePipe == null)
            {
                return true;
            }
            ElementId sourceSystem = sourcePipe.get_Parameter(
                BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)
                == null
                    ? ElementId.InvalidElementId
                    : sourcePipe.get_Parameter(
                        BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)
                        .AsElementId();
            ElementId targetSystem = target.get_Parameter(
                BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)
                == null
                    ? ElementId.InvalidElementId
                    : target.get_Parameter(
                        BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)
                        .AsElementId();
            return sourceSystem == ElementId.InvalidElementId
                || targetSystem == ElementId.InvalidElementId
                || sourceSystem == targetSystem;
        }
    }
}
