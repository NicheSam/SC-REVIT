using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;
using RfaMetadataAddin.Drainage;
using System;
using System.Collections.Generic;
using System.Linq;

namespace RfaMetadataAddin
{
    [Transaction(TransactionMode.Manual)]
    public class AlignPipeCenterlineCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            UIDocument uiDocument =
                commandData.Application.ActiveUIDocument;
            if (uiDocument == null)
            {
                message = "請先開啟 Revit 專案。";
                return Result.Failed;
            }

            Document document = uiDocument.Document;
            try
            {
                Reference referencePick =
                    uiDocument.Selection.PickObject(
                        ObjectType.Element,
                        new DrainageRepairPipeFilter(
                            ElementId.InvalidElementId),
                        "1/2 點選高程基準管；按 Esc 結束");
                Pipe referencePipe =
                    document.GetElement(referencePick) as Pipe;
                if (referencePipe == null)
                {
                    return Result.Cancelled;
                }

                int successCount = 0;
                var failures = new List<string>();
                using (var group = new TransactionGroup(
                    document,
                    "管中心對齊"))
                {
                    group.Start();
                    while (true)
                    {
                        try
                        {
                            Reference targetPick =
                                uiDocument.Selection.PickObject(
                                    ObjectType.Element,
                                    new DrainageRepairPipeFilter(
                                        referencePipe.Id),
                                    "2/2 點選要對齊的獨立管段；可連續點選，按 Esc 結束");
                            Pipe targetPipe =
                                document.GetElement(targetPick) as Pipe;
                            using (var transaction =
                                new Transaction(
                                    document,
                                    "管中心對齊－單支"))
                            {
                                transaction.Start();
                                DrainageRepairService.AlignCenterlineElevation(
                                    referencePipe,
                                    targetPipe,
                                    DrainageRepairService.SafeGlobalPoint(
                                        targetPick));
                                transaction.Commit();
                                successCount++;
                            }
                        }
                        catch (Autodesk.Revit.Exceptions.OperationCanceledException)
                        {
                            break;
                        }
                        catch (Exception ex)
                        {
                            failures.Add(ex.Message);
                            TaskDialog.Show(
                                "管中心對齊－本支未修改",
                                ex.Message
                                + Environment.NewLine
                                + Environment.NewLine
                                + "按「確定」後可繼續選取；按 Esc 結束。");
                        }
                    }

                    if (successCount > 0)
                    {
                        group.Assimilate();
                    }
                    else
                    {
                        group.RollBack();
                    }
                }

                if (failures.Count > 0)
                {
                    TaskDialog.Show(
                        "管中心對齊",
                        "成功 " + successCount
                        + " 支；失敗 " + failures.Count + " 支。"
                        + Environment.NewLine
                        + string.Join(
                            Environment.NewLine,
                            failures.Take(8)));
                }
                return Result.Succeeded;
            }
            catch (Autodesk.Revit.Exceptions.OperationCanceledException)
            {
                return Result.Cancelled;
            }
            catch (Exception ex)
            {
                message = ex.Message;
                return Result.Failed;
            }
        }
    }

    [Transaction(TransactionMode.Manual)]
    public class ExtendPipeVerticallyDownCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            return DrainageRepairCommandRunner.RunSingle(
                commandData,
                ref message,
                "垂直向下",
                (document, source, referencePipe) =>
                    DrainageRepairService.CreateVerticalDown(
                        document,
                        source,
                        referencePipe));
        }
    }

    [Transaction(TransactionMode.Manual)]
    public class ExtendPipeDownFortyFiveCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            UIDocument uiDocument =
                commandData.Application.ActiveUIDocument;
            if (uiDocument == null)
            {
                message = "請先開啟 Revit 專案。";
                return Result.Failed;
            }
            Document document = uiDocument.Document;
            try
            {
                Reference sourcePick =
                    uiDocument.Selection.PickObject(
                        ObjectType.Element,
                        new DrainageSourceSelectionFilter(),
                        "1/2 點選要以單45°接入的設備接口或開放管端；按 Esc 結束");
                Element sourceElement =
                    document.GetElement(sourcePick);
                DrainageSourceRef source =
                    DrainageSourceResolver.Resolve(
                        sourceElement,
                        DrainageRepairService.SafeGlobalPoint(
                            sourcePick));
                double diameterMm =
                    DrainageSourceResolver.ReadDiameterMm(source);
                if (diameterMm <= 0)
                {
                    throw new InvalidOperationException(
                        "SOURCE_CONNECTOR_DIAMETER_UNRESOLVED");
                }

                Reference targetPick =
                    uiDocument.Selection.PickObject(
                        ObjectType.Element,
                        new DrainageMainSelectionFilter(
                            sourceElement.Id),
                        "2/2 點選要實際接入的目標主管");
                Pipe targetPipe =
                    document.GetElement(targetPick) as Pipe;
                if (targetPipe == null)
                {
                    throw new InvalidOperationException(
                        "TARGET_NOT_FOUND");
                }
                var target = new DrainageTargetRef
                {
                    MainPipe = targetPipe,
                    Score = 1000,
                    Resolution = "ExplicitUserPick",
                    RequiresUserConfirmation = false,
                    Evidence = new List<string>
                    {
                        "使用者明確點選向下45度的目標主管"
                    }
                };
                DrainageConfigurationProfile configuration =
                    DrainageConfigurationStore.ResolveForPipe(
                        document,
                        targetPipe,
                        diameterMm,
                        source);
                if (configuration == null)
                {
                    throw new InvalidOperationException(
                        "PROFILE_NOT_MATCHED：來源與目標主管沒有相符的 GravityDrainage Connection Profile。");
                }

                var workflow = new DrainageWorkflowService();
                DrainageRoutePlan plan = workflow.Plan(
                    commandData.Application,
                    new DrainageRouteRequest
                    {
                        Source = source,
                        Target = target,
                        Configuration = configuration,
                        DiameterMm = diameterMm,
                        MainDiameterMm =
                            ReadPipeDiameterMm(targetPipe),
                        DownstreamMode = "auto",
                        ActorKind =
                            DrainageActorKinds.HumanGui,
                        IdempotencyKey =
                            "DIK-DOWN45-"
                            + Guid.NewGuid().ToString("N")
                    });
                if (!string.Equals(
                    plan.RouteKind,
                    "single_45",
                    StringComparison.OrdinalIgnoreCase))
                {
                    DrainagePreviewServer.Clear(document);
                    uiDocument.RefreshActiveView();
                    throw new InvalidOperationException(
                        "DOWN45_ROUTE_NOT_SINGLE45：目前幾何求解結果為 "
                        + (string.IsNullOrWhiteSpace(plan.RouteKind)
                            ? "無可行路徑"
                            : plan.RouteKind)
                        + "，此按鈕只允許單一45°彎頭後直接接入主管。");
                }

                DrainageExecutionResult result =
                    workflow.Execute(
                        commandData.Application,
                        plan);
                if (!result.Succeeded)
                {
                    throw new InvalidOperationException(
                        result.Message);
                }
                return Result.Succeeded;
            }
            catch (Autodesk.Revit.Exceptions.OperationCanceledException)
            {
                DrainagePreviewServer.Clear(document);
                uiDocument.RefreshActiveView();
                return Result.Cancelled;
            }
            catch (Exception ex)
            {
                DrainagePreviewServer.Clear(document);
                uiDocument.RefreshActiveView();
                message = ex.Message;
                TaskDialog.Show(
                    "向下45°－未建立",
                    ex.Message);
                return Result.Failed;
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
    }

    [Transaction(TransactionMode.Manual)]
    public class ConnectPipeFortyFiveCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            UIDocument uiDocument =
                commandData.Application.ActiveUIDocument;
            if (uiDocument == null)
            {
                message = "請先開啟 Revit 專案。";
                return Result.Failed;
            }
            Document document = uiDocument.Document;
            try
            {
                DrainageRepairEndpoint source =
                    DrainageRepairService.PickOpenEndpoint(
                        uiDocument,
                        ElementId.InvalidElementId,
                        "1/2 點選較高管段的開放端；按 Esc 結束");
                DrainageRepairEndpoint target =
                    DrainageRepairService.PickOpenEndpoint(
                        uiDocument,
                        source.Pipe.Id,
                        "2/2 點選較低管段的開放端；兩端必須可用一段45°斜管接合");
                using (var transaction = new Transaction(
                    document,
                    "45度對接"))
                {
                    transaction.Start();
                    DrainageRepairService.CreateFortyFiveBridge(
                        document,
                        source,
                        target);
                    transaction.Commit();
                }
                return Result.Succeeded;
            }
            catch (Autodesk.Revit.Exceptions.OperationCanceledException)
            {
                return Result.Cancelled;
            }
            catch (Exception ex)
            {
                message = ex.Message;
                TaskDialog.Show(
                    "45度對接－未建立",
                    ex.Message);
                return Result.Failed;
            }
        }
    }

    internal static class DrainageRepairCommandRunner
    {
        internal delegate void RepairAction(
            Document document,
            DrainageRepairEndpoint source,
            Pipe referencePipe);

        public static Result RunSingle(
            ExternalCommandData commandData,
            ref string message,
            string commandName,
            RepairAction action)
        {
            UIDocument uiDocument =
                commandData.Application.ActiveUIDocument;
            if (uiDocument == null)
            {
                message = "請先開啟 Revit 專案。";
                return Result.Failed;
            }
            Document document = uiDocument.Document;
            try
            {
                DrainageRepairEndpoint source =
                    DrainageRepairService.PickOpenEndpoint(
                        uiDocument,
                        ElementId.InvalidElementId,
                        "1/2 點選要延伸的開放管端；按 Esc 結束");
                Reference referencePick =
                    uiDocument.Selection.PickObject(
                        ObjectType.Element,
                        new DrainageRepairPipeFilter(
                            source.Pipe.Id),
                        "2/2 點選高度基準管；只讀取中心線高程，不會接入該管");
                Pipe referencePipe =
                    document.GetElement(referencePick) as Pipe;
                using (var transaction =
                    new Transaction(document, commandName))
                {
                    transaction.Start();
                    action(document, source, referencePipe);
                    transaction.Commit();
                }
                return Result.Succeeded;
            }
            catch (Autodesk.Revit.Exceptions.OperationCanceledException)
            {
                return Result.Cancelled;
            }
            catch (Exception ex)
            {
                message = ex.Message;
                TaskDialog.Show(
                    commandName + "－未建立",
                    ex.Message);
                return Result.Failed;
            }
        }
    }
}

