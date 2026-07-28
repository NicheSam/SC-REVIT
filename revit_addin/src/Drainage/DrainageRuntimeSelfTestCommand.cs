using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.UI;
using RfaMetadataAddin.Drainage;
using System;
using System.Collections.Generic;
using System.Linq;

namespace RfaMetadataAddin
{
    [Transaction(TransactionMode.Manual)]
    public class DrainageRuntimeSelfTestCommand : IExternalCommand
    {
        private const string TestTagPrefix =
            "SC_DRAINAGE_RUNTIME_TEST:";

        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            UIDocument uiDocument =
                commandData.Application.ActiveUIDocument;
            if (uiDocument == null)
            {
                message = "REVIT_DOCUMENT_REQUIRED";
                return Result.Failed;
            }

            Document document = uiDocument.Document;
            var results = new List<string>();
            try
            {
                RunCenterlineTest(document, results);
            }
            catch (Exception ex)
            {
                results.Add(
                    "CENTER_ALIGN: FAIL - " + ex.Message);
            }

            try
            {
                RunDownFortyFiveTest(
                    commandData.Application,
                    results);
            }
            catch (Exception ex)
            {
                results.Add(
                    "DOWN45: FAIL - " + ex.Message);
            }

            TaskDialog.Show(
                "SC Drainage Runtime Self Test",
                string.Join(
                    Environment.NewLine,
                    results));
            return Result.Succeeded;
        }

        private static void RunCenterlineTest(
            Document document,
            IList<string> results)
        {
            Pipe referencePipe = FindTaggedPipe(
                document,
                "CENTER_REFERENCE");
            Pipe targetPipe = FindTaggedPipe(
                document,
                "CENTER_TARGET_GT100MM");
            if (referencePipe == null || targetPipe == null)
            {
                throw new InvalidOperationException(
                    "CENTER_FIXTURES_MISSING");
            }

            Line referenceBefore = ReadLine(referencePipe);
            Line targetBefore = ReadLine(targetPipe);
            XYZ targetSample =
                targetBefore.Evaluate(0.5, true);
            double expectedZ;
            double unusedParameter;
            if (!DrainageEngineeringCore
                .TryProjectPlanElevation(
                    ToPoint(referenceBefore.GetEndPoint(0)),
                    ToPoint(referenceBefore.GetEndPoint(1)),
                    ToPoint(targetSample),
                    out expectedZ,
                    out unusedParameter))
            {
                throw new InvalidOperationException(
                    "CENTER_REFERENCE_INVALID");
            }

            double beforeZ =
                targetBefore.GetEndPoint(0).Z;
            double deltaMm =
                UnitUtils.ConvertFromInternalUnits(
                    expectedZ - beforeZ,
                    UnitTypeId.Millimeters);
            if (Math.Abs(deltaMm) <= 100.0)
            {
                throw new InvalidOperationException(
                    "CENTER_DELTA_NOT_GREATER_THAN_100MM");
            }

            using (var transaction =
                new Transaction(
                    document,
                    "SC test - center align"))
            {
                transaction.Start();
                DrainageRepairService
                    .AlignCenterlineElevation(
                        referencePipe,
                        targetPipe,
                        targetSample);
                transaction.Commit();
            }

            Line targetAfter = ReadLine(targetPipe);
            bool xyPreserved =
                NearlyEqual(
                    targetBefore.GetEndPoint(0).X,
                    targetAfter.GetEndPoint(0).X)
                && NearlyEqual(
                    targetBefore.GetEndPoint(0).Y,
                    targetAfter.GetEndPoint(0).Y)
                && NearlyEqual(
                    targetBefore.GetEndPoint(1).X,
                    targetAfter.GetEndPoint(1).X)
                && NearlyEqual(
                    targetBefore.GetEndPoint(1).Y,
                    targetAfter.GetEndPoint(1).Y);
            bool zAligned =
                NearlyEqual(
                    expectedZ,
                    targetAfter.GetEndPoint(0).Z)
                && NearlyEqual(
                    expectedZ,
                    targetAfter.GetEndPoint(1).Z);
            if (!xyPreserved || !zAligned)
            {
                throw new InvalidOperationException(
                    "CENTER_POSTCONDITION_FAILED");
            }

            results.Add(
                "CENTER_ALIGN: PASS"
                + " | reference="
                + referencePipe.Id.Value
                + " | target="
                + targetPipe.Id.Value
                + " | delta_mm="
                + Math.Round(deltaMm, 1));
        }

