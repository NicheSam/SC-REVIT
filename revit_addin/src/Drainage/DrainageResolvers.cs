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
            Pipe pipe = element as Pipe;
            if (pipe != null
                && DrainageSourceResolver.IsVerticalPipe(pipe))
            {
                return true;
            }
            FamilyInstance instance = element as FamilyInstance;
            return instance != null
                && instance.Category != null
                && instance.Category.Id.Value
                    == (long)BuiltInCategory.OST_PlumbingFixtures;
        }

        public bool AllowReference(Reference reference, XYZ position)
        {
            return true;
        }
    }

    internal sealed class DrainageMainSelectionFilter :
        ISelectionFilter
    {
        public bool AllowElement(Element element)
        {
            Pipe pipe = element as Pipe;
            if (pipe == null)
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

            FamilyInstance fixture = sourceElement as FamilyInstance;
            if (fixture != null
                && fixture.Category != null
                && fixture.Category.Id.Value
                    == (long)BuiltInCategory.OST_PlumbingFixtures)
            {
                Connector connector = ResolveFixtureConnector(fixture);
                return new DrainageSourceRef
                {
                    SourceElement = fixture,
                    SourceConnector = connector,
                    Kind = DrainageSourceKind.PlumbingFixture,
                    PickPoint = pickPoint
                };
            }

            Pipe standpipe = sourceElement as Pipe;
            if (standpipe != null && IsVerticalPipe(standpipe))
            {
                Connector connector = ResolveOpenPipeEnd(
                    standpipe,
                    pickPoint);
                return new DrainageSourceRef
                {
                    SourceElement = standpipe,
                    SourceConnector = connector,
                    Kind = DrainageSourceKind.Standpipe,
                    PickPoint = pickPoint
                };
            }

            throw new InvalidOperationException(
                "SOURCE_NOT_SUPPORTED: 只接受衛生器具或有未連接端的立管。");
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

        private static Connector ResolveFixtureConnector(
            FamilyInstance fixture)
        {
            if (fixture.MEPModel == null
                || fixture.MEPModel.ConnectorManager == null)
            {
                throw new InvalidOperationException(
                    "SOURCE_CONNECTOR_MISSING: 衛生器具沒有 MEP connector。");
            }
            List<Connector> candidates = fixture.MEPModel
                .ConnectorManager
                .Connectors
                .Cast<Connector>()
                .Where(connector =>
                    connector.Domain == Domain.DomainPiping
                    && connector.ConnectorType
                        == ConnectorType.End
                    && !connector.IsConnected)
                .ToList();
            List<Connector> sanitary = candidates
                .Where(connector =>
                    string.Equals(
                        SafeSystemClassification(connector),
                        "Sanitary",
                        StringComparison.OrdinalIgnoreCase)
                    || string.Equals(
                        SafeSystemClassification(connector),
                        "Waste",
                        StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (sanitary.Count == 1)
            {
                return sanitary[0];
            }
            if (sanitary.Count == 0 && candidates.Count == 1)
            {
                return candidates[0];
            }
            if (sanitary.Count > 1 || candidates.Count > 1)
            {
                throw new InvalidOperationException(
                    "SOURCE_CONNECTOR_AMBIGUOUS: 衛生器具有多個未連接排水 connector。");
            }
            throw new InvalidOperationException(
                "SOURCE_CONNECTOR_MISSING: 衛生器具沒有可用的未連接排水 connector。");
        }

        private static Connector ResolveOpenPipeEnd(
            Pipe pipe,
            XYZ pickPoint)
        {
            List<Connector> candidates = pipe.ConnectorManager
                .Connectors
                .Cast<Connector>()
                .Where(connector =>
                    connector.ConnectorType
                        == ConnectorType.End
                    && !connector.IsConnected)
                .ToList();
            if (candidates.Count == 1)
            {
                return candidates[0];
            }
            if (candidates.Count == 0)
            {
                throw new InvalidOperationException(
                    "SOURCE_CONNECTOR_CONNECTED: 立管沒有未連接端。");
            }
            if (pickPoint == null)
            {
                throw new InvalidOperationException(
                    "SOURCE_CONNECTOR_AMBIGUOUS: 請靠近要接管的立管端點點選。");
            }
            Connector nearest = candidates
                .OrderBy(item => item.Origin.DistanceTo(pickPoint))
                .First();
            double secondDistance = candidates
                .OrderBy(item => item.Origin.DistanceTo(pickPoint))
                .Skip(1)
                .Select(item => item.Origin.DistanceTo(pickPoint))
                .FirstOrDefault();
            double firstDistance =
                nearest.Origin.DistanceTo(pickPoint);
            if (Math.Abs(secondDistance - firstDistance)
                < UnitUtils.ConvertToInternalUnits(
                    50,
                    UnitTypeId.Millimeters))
            {
                throw new InvalidOperationException(
                    "SOURCE_CONNECTOR_AMBIGUOUS: 無法判定立管接入端，請更靠近端點點選。");
            }
            return nearest;
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

            IEnumerable<Pipe> pipes = activeView != null
                ? new FilteredElementCollector(
                    document,
                    activeView.Id)
                    .OfClass(typeof(Pipe))
                    .Cast<Pipe>()
                : Enumerable.Empty<Pipe>();
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
                        sourceDiameterMm);
                double score = 100.0 - distance * 2.0;
                var evidence = new List<string>();
                if (configuration != null)
                {
                    score += 30.0;
                    evidence.Add("管類型有專案排水設定");
                }
                else
                {
                    score -= 50.0;
                    evidence.Add("管類型缺少專案排水設定");
                }
                if (IsBelowSource(pipe, source.SourceConnector.Origin))
                {
                    score += 15.0;
                    evidence.Add("幹管位於接入端下方");
                }
                if (HasCompatibleSystem(source.SourceElement, pipe))
                {
                    score += 20.0;
                    evidence.Add("系統類型相容");
                }
                ranked.Add(new DrainageTargetRef
                {
                    MainPipe = pipe,
                    Score = score,
                    DistanceFeet = distance,
                    Resolution = "BoundedActiveViewSearch",
                    Evidence = evidence
                });
            }

            ranked = ranked
                .OrderByDescending(item => item.Score)
                .ThenBy(item => item.DistanceFeet)
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