namespace RfaMetadataAddin.Drainage
{
    internal sealed class DrainageRepairPipeFilter :
        ISelectionFilter
    {
        private readonly ElementId _excludedId;

        public DrainageRepairPipeFilter(ElementId excludedId)
        {
            _excludedId = excludedId;
        }

        public bool AllowElement(Element element)
        {
            Pipe pipe = element as Pipe;
            return pipe != null
                && (_excludedId == null
                    || _excludedId == ElementId.InvalidElementId
                    || pipe.Id.Value != _excludedId.Value)
                && pipe.Location is LocationCurve;
        }

        public bool AllowReference(
            Reference reference,
            XYZ position)
        {
            return true;
        }
    }

    internal sealed class DrainageRepairOpenPipeFilter :
        ISelectionFilter
    {
        private readonly ElementId _excludedId;

        public DrainageRepairOpenPipeFilter(ElementId excludedId)
        {
            _excludedId = excludedId;
        }

        public bool AllowElement(Element element)
        {
            Pipe pipe = element as Pipe;
            return pipe != null
                && (_excludedId == null
                    || _excludedId == ElementId.InvalidElementId
                    || pipe.Id.Value != _excludedId.Value)
                && DrainageRepairService.GetOpenEndConnectors(pipe)
                    .Any();
        }

        public bool AllowReference(
            Reference reference,
            XYZ position)
        {
            return true;
        }
    }

