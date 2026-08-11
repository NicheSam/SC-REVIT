using Autodesk.Revit.DB;
using System;
using System.Collections.Generic;
using System.Linq;

namespace RfaMetadataAddin
{
    public partial class RfaMetadataApplication
    {
        private const int CadPathMaximumSegments = 50000;

        private class CadPathSegment
        {
            public XYZ Start { get; set; }
            public XYZ End { get; set; }
            public XYZ Direction { get; set; }
            public string Layer { get; set; }
        }

        private class CadPathSource
        {
            public ImportInstance ImportInstance { get; set; }
            public string Name { get; set; }
            public string Path { get; set; }
            public bool Conformal { get; set; }
            public bool Truncated { get; set; }
            public int AnchorCount { get; set; }
            public double MaximumAnchorResidualMm { get; set; }
            public bool AnchorGeometrySufficient { get; set; }
            public bool CoordinateVerified { get; set; }
            public int RawSegmentCount { get; set; }
            public int OutOfScopeSegmentCount { get; set; }
            public List<CadPathSegment> Segments { get; private set; }

            public CadPathSource()
            {
                Segments = new List<CadPathSegment>();
            }
        }

        private class CadPathExtractionScope
        {
            public double Buffer { get; set; }
            public List<Line> Corridors { get; private set; }

            public CadPathExtractionScope()
            {
                Corridors = new List<Line>();
            }
        }

        private class CadPathMatchSummary
        {
            public CadPathSource Source { get; set; }
            public int SampleCount { get; set; }
            public int MatchedSampleCount { get; set; }
            public double CoverageRatio { get; set; }
            public double MeanOffsetMm { get; set; }
            public double MaxOffsetMm { get; set; }
            public int JunctionCount { get; set; }
            public int MatchedJunctionCount { get; set; }
            public double TopologyMatchRatio { get; set; }
            public double Score { get; set; }
            public Dictionary<string, int> MatchedLayers { get; private set; }

            public CadPathMatchSummary()
            {
                MatchedLayers = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            }
        }

        private class CadPathSpatialIndex
        {
            private readonly double _cellSize;
            private readonly Dictionary<string, List<CadPathSegment>> _cells;

            public CadPathSpatialIndex(IEnumerable<CadPathSegment> segments, double cellSize, double expansion)
            {
                _cellSize = cellSize;
                _cells = new Dictionary<string, List<CadPathSegment>>(StringComparer.Ordinal);
                foreach (CadPathSegment segment in segments)
                {
                    double length = DistanceXY(segment.Start, segment.End);
                    int steps = Math.Max(1, Math.Min(2000, (int)Math.Ceiling(length / (_cellSize * 0.5))));
                    int neighborRange = Math.Max(1, (int)Math.Ceiling(expansion / _cellSize));
                    for (int step = 0; step <= steps; step++)
                    {
                        double parameter = (double)step / steps;
                        XYZ point = segment.Start + (segment.End - segment.Start) * parameter;
                        int centerX = Cell(point.X);
                        int centerY = Cell(point.Y);
                        for (int offsetX = -neighborRange; offsetX <= neighborRange; offsetX++)
                        {
                            for (int offsetY = -neighborRange; offsetY <= neighborRange; offsetY++)
                            {
                                string key = Key(centerX + offsetX, centerY + offsetY);
                                List<CadPathSegment> bucket;
                                if (!_cells.TryGetValue(key, out bucket))
                                {
                                    bucket = new List<CadPathSegment>();
                                    _cells[key] = bucket;
                                }
                                if (!bucket.Contains(segment))
                                {
                                    bucket.Add(segment);
                                }
                            }
                        }
                    }
                }
            }

            public IEnumerable<CadPathSegment> Near(XYZ point)
            {
                List<CadPathSegment> bucket;
                return _cells.TryGetValue(Key(Cell(point.X), Cell(point.Y)), out bucket)
                    ? bucket
                    : Enumerable.Empty<CadPathSegment>();
            }

            private int Cell(double value)
            {
                return (int)Math.Floor(value / _cellSize);
            }

            private static string Key(int x, int y)
            {
                return x.ToString() + ":" + y.ToString();
            }
        }

