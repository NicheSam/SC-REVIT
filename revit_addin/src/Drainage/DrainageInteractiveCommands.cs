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
            var warnings = new List<string>();
            int successCount = 0;

            using (var group = new TransactionGroup(
                document,
                "排水接入幹管"))
            {
                group.Start();
                while (true)
                {
                    Element sourceElement = null;
                    try
                    {
                        Reference sourceReference =
                            uiDocument.Selection.PickObject(
                                 ObjectType.Element,
                                 new DrainageSourceSelectionFilter(),
                                 "1/2 點選設備接口或任意開放管端；按 Esc 結束");
                        sourceElement = document.GetElement(
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

                        var request = new DrainageRouteRequest
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
                        };
                        DrainageExecutionResult result =
                            workflow
                                .ConnectResolvingAmbiguousDownstream(
                                uiApplication,
                                request);
                        if (!result.Succeeded)
                        {
                            string failure = FormatFailure(
                                sourceElement,
                                result.FailureCode,
                                result.Message);
                            failures.Add(failure);
                            ClearActivePreview(uiDocument);
                            ShowBranchFailure(failure);
                        }
                        else
                        {
                            successCount++;
                            if (result.Warnings != null
                                && result.Warnings.Contains(
                                    "LONG_TRANSITION_USED"))
                            {
                                warnings.Add(
                                    "來源 ID "
                                    + sourceElement.Id.Value
                                    + "：已建立，但斜接段仍長於偏好值；請檢查現場空間。");
                            }
                        }
                    }
                    catch (Autodesk.Revit.Exceptions.OperationCanceledException)
                    {
                        ClearActivePreview(uiDocument);
                        break;
                    }
                    catch (Exception ex)
                    {
                        string failure = FormatFailure(
                            sourceElement,
                            DrainageFailureCode.CommitFailed,
                            ex.Message);
                        failures.Add(failure);
                        ClearActivePreview(uiDocument);
                        ShowBranchFailure(failure);
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

            if (failures.Count > 0
                || warnings.Count > 0)
            {
                var summaryLines = new List<string>();
                if (failures.Count > 0)
                {
                    summaryLines.AddRange(
                        failures.Take(10));
                }
                if (warnings.Count > 0)
                {
                    if (summaryLines.Count > 0)
                    {
                        summaryLines.Add("");
                    }
                    summaryLines.Add("提示：");
                    summaryLines.AddRange(
                        warnings.Take(10));
                }
                TaskDialog.Show(
                    "排水接入幹管",
                    "成功 " + successCount
                    + " 支；失敗 " + failures.Count
                    + " 支。"
                    + Environment.NewLine
                    + Environment.NewLine
                    + string.Join(
                        Environment.NewLine,
                        summaryLines));
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
            DrainageFailureCode failureCode,
            string reason)
        {
            string title;
            string cause;
            string action;
            DescribeFailure(
                failureCode,
                reason,
                out title,
                out cause,
                out action);
            return "無法建立：" + title
                + Environment.NewLine
                + "原因：" + cause
                + Environment.NewLine
                + "處理方式：" + action
                + Environment.NewLine
                + Environment.NewLine
                + "技術資訊：來源 ID "
                + (source == null
                    ? "?"
                    : source.Id.Value.ToString())
                + "｜"
                + ReadPrimaryFailureCode(reason, failureCode);
        }

        private static void DescribeFailure(
            DrainageFailureCode failureCode,
            string reason,
            out string title,
            out string cause,
            out string action)
        {
            string value = reason ?? "";
            if (value.IndexOf(
                    "PERPENDICULAR_DROP_TOO_LONG",
                    StringComparison.OrdinalIgnoreCase) >= 0)
            {
                title = "直連斜管過長";
                cause =
                    "直接吸收高差的斜管超過目前管徑允許的長度，"
                    + "而其他彎頭路型也沒有足夠安裝空間。";
                action =
                    "請增加主管附近的轉折空間、縮短接管距離，"
                    + "或調整支管與主管的相對位置。";
                return;
            }
            if (value.IndexOf(
                    "MAIN_DOWNSTREAM_UNRESOLVED",
                    StringComparison.OrdinalIgnoreCase) >= 0
                || failureCode
                    == DrainageFailureCode.TargetDownstreamUnresolved)
            {
                title = "無法判斷主管流向";
                cause =
                    "所選主管的坡度或連接關係不足，無法可靠確認哪一端是下游。"
                    + "系統已停止，避免斜 T／Y 方向放反。";
                action =
                    "請改選流向明確的主管；若主管為水平管，"
                    + "先建立可辨識的坡度或上下游連接關係後再試。";
                return;
            }
            if (value.IndexOf(
                    "SOURCE_BELOW_TARGET_MAIN",
                    StringComparison.OrdinalIgnoreCase) >= 0
                || failureCode
                    == DrainageFailureCode.SourceBelowTargetMain)
            {
                title = "支管低於主管";
                cause =
                    "支管接口低於目標主管中心線，重力排水路徑會向上回流。";
                action =
                    "請降低主管、提高支管，或改選較低且符合流向的主管。";
                return;
            }
            if (value.IndexOf(
                    "PROFILE_NOT_MATCHED",
                    StringComparison.OrdinalIgnoreCase) >= 0
                || failureCode == DrainageFailureCode.ProfileNotMatched)
            {
                title = "找不到適用的管件設定";
                cause =
                    "來源接口、系統、管型或管徑沒有符合的排水設定列。";
                action =
                    "請開啟「管件設定」，確認目標 Pipe Type、"
                    + "系統類型、管徑範圍與管件後儲存。";
                return;
            }
            if (value.IndexOf(
                    "SOURCE_CONNECTOR_AMBIGUOUS",
                    StringComparison.OrdinalIgnoreCase) >= 0
                || failureCode
                    == DrainageFailureCode.SourceConnectorAmbiguous)
            {
                title = "無法確定要使用哪個接口";
                cause =
                    "所選物件有多個條件相近的開放管接口。";
                action =
                    "請靠近要接管的端點點選；必要時先封閉或接妥其他接口。";
                return;
            }
            if (value.IndexOf(
                    "SOURCE_CONNECTOR",
                    StringComparison.OrdinalIgnoreCase) >= 0
                || failureCode
                    == DrainageFailureCode.SourceConnectorMissing)
            {
                title = "找不到可用的支管接口";
                cause =
                    "所選物件沒有可用的開放圓形 piping connector，"
                    + "或接口尺寸無法讀取。";
                action =
                    "請點選開放管端，並檢查族群 connector 的領域、"
                    + "形狀、方向與管徑。";
                return;
            }
            if (value.IndexOf(
                    "TARGET_FITTING_CLEARANCE_CONFLICT",
                    StringComparison.OrdinalIgnoreCase) >= 0
                || failureCode
                    == DrainageFailureCode
                        .TargetFittingClearanceConflict)
            {
                title = "主管既有管件會與新接頭衝突";
                cause =
                    "可行的斜接位置落在主管既有彎頭、三通或其必要安裝淨距內。";
                action =
                    "請改選既有管件外側的主管管段，或先調整主管上的管件位置。技術資訊中的 ID 是阻擋管件。";
                return;
            }
            if (value.IndexOf(
                    "TARGET_SEGMENT_CAPACITY_INSUFFICIENT",
                    StringComparison.OrdinalIgnoreCase) >= 0
                || failureCode
                    == DrainageFailureCode
                        .TargetSegmentCapacityInsufficient)
            {
                title = "所選主管管段長度不足";
                cause =
                    "系統已嘗試延長支管開放端，但斜 T／Y 仍會超出所選主管管段的可用範圍。";
                action =
                    "請選擇較長的相鄰主管管段，或調整主管端點與既有接頭；這不是支管距離太近。";
                return;
            }
            if (value.IndexOf(
                    "SOURCE_GEOMETRY_ADJUSTMENT",
                    StringComparison.OrdinalIgnoreCase) >= 0
                || value.IndexOf(
                    "SOURCE_CONNECTED_END_VERIFY_FAILED",
                    StringComparison.OrdinalIgnoreCase) >= 0
                || failureCode
                    == DrainageFailureCode
                        .SourceGeometryAdjustmentBlocked)
            {
                title = "無法安全調整支管長度";
                cause =
                    "自動斜接需要延長支管開放端，但來源管的另一端連接或拓撲無法保持不變。";
                action =
                    "請確認點選端是開放端，並檢查另一端設備或管件連接；模型已回復到操作前狀態。";
                return;
            }
            if (value.IndexOf(
                    "TANGENT_TOO_SHORT",
                    StringComparison.OrdinalIgnoreCase) >= 0
                || failureCode
                    == DrainageFailureCode.MinimumTangentViolation)
            {
                title = "管件安裝空間不足";
                cause =
                    "45° 彎頭、斜 T／Y 的 takeout 或最短直管無法容納。";
                action =
                    "請拉開支管與主管的距離，或改選遠離主管端點及既有管件的位置。";
                return;
            }
            if (value.IndexOf(
                    "NO_FEASIBLE_ROUTE",
                    StringComparison.OrdinalIgnoreCase) >= 0
                || failureCode == DrainageFailureCode.NoFeasibleRoute
                || failureCode == DrainageFailureCode.RouteBlocked
                || failureCode
                    == DrainageFailureCode.SourceAxisRouteUnresolved)
            {
                title = "目前位置沒有合格接管路徑";
                cause =
                    "可用的 45°／雙 45° 路徑未同時滿足方向、高程、"
                    + "最短直管與管件空間條件。";
                action =
                    "請增加支管與主管間距、調整高程，或改選較合適的接入位置。";
                return;
            }
            if (failureCode == DrainageFailureCode.SlopeValidationFailed)
            {
                title = "排水坡度不成立";
                cause =
                    "建立後的支管未通過設定坡度或沿流向下降檢查。";
                action =
                    "請檢查來源與主管高程，並確認管件設定中的坡度值。";
                return;
            }
            if (failureCode
                    == DrainageFailureCode.JunctionDirectionInvalid)
            {
                title = "主管接頭方向不正確";
                cause =
                    "斜 T／Y 的實際支口方向或連接關係未通過下游檢查。";
                action =
                    "請確認主管流向與設定的斜 T／Y 族群方向後再試。";
                return;
            }
            if (failureCode
                    == DrainageFailureCode.ConfigurationInvalid
                || failureCode
                    == DrainageFailureCode.ConfigurationMissing)
            {
                title = "管件設定不完整";
                cause =
                    "必要的斜 T／Y、45° 彎頭或 Routing Preference 無法使用。";
                action =
                    "請在「管件設定」補齊並驗證該管型與管徑的管件。";
                return;
            }
            if (failureCode
                    == DrainageFailureCode.TopologyValidationFailed)
            {
                title = "建立後的連接不完整";
                cause =
                    "管段、彎頭與主管接頭沒有形成完整且無循環的排水拓撲。";
                action =
                    "請檢查附近既有接頭與短管，清除衝突後再試。";
                return;
            }

            title = "Revit 無法完成這支接管";
            cause =
                "建立或驗證過程發生未分類錯誤，模型已回復到操作前狀態。";
            action =
                "請記下下方技術資訊；若重試仍失敗，保留模型位置供程式檢查。";
        }

        private static string ReadPrimaryFailureCode(
            string reason,
            DrainageFailureCode failureCode)
        {
            string value = (reason ?? "").Trim();
            int separator = value.IndexOfAny(
                new[] { ':', '\r', '\n', ',', ' ' });
            string code = separator < 0
                ? value
                : value.Substring(0, separator);
            if (!string.IsNullOrWhiteSpace(code)
                && code.All(
                    character =>
                        character == '_'
                        || character >= 'A' && character <= 'Z'
                        || character >= '0' && character <= '9'))
            {
                return code;
            }
            return failureCode.ToString();
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