    internal sealed class DrainageRepairEndpoint
    {
        public Pipe Pipe { get; set; }
        public Connector Connector { get; set; }
        public XYZ PickPoint { get; set; }
    }

    internal static class DrainageRepairService
    {
        private static readonly double OneMillimeter =
            UnitUtils.ConvertToInternalUnits(
                1,
                UnitTypeId.Millimeters);
        private static readonly double MinimumSegment =
            UnitUtils.ConvertToInternalUnits(
                100,
                UnitTypeId.Millimeters);
        private static readonly double MaximumDrop =
            UnitUtils.ConvertToInternalUnits(
                5000,
                UnitTypeId.Millimeters);

        public static XYZ SafeGlobalPoint(Reference reference)
        {
            try
            {
                return reference == null
                    ? null
                    : reference.GlobalPoint;
            }
            catch
            {
                return null;
            }
        }

        public static DrainageRepairEndpoint PickOpenEndpoint(
            UIDocument uiDocument,
            ElementId excludedId,
            string prompt)
        {
            Reference reference =
                uiDocument.Selection.PickObject(
                    ObjectType.Element,
                    new DrainageRepairOpenPipeFilter(excludedId),
                    prompt);
            Pipe pipe = uiDocument.Document.GetElement(
                reference) as Pipe;
            if (pipe == null)
            {
                throw new InvalidOperationException(
                    "REPAIR_SOURCE_NOT_PIPE");
            }
            XYZ pickPoint = SafeGlobalPoint(reference);
            IList<Connector> openEnds =
                GetOpenEndConnectors(pipe).ToList();
            if (openEnds.Count == 0)
            {
                throw new InvalidOperationException(
                    "REPAIR_OPEN_END_MISSING：選取管段沒有開放端。");
            }
            Connector selected = pickPoint == null
                ? openEnds.OrderBy(item => item.Origin.Z).First()
                : openEnds.OrderBy(
                    item => item.Origin.DistanceTo(pickPoint))
                    .First();
            return new DrainageRepairEndpoint
            {
                Pipe = pipe,
                Connector = selected,
                PickPoint = pickPoint
            };
        }

