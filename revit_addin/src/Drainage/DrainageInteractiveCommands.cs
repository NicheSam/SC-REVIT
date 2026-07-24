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
            Pipe pinnedMain = ResolvePinnedMain(
                document,
                uiDocument.Selection.GetElementIds());
            var targetResolver = new DrainageTargetResolver();
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
                                "點選器具或立管接入端；按 Esc 結束");
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

                        IList<DrainageTargetRef> candidates =
                            targetResolver.RankCandidates(
                                document,
                                document.ActiveView,
                                source,
                                pinnedMain);
                        DrainageTargetRef target =
                            candidates.FirstOrDefault();
                        if (target == null
                            || target.RequiresUserConfirmation)
                        {
                            target = PromptForMain(
                                uiDocument,
                                source);
                        }
                        DrainageConfigurationProfile configuration =
                            DrainageConfigurationStore.ResolveForPipe(
                                document,
                                target.MainPipe,
                                diameterMm);
                        if (configuration == null)
                        {
                            throw new System.InvalidOperationException(
                                "CONFIGURATION_MISSING: 目標幹管的 Pipe Type 沒有適用的排水管件設定。");
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
                                    DownstreamMode = "auto",
                                    ActorKind = "human_interactive",
                                    IdempotencyKey =
                                        "DIK-"
                                        + Guid.NewGuid().ToString("N")
                                });
                        if (!result.Succeeded)
                        {
                            failures.Add(
                                FormatFailure(
                                    sourceElement,
                                    result.Message));
                        }
                        else
                        {
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

        private static Pipe ResolvePinnedMain(
            Document document,
            ICollection<ElementId> selectedIds)
        {
            var filter = new DrainageMainSelectionFilter();
            List<Pipe> selectedPipes = selectedIds
                .Select(id => document.GetElement(id) as Pipe)
                .Where(pipe => pipe != null
                    && filter.AllowElement(pipe))
                .ToList();
            return selectedPipes.Count == 1
                ? selectedPipes[0]
                : null;
        }

        private static DrainageTargetRef PromptForMain(
            UIDocument uiDocument,
            DrainageSourceRef source)
        {
            Reference reference =
                uiDocument.Selection.PickObject(
                    ObjectType.Element,
                    new DrainageMainSelectionFilter(),
                    "候選幹管不明確，請點選本支要接入的幹管");
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
            return "ID "
                + (source == null
                    ? "?"
                    : source.Id.Value.ToString())
                + "："
                + (string.IsNullOrWhiteSpace(reason)
                    ? "接管失敗"
                    : reason);
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