        private static object BuildFireBranchCadPathShadowReport(
            Document doc,
            List<List<FireBranchItem>> rows,
            double branchZ,
            double extension)
        {
            double distanceTolerance = UnitUtils.ConvertToInternalUnits(150, UnitTypeId.Millimeters);
            double topologyProbeDistance = UnitUtils.ConvertToInternalUnits(300, UnitTypeId.Millimeters);
            double sampleSpacing = UnitUtils.ConvertToInternalUnits(500, UnitTypeId.Millimeters);
            double cellSize = UnitUtils.ConvertToInternalUnits(1000, UnitTypeId.Millimeters);
            double junctionTolerance = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Millimeters);
            double corridorBuffer = UnitUtils.ConvertToInternalUnits(1000, UnitTypeId.Millimeters);
            double angleToleranceDegrees = 15;

            List<Line> plannedSegments = BuildFireBranchPlannedLines(rows, branchZ, extension);
            var extractionScope = new CadPathExtractionScope { Buffer = corridorBuffer };
            extractionScope.Corridors.AddRange(plannedSegments);
            List<CadPathSource> sources = ReadVisibleCadPathSources(doc, extractionScope);
            if (sources.Count == 0)
            {
                return new
                {
                    mode = "shadow",
                    status = "cad_unavailable",
                    evidence_level = "geometry_only",
                    source_count = 0,
                    warning_codes = new[] { "cad_source_not_visible" }
                };
            }

            List<FireBranchJunctionPlan> junctionPlans = BuildFireBranchJunctionPlans(
                rows,
                junctionTolerance,
                branchZ);
            var summaries = new List<CadPathMatchSummary>();
            foreach (CadPathSource source in sources)
            {
                summaries.Add(MatchCadPathSource(
                    source,
                    plannedSegments,
                    junctionPlans,
                    distanceTolerance,
                    topologyProbeDistance,
                    sampleSpacing,
                    cellSize,
                    angleToleranceDegrees));
            }
            summaries = summaries.OrderByDescending(item => item.Score).ToList();
            CadPathMatchSummary best = summaries.First();
            CadPathMatchSummary second = summaries.Skip(1).FirstOrDefault();
            bool sourceAmbiguous = second != null
                && second.CoverageRatio >= 0.5
                && best.Score - second.Score < 0.05;

            string status;
            string confidence;
            var warningCodes = new List<string>();
            if (best.Source.Segments.Count == 0)
            {
                status = "cad_no_paths";
                confidence = "low";
                warningCodes.Add("cad_curve_geometry_not_found");
            }
            else if (sourceAmbiguous)
            {
                status = "ambiguous_source";
                confidence = "review";
                warningCodes.Add("multiple_cad_sources_match");
            }
            else if (best.CoverageRatio >= 0.8 && best.TopologyMatchRatio >= 0.8)
            {
                status = "matched";
                confidence = "high";
            }
            else if (best.CoverageRatio < 0.3)
            {
                status = "mismatch";
                confidence = "low";
                warningCodes.Add("cad_route_coverage_low");
            }
            else
            {
                status = "ambiguous";
                confidence = "review";
                warningCodes.Add("cad_route_match_inconclusive");
            }
            if (!best.Source.Conformal)
            {
                status = "invalid_transform";
                confidence = "low";
                warningCodes.Add("cad_transform_non_conformal");
            }
            else if (best.Source.MaximumAnchorResidualMm > 1.0)
            {
                status = "invalid_transform";
                confidence = "low";
                warningCodes.Add("cad_anchor_residual_exceeded");
            }
            else if (!best.Source.AnchorGeometrySufficient)
            {
                warningCodes.Add("cad_anchor_unverified");
            }
            if (best.Source.Truncated)
            {
                warningCodes.Add("cad_segment_limit_reached");
            }