        public static IEnumerable<Connector> GetOpenEndConnectors(
            Pipe pipe)
        {
            return pipe == null
                || pipe.ConnectorManager == null
                ? Enumerable.Empty<Connector>()
                : pipe.ConnectorManager.Connectors
                    .Cast<Connector>()
                    .Where(item =>
                        item.Domain == Domain.DomainPiping
                        && item.ConnectorType == ConnectorType.End
                        && !item.IsConnected);
        }

        public static void AlignCenterlineElevation(
            Pipe referencePipe,
            Pipe targetPipe,
            XYZ targetPickPoint)
        {
            if (referencePipe == null || targetPipe == null)
            {
                throw new InvalidOperationException(
                    "CENTER_ALIGN_PIPE_MISSING");
            }
            if (targetPipe.Pinned)
            {
                throw new InvalidOperationException(
                    "CENTER_ALIGN_TARGET_PINNED：目標管已釘選。");
            }
            if (targetPipe.GroupId != ElementId.InvalidElementId)
            {
                throw new InvalidOperationException(
                    "CENTER_ALIGN_TARGET_GROUPED：目標管位於群組內。");
            }
            List<Connector> connectedEnds =
                GetEndConnectors(targetPipe)
                    .Where(item => item.IsConnected)
                    .ToList();
            if (connectedEnds.Count > 1)
            {
                throw new InvalidOperationException(
                    "CENTER_ALIGN_TARGET_FULLY_CONNECTED：目標管兩端都已連接；為避免扯動既有系統，不自動修改。");
            }

            Line referenceLine = ReadLine(referencePipe);
            Line targetLine = ReadLine(targetPipe);
            bool connectedAtStart = connectedEnds.Count == 1
                && connectedEnds[0].Origin.DistanceTo(
                    targetLine.GetEndPoint(0))
                    <= connectedEnds[0].Origin.DistanceTo(
                        targetLine.GetEndPoint(1));
            XYZ targetSample = connectedEnds.Count == 1
                ? connectedAtStart
                    ? targetLine.GetEndPoint(1)
                    : targetLine.GetEndPoint(0)
                : targetPickPoint
                    ?? targetLine.Evaluate(0.5, true);
            double referenceZ;
            double unusedParameter;
            if (!DrainageEngineeringCore.TryProjectPlanElevation(
                ToPoint(referenceLine.GetEndPoint(0)),
                ToPoint(referenceLine.GetEndPoint(1)),
                ToPoint(targetSample),
                out referenceZ,
                out unusedParameter))
            {
                throw new InvalidOperationException(
                    "CENTER_ALIGN_REFERENCE_VERTICAL：高程基準管不可為垂直管。");
            }

            double targetZ;
            if (!DrainageEngineeringCore.TryProjectPlanElevation(
                ToPoint(targetLine.GetEndPoint(0)),
                ToPoint(targetLine.GetEndPoint(1)),
                ToPoint(targetSample),
                out targetZ,
                out unusedParameter))
            {
                targetZ = targetLine.GetEndPoint(0).Z;
            }
            double deltaZ = referenceZ - targetZ;
            if (Math.Abs(deltaZ) <= OneMillimeter)
            {
                throw new InvalidOperationException(
                    "CENTER_ALIGN_ALREADY_ALIGNED：中心線高程差小於 1 mm。");
            }

            XYZ before0 = targetLine.GetEndPoint(0);
            XYZ before1 = targetLine.GetEndPoint(1);
            if (connectedEnds.Count == 1)
            {
                XYZ after0 = connectedAtStart
                    ? before0
                    : before0 + new XYZ(0, 0, deltaZ);
                XYZ after1 = connectedAtStart
                    ? before1 + new XYZ(0, 0, deltaZ)
                    : before1;
                if (after0.DistanceTo(after1)
                    <= targetPipe.Document.Application
                        .ShortCurveTolerance)
                {
                    throw new InvalidOperationException(
                        "CENTER_ALIGN_RESULT_TOO_SHORT");
                }
                LocationCurve targetLocation =
                    targetPipe.Location as LocationCurve;
                targetLocation.Curve =
                    Line.CreateBound(after0, after1);
            }
            else
            {
                ElementTransformUtils.MoveElement(
                    targetPipe.Document,
                    targetPipe.Id,
                    new XYZ(0, 0, deltaZ));
            }
            targetPipe.Document.Regenerate();
            Line after = ReadLine(targetPipe);
            if (connectedEnds.Count == 1)
            {
                XYZ anchoredBefore = connectedAtStart
                    ? before0
                    : before1;
                XYZ anchoredAfter = connectedAtStart
                    ? after.GetEndPoint(0)
                    : after.GetEndPoint(1);
                XYZ adjustedBefore = connectedAtStart
                    ? before1
                    : before0;
                XYZ adjustedAfter = connectedAtStart
                    ? after.GetEndPoint(1)
                    : after.GetEndPoint(0);
                Connector anchoredConnectorAfter =
                    GetEndConnectors(targetPipe)
                        .OrderBy(item =>
                            item.Origin.DistanceTo(anchoredBefore))
                        .FirstOrDefault();
                if (anchoredBefore.DistanceTo(anchoredAfter)
                        > OneMillimeter
                    || anchoredConnectorAfter == null
                    || anchoredConnectorAfter.Origin.DistanceTo(
                        anchoredBefore) > OneMillimeter
                    || !anchoredConnectorAfter.IsConnected
                    || Math.Abs(
                        adjustedAfter.Z
                        - adjustedBefore.Z
                        - deltaZ) > OneMillimeter
                    || Math.Abs(
                        adjustedAfter.X - adjustedBefore.X)
                        > OneMillimeter
                    || Math.Abs(
                        adjustedAfter.Y - adjustedBefore.Y)
                        > OneMillimeter)
                {
                    throw new InvalidOperationException(
                        "CENTER_ALIGN_CONNECTED_END_VERIFY_FAILED");
                }
            }
            else
            {
                ValidateVerticalTranslation(
                    before0,
                    before1,
                    after.GetEndPoint(0),
                    after.GetEndPoint(1),
                    deltaZ);
            }
        }

