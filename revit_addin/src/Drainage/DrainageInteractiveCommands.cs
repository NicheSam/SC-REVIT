using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.Exceptions;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;
using System;
using System.Collections.Generic;
using System.Linq;
using RfaMetadataAddin.Drainage;

namespace RfaMetadataAddin
{
    [Transaction(TransactionMode.Manual)]
    public class ConnectDrainageToMainCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            UIApplication uiApplication =
                commandData.Application;
            UIDocument uiDocument =
                uiApplication.ActiveUIDocument;
            if (uiDocument == null)
            {
                message = "請先開啟 Revit 專案。";
                return Result.Failed;
            }

            Document document = uiDocument.Document;
            var workflow = new DrainageWorkflowService();
            var failures = new List<string>();
            int successCount = 0;

            using (var group = new TransactionGroup(
                document,
                "排水接入幹管"))
            {
                group.Start();
                while (true)
                {
                    try
                    {
                        Reference sourceReference =
                            uiDocument.Selection.PickObject(
                                 ObjectType.Element,
                                 new DrainageSourceSelectionFilter(),
                                 "1/2 點選設備接口或任意開放管端；按 Esc 結束");
                        Element sourceElement = document.GetElement(
                            sourceReference);
                        DrainageSourceRef source =
                            DrainageSourceResolver.Resolve(
                                sourceElement,
                                SafeGlobalPoint(sourceReference));
                        double diameterMm =
                            DrainageSourceResolver.ReadDiameterMm(
                                source);
                        if (diameterMm <= 0)
                        {
                            throw new System.InvalidOperationException(
                                "SOURCE_CONNECTOR_DIAMETER_UNRESOLVED");
                        }

                        DrainageTargetRef target = PromptForMain(
                            uiDocument,
                            source);
                        DrainageConfigurationProfile configuration =
                            DrainageConfigurationStore.ResolveForPipe(
                                 document,
                                 target.MainPipe,
                                 diameterMm,
                                 source);
                         if (configuration == null)
                         {
                             throw new System.InvalidOperationException(
                                 "PROFILE_NOT_MATCHED: 來源 connector 與目標幹管沒有相符的 GravityDrainage Connection Profile。");
                        }

                        DrainageExecutionResult result =
                            workflow.Connect(
                                uiApplication,
                                new DrainageRouteRequest
                                {
                                    Source = source,
                                    Target = target,
                                    Configuration = configuration,
                                    DiameterMm = diameterMm,
                                    MainDiameterMm =
                                        ReadPipeDiameterMm(
                                            target.MainPipe),
                                    DownstreamMode = "auto",
                                    ActorKind =
                                        DrainageActorKinds.HumanGui,
                                    IdempotencyKey =
                                        "DIK-"
                                        + Guid.NewGuid().ToString("N")
                                });
                        if (!result.Succeeded)
                        {
                            string failure = FormatFailure(
                                sourceElement,
                                result.Message);
                            failures.Add(failure);
                            ClearActivePreview(uiDocument);
                            ShowBranchFailure(failure);
                        }
                        else
                        {
                            successCount++;
                        }
                    }
                    catch (Autodesk.Revit.Exceptions.OperationCanceledException)
                    {
                        ClearActivePreview(uiDocument);
                        break;
                    }
                    catch (Exception ex)
                    {
                        failures.Add(ex.Message);
                        ClearActivePreview(uiDocument);
                        ShowBranchFailure(ex.Message);
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
                    "排水接入幹管",
                    "成功 " + successCount
                    + " 支；失敗 " + failures.Count
                    + " 支。"
                    + Environment.NewLine
                    + Environment.NewLine
                    + string.Join(
                        Environment.NewLine,
                        failures.Take(10)));
            }
            return Result.Succeeded;
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

        private static void ClearActivePreview(
            UIDocument uiDocument)
        {
            if (uiDocument == null)
            {
                return;
            }
            DrainagePreviewServer.Clear(uiDocument.Document);
            uiDocument.RefreshActiveView();
        }

        private static void ShowBranchFailure(string failure)
        {
            TaskDialog.Show(
                "排水接入幹管－本支未建立",
                failure
                + Environment.NewLine
                + Environment.NewLine
                + "按「確定」後可繼續點選下一支；按 Esc 結束命令。");
        }

        private static DrainageTargetRef PromptForMain(
            UIDocument uiDocument,
            DrainageSourceRef source)
        {
            Reference reference =
                uiDocument.Selection.PickObject(
                    ObjectType.Element,
                    new DrainageMainSelectionFilter(
                        source == null
                            || source.SourceElement == null
                            ? ElementId.InvalidElementId
                            : source.SourceElement.Id),
                    "2/2 點選本支要接入的目標主管；按 Esc 結束");
            Pipe pipe = uiDocument.Document.GetElement(
                reference) as Pipe;
            if (pipe == null)
            {
                throw new System.InvalidOperationException(
                    "TARGET_NOT_FOUND");
            }
            return new DrainageTargetRef
            {
                MainPipe = pipe,
                Score = 1000,
                Resolution = "ExplicitUserPick",
                RequiresUserConfirmation = false,
                Evidence = new List<string>
                {
                    "使用者明確點選幹管"
                }
            };
        }

        private static XYZ SafeGlobalPoint(Reference reference)
        {
            try
            {
                return reference.GlobalPoint;
            }
            catch
            {
                return null;
            }
        }

        private static string FormatFailure(
            Element source,
            string reason)
        {
            string userReason = reason;
            if (!string.IsNullOrWhiteSpace(reason)
                && reason.IndexOf(
                    "SOURCE_BELOW_TARGET_MAIN",
                    StringComparison.OrdinalIgnoreCase) >= 0)
            {
                userReason =
                    "SOURCE_BELOW_TARGET_MAIN：支管接口低於目標主管中心線高程，"
                    + "重力排水不得向上接入。";
            }
            else if (!string.IsNullOrWhiteSpace(reason)
                && reason.IndexOf(
                    "SINGLE45_TANGENT_TOO_SHORT",
                    StringComparison.OrdinalIgnoreCase) >= 0
                && reason.IndexOf(
                    "DOUBLE_45_TANGENT_TOO_SHORT",
                    StringComparison.OrdinalIgnoreCase) >= 0)
            {
                userReason =
                    "NO_FEASIBLE_ROUTE：正向 45° 與雙 45° 所需的直管、"
                    + "管件 takeout 或高程空間不足；已禁止用反向折返假接。"
                    + "請調整來源或主管高程，或增加可用接管範圍。";
            }
            return "ID "
                + (source == null
                    ? "?"
                    : source.Id.Value.ToString())
                + "："
                + (string.IsNullOrWhiteSpace(userReason)
                    ? "接管失敗"
                    : userReason);
        }
    }

    [Transaction(TransactionMode.Manual)]
    public class OpenDrainageConfigurationCommand :
        IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            try
            {
                var window = new DrainageConfigurationWindow(
                    commandData.Application);
                window.ShowDialog();
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = ex.Message;
                return Result.Failed;
            }
        }
    }
}