            var sourceResults = summaries.Select(summary => new
            {
                import_id = summary.Source.ImportInstance.Id.Value,
                name = summary.Source.Name,
                path = summary.Source.Path,
                is_linked = summary.Source.ImportInstance.IsLinked,
                conformal = summary.Source.Conformal,
                coordinate_verified = summary.Source.CoordinateVerified,
                anchor_count = summary.Source.AnchorCount,
                anchor_geometry_sufficient = summary.Source.AnchorGeometrySufficient,
                max_anchor_residual_mm = summary.Source.MaximumAnchorResidualMm,
                raw_segment_count = summary.Source.RawSegmentCount,
                out_of_scope_segment_count = summary.Source.OutOfScopeSegmentCount,
                segment_count = summary.Source.Segments.Count,
                truncated = summary.Source.Truncated,
                coverage_ratio = summary.CoverageRatio,
                topology_match_ratio = summary.TopologyMatchRatio,
                score = summary.Score
            }).ToList();
            var matchedLayers = best.MatchedLayers
                .OrderByDescending(item => item.Value)
                .Take(10)
                .Select(item => new { name = item.Key, matched_samples = item.Value })
                .ToList();

            return new
            {
                mode = "shadow",
                status = status,
                confidence = confidence,
                evidence_level = best.Source.CoordinateVerified
                    ? "geometry_with_verified_transform"
                    : "geometry_only",
                coordinate_contract = "cad_geometry_to_import_total_transform_to_revit_model",
                extraction_scope = "selected_sprinkler_route_corridors",
                corridor_buffer_mm = 1000,
                affects_creation = false,
                source_count = sources.Count,
                selected_import_id = best.Source.ImportInstance.Id.Value,
                selected_source_name = best.Source.Name,
                selected_source_path = best.Source.Path,
                coordinate_verified = best.Source.CoordinateVerified,
                anchor_count = best.Source.AnchorCount,
                anchor_geometry_sufficient = best.Source.AnchorGeometrySufficient,
                max_anchor_residual_mm = best.Source.MaximumAnchorResidualMm,
                planned_segment_count = plannedSegments.Count,
                raw_cad_segment_count = best.Source.RawSegmentCount,
                out_of_scope_segment_count = best.Source.OutOfScopeSegmentCount,
                cad_segment_count = best.Source.Segments.Count,
                sample_count = best.SampleCount,
                matched_sample_count = best.MatchedSampleCount,
                coverage_ratio = best.CoverageRatio,
                mean_offset_mm = best.MeanOffsetMm,
                max_offset_mm = best.MaxOffsetMm,
                junction_count = best.JunctionCount,
                matched_junction_count = best.MatchedJunctionCount,
                topology_match_ratio = best.TopologyMatchRatio,
                distance_tolerance_mm = 150,
                angle_tolerance_degrees = angleToleranceDegrees,
                matched_layers = matchedLayers,
                sources = sourceResults,
                warning_codes = warningCodes
            };
        }

        private static List<Line> BuildFireBranchPlannedLines(
            List<List<FireBranchItem>> rows,
            double branchZ,
            double extension)
        {
            var result = new List<Line>();
            foreach (List<FireBranchItem> row in rows)
            {
                double rowMain = row.Average(item => item.MainParameter);
                double rowMin = 0 - extension;
                double rowMax = row.Max(item => item.BranchParameter) + extension;
                XYZ mainStart = row[0].MainStart;
                XYZ mainDirection = row[0].MainDirection;
                XYZ branchDirection = row[0].BranchDirection;
                XYZ start = new XYZ(
                    mainStart.X + mainDirection.X * rowMain + branchDirection.X * rowMin,
                    mainStart.Y + mainDirection.Y * rowMain + branchDirection.Y * rowMin,
                    branchZ);
                XYZ end = new XYZ(
                    mainStart.X + mainDirection.X * rowMain + branchDirection.X * rowMax,
                    mainStart.Y + mainDirection.Y * rowMain + branchDirection.Y * rowMax,
                    branchZ);
                if (start.DistanceTo(end) > 0.001)
                {
                    result.Add(Line.CreateBound(start, end));
                }
            }
            return result;
        }