        public static void CreateVerticalDown(
            Document document,
            DrainageRepairEndpoint source,
            Pipe referencePipe)
        {
            ValidateSource(source);
            Line sourceLine = ReadLine(source.Pipe);
            XYZ sourceDirection =
                (sourceLine.GetEndPoint(1)
                    - sourceLine.GetEndPoint(0)).Normalize();
            if (Math.Abs(sourceDirection.Z) < 0.999)
            {
                throw new InvalidOperationException(
                    "VERTICAL_DOWN_SOURCE_NOT_VERTICAL：此命令只延伸垂直管；水平轉垂直請使用下翻彎。");
            }
            double targetZ = ReadReferenceElevation(
                referencePipe,
                source.Connector.Origin);
            XYZ start = source.Connector.Origin;
            XYZ end = new XYZ(start.X, start.Y, targetZ);
            double drop = start.Z - end.Z;
            ValidateDrop(drop, "VERTICAL_DOWN");
            if (!DrainageEngineeringCore
                .IsDownwardVerticalDisplacement(
                    end.X - start.X,
                    end.Y - start.Y,
                    end.Z - start.Z,
                    OneMillimeter,
                    MinimumSegment))
            {
                throw new InvalidOperationException(
                    "VERTICAL_DOWN_GEOMETRY_INVALID");
            }

            Pipe extension = Pipe.Create(
                document,
                source.Pipe.GetTypeId(),
                ReadLevelId(source.Pipe),
                source.Connector,
                end);
            CopyDiameter(source.Pipe, extension);
            document.Regenerate();
            if (!source.Connector.IsConnected)
            {
                throw new InvalidOperationException(
                    "VERTICAL_DOWN_CONNECTIVITY_INVALID");
            }
        }