        private static void RunDownFortyFiveTest(
            UIApplication uiApplication,
            IList<string> results)
        {
            Document document =
                uiApplication.ActiveUIDocument.Document;
            DrainageConfigurationProfile profile =
                DrainageConfigurationStore
                    .Load(document)
                    .Profiles
                    .Where(item =>
                        item != null
                        && item.Enabled
                        && item.PipeTypeId > 0
                        && item.TargetSystemTypeId > 0)
                    .OrderBy(item => item.ProfileId)
                    .FirstOrDefault();
            if (profile == null)
            {
                throw new InvalidOperationException(
                    "PROFILE_NOT_MATCHED");
            }

            Pipe mainPipe = FindTaggedPipe(
                document,
                "DOWN45_MAIN");
            Pipe sourcePipe = FindTaggedPipe(
                document,
                "DOWN45_SOURCE");
            if (mainPipe == null || sourcePipe == null)
            {
                CreateDownFortyFiveFixtures(
                    document,
                    profile,
                    out mainPipe,
                    out sourcePipe);
            }

            Line sourceLine = ReadLine(sourcePipe);
            XYZ sourcePick =
                sourceLine.GetEndPoint(0).Z
                < sourceLine.GetEndPoint(1).Z
                    ? sourceLine.GetEndPoint(0)
                    : sourceLine.GetEndPoint(1);
            DrainageSourceRef source =
                DrainageSourceResolver.Resolve(
                    sourcePipe,
                    sourcePick);
            double sourceDiameterMm =
                DrainageSourceResolver
                    .ReadDiameterMm(source);
            DrainageConfigurationProfile resolved =
                DrainageConfigurationStore
                    .ResolveForPipe(
                        document,
                        mainPipe,
                        sourceDiameterMm,
                        source);
            if (resolved == null)
            {
                throw new InvalidOperationException(
                    "PROFILE_NOT_MATCHED_FOR_FIXTURE");
            }

            var target = new DrainageTargetRef
            {
                MainPipe = mainPipe,
                Score = 1000.0,
                Resolution = "RuntimeSelfTest",
                RequiresUserConfirmation = false,
                Evidence = new List<string>
                {
                    "Explicit tagged runtime fixture"
                }
            };
            var request = new DrainageRouteRequest
            {
                Source = source,
                Target = target,
                Configuration = resolved,
                DiameterMm = sourceDiameterMm,
                MainDiameterMm =
                    ReadDiameterMm(mainPipe),
                DownstreamMode = "auto",
                ActorKind = DrainageActorKinds.HumanGui,
                IdempotencyKey =
                    "DIK-RUNTIME-"
                    + Guid.NewGuid().ToString("N")
            };
            var workflow = new DrainageWorkflowService();
            DrainageRoutePlan plan =
                workflow.Plan(
                    uiApplication,
                    request);
            if (!string.Equals(
                plan.RouteKind,
                "single_45",
                StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException(
                    "DOWN45_ROUTE_NOT_SINGLE45"
                    + " | route="
                    + (plan.RouteKind ?? "")
                    + " | issues="
                    + string.Join(",", plan.Issues));
            }

            DrainageExecutionResult execution =
                workflow.Execute(
                    uiApplication,
                    plan);
            if (!execution.Succeeded)
            {
                throw new InvalidOperationException(
                    execution.Message);
            }

            int fittingCount =
                execution.CreatedElementIds
                    .Select(document.GetElement)
                    .Count(item =>
                        item != null
                        && item.Category != null
                        && item.Category.Id.Value
                        == (long)BuiltInCategory
                            .OST_PipeFitting);
            results.Add(
                "DOWN45: PASS"
                + " | source="
                + sourcePipe.Id.Value
                + " | main="
                + mainPipe.Id.Value
                + " | route="
                + plan.RouteKind
                + " | created="
                + execution.CreatedElementIds.Count
                + " | fittings="
                + fittingCount);
        }

        private static void CreateDownFortyFiveFixtures(
            Document document,
            DrainageConfigurationProfile profile,
            out Pipe mainPipe,
            out Pipe sourcePipe)
        {
            Pipe template =
                new FilteredElementCollector(document)
                    .OfCategory(
                        BuiltInCategory.OST_PipeCurves)
                    .WhereElementIsNotElementType()
                    .Cast<Pipe>()
                    .FirstOrDefault(item =>
                        item.GetTypeId().Value
                        == profile.PipeTypeId);
            if (template == null)
            {
                throw new InvalidOperationException(
                    "PROFILE_PIPE_TEMPLATE_MISSING");
            }

            IList<Pipe> existing =
                new FilteredElementCollector(document)
                    .OfCategory(
                        BuiltInCategory.OST_PipeCurves)
                    .WhereElementIsNotElementType()
                    .Cast<Pipe>()
                    .ToList();
            double maxX = existing
                .SelectMany(item =>
                {
                    Line line = ReadLine(item);
                    return new[]
                    {
                        line.GetEndPoint(0).X,
                        line.GetEndPoint(1).X
                    };
                })
                .Max();
            double maxY = existing
                .SelectMany(item =>
                {
                    Line line = ReadLine(item);
                    return new[]
                    {
                        line.GetEndPoint(0).Y,
                        line.GetEndPoint(1).Y
                    };
                })
                .Max();
            double x = maxX + 50.0;
            double y = maxY + 50.0;

            using (var transaction =
                new Transaction(
                    document,
                    "SC test - down45 fixtures"))
            {
                transaction.Start();
                mainPipe = Pipe.Create(
                    document,
                    new ElementId(
                        profile.TargetSystemTypeId),
                    new ElementId(profile.PipeTypeId),
                    template.LevelId,
                    new XYZ(x, y, -25.0),
                    new XYZ(x + 30.0, y, -25.3));
                sourcePipe = Pipe.Create(
                    document,
                    new ElementId(
                        profile.TargetSystemTypeId),
                    new ElementId(profile.PipeTypeId),
                    template.LevelId,
                    new XYZ(x + 10.0, y - 10.0, -12.0),
                    new XYZ(x + 10.0, y - 10.0, -15.0));
                SetDiameterMm(mainPipe, 100.0);
                SetDiameterMm(sourcePipe, 80.0);
                SetTag(mainPipe, "DOWN45_MAIN");
                SetTag(sourcePipe, "DOWN45_SOURCE");
                transaction.Commit();
            }
        }

        private static Pipe FindTaggedPipe(
            Document document,
            string suffix)
        {
            string expected = TestTagPrefix + suffix;
            return new FilteredElementCollector(document)
                .OfCategory(
                    BuiltInCategory.OST_PipeCurves)
                .WhereElementIsNotElementType()
                .Cast<Pipe>()
                .FirstOrDefault(item =>
                {
                    Parameter parameter =
                        item.get_Parameter(
                            BuiltInParameter
                                .ALL_MODEL_INSTANCE_COMMENTS);
                    return parameter != null
                        && string.Equals(
                            parameter.AsString(),
                            expected,
                            StringComparison.Ordinal);
                });
        }

        private static void SetTag(
            Pipe pipe,
            string suffix)
        {
            Parameter parameter =
                pipe.get_Parameter(
                    BuiltInParameter
                        .ALL_MODEL_INSTANCE_COMMENTS);
            if (parameter != null && !parameter.IsReadOnly)
            {
                parameter.Set(TestTagPrefix + suffix);
            }
        }

        private static void SetDiameterMm(
            Pipe pipe,
            double diameterMm)
        {
            Parameter parameter =
                pipe.get_Parameter(
                    BuiltInParameter
                        .RBS_PIPE_DIAMETER_PARAM);
            if (parameter == null || parameter.IsReadOnly)
            {
                throw new InvalidOperationException(
                    "PIPE_DIAMETER_NOT_WRITABLE");
            }
            parameter.Set(
                UnitUtils.ConvertToInternalUnits(
                    diameterMm,
                    UnitTypeId.Millimeters));
        }

        private static double ReadDiameterMm(
            Pipe pipe)
        {
            Parameter parameter =
                pipe.get_Parameter(
                    BuiltInParameter
                        .RBS_PIPE_DIAMETER_PARAM);
            return parameter == null
                ? 0.0
                : UnitUtils.ConvertFromInternalUnits(
                    parameter.AsDouble(),
                    UnitTypeId.Millimeters);
        }

        private static Line ReadLine(Pipe pipe)
        {
            LocationCurve location =
                pipe == null
                    ? null
                    : pipe.Location as LocationCurve;
            Line line =
                location == null
                    ? null
                    : location.Curve as Line;
            if (line == null)
            {
                throw new InvalidOperationException(
                    "PIPE_LINE_REQUIRED");
            }
            return line;
        }

        private static DrainageGeometryPoint ToPoint(
            XYZ point)
        {
            return new DrainageGeometryPoint
            {
                X = point.X,
                Y = point.Y,
                Z = point.Z
            };
        }

        private static bool NearlyEqual(
            double left,
            double right)
        {
            return Math.Abs(left - right) <= 0.000001;
        }
    }
}