        private static List<CadPathSource> ReadVisibleCadPathSources(
            Document doc,
            CadPathExtractionScope extractionScope)
        {
            var result = new List<CadPathSource>();
            View activeView = doc.ActiveView;
            if (activeView == null)
            {
                return result;
            }
            Options options = new Options
            {
                ComputeReferences = false,
                IncludeNonVisibleObjects = false,
                View = activeView
            };
            foreach (ImportInstance importInstance in new FilteredElementCollector(doc, activeView.Id)
                .OfClass(typeof(ImportInstance))
                .Cast<ImportInstance>()
                .OrderBy(item => item.Id.Value))
            {
                Autodesk.Revit.DB.Transform importTransform = importInstance.GetTotalTransform();
                var source = new CadPathSource
                {
                    ImportInstance = importInstance,
                    Name = GetCadImportTypeName(doc, importInstance),
                    Path = GetCadImportPath(doc, importInstance),
                    Conformal = importTransform.IsConformal
                };
                try
                {
                    GeometryElement geometry = importInstance.get_Geometry(options);
                    if (geometry != null)
                    {
                        foreach (GeometryObject item in geometry)
                        {
                            GeometryInstance root = item as GeometryInstance;
                            if (root != null)
                            {
                                TraverseCadPathGeometry(
                                    doc,
                                    root.GetSymbolGeometry(),
                                    root.Transform,
                                    source,
                                    extractionScope);
                            }
                            else
                            {
                                AddCadPathGeometryObject(
                                    doc,
                                    item,
                                    importTransform,
                                    source,
                                    extractionScope);
                            }
                            if (source.Truncated)
                            {
                                break;
                            }
                        }
                    }
                }
                catch
                {
                    source.Segments.Clear();
                }
                ReadCadPathCoordinateEvidence(doc, importInstance, source);
                result.Add(source);
            }
            return result;
        }

        private static void ReadCadPathCoordinateEvidence(
            Document doc,
            ImportInstance importInstance,
            CadPathSource source)
        {
            try
            {
                List<Dictionary<string, object>> anchors = ScanCadBlockPoints(
                    doc,
                    importInstance,
                    "",
                    50);
                source.AnchorCount = anchors.Count;
                source.MaximumAnchorResidualMm = 0;
                bool allConformal = source.Conformal;
                foreach (Dictionary<string, object> anchor in anchors)
                {
                    if (anchor.ContainsKey("conformal") && !Convert.ToBoolean(anchor["conformal"]))
                    {
                        allConformal = false;
                    }
                    if (anchor.ContainsKey("anchor_residual_mm"))
                    {
                        source.MaximumAnchorResidualMm = Math.Max(
                        source.MaximumAnchorResidualMm,
                            Convert.ToDouble(anchor["anchor_residual_mm"]));
                    }
                }
                source.AnchorGeometrySufficient = HasNonCollinearCadPathAnchors(anchors);
                source.CoordinateVerified = source.AnchorGeometrySufficient
                    && allConformal
                    && source.MaximumAnchorResidualMm <= 1.0;
            }
            catch
            {
                source.AnchorCount = 0;
                source.MaximumAnchorResidualMm = 0;
                source.AnchorGeometrySufficient = false;
                source.CoordinateVerified = false;
            }
        }

        private static bool HasNonCollinearCadPathAnchors(
            List<Dictionary<string, object>> anchors)
        {
            if (anchors.Count < 3)
            {
                return false;
            }
            double areaTolerance = Math.Pow(
                UnitUtils.ConvertToInternalUnits(1, UnitTypeId.Millimeters),
                2);
            for (int first = 0; first < anchors.Count - 2; first++)
            {
                double ax = Convert.ToDouble(anchors[first]["x"]);
                double ay = Convert.ToDouble(anchors[first]["y"]);
                for (int second = first + 1; second < anchors.Count - 1; second++)
                {
                    double bx = Convert.ToDouble(anchors[second]["x"]);
                    double by = Convert.ToDouble(anchors[second]["y"]);
                    for (int third = second + 1; third < anchors.Count; third++)
                    {
                        double cx = Convert.ToDouble(anchors[third]["x"]);
                        double cy = Convert.ToDouble(anchors[third]["y"]);
                        double twiceArea = Math.Abs(
                            (bx - ax) * (cy - ay)
                            - (by - ay) * (cx - ax));
                        if (twiceArea > areaTolerance)
                        {
                            return true;
                        }
                    }
                }
            }
            return false;
        }