        public static void CreateDownFortyFive(
            Document document,
            DrainageRepairEndpoint source,
            Pipe referencePipe)
        {
            ValidateSource(source);
            XYZ start = source.Connector.Origin;
            XYZ referencePoint = ReadReferencePlanPoint(
                referencePipe,
                start);
            double targetZ = referencePoint.Z;
            double drop = start.Z - targetZ;
            ValidateDrop(drop, "DOWN45");
            XYZ planVector = new XYZ(
                referencePoint.X - start.X,
                referencePoint.Y - start.Y,
                0);
            double availablePlan = planVector.GetLength();
            if (availablePlan + OneMillimeter < drop)
            {
                throw new InvalidOperationException(
                    "DOWN45_PLAN_SPACE_INSUFFICIENT：到高度基準管的平面距離小於所需 45° 水平投影。");
            }
            XYZ planDirection = planVector.Normalize();
            XYZ end = new XYZ(
                start.X + planDirection.X * drop,
                start.Y + planDirection.Y * drop,
                targetZ);
            if (!DrainageEngineeringCore
                .IsDownwardFortyFiveDisplacement(
                    end.X - start.X,
                    end.Y - start.Y,
                    end.Z - start.Z,
                    0.1,
                    MinimumSegment))
            {
                throw new InvalidOperationException(
                    "DOWN45_GEOMETRY_INVALID");
            }
            XYZ sourceAxis = ReadPipeAxis(source.Pipe);
            double sourceAngle = AcuteAngleDegrees(
                sourceAxis,
                end - start);
            if (Math.Abs(sourceAngle - 45.0) > 2.0)
            {
                throw new InvalidOperationException(
                    "DOWN45_SOURCE_ANGLE_INVALID：來源管軸與新管無法形成 45° 彎頭。");
            }

            Pipe segment = CreateUnconnectedPipe(
                document,
                source.Pipe,
                start,
                end);
            Connector segmentStart =
                FindConnectorNear(segment, start);
            FamilyInstance elbow =
                document.Create.NewElbowFitting(
                    source.Connector,
                    segmentStart);
            document.Regenerate();
            ValidateElbowAndConnection(
                elbow,
                source.Connector,
                segmentStart,
                "DOWN45");
        }

        public static void CreateFortyFiveBridge(
            Document document,
            DrainageRepairEndpoint source,
            DrainageRepairEndpoint target)
        {
            ValidateSource(source);
            ValidateSource(target);
            XYZ start = source.Connector.Origin;
            XYZ end = target.Connector.Origin;
            ValidateDrop(start.Z - end.Z, "FORTY_FIVE_BRIDGE");
            XYZ displacement = end - start;
            if (!DrainageEngineeringCore
                .IsDownwardFortyFiveDisplacement(
                    displacement.X,
                    displacement.Y,
                    displacement.Z,
                    2.0,
                    MinimumSegment))
            {
                throw new InvalidOperationException(
                    "FORTY_FIVE_BRIDGE_NOT_45：兩個開放端無法用一段 45° 斜管接合；請先用管中心對齊調整位置。");
            }
            if (Math.Abs(
                ReadDiameter(source.Pipe)
                - ReadDiameter(target.Pipe)) > OneMillimeter)
            {
                throw new InvalidOperationException(
                    "FORTY_FIVE_BRIDGE_DIAMETER_MISMATCH：第一階段 45 度對接只支援同徑管。");
            }
            if (ReadSystemTypeId(source.Pipe).Value
                != ReadSystemTypeId(target.Pipe).Value)
            {
                throw new InvalidOperationException(
                    "FORTY_FIVE_BRIDGE_SYSTEM_MISMATCH");
            }
            double sourceAngle = AcuteAngleDegrees(
                ReadPipeAxis(source.Pipe),
                displacement);
            double targetAngle = AcuteAngleDegrees(
                ReadPipeAxis(target.Pipe),
                displacement);
            if (Math.Abs(sourceAngle - 45.0) > 2.0
                || Math.Abs(targetAngle - 45.0) > 2.0)
            {
                throw new InvalidOperationException(
                    "FORTY_FIVE_BRIDGE_ENDPOINT_ANGLE_INVALID：斜管與兩支管都必須形成 45°。");
            }

            Pipe segment = CreateUnconnectedPipe(
                document,
                source.Pipe,
                start,
                end);
            Connector segmentStart =
                FindConnectorNear(segment, start);
            Connector segmentEnd =
                FindConnectorNear(segment, end);
            FamilyInstance first =
                document.Create.NewElbowFitting(
                    source.Connector,
                    segmentStart);
            FamilyInstance second =
                document.Create.NewElbowFitting(
                    target.Connector,
                    segmentEnd);
            document.Regenerate();
            ValidateElbowAndConnection(
                first,
                source.Connector,
                segmentStart,
                "FORTY_FIVE_BRIDGE_START");
            ValidateElbowAndConnection(
                second,
                target.Connector,
                segmentEnd,
                "FORTY_FIVE_BRIDGE_END");
        }

        private static void ValidateSource(
            DrainageRepairEndpoint source)
        {
            if (source == null
                || source.Pipe == null
                || source.Connector == null)
            {
                throw new InvalidOperationException(
                    "REPAIR_SOURCE_MISSING");
            }
            if (source.Connector.IsConnected)
            {
                throw new InvalidOperationException(
                    "REPAIR_SOURCE_ALREADY_CONNECTED");
            }
            if (source.Pipe.Pinned)
            {
                throw new InvalidOperationException(
                    "REPAIR_SOURCE_PINNED");
            }
        }

        private static void ValidateDrop(
            double drop,
            string code)
        {
            if (drop < MinimumSegment)
            {
                throw new InvalidOperationException(
                    code
                    + "_DROP_TOO_SMALL：來源端必須至少高於基準高程 100 mm。");
            }
            if (drop > MaximumDrop)
            {
                throw new InvalidOperationException(
                    code
                    + "_DROP_TOO_LARGE：垂直落差超過 5000 mm，已拒絕自動建立。");
            }
        }

        private static double ReadReferenceElevation(
            Pipe referencePipe,
            XYZ point)
        {
            return ReadReferencePlanPoint(
                referencePipe,
                point).Z;
        }

        private static XYZ ReadReferencePlanPoint(
            Pipe referencePipe,
            XYZ point)
        {
            Line line = ReadLine(referencePipe);
            XYZ start = line.GetEndPoint(0);
            XYZ end = line.GetEndPoint(1);
            double elevation;
            double parameter;
            if (!DrainageEngineeringCore.TryProjectPlanElevation(
                ToPoint(start),
                ToPoint(end),
                ToPoint(point),
                out elevation,
                out parameter))
            {
                throw new InvalidOperationException(
                    "REPAIR_REFERENCE_VERTICAL：高度基準管不可為垂直管。");
            }
            return new XYZ(
                start.X + (end.X - start.X) * parameter,
                start.Y + (end.Y - start.Y) * parameter,
                elevation);
        }

        private static Pipe CreateUnconnectedPipe(
            Document document,
            Pipe sourcePipe,
            XYZ start,
            XYZ end)
        {
            Pipe result = Pipe.Create(
                document,
                ReadSystemTypeId(sourcePipe),
                sourcePipe.GetTypeId(),
                ReadLevelId(sourcePipe),
                start,
                end);
            CopyDiameter(sourcePipe, result);
            document.Regenerate();
            return result;
        }