        private static void TraverseCadPathGeometry(
            Document doc,
            GeometryElement geometry,
            Autodesk.Revit.DB.Transform pathTransform,
            CadPathSource source,
            CadPathExtractionScope extractionScope)
        {
            if (geometry == null || source.Truncated)
            {
                return;
            }
            foreach (GeometryObject item in geometry)
            {
                GeometryInstance instance = item as GeometryInstance;
                if (instance != null)
                {
                    try
                    {
                        TraverseCadPathGeometry(
                            doc,
                            instance.GetSymbolGeometry(),
                            pathTransform.Multiply(instance.Transform),
                            source,
                            extractionScope);
                    }
                    catch
                    {
                    }
                }
                else
                {
                    AddCadPathGeometryObject(
                        doc,
                        item,
                        pathTransform,
                        source,
                        extractionScope);
                }
                if (source.Truncated)
                {
                    return;
                }
            }
        }

        private static void AddCadPathGeometryObject(
            Document doc,
            GeometryObject item,
            Autodesk.Revit.DB.Transform transform,
            CadPathSource source,
            CadPathExtractionScope extractionScope)
        {
            string layer = GetCadPathLayerName(doc, item);
            PolyLine polyLine = item as PolyLine;
            if (polyLine != null)
            {
                IList<XYZ> points = polyLine.GetCoordinates();
                for (int index = 1; index < points.Count; index++)
                {
                    AddCadPathSegment(
                        source,
                        transform.OfPoint(points[index - 1]),
                        transform.OfPoint(points[index]),
                        layer,
                        extractionScope);
                }
                return;
            }

            Curve curve = item as Curve;
            if (curve == null)
            {
                return;
            }
            IList<XYZ> tessellated;
            try
            {
                tessellated = curve.Tessellate();
            }
            catch
            {
                return;
            }
            for (int index = 1; index < tessellated.Count; index++)
            {
                AddCadPathSegment(
                    source,
                    transform.OfPoint(tessellated[index - 1]),
                    transform.OfPoint(tessellated[index]),
                    layer,
                    extractionScope);
            }
        }

        private static void AddCadPathSegment(
            CadPathSource source,
            XYZ start,
            XYZ end,
            string layer,
            CadPathExtractionScope extractionScope)
        {
            XYZ direction = NormalizeXY(end - start);
            double length = DistanceXY(start, end);
            if (direction.GetLength() < 0.001
                || length < UnitUtils.ConvertToInternalUnits(50, UnitTypeId.Millimeters))
            {
                return;
            }
            source.RawSegmentCount += 1;
            if (!CadPathSegmentIntersectsScope(start, end, extractionScope))
            {
                source.OutOfScopeSegmentCount += 1;
                return;
            }
            if (source.Segments.Count >= CadPathMaximumSegments)
            {
                source.Truncated = true;
                return;
            }
            source.Segments.Add(new CadPathSegment
            {
                Start = start,
                End = end,
                Direction = direction,
                Layer = layer
            });
        }

        private static bool CadPathSegmentIntersectsScope(
            XYZ start,
            XYZ end,
            CadPathExtractionScope extractionScope)
        {
            if (extractionScope == null || extractionScope.Corridors.Count == 0)
            {
                return false;
            }
            foreach (Line corridor in extractionScope.Corridors)
            {
                XYZ corridorStart = corridor.GetEndPoint(0);
                XYZ corridorEnd = corridor.GetEndPoint(1);
                if (CadPathSegmentsIntersectXY(start, end, corridorStart, corridorEnd))
                {
                    return true;
                }
                double distance = Math.Min(
                    Math.Min(
                        DistancePointToSegmentXY(start, corridorStart, corridorEnd),
                        DistancePointToSegmentXY(end, corridorStart, corridorEnd)),
                    Math.Min(
                        DistancePointToSegmentXY(corridorStart, start, end),
                        DistancePointToSegmentXY(corridorEnd, start, end)));
                if (distance <= extractionScope.Buffer)
                {
                    return true;
                }
            }
            return false;
        }

        private static bool CadPathSegmentsIntersectXY(
            XYZ firstStart,
            XYZ firstEnd,
            XYZ secondStart,
            XYZ secondEnd)
        {
            double firstSideA = CrossXY(firstStart, firstEnd, secondStart);
            double firstSideB = CrossXY(firstStart, firstEnd, secondEnd);
            double secondSideA = CrossXY(secondStart, secondEnd, firstStart);
            double secondSideB = CrossXY(secondStart, secondEnd, firstEnd);
            double tolerance = 0.000001;
            return firstSideA * firstSideB <= tolerance
                && secondSideA * secondSideB <= tolerance
                && Math.Max(Math.Min(firstStart.X, firstEnd.X), Math.Min(secondStart.X, secondEnd.X))
                    <= Math.Min(Math.Max(firstStart.X, firstEnd.X), Math.Max(secondStart.X, secondEnd.X)) + tolerance
                && Math.Max(Math.Min(firstStart.Y, firstEnd.Y), Math.Min(secondStart.Y, secondEnd.Y))
                    <= Math.Min(Math.Max(firstStart.Y, firstEnd.Y), Math.Max(secondStart.Y, secondEnd.Y)) + tolerance;
        }

        private static double CrossXY(XYZ lineStart, XYZ lineEnd, XYZ point)
        {
            return (lineEnd.X - lineStart.X) * (point.Y - lineStart.Y)
                - (lineEnd.Y - lineStart.Y) * (point.X - lineStart.X);
        }

        private static string GetCadPathLayerName(Document doc, GeometryObject item)
        {
            try
            {
                if (item == null || item.GraphicsStyleId == ElementId.InvalidElementId)
                {
                    return "";
                }
                GraphicsStyle style = doc.GetElement(item.GraphicsStyleId) as GraphicsStyle;
                Category category = style != null ? style.GraphicsStyleCategory : null;
                return category != null ? category.Name ?? "" : "";
            }
            catch
            {
                return "";
            }
        }

        private static CadPathMatchSummary MatchCadPathSource(
            CadPathSource source,
            List<Line> plannedSegments,
            List<FireBranchJunctionPlan> junctionPlans,
            double distanceTolerance,
            double topologyProbeDistance,
            double sampleSpacing,
            double cellSize,
            double angleToleranceDegrees)
        {
            var summary = new CadPathMatchSummary { Source = source };
            if (source.Segments.Count == 0)
            {
                return summary;
            }
            var index = new CadPathSpatialIndex(source.Segments, cellSize, distanceTolerance);
            double offsetSum = 0;
            double maximumOffset = 0;
            foreach (Line planned in plannedSegments)
            {
                XYZ start = planned.GetEndPoint(0);
                XYZ end = planned.GetEndPoint(1);
                XYZ direction = NormalizeXY(end - start);
                double length = DistanceXY(start, end);
                int sampleCount = Math.Max(3, Math.Min(80, (int)Math.Ceiling(length / sampleSpacing) + 1));
                for (int sampleIndex = 0; sampleIndex < sampleCount; sampleIndex++)
                {
                    double parameter = sampleCount == 1 ? 0 : (double)sampleIndex / (sampleCount - 1);
                    XYZ point = start + (end - start) * parameter;
                    summary.SampleCount += 1;
                    CadPathSegment match;
                    double distance;
                    if (!TryFindCadPathMatch(
                        index,
                        point,
                        direction,
                        distanceTolerance,
                        angleToleranceDegrees,
                        out match,
                        out distance))
                    {
                        continue;
                    }
                    summary.MatchedSampleCount += 1;
                    offsetSum += distance;
                    maximumOffset = Math.Max(maximumOffset, distance);
                    string layer = string.IsNullOrWhiteSpace(match.Layer) ? "(unknown)" : match.Layer;
                    summary.MatchedLayers[layer] = summary.MatchedLayers.ContainsKey(layer)
                        ? summary.MatchedLayers[layer] + 1
                        : 1;
                }
            }
            summary.CoverageRatio = summary.SampleCount > 0
                ? (double)summary.MatchedSampleCount / summary.SampleCount
                : 0;
            summary.MeanOffsetMm = summary.MatchedSampleCount > 0
                ? offsetSum / summary.MatchedSampleCount * 304.8
                : 0;
            summary.MaxOffsetMm = maximumOffset * 304.8;

            foreach (FireBranchJunctionPlan plan in junctionPlans)
            {
                summary.JunctionCount += 1;
                if (CadPathJunctionMatches(
                    index,
                    plan,
                    distanceTolerance,
                    topologyProbeDistance,
                    angleToleranceDegrees))
                {
                    summary.MatchedJunctionCount += 1;
                }
            }
            summary.TopologyMatchRatio = summary.JunctionCount > 0
                ? (double)summary.MatchedJunctionCount / summary.JunctionCount
                : 0;
            summary.Score = summary.CoverageRatio * 0.8 + summary.TopologyMatchRatio * 0.2;
            return summary;
        }