        private static void CopyDiameter(
            Pipe source,
            Pipe target)
        {
            Parameter sourceDiameter = source.get_Parameter(
                BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
            Parameter targetDiameter = target.get_Parameter(
                BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
            if (sourceDiameter == null
                || targetDiameter == null
                || targetDiameter.IsReadOnly)
            {
                throw new InvalidOperationException(
                    "REPAIR_DIAMETER_UNAVAILABLE");
            }
            targetDiameter.Set(sourceDiameter.AsDouble());
        }

        private static double ReadDiameter(Pipe pipe)
        {
            Parameter parameter = pipe.get_Parameter(
                BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
            return parameter == null ? 0 : parameter.AsDouble();
        }

        private static ElementId ReadSystemTypeId(Pipe pipe)
        {
            Parameter parameter = pipe.get_Parameter(
                BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM);
            ElementId id = parameter == null
                ? ElementId.InvalidElementId
                : parameter.AsElementId();
            if (id == ElementId.InvalidElementId)
            {
                throw new InvalidOperationException(
                    "REPAIR_SYSTEM_TYPE_UNRESOLVED");
            }
            return id;
        }

        private static ElementId ReadLevelId(Pipe pipe)
        {
            BuiltInParameter[] candidates =
            {
                BuiltInParameter.RBS_START_LEVEL_PARAM,
                BuiltInParameter.RBS_END_LEVEL_PARAM,
                BuiltInParameter.LEVEL_PARAM
            };
            foreach (BuiltInParameter candidate in candidates)
            {
                Parameter parameter =
                    pipe.get_Parameter(candidate);
                if (parameter == null
                    || parameter.StorageType != StorageType.ElementId)
                {
                    continue;
                }
                ElementId id = parameter.AsElementId();
                if (id != ElementId.InvalidElementId)
                {
                    return id;
                }
            }
            throw new InvalidOperationException(
                "REPAIR_LEVEL_UNRESOLVED");
        }

        private static IEnumerable<Connector> GetEndConnectors(
            Pipe pipe)
        {
            return pipe == null
                || pipe.ConnectorManager == null
                ? Enumerable.Empty<Connector>()
                : pipe.ConnectorManager.Connectors
                    .Cast<Connector>()
                    .Where(item =>
                        item.Domain == Domain.DomainPiping
                        && item.ConnectorType == ConnectorType.End);
        }

        private static Connector FindConnectorNear(
            Pipe pipe,
            XYZ point)
        {
            Connector connector = GetEndConnectors(pipe)
                .OrderBy(item => item.Origin.DistanceTo(point))
                .FirstOrDefault();
            if (connector == null
                || connector.Origin.DistanceTo(point)
                    > UnitUtils.ConvertToInternalUnits(
                        5,
                        UnitTypeId.Millimeters))
            {
                throw new InvalidOperationException(
                    "REPAIR_CREATED_CONNECTOR_MISSING");
            }
            return connector;
        }

        private static Line ReadLine(Pipe pipe)
        {
            LocationCurve location =
                pipe == null ? null : pipe.Location as LocationCurve;
            Line line = location == null
                ? null
                : location.Curve as Line;
            if (line == null)
            {
                throw new InvalidOperationException(
                    "REPAIR_PIPE_NOT_STRAIGHT");
            }
            return line;
        }

        private static XYZ ReadPipeAxis(Pipe pipe)
        {
            Line line = ReadLine(pipe);
            return (line.GetEndPoint(1)
                - line.GetEndPoint(0)).Normalize();
        }

        private static double AcuteAngleDegrees(
            XYZ first,
            XYZ second)
        {
            double dot = Math.Abs(
                first.Normalize().DotProduct(
                    second.Normalize()));
            dot = Math.Max(-1, Math.Min(1, dot));
            return Math.Acos(dot) * 180.0 / Math.PI;
        }

        private static void ValidateElbowAndConnection(
            FamilyInstance elbow,
            Connector first,
            Connector second,
            string code)
        {
            if (elbow == null
                || !first.IsConnected
                || !second.IsConnected)
            {
                throw new InvalidOperationException(
                    code
                    + "_ELBOW_CONNECTIVITY_INVALID");
            }
        }

        private static void ValidateVerticalTranslation(
            XYZ before0,
            XYZ before1,
            XYZ after0,
            XYZ after1,
            double expectedDelta)
        {
            bool valid =
                Math.Abs(after0.X - before0.X) <= OneMillimeter
                && Math.Abs(after0.Y - before0.Y) <= OneMillimeter
                && Math.Abs(after1.X - before1.X) <= OneMillimeter
                && Math.Abs(after1.Y - before1.Y) <= OneMillimeter
                && Math.Abs(
                    (after0.Z - before0.Z)
                    - expectedDelta) <= OneMillimeter
                && Math.Abs(
                    (after1.Z - before1.Z)
                    - expectedDelta) <= OneMillimeter;
            if (!valid)
            {
                throw new InvalidOperationException(
                    "CENTER_ALIGN_POST_VALIDATION_FAILED");
            }
        }

        private static DrainageGeometryPoint ToPoint(XYZ point)
        {
            return new DrainageGeometryPoint
            {
                X = point.X,
                Y = point.Y,
                Z = point.Z
            };
        }
    }
}