        private static bool CadPathJunctionMatches(
            CadPathSpatialIndex index,
            FireBranchJunctionPlan plan,
            double distanceTolerance,
            double probeDistance,
            double angleToleranceDegrees)
        {
            FireBranchItem first = plan.Rows[0][0];
            XYZ tiePoint = new XYZ(
                first.MainStart.X + first.MainDirection.X * plan.MainParameter,
                first.MainStart.Y + first.MainDirection.Y * plan.MainParameter,
                first.MainZ);
            var directions = new List<XYZ>
            {
                first.MainDirection,
                first.MainDirection.Negate()
            };
            foreach (List<FireBranchItem> row in plan.Rows)
            {
                XYZ branchDirection = row[0].BranchDirection;
                if (!directions.Any(item => DotXY(item, branchDirection) > 0.999))
                {
                    directions.Add(branchDirection);
                }
            }
            foreach (XYZ direction in directions)
            {
                XYZ probe = tiePoint + direction * probeDistance;
                CadPathSegment match;
                double distance;
                if (!TryFindCadPathMatch(
                    index,
                    probe,
                    direction,
                    distanceTolerance,
                    angleToleranceDegrees,
                    out match,
                    out distance))
                {
                    return false;
                }
            }
            return true;
        }

        private static bool TryFindCadPathMatch(
            CadPathSpatialIndex index,
            XYZ point,
            XYZ direction,
            double distanceTolerance,
            double angleToleranceDegrees,
            out CadPathSegment match,
            out double distance)
        {
            match = null;
            distance = double.MaxValue;
            foreach (CadPathSegment candidate in index.Near(point))
            {
                double alignment = Math.Max(-1, Math.Min(1, Math.Abs(DotXY(direction, candidate.Direction))));
                double angle = Math.Acos(alignment) * 180.0 / Math.PI;
                if (angle > angleToleranceDegrees)
                {
                    continue;
                }
                double candidateDistance = DistancePointToSegmentXY(point, candidate.Start, candidate.End);
                if (candidateDistance <= distanceTolerance && candidateDistance < distance)
                {
                    match = candidate;
                    distance = candidateDistance;
                }
            }
            return match != null;
        }

        private static double DistancePointToSegmentXY(XYZ point, XYZ start, XYZ end)
        {
            double dx = end.X - start.X;
            double dy = end.Y - start.Y;
            double lengthSquared = dx * dx + dy * dy;
            if (lengthSquared < 0.0000001)
            {
                return DistanceXY(point, start);
            }
            double parameter = ((point.X - start.X) * dx + (point.Y - start.Y) * dy) / lengthSquared;
            parameter = Math.Max(0, Math.Min(1, parameter));
            double nearestX = start.X + dx * parameter;
            double nearestY = start.Y + dy * parameter;
            double offsetX = point.X - nearestX;
            double offsetY = point.Y - nearestY;
            return Math.Sqrt(offsetX * offsetX + offsetY * offsetY);
        }

        private static double DistanceXY(XYZ a, XYZ b)
        {
            double dx = a.X - b.X;
            double dy = a.Y - b.Y;
            return Math.Sqrt(dx * dx + dy * dy);
        }
    }
}
