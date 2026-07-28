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
    public partial class RfaMetadataApplication : IExternalApplication
    {
        private static readonly string BaseDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "RevitFamilyClassifier",
            "runtime",
            "queue"
        );
        private static readonly string RequestDir = Path.Combine(BaseDir, "requests");
        private static readonly string ResponseDir = Path.Combine(BaseDir, "responses");
        private static readonly string ErrorDir = Path.Combine(BaseDir, "errors");
        private static readonly string HeartbeatFile = Path.Combine(BaseDir, "listener_heartbeat.json");
        private class FireBranchItem
        {
            public FamilyInstance Sprinkler { get; set; }
            public XYZ Point { get; set; }
            public Pipe MainPipe { get; set; }
            public long MainPipeId { get; set; }
            public XYZ MainStart { get; set; }
            public XYZ MainDirection { get; set; }
            public XYZ BranchDirection { get; set; }
            public double MainZ { get; set; }
            public double MainParameter { get; set; }
            public double BranchParameter { get; set; }
            public int SideSign { get; set; }
        }

        private class OpeningPlanReference
        {
            public string Kind { get; set; }
            public string Name { get; set; }
            public XYZ Start { get; set; }
            public XYZ End { get; set; }
            public XYZ Direction { get; set; }
            public XYZ Normal { get; set; }
            public double Offset { get; set; }
            public double MinAlong { get; set; }
            public double MaxAlong { get; set; }
            public double Weight { get; set; }
            public bool IsAxis { get; set; }
        }
        private const string RibbonTabName = "SC 族群工具";
        private const string RibbonPanelName = "族群管理";

        public Result OnStartup(UIControlledApplication application)
        {
            string stage = "create_directories";
            try
            {
                Directory.CreateDirectory(RequestDir);
                Directory.CreateDirectory(ResponseDir);
                Directory.CreateDirectory(ErrorDir);
                string startupFault = Path.Combine(
                    ErrorDir,
                    "startup_fault.json");
                if (File.Exists(startupFault))
                {
                    File.Delete(startupFault);
                }
                string startupTextFault = Path.Combine(
                    ErrorDir,
                    "startup_fault.txt");
                if (File.Exists(startupTextFault))
                {
                    File.Delete(startupTextFault);
                }
                stage = "ensure_ribbon";
                EnsureRibbon(application);
                stage = "initialize_document_state";
                InitializeDrainageDocumentState(application);
                stage = "register_preview_server";
                DrainagePreviewServer.Register();
                stage = "subscribe_idling";
                application.Idling += OnIdling;
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                try
                {
                    string fallbackErrorDir = Path.Combine(
                        Environment.GetFolderPath(
                            Environment.SpecialFolder.LocalApplicationData),
                        "RevitFamilyClassifier",
                        "runtime",
                        "queue",
                        "errors");
                    Directory.CreateDirectory(fallbackErrorDir);
                    File.WriteAllText(
                        Path.Combine(
                            fallbackErrorDir,
                            "startup_fault.txt"),
                        stage + "\r\n" + ex,
                        Encoding.UTF8);
                }
                catch
                {
                    // Continue to the structured logger below.
                }
                try
                {
                    Directory.CreateDirectory(ErrorDir);
                    File.WriteAllText(
                        Path.Combine(ErrorDir, "startup_fault.json"),
                        new JavaScriptSerializer().Serialize(new
                        {
                            stage = stage,
                            error = ex.ToString()
                        }),
                        Encoding.UTF8);
                }
                catch
                {
                    // Preserve the original startup failure.
                }
                return Result.Failed;
            }
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            application.Idling -= OnIdling;
            DrainagePreviewServer.Unregister();
            ShutdownDrainageDocumentState(application);
            return Result.Succeeded;
        }

        private void OnIdling(object sender, IdlingEventArgs e)
        {
            try
            {
                UIApplication uiApp = sender as UIApplication;
                if (uiApp == null)
                {
                    return;
                }

                WriteHeartbeat();

                foreach (string requestFile in Directory.GetFiles(RequestDir, "*.json").Take(3))
                {
                    ProcessRequest(uiApp, requestFile);
                }
            }
            catch (Exception ex)
            {
                try
                {
                    File.WriteAllText(
                        Path.Combine(ErrorDir, "listener_fault.json"),
                        new JavaScriptSerializer().Serialize(new { error = ex.ToString() })
                    );
                }
                catch
                {
                    // Ignore secondary logging failures to avoid breaking the listener loop.
                }
            }
        }

        private static void WriteHeartbeat()
        {
            var serializer = new JavaScriptSerializer();
            string payload = serializer.Serialize(new
            {
                utc = DateTime.UtcNow.ToString("o")
            });
            File.WriteAllText(HeartbeatFile, payload, Encoding.UTF8);
        }

        private static void EnsureRibbon(UIControlledApplication application)
        {
            try
            {
                application.CreateRibbonTab(RibbonTabName);
            }
            catch
            {
                // Revit throws when the ribbon tab already exists; this is expected.
            }

            RibbonPanel panel = application
                .GetRibbonPanels(RibbonTabName)
                .FirstOrDefault(item => item.Name == RibbonPanelName)
                ?? application.CreateRibbonPanel(RibbonTabName, RibbonPanelName);

            string assemblyPath = Assembly.GetExecutingAssembly().Location;
            PushButtonData archiveButtonData = new PushButtonData(
                "OpenFamilyArchive",
                "族群歸檔",
                assemblyPath,
                "RfaMetadataAddin.OpenFamilyArchiveCommand"
            );
            PushButtonData recoveryButtonData = new PushButtonData(
                "OpenProjectRecovery",
                "專案回收",
                assemblyPath,
                "RfaMetadataAddin.OpenProjectRecoveryCommand"
            );
            PushButtonData placementButtonData = new PushButtonData(
                "OpenPointPlacement",
                "批量點位放置",
                assemblyPath,
                "RfaMetadataAddin.OpenPointPlacementCommand"
            );
            PushButtonData fireBranchButtonData = new PushButtonData(
                "OpenFireBranch",
                "消防支管建立",
                assemblyPath,
                "RfaMetadataAddin.OpenFireBranchCommand"
            );
            PushButtonData drainageConnectButtonData = new PushButtonData(
                "ConnectDrainageToMain",
                "\u6392\u6c34\u63a5\u5165\u5e79\u7ba1",
                assemblyPath,
                "RfaMetadataAddin.ConnectDrainageToMainCommand"
            );
            PushButtonData drainageSettingsButtonData = new PushButtonData(
                "OpenDrainageConfiguration",
                "\u7ba1\u4ef6\u8a2d\u5b9a",
                assemblyPath,
                "RfaMetadataAddin.OpenDrainageConfigurationCommand"
            );
            PushButtonData alignPipeCenterlineButtonData = new PushButtonData(
                "AlignPipeCenterline",
                "\u7ba1\u4e2d\u5fc3\u5c0d\u9f4a",
                assemblyPath,
                "RfaMetadataAddin.AlignPipeCenterlineCommand"
            );
            PushButtonData extendPipeDown45ButtonData = new PushButtonData(
                "ExtendPipeDown45",
                "\u5411\u4e0b45\u00b0",
                assemblyPath,
                "RfaMetadataAddin.ExtendPipeDownFortyFiveCommand"
            );
            PushButtonData extendPipeVerticalDownButtonData = new PushButtonData(
                "ExtendPipeVerticalDown",
                "\u5782\u76f4\u5411\u4e0b",
                assemblyPath,
                "RfaMetadataAddin.ExtendPipeVerticallyDownCommand"
            );
            PushButtonData connectPipeFortyFiveButtonData = new PushButtonData(
                "ConnectPipeFortyFive",
                "45\u5ea6\u5c0d\u63a5",
                assemblyPath,
                "RfaMetadataAddin.ConnectPipeFortyFiveCommand"
            );
            PushButtonData openingButtonData = new PushButtonData(
                "OpenOpeningCheck",
                "開孔定位",
                assemblyPath,
                "RfaMetadataAddin.OpenOpeningCheckCommand"
            );

            PushButtonData backstageButtonData = new PushButtonData(
                "OpenBackstage",
                "SC " + "\u5f8c\u53f0",
                assemblyPath,
                "RfaMetadataAddin.OpenBackstageCommand"
            );
            PushButtonData elementInspectorButtonData = new PushButtonData(
                "OpenElementInspector",
                "\u8eab\u4efd\u6aa2\u67e5",
                assemblyPath,
                "RfaMetadataAddin.OpenElementInspectorCommand"
            );
            PushButtonData parameterAuditButtonData = new PushButtonData(
                "OpenParameterAudit",
                "\u53c3\u6578\u5065\u6aa2",
                assemblyPath,
                "RfaMetadataAddin.OpenParameterAuditCommand"
            );
            PushButtonData connectFittingButtonData = new PushButtonData(
                "OpenConnectFitting",
                "\u65b7\u9ede\u6aa2\u67e5",
                assemblyPath,
                "RfaMetadataAddin.OpenConnectFittingCommand"
            );
            PushButtonData pipingSupportButtonData = new PushButtonData(
                "OpenPipingSupport",
                "\u7ba1\u652f\u6490\u9810\u89bd",
                assemblyPath,
                "RfaMetadataAddin.OpenPipingSupportCommand"
            );

            PushButton archiveButton = panel.AddItem(archiveButtonData) as PushButton;
            if (archiveButton != null)
            {
                archiveButton.ToolTip = "開啟族群歸檔工具";
                archiveButton.LongDescription = "Classify, rename, standardize and ingest external RFA files.";
                archiveButton.Image = ScIconFactory.Create("family_archive", 16);
                archiveButton.LargeImage = ScIconFactory.Create("family_archive", 32);
            }

            PushButton recoveryButton = panel.AddItem(recoveryButtonData) as PushButton;
            if (recoveryButton != null)
            {
                recoveryButton.ToolTip = "開啟專案族群回收工具";
                recoveryButton.LongDescription = "Scan loaded and used families in the active Revit project.";
                recoveryButton.Image = ScIconFactory.Create("project_recovery", 16);
                recoveryButton.LargeImage = ScIconFactory.Create("project_recovery", 32);
            }

            PushButton placementButton = panel.AddItem(placementButtonData) as PushButton;
            if (placementButton != null)
            {
                placementButton.ToolTip = "開啟批量點位放置工具";
                placementButton.LongDescription = "Batch place Revit point families from CAD/DWG block points.";
                placementButton.Image = ScIconFactory.Create("point_placement", 16);
                placementButton.LargeImage = ScIconFactory.Create("point_placement", 32);
            }

            PushButton backstageButton = panel.AddItem(backstageButtonData) as PushButton;
            if (backstageButton != null)
            {
                backstageButton.ToolTip = "\u958b\u555f SC \u5f8c\u53f0\u7ba1\u7406";
                backstageButton.LongDescription = "Open SC REVIT backstage for batch records and managed cleanup actions.";
                backstageButton.Image = ScIconFactory.Create("backstage", 16);
                backstageButton.LargeImage = ScIconFactory.Create("backstage", 32);
            }

            RibbonPanel firePanel = application
                .GetRibbonPanels(RibbonTabName)
                .FirstOrDefault(item => item.Name == "消防系統")
                ?? application.CreateRibbonPanel(RibbonTabName, "消防系統");
            PushButton fireBranchButton = firePanel.AddItem(fireBranchButtonData) as PushButton;
            if (fireBranchButton != null)
            {
                fireBranchButton.ToolTip = "開啟消防支管建立工具";
                fireBranchButton.LongDescription = "Create first-pass sprinkler branch pipes from selected main pipe and sprinklers.";
                fireBranchButton.Image = ScIconFactory.Create("fire_branch", 16);
                fireBranchButton.LargeImage = ScIconFactory.Create("fire_branch", 32);
            }

            RibbonPanel drainagePanel = application
                .GetRibbonPanels(RibbonTabName)
                .FirstOrDefault(item => item.Name == "\u6392\u6c34\u7cfb\u7d71")
                ?? application.CreateRibbonPanel(RibbonTabName, "\u6392\u6c34\u7cfb\u7d71");
            SplitButtonData drainageSplitButtonData = new SplitButtonData(
                "DrainageConnectionWorkflow",
                "\u6392\u6c34\u63a5\u5165\u5e79\u7ba1");
            SplitButton drainageSplitButton =
                drainagePanel.AddItem(drainageSplitButtonData) as SplitButton;
            if (drainageSplitButton != null)
            {
                drainageSplitButton.IsSynchronizedWithCurrentItem = false;
                PushButton drainageConnectButton =
                    drainageSplitButton.AddPushButton(drainageConnectButtonData);
                drainageConnectButton.ToolTip =
                    "\u9023\u7e8c\u9078\u53d6\u5668\u5177\u6216\u7acb\u7ba1\uff0c\u81ea\u52d5\u63a5\u5165\u6392\u6c34\u5e79\u7ba1";
                drainageConnectButton.LongDescription =
                    "Continuously connect sanitary sources to a ranked main pipe. Press Esc to finish the batch.";
                drainageConnectButton.Image = ScIconFactory.Create("drainage_connect", 16);
                drainageConnectButton.LargeImage = ScIconFactory.Create("drainage_connect", 32);

                PushButton drainageSettingsButton =
                    drainageSplitButton.AddPushButton(drainageSettingsButtonData);
                drainageSettingsButton.ToolTip =
                    "\u4f9d Pipe Type \u8a2d\u5b9a\u659cT\u3001Y\u300145\u5ea6\u5f4e\u982d\u8207\u652f\u7ba1\u5761\u5ea6";
                drainageSettingsButton.Image = ScIconFactory.Create("drainage_settings", 16);
                drainageSettingsButton.LargeImage = ScIconFactory.Create("drainage_settings", 32);
            }

            SplitButtonData drainageRepairSplitButtonData =
                new SplitButtonData(
                    "DrainageRepairWorkflow",
                    "\u7ba1\u4e2d\u5fc3\u5c0d\u9f4a");
            SplitButton drainageRepairSplitButton =
                drainagePanel.AddItem(
                    drainageRepairSplitButtonData) as SplitButton;
            if (drainageRepairSplitButton != null)
            {
                drainageRepairSplitButton
                    .IsSynchronizedWithCurrentItem = true;

                PushButton alignPipeCenterlineButton =
                    drainageRepairSplitButton.AddPushButton(
                        alignPipeCenterlineButtonData);
                alignPipeCenterlineButton.ToolTip =
                    "\u5148\u9ede\u9ad8\u7a0b\u57fa\u6e96\u7ba1\uff0c\u518d\u9023\u7e8c\u5c07\u7368\u7acb\u7ba1\u6bb5\u7684\u4e2d\u5fc3\u7dda\u5c0d\u9f4a\u81f3\u57fa\u6e96\u7ba1\u5c40\u90e8\u9ad8\u7a0b";
                alignPipeCenterlineButton.Image =
                    ScIconFactory.Create("align_centerline", 16);
                alignPipeCenterlineButton.LargeImage =
                    ScIconFactory.Create("align_centerline", 32);

                PushButton connectPipeFortyFiveButton =
                    drainageRepairSplitButton.AddPushButton(
                        connectPipeFortyFiveButtonData);
                connectPipeFortyFiveButton.ToolTip =
                    "\u9078\u53d6\u5169\u500b\u958b\u653e\u7ba1\u7aef\uff0c\u4ee5\u4e00\u6bb545\u00b0\u659c\u7ba1\u8207\u5169\u500b45\u00b0\u5f4e\u982d\u5c0d\u63a5";
                connectPipeFortyFiveButton.Image =
                    ScIconFactory.Create("connect_45", 16);
                connectPipeFortyFiveButton.LargeImage =
                    ScIconFactory.Create("connect_45", 32);

                PushButton extendPipeDown45Button =
                    drainageRepairSplitButton.AddPushButton(
                        extendPipeDown45ButtonData);
                extendPipeDown45Button.ToolTip =
                    "\u9078\u53d6\u8a2d\u5099\u63a5\u53e3\u6216\u958b\u653e\u7ba1\u7aef\uff0c\u518d\u9078\u76ee\u6a19\u4e3b\u7ba1\uff1b\u53ea\u6709\u53ef\u4ee5\u55ae45\u00b0\u8def\u5f91\u5efa\u7acb\u6642\u624d\u6703\u5be6\u969b\u63a5\u5165";
                extendPipeDown45Button.Image =
                    ScIconFactory.Create("down_45", 16);
                extendPipeDown45Button.LargeImage =
                    ScIconFactory.Create("down_45", 32);

                PushButton extendPipeVerticalDownButton =
                    drainageRepairSplitButton.AddPushButton(
                        extendPipeVerticalDownButtonData);
                extendPipeVerticalDownButton.ToolTip =
                    "\u5c07\u5782\u76f4\u7ba1\u7684\u4e0b\u65b9\u958b\u653e\u7aef\u5ef6\u4f38\u5230\u9ad8\u5ea6\u57fa\u6e96\u7ba1\u7684\u5c40\u90e8\u4e2d\u5fc3\u7dda\u9ad8\u7a0b";
                extendPipeVerticalDownButton.Image =
                    ScIconFactory.Create("vertical_down", 16);
                extendPipeVerticalDownButton.LargeImage =
                    ScIconFactory.Create("vertical_down", 32);

            }

            RibbonPanel coordinationPanel = application
                .GetRibbonPanels(RibbonTabName)
                .FirstOrDefault(item => item.Name == "協調檢查")
                ?? application.CreateRibbonPanel(RibbonTabName, "協調檢查");
            PushButton openingButton = coordinationPanel.AddItem(openingButtonData) as PushButton;
            if (openingButton != null)
            {
                openingButton.ToolTip = "開啟套管 / 開孔定位工具";
                openingButton.LongDescription = "Scan MEP elements against linked architectural elements and list opening candidates.";
                openingButton.Image = ScIconFactory.Create("opening_locator", 16);
                openingButton.LargeImage = ScIconFactory.Create("opening_locator", 32);
            }

            RibbonPanel mepCheckPanel = application
                .GetRibbonPanels(RibbonTabName)
                .FirstOrDefault(item => item.Name == "MEP \u6aa2\u67e5")
                ?? application.CreateRibbonPanel(RibbonTabName, "MEP \u6aa2\u67e5");
            PushButton elementInspectorButton = mepCheckPanel.AddItem(elementInspectorButtonData) as PushButton;
            if (elementInspectorButton != null)
            {
                elementInspectorButton.ToolTip = "\u5224\u65b7\u9078\u53d6\u5143\u4ef6\u80fd\u5426\u88ab SC \u5f8c\u53f0\u8ffd\u8e64\u3001\u5831\u8868\u6216\u540c\u6b65\u7ba1\u7406";
                elementInspectorButton.LongDescription = "Check whether selected elements have usable identity data for SC REVIT management.";
                elementInspectorButton.Image = ScIconFactory.Create("element_inspector", 16);
                elementInspectorButton.LargeImage = ScIconFactory.Create("element_inspector", 32);
            }
            PushButton parameterAuditButton = mepCheckPanel.AddItem(parameterAuditButtonData) as PushButton;
            if (parameterAuditButton != null)
            {
                parameterAuditButton.ToolTip = "\u6aa2\u67e5\u9078\u53d6\u6216\u76ee\u524d\u8996\u5716\u5167\u5143\u4ef6\u7684 SC_ \u53c3\u6578\u662f\u5426\u7f3a\u5c11\u6216\u7a7a\u503c";
                parameterAuditButton.LongDescription = "Check SC-prefixed parameters and explain missing or empty values.";
                parameterAuditButton.Image = ScIconFactory.Create("parameter_audit", 16);
                parameterAuditButton.LargeImage = ScIconFactory.Create("parameter_audit", 32);
            }

            RibbonPanel mepAssistPanel = application
                .GetRibbonPanels(RibbonTabName)
                .FirstOrDefault(item => item.Name == "MEP \u5efa\u6a21\u8f14\u52a9")
                ?? application.CreateRibbonPanel(RibbonTabName, "MEP \u5efa\u6a21\u8f14\u52a9");
            PushButton connectFittingButton = mepAssistPanel.AddItem(connectFittingButtonData) as PushButton;
            if (connectFittingButton != null)
            {
                connectFittingButton.ToolTip = "\u627e\u51fa pipe / duct / conduit \u65b7\u9ede\uff0c\u4e26\u53ea\u5c0d\u53ef\u4fee\u5fa9\u7684 pipe \u57f7\u884c\u81ea\u52d5\u4fee\u5fa9";
                connectFittingButton.LongDescription = "Find disconnected MEP endpoints and repair only eligible pipe endpoint pairs.";
                connectFittingButton.Image = ScIconFactory.Create("breakpoint_check", 16);
                connectFittingButton.LargeImage = ScIconFactory.Create("breakpoint_check", 32);
            }
            PushButton pipingSupportButton = mepAssistPanel.AddItem(pipingSupportButtonData) as PushButton;
            if (pipingSupportButton != null)
            {
                pipingSupportButton.ToolTip = "\u4f9d\u9078\u53d6 pipe \u7522\u751f\u652f\u6490\u5019\u9078\u9ede\u8207\u9810\u89bd\u6a19\u8a18";
                pipingSupportButton.LongDescription = "Create preview markers for candidate pipe support points. Family placement is reserved for the next phase.";
                pipingSupportButton.Image = ScIconFactory.Create("piping_support", 16);
                pipingSupportButton.LargeImage = ScIconFactory.Create("piping_support", 32);
            }
        }

        private static void DeleteNumberedBackups(string inputPath)
        {
            string directory = Path.GetDirectoryName(inputPath);
            string stem = Path.GetFileNameWithoutExtension(inputPath);
            if (string.IsNullOrWhiteSpace(directory) || string.IsNullOrWhiteSpace(stem))
            {
                return;
            }

            Regex backupPattern = new Regex(
                "^" + Regex.Escape(stem) + @"\.\d{4}\.rfa$",
                RegexOptions.IgnoreCase
            );

            foreach (string candidate in Directory.GetFiles(directory, stem + ".*.rfa"))
            {
                string fileName = Path.GetFileName(candidate);
                if (backupPattern.IsMatch(fileName))
                {
                    File.Delete(candidate);
                }
            }
        }

        private static void TraverseGeometryInstances(
            Document doc,
            GeometryElement geometry,
            Autodesk.Revit.DB.Transform transform,
            string filter,
            int limit,
            List<Dictionary<string, object>> points)
        {
            if (geometry == null || points.Count >= limit)
            {
                return;
            }
            foreach (GeometryObject geometryObject in geometry)
            {
                if (points.Count >= limit)
                {
                    return;
                }
                GeometryInstance instance = geometryObject as GeometryInstance;
                if (instance == null)
                {
                    continue;
                }

                Autodesk.Revit.DB.Transform instanceTransform = transform.Multiply(instance.Transform);
                string blockName = GetGeometryInstanceName(doc, instance);
                bool matched = string.IsNullOrWhiteSpace(filter)
                    || string.Equals(blockName, filter, StringComparison.OrdinalIgnoreCase);
                if (matched)
                {
                    XYZ origin = instanceTransform.Origin;
                    double rotationRadians = Math.Atan2(instanceTransform.BasisX.Y, instanceTransform.BasisX.X);
                    points.Add(new Dictionary<string, object>
                    {
                        { "block_name", blockName },
                        { "x", origin.X },
                        { "y", origin.Y },
                        { "z", origin.Z },
                        { "rotation_degrees", rotationRadians * 180.0 / Math.PI }
                    });
                }

                try
                {
                    TraverseGeometryInstances(
                        doc,
                        instance.GetInstanceGeometry(),
                        instanceTransform,
                        filter,
                        limit,
                        points
                    );
                }
                catch
                {
                    // Some imported geometry cannot be expanded. Keep whatever has already been found.
                }
            }
        }

        private static string GetGeometryInstanceName(Document doc, GeometryInstance instance)
        {
            try
            {
                using (SymbolGeometryId symbolGeometryId = instance.GetSymbolGeometryId())
                {
                    if (symbolGeometryId != null)
                    {
                        Element symbolElement = doc.GetElement(symbolGeometryId.SymbolId);
                        if (symbolElement != null && !string.IsNullOrWhiteSpace(symbolElement.Name))
                        {
                            return symbolElement.Name;
                        }
                        string identifier = symbolGeometryId.ToString();
                        if (!string.IsNullOrWhiteSpace(identifier))
                        {
                            return identifier;
                        }
                    }
                }
            }
            catch
            {
                // Fall back below.
            }
            return "未命名圖塊";
        }

        private static string GetCadImportTypeName(Document doc, ImportInstance importInstance)
        {
            try
            {
                Element typeElement = doc.GetElement(importInstance.GetTypeId());
                if (typeElement != null && !string.IsNullOrWhiteSpace(typeElement.Name))
                {
                    return typeElement.Name;
                }
            }
            catch
            {
                // Fall back below.
            }
            return string.IsNullOrWhiteSpace(importInstance.Name)
                ? "未命名 CAD"
                : importInstance.Name;
        }

        private static string GetCadImportPath(Document doc, ImportInstance importInstance)
        {
            try
            {
                ExternalFileReference reference = ExternalFileUtils.GetExternalFileReference(
                    doc,
                    importInstance.GetTypeId()
                );
                if (reference != null)
                {
                    ModelPath modelPath = reference.GetAbsolutePath();
                    if (modelPath != null)
                    {
                        string path = ModelPathUtils.ConvertModelPathToUserVisiblePath(modelPath);
                        if (!string.IsNullOrWhiteSpace(path))
                        {
                            return path;
                        }
                    }
                }
            }
            catch
            {
                // Imported CAD may not keep an external reference path.
            }
            return "";
        }

        private static List<Dictionary<string, object>> ScanCadBlockPoints(
            Document doc,
            ImportInstance importInstance,
            string blockFilter,
            int limit)
        {
            Options options = new Options
            {
                ComputeReferences = false,
                IncludeNonVisibleObjects = true,
                DetailLevel = ViewDetailLevel.Fine
            };
            GeometryElement geometry = importInstance.get_Geometry(options);
            var points = new List<Dictionary<string, object>>();
            TraverseGeometryInstances(
                doc,
                geometry,
                importInstance.GetTotalTransform(),
                blockFilter,
                Math.Max(limit, 1),
                points
            );
            return points;
        }

        private static List<Dictionary<string, object>> ReadPointPayload(Dictionary<string, object> payload)
        {
            var points = new List<Dictionary<string, object>>();
            IEnumerable rawPoints = payload.ContainsKey("points")
                ? payload["points"] as IEnumerable
                : null;
            if (rawPoints == null)
            {
                return points;
            }
            foreach (object item in rawPoints)
            {
                Dictionary<string, object> point = item as Dictionary<string, object>;
                if (point != null)
                {
                    points.Add(point);
                }
            }
            return points;
        }

        private static List<Dictionary<string, object>> TransformDwgBlockPoints(
            ImportInstance importInstance,
            List<Dictionary<string, object>> rawPoints,
            int limit)
        {
            var transformedPoints = new List<Dictionary<string, object>>();
            Autodesk.Revit.DB.Transform transform = importInstance.GetTotalTransform();
            double baseRotationDegrees = Math.Atan2(transform.BasisX.Y, transform.BasisX.X) * 180.0 / Math.PI;
            foreach (Dictionary<string, object> rawPoint in rawPoints.Take(Math.Max(limit, 1)))
            {
                double x = rawPoint.ContainsKey("x") ? Convert.ToDouble(rawPoint["x"]) : 0;
                double y = rawPoint.ContainsKey("y") ? Convert.ToDouble(rawPoint["y"]) : 0;
                double z = rawPoint.ContainsKey("z") ? Convert.ToDouble(rawPoint["z"]) : 0;
                double rotation = rawPoint.ContainsKey("rotation_degrees")
                    ? Convert.ToDouble(rawPoint["rotation_degrees"])
                    : 0;
                XYZ sourcePoint = new XYZ(x, y, z);
                XYZ targetPoint = transform.OfPoint(sourcePoint);
                transformedPoints.Add(new Dictionary<string, object>
                {
                    { "block_name", rawPoint.ContainsKey("block_name") ? rawPoint["block_name"] : "" },
                    { "x", targetPoint.X },
                    { "y", targetPoint.Y },
                    { "z", targetPoint.Z },
                    { "rotation_degrees", rotation + baseRotationDegrees },
                    { "source_x", x },
                    { "source_y", y },
                    { "source_z", z },
                    { "handle", rawPoint.ContainsKey("handle") ? rawPoint["handle"] : "" },
                    { "layer", rawPoint.ContainsKey("layer") ? rawPoint["layer"] : "" }
                });
            }
            return transformedPoints;
        }

        private static bool IsDuplicatePoint(
            Document doc,
            FamilySymbol symbol,
            Level level,
            XYZ location,
            double toleranceFeet)
        {
            foreach (FamilyInstance instance in new FilteredElementCollector(doc)
                .OfClass(typeof(FamilyInstance))
                .Cast<FamilyInstance>())
            {
                if (instance.Symbol == null || instance.Symbol.Id != symbol.Id)
                {
                    continue;
                }
                if (instance.LevelId != level.Id)
                {
                    continue;
                }
                LocationPoint locationPoint = instance.Location as LocationPoint;
                if (locationPoint == null)
                {
                    continue;
                }
                double dx = locationPoint.Point.X - location.X;
                double dy = locationPoint.Point.Y - location.Y;
                if (Math.Sqrt(dx * dx + dy * dy) <= toleranceFeet)
                {
                    return true;
                }
            }
            return false;
        }

        private static void TrySetInstanceVerticalOffset(FamilyInstance instance, double offsetFeet)
        {
            BuiltInParameter[] builtInParameters = new BuiltInParameter[]
            {
                BuiltInParameter.RBS_OFFSET_PARAM,
                BuiltInParameter.INSTANCE_ELEVATION_PARAM,
                BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM,
                BuiltInParameter.FAMILY_FREEINST_DEFAULT_ELEVATION,
                BuiltInParameter.FAMILY_WPB_DEFAULT_ELEVATION
            };
            foreach (BuiltInParameter builtInParameter in builtInParameters)
            {
                if (TrySetDoubleParameter(instance.get_Parameter(builtInParameter), offsetFeet))
                {
                    return;
                }
            }

            string[] parameterNames = new string[]
            {
                "距離樓層的高度",
                "偏移",
                "Elevation from Level",
                "Offset from Host",
                "Offset"
            };
            foreach (string parameterName in parameterNames)
            {
                if (TrySetDoubleParameter(instance.LookupParameter(parameterName), offsetFeet))
                {
                    return;
                }
            }
        }

        private static void TrySetInstanceLevel(FamilyInstance instance, Level level)
        {
            BuiltInParameter[] builtInParameters = new BuiltInParameter[]
            {
                BuiltInParameter.FAMILY_LEVEL_PARAM,
                BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM,
                BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM
            };
            foreach (BuiltInParameter builtInParameter in builtInParameters)
            {
                TrySetElementIdParameter(instance.get_Parameter(builtInParameter), level.Id);
            }

            string[] parameterNames = new string[]
            {
                "基準樓層",
                "樓層",
                "Level",
                "Schedule Level",
                "Reference Level"
            };
            foreach (string parameterName in parameterNames)
            {
                TrySetElementIdParameter(instance.LookupParameter(parameterName), level.Id);
            }
        }

        private static bool TrySetColumnVerticalPlacement(FamilyInstance instance, Level level, double offsetFeet)
        {
            bool changed = false;
            changed = TrySetElementIdParameter(
                instance.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM),
                level.Id
            ) || changed;
            changed = TrySetDoubleParameter(
                instance.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM),
                offsetFeet
            ) || changed;
            return changed;
        }

        private static bool IsColumnFamilySymbol(FamilySymbol symbol)
        {
            if (symbol == null || symbol.Category == null)
            {
                return false;
            }
            long categoryId = symbol.Category.Id.Value;
            return categoryId == (long)BuiltInCategory.OST_Columns
                || categoryId == (long)BuiltInCategory.OST_StructuralColumns;
        }

        private static void ApplyVerticalPlacement(
            Document doc,
            FamilyInstance instance,
            FamilySymbol symbol,
            Level level,
            double offsetFeet,
            double targetZ)
        {
            if (IsColumnFamilySymbol(symbol))
            {
                bool changed = TrySetColumnVerticalPlacement(instance, level, offsetFeet);
                doc.Regenerate();
                if (!changed)
                {
                    ForceInstanceZ(doc, instance, targetZ);
                }
                return;
            }

            TrySetInstanceLevel(instance, level);
            TrySetInstanceVerticalOffset(instance, offsetFeet);
            doc.Regenerate();
            ForceInstanceZ(doc, instance, targetZ);
            doc.Regenerate();
            TrySetInstanceLevel(instance, level);
            TrySetInstanceVerticalOffset(instance, offsetFeet);
        }

        private static bool TrySetElementIdParameter(Parameter parameter, ElementId value)
        {
            if (parameter == null || parameter.IsReadOnly || parameter.StorageType != StorageType.ElementId)
            {
                return false;
            }
            parameter.Set(value);
            return true;
        }

        private static bool TrySetDoubleParameter(Parameter parameter, double value)
        {
            if (parameter == null || parameter.IsReadOnly || parameter.StorageType != StorageType.Double)
            {
                return false;
            }
            parameter.Set(value);
            return true;
        }

        private static void ForceInstanceZ(Document doc, FamilyInstance instance, double targetZ)
        {
            LocationPoint locationPoint = instance.Location as LocationPoint;
            if (locationPoint == null)
            {
                return;
            }

            double deltaZ = targetZ - locationPoint.Point.Z;
            if (Math.Abs(deltaZ) < 0.000001)
            {
                return;
            }

            try
            {
                locationPoint.Point = new XYZ(locationPoint.Point.X, locationPoint.Point.Y, targetZ);
            }
            catch
            {
                ElementTransformUtils.MoveElement(doc, instance.Id, new XYZ(0, 0, deltaZ));
            }
        }

        private static string SanitizeGroupName(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return "族群";
            }
            string sanitized = Regex.Replace(value, @"[\\/:*?""<>|{}\[\];=]", "_");
            return sanitized.Length > 40 ? sanitized.Substring(0, 40) : sanitized;
        }

        private static string MakeUniqueGroupTypeName(Document doc, string baseName)
        {
            var existing = new HashSet<string>(
                new FilteredElementCollector(doc)
                    .OfClass(typeof(GroupType))
                    .Cast<GroupType>()
                    .Select(item => item.Name)
            );
            if (!existing.Contains(baseName))
            {
                return baseName;
            }
            int index = 2;
            while (existing.Contains(baseName + "_" + index.ToString("00")))
            {
                index++;
            }
            return baseName + "_" + index.ToString("00");
        }

        private static XYZ GetElementPoint(Element element)
        {
            LocationPoint locationPoint = element.Location as LocationPoint;
            if (locationPoint != null)
            {
                return locationPoint.Point;
            }
            LocationCurve locationCurve = element.Location as LocationCurve;
            if (locationCurve != null)
            {
                Curve curve = locationCurve.Curve;
                return (curve.GetEndPoint(0) + curve.GetEndPoint(1)) * 0.5;
            }
            BoundingBoxXYZ box = element.get_BoundingBox(null);
            if (box != null)
            {
                return (box.Min + box.Max) * 0.5;
            }
            return XYZ.Zero;
        }

        private static Connector GetFirstConnector(Element element)
        {
            ConnectorSet connectors = null;
            Pipe pipe = element as Pipe;
            if (pipe != null)
            {
                connectors = pipe.ConnectorManager.Connectors;
            }
            FamilyInstance instance = element as FamilyInstance;
            if (instance != null && instance.MEPModel != null && instance.MEPModel.ConnectorManager != null)
            {
                connectors = instance.MEPModel.ConnectorManager.Connectors;
            }
            if (connectors == null)
            {
                return null;
            }
            foreach (Connector connector in connectors)
            {
                return connector;
            }
            return null;
        }

        private static Connector FindConnectorNear(Element element, XYZ point)
        {
            ConnectorSet connectors = null;
            Pipe pipe = element as Pipe;
            if (pipe != null)
            {
                connectors = pipe.ConnectorManager.Connectors;
            }
            FamilyInstance instance = element as FamilyInstance;
            if (instance != null && instance.MEPModel != null && instance.MEPModel.ConnectorManager != null)
            {
                connectors = instance.MEPModel.ConnectorManager.Connectors;
            }
            if (connectors == null)
            {
                return null;
            }
            Connector best = null;
            double bestDistance = double.MaxValue;
            foreach (Connector connector in connectors)
            {
                double distance = connector.Origin.DistanceTo(point);
                if (distance < bestDistance)
                {
                    best = connector;
                    bestDistance = distance;
                }
            }
            return best;
        }

        private static XYZ GetFamilyConnectionPoint(FamilyInstance instance)
        {
            Connector connector = GetFirstConnector(instance);
            return connector != null ? connector.Origin : GetElementPoint(instance);
        }

        private static bool IsSprinkler(FamilyInstance instance)
        {
            if (instance == null || instance.Category == null)
            {
                return false;
            }
            if (instance.Category.Id.Value == (long)BuiltInCategory.OST_Sprinklers)
            {
                return true;
            }
            string name = instance.Category.Name ?? "";
            return name.Contains("撒水頭") || name.Contains("灑水頭") || name.Contains("Sprinkler");
        }

        private static double DotXY(XYZ a, XYZ b)
        {
            return a.X * b.X + a.Y * b.Y;
        }

        private static XYZ NormalizeXY(XYZ vector)
        {
            double length = Math.Sqrt(vector.X * vector.X + vector.Y * vector.Y);
            if (length < 0.000001)
            {
                return XYZ.BasisX;
            }
            return new XYZ(vector.X / length, vector.Y / length, 0);
        }

        private static XYZ PrincipalDirectionXY(List<XYZ> points)
        {
            if (points.Count < 2)
            {
                return XYZ.BasisX;
            }
            XYZ first = points.First();
            XYZ farthest = points.Last();
            double maxDistance = -1;
            foreach (XYZ a in points)
            {
                foreach (XYZ b in points)
                {
                    double dx = a.X - b.X;
                    double dy = a.Y - b.Y;
                    double distance = dx * dx + dy * dy;
                    if (distance > maxDistance)
                    {
                        maxDistance = distance;
                        first = a;
                        farthest = b;
                    }
                }
            }
            return NormalizeXY(farthest - first);
        }

        private static XYZ ClosestPointOnLineXY(XYZ point, XYZ lineOrigin, XYZ lineDirection, double z)
        {
            XYZ direction = NormalizeXY(lineDirection);
            double t = DotXY(point - lineOrigin, direction);
            XYZ projected = lineOrigin + direction * t;
            return new XYZ(projected.X, projected.Y, z);
        }

        private static Pipe CreateFirePipe(
            Document doc,
            ElementId systemTypeId,
            ElementId pipeTypeId,
            ElementId levelId,
            XYZ start,
            XYZ end,
            double diameterFeet)
        {
            if (start.DistanceTo(end) < 0.01)
            {
                return null;
            }
            Pipe pipe = Pipe.Create(doc, systemTypeId, pipeTypeId, levelId, start, end);
            Parameter diameter = pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
            if (diameter != null && !diameter.IsReadOnly)
            {
                diameter.Set(diameterFeet);
            }
            doc.Regenerate();
            return pipe;
        }

        private static Pipe CreateFirePipeFromConnector(
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
                return null;
            }
            Pipe pipe = Pipe.Create(doc, pipeTypeId, levelId, startConnector, end);
            Parameter diameter = pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
            if (diameter != null && !diameter.IsReadOnly)
            {
                diameter.Set(diameterFeet);
            }
            doc.Regenerate();
            return pipe;
        }

        private static ElementId GetPipeLevelId(Document doc, Pipe pipe)
        {
            BuiltInParameter[] levelParameters = new BuiltInParameter[]
            {
                BuiltInParameter.RBS_START_LEVEL_PARAM,
                BuiltInParameter.RBS_END_LEVEL_PARAM,
                BuiltInParameter.LEVEL_PARAM
            };
            foreach (BuiltInParameter builtInParameter in levelParameters)
            {
                Parameter parameter = pipe.get_Parameter(builtInParameter);
                if (parameter != null && parameter.StorageType == StorageType.ElementId)
                {
                    ElementId id = parameter.AsElementId();
                    if (id != ElementId.InvalidElementId)
                    {
                        return id;
                    }
                }
            }

            XYZ point = GetElementPoint(pipe);
            Level nearest = new FilteredElementCollector(doc)
                .OfClass(typeof(Level))
                .Cast<Level>()
                .OrderBy(level => Math.Abs(level.Elevation - point.Z))
                .FirstOrDefault();
            return nearest != null ? nearest.Id : ElementId.InvalidElementId;
        }

        private static Dictionary<string, object> SerializePipeInfo(Document doc, Pipe pipe)
        {
            LocationCurve locationCurve = pipe.Location as LocationCurve;
            XYZ start = XYZ.Zero;
            XYZ end = XYZ.Zero;
            if (locationCurve != null)
            {
                start = locationCurve.Curve.GetEndPoint(0);
                end = locationCurve.Curve.GetEndPoint(1);
            }
            ElementId levelId = GetPipeLevelId(doc, pipe);
            Parameter diameter = pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
            double diameterMm = diameter != null
                ? UnitUtils.ConvertFromInternalUnits(diameter.AsDouble(), UnitTypeId.Millimeters)
                : 0;
            return new Dictionary<string, object>
            {
                { "element_id", pipe.Id.Value },
                { "unique_id", pipe.UniqueId },
                { "name", pipe.Name },
                { "level_id", levelId != ElementId.InvalidElementId ? levelId.Value : 0 },
                { "pipe_type_id", pipe.GetTypeId().Value },
                { "system_type_id", pipe.MEPSystem != null ? pipe.MEPSystem.GetTypeId().Value : 0 },
                { "diameter_mm", diameterMm },
                { "start", SerializePoint(start) },
                { "end", SerializePoint(end) },
                { "mid", SerializePoint((start + end) * 0.5) }
            };
        }

        private static Dictionary<string, object> SerializeSprinklerInfo(FamilyInstance instance)
        {
            XYZ point = GetFamilyConnectionPoint(instance);
            return new Dictionary<string, object>
            {
                { "element_id", instance.Id.Value },
                { "name", instance.Name },
                { "family_name", instance.Symbol != null ? instance.Symbol.FamilyName : "" },
                { "type_name", instance.Symbol != null ? instance.Symbol.Name : "" },
                { "point", SerializePoint(point) }
            };
        }

        private static bool TryConnectElements(Document doc, Element a, XYZ pointA, Element b, XYZ pointB)
        {
            Connector connectorA = FindConnectorNear(a, pointA);
            Connector connectorB = FindConnectorNear(b, pointB);
            if (connectorA == null || connectorB == null)
            {
                return false;
            }
            try
            {
                if (!connectorA.IsConnectedTo(connectorB))
                {
                    connectorA.ConnectTo(connectorB);
                }
                return connectorA.IsConnectedTo(connectorB);
            }
            catch
            {
                // Connector connection may fail when Revit cannot resolve a valid fitting.
                return false;
            }
        }

        private static bool IsPointOnPipeXY(Pipe pipe, XYZ point, double toleranceFeet)
        {
            LocationCurve locationCurve = pipe.Location as LocationCurve;
            if (locationCurve == null)
            {
                return false;
            }
            XYZ start = locationCurve.Curve.GetEndPoint(0);
            XYZ end = locationCurve.Curve.GetEndPoint(1);
            XYZ direction = NormalizeXY(end - start);
            double length = Math.Sqrt(Math.Pow(end.X - start.X, 2) + Math.Pow(end.Y - start.Y, 2));
            double t = DotXY(point - start, direction);
            XYZ projected = start + direction * t;
            double distance = Math.Sqrt(Math.Pow(point.X - projected.X, 2) + Math.Pow(point.Y - projected.Y, 2));
            return t > toleranceFeet && t < length - toleranceFeet && distance <= toleranceFeet;
        }

        private static bool IsPointOnPipeXYIncludingEnds(Pipe pipe, XYZ point, double toleranceFeet)
        {
            LocationCurve locationCurve = pipe.Location as LocationCurve;
            if (locationCurve == null)
            {
                return false;
            }
            XYZ start = locationCurve.Curve.GetEndPoint(0);
            XYZ end = locationCurve.Curve.GetEndPoint(1);
            XYZ direction = NormalizeXY(end - start);
            double length = Math.Sqrt(Math.Pow(end.X - start.X, 2) + Math.Pow(end.Y - start.Y, 2));
            double t = DotXY(point - start, direction);
            XYZ projected = start + direction * t;
            double distance = Math.Sqrt(Math.Pow(point.X - projected.X, 2) + Math.Pow(point.Y - projected.Y, 2));
            return t >= -toleranceFeet && t <= length + toleranceFeet && distance <= toleranceFeet;
        }

        private static bool IsPointAtPipeEnd(Pipe pipe, XYZ point, double toleranceFeet)
        {
            LocationCurve locationCurve = pipe.Location as LocationCurve;
            if (locationCurve == null)
            {
                return false;
            }
            XYZ start = locationCurve.Curve.GetEndPoint(0);
            XYZ end = locationCurve.Curve.GetEndPoint(1);
            return start.DistanceTo(point) <= toleranceFeet || end.DistanceTo(point) <= toleranceFeet;
        }

        private static double ResolvePipeCenterZ(Level level, double fallbackZ, double offsetCm, double diameterFeet, string heightReference)
        {
            double referenceZ = (level != null ? level.Elevation : fallbackZ)
                + UnitUtils.ConvertToInternalUnits(offsetCm, UnitTypeId.Centimeters);
            if (heightReference == "管上端")
            {
                return referenceZ - diameterFeet / 2.0;
            }
            if (heightReference == "管下端")
            {
                return referenceZ + diameterFeet / 2.0;
            }
            return referenceZ;
        }

        private static FamilyInstance TryNewTeeFitting(Document doc, Connector mainA, Connector mainB, Connector branch)
        {
            if (mainA == null || mainB == null || branch == null)
            {
                return null;
            }

            Connector[][] orders = new Connector[][]
            {
                new Connector[] { mainA, mainB, branch },
                new Connector[] { mainB, mainA, branch },
                new Connector[] { mainA, branch, mainB },
                new Connector[] { mainB, branch, mainA },
                new Connector[] { branch, mainA, mainB },
                new Connector[] { branch, mainB, mainA },
            };
            foreach (Connector[] order in orders)
            {
                try
                {
                    FamilyInstance fitting = doc.Create.NewTeeFitting(order[0], order[1], order[2]);
                    doc.Regenerate();
                    if (fitting != null)
                    {
                        return fitting;
                    }
                }
                catch
                {
                    // Revit API fitting creation is order-sensitive.
                }
            }
            return null;
        }

        private static bool TryCreateTeeAtPoint(Document doc, List<Pipe> mainSegments, Pipe branchPipe, XYZ tiePoint)
        {
            if (branchPipe == null)
            {
                return false;
            }
            double tolerance = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters);
            Pipe target = mainSegments.FirstOrDefault(pipe => IsPointOnPipeXY(pipe, tiePoint, tolerance));
            if (target == null)
            {
                return false;
            }
            try
            {
                doc.Regenerate();
                ElementId newSegmentId = PlumbingUtils.BreakCurve(doc, target.Id, tiePoint);
                Pipe newSegment = doc.GetElement(newSegmentId) as Pipe;
                if (newSegment != null)
                {
                    mainSegments.Add(newSegment);
                }
                doc.Regenerate();

                Connector mainA = FindConnectorNear(target, tiePoint);
                Connector mainB = newSegment != null ? FindConnectorNear(newSegment, tiePoint) : null;
                Connector branchConnector = FindConnectorNear(branchPipe, tiePoint);
                return TryNewTeeFitting(doc, mainA, mainB, branchConnector) != null;
            }
            catch
            {
                // Revit API fitting creation may fail; fallback below.
                }
            return false;
        }

        private static bool TryCreateElbowAtPipeEnd(Document doc, List<Pipe> pipeSegments, Pipe connectingPipe, XYZ tiePoint)
        {
            if (connectingPipe == null)
            {
                return false;
            }
            double tolerance = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters);
            Pipe target = pipeSegments.FirstOrDefault(pipe => IsPointAtPipeEnd(pipe, tiePoint, tolerance));
            if (target == null)
            {
                return false;
            }
            try
            {
                doc.Regenerate();
                Connector targetConnector = FindConnectorNear(target, tiePoint);
                Connector connectingConnector = FindConnectorNear(connectingPipe, tiePoint);
                if (targetConnector != null && connectingConnector != null)
                {
                    FamilyInstance fitting = doc.Create.NewElbowFitting(targetConnector, connectingConnector);
                    doc.Regenerate();
                    return fitting != null;
                }
            }
            catch
            {
                // Revit API fitting creation may fail; fallback below.
                }
            return false;
        }

        private static FamilyInstance TryNewCrossFitting(Document doc, Connector a, Connector b, Connector c, Connector d)
        {
            if (a == null || b == null || c == null || d == null)
            {
                return null;
            }
            Connector[][] orders = new Connector[][]
            {
                new Connector[] { a, b, c, d },
                new Connector[] { a, b, d, c },
                new Connector[] { c, d, a, b },
                new Connector[] { c, d, b, a },
                new Connector[] { a, c, b, d },
                new Connector[] { a, d, b, c },
            };
            foreach (Connector[] order in orders)
            {
                try
                {
                    FamilyInstance fitting = doc.Create.NewCrossFitting(order[0], order[1], order[2], order[3]);
                    doc.Regenerate();
                    if (fitting != null)
                    {
                        return fitting;
                    }
                }
                catch
                {
                    // Revit API fitting creation may fail; fallback below.
            }
            }
            return null;
        }

        private static bool TryCreateCrossAtPoint(Document doc, List<Pipe> mainSegments, List<Pipe> branchSegments, XYZ tiePoint)
        {
            double tolerance = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters);
            Pipe mainTarget = mainSegments.FirstOrDefault(pipe => IsPointOnPipeXY(pipe, tiePoint, tolerance));
            Pipe branchTarget = branchSegments.FirstOrDefault(pipe => IsPointOnPipeXY(pipe, tiePoint, tolerance));
            if (mainTarget == null || branchTarget == null)
            {
                return false;
            }
            try
            {
                doc.Regenerate();
                ElementId newMainId = PlumbingUtils.BreakCurve(doc, mainTarget.Id, tiePoint);
                ElementId newBranchId = PlumbingUtils.BreakCurve(doc, branchTarget.Id, tiePoint);
                Pipe newMain = doc.GetElement(newMainId) as Pipe;
                Pipe newBranch = doc.GetElement(newBranchId) as Pipe;
                if (newMain != null)
                {
                    mainSegments.Add(newMain);
                }
                if (newBranch != null)
                {
                    branchSegments.Add(newBranch);
                }
                doc.Regenerate();

                Connector mainA = FindConnectorNear(mainTarget, tiePoint);
                Connector mainB = newMain != null ? FindConnectorNear(newMain, tiePoint) : null;
                Connector branchA = FindConnectorNear(branchTarget, tiePoint);
                Connector branchB = newBranch != null ? FindConnectorNear(newBranch, tiePoint) : null;
                return TryNewCrossFitting(doc, mainA, mainB, branchA, branchB) != null;
            }
            catch
            {
                return false;
            }
        }

        private static bool TryConnectPipeToRun(Document doc, List<Pipe> runSegments, Pipe connectingPipe, XYZ tiePoint)
        {
            double tolerance = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters);
            Pipe target = runSegments.FirstOrDefault(pipe => IsPointOnPipeXYIncludingEnds(pipe, tiePoint, tolerance));
            if (target == null)
            {
                return false;
            }
            if (IsPointAtPipeEnd(target, tiePoint, tolerance))
            {
                return TryCreateElbowAtPipeEnd(doc, runSegments, connectingPipe, tiePoint);
            }
            return TryCreateTeeAtPoint(doc, runSegments, connectingPipe, tiePoint);
        }


        private static BuiltInCategory? GetOpeningMepCategory(string key)
        {
            if (key == "pipe")
            {
                return BuiltInCategory.OST_PipeCurves;
            }
            if (key == "conduit")
            {
                return BuiltInCategory.OST_Conduit;
            }
            if (key == "duct")
            {
                return BuiltInCategory.OST_DuctCurves;
            }
            if (key == "cable_tray")
            {
                return BuiltInCategory.OST_CableTray;
            }
            return null;
        }

        private static BuiltInCategory? GetOpeningHostCategory(string key)
        {
            if (key == "wall")
            {
                return BuiltInCategory.OST_Walls;
            }
            if (key == "floor")
            {
                return BuiltInCategory.OST_Floors;
            }
            if (key == "beam")
            {
                return BuiltInCategory.OST_StructuralFraming;
            }
            if (key == "column")
            {
                return BuiltInCategory.OST_StructuralColumns;
            }
            return null;
        }

        private static string GetOpeningMepLabel(string key)
        {
            if (key == "pipe") return "管";
            if (key == "conduit") return "電管";
            if (key == "duct") return "風管";
            if (key == "cable_tray") return "電纜架";
            return key;
        }

        private static string GetElementParameterText(Element element, string[] names)
        {
            if (element == null || names == null)
            {
                return "";
            }
            foreach (string name in names)
            {
                try
                {
                    Parameter parameter = element.LookupParameter(name);
                    string value = ParameterToText(parameter);
                    if (!string.IsNullOrWhiteSpace(value))
                    {
                        return value;
                    }
                }
                catch
                {
                }
            }
            foreach (Parameter parameter in element.Parameters)
            {
                if (parameter == null || parameter.Definition == null)
                {
                    continue;
                }
                string parameterName = parameter.Definition.Name ?? "";
                foreach (string name in names)
                {
                    if (string.Equals(parameterName, name, StringComparison.OrdinalIgnoreCase)
                        || parameterName.IndexOf(name, StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        string value = ParameterToText(parameter);
                        if (!string.IsNullOrWhiteSpace(value))
                        {
                            return value;
                        }
                    }
                }
            }
            return "";
        }

        private static string ParameterToText(Parameter parameter)
        {
            if (parameter == null)
            {
                return "";
            }
            try
            {
                if (parameter.StorageType == StorageType.String)
                {
                    return parameter.AsString() ?? "";
                }
                if (parameter.StorageType == StorageType.ElementId)
                {
                    return parameter.AsValueString() ?? "";
                }
                return parameter.AsValueString() ?? "";
            }
            catch
            {
                return "";
            }
        }

        private static string NormalizeOpeningSystemName(string value, string mepKey)
        {
            string text = (value ?? "").Trim();
            string probe = text.ToLowerInvariant();
            if (probe.Contains("消防") || probe.Contains("fire") || probe.Contains("sprinkler") || probe.Contains("fp"))
            {
                return "消防";
            }
            if (probe.Contains("給排水") || probe.Contains("排水") || probe.Contains("給水") || probe.Contains("衛生") || probe.Contains("plumbing") || probe.Contains("plb"))
            {
                return "給排水";
            }
            if (probe.Contains("風管") || probe.Contains("空調") || probe.Contains("hvac") || probe.Contains("duct"))
            {
                return "空調";
            }
            if (probe.Contains("弱電") || probe.Contains("通信") || probe.Contains("資料") || probe.Contains("data") || probe.Contains("telecom") || probe.Contains("elv"))
            {
                return "弱電";
            }
            if (probe.Contains("照明") || probe.Contains("lighting") || probe.Contains("ltg"))
            {
                return "照明";
            }
            if (probe.Contains("動力") || probe.Contains("power") || probe.Contains("pwr"))
            {
                return "動力";
            }
            if (mepKey == "conduit" || mepKey == "cable_tray")
            {
                return "電氣";
            }
            if (mepKey == "duct")
            {
                return "空調";
            }
            if (!string.IsNullOrWhiteSpace(text))
            {
                return text;
            }
            return "未分類";
        }

        private static string GetOpeningSystemName(Element mep, string mepKey)
        {
            string systemName = "";
            try
            {
                PropertyInfo systemProperty = mep.GetType().GetProperty("MEPSystem");
                object system = systemProperty != null ? systemProperty.GetValue(mep, null) : null;
                if (system != null)
                {
                    PropertyInfo nameProperty = system.GetType().GetProperty("Name");
                    systemName = nameProperty != null ? nameProperty.GetValue(system, null) as string : "";
                }
            }
            catch
            {
                systemName = "";
            }
            if (string.IsNullOrWhiteSpace(systemName))
            {
                systemName = GetElementParameterText(
                    mep,
                    new string[]
                    {
                        "系統名稱",
                        "系統類型",
                        "系統分類",
                        "System Name",
                        "System Type",
                        "System Classification"
                    }
                );
            }
            return NormalizeOpeningSystemName(systemName, mepKey);
        }

        private static string GetOpeningHostLabel(string key)
        {
            if (key == "wall") return "牆";
            if (key == "floor") return "樓板";
            if (key == "beam") return "梁";
            if (key == "column") return "柱";
            return key;
        }

        private static List<Element> CollectOpeningMepElements(Document doc, List<string> mepTypes)
        {
            var elements = new List<Element>();
            foreach (string key in mepTypes)
            {
                BuiltInCategory? category = GetOpeningMepCategory(key);
                if (!category.HasValue)
                {
                    continue;
                }
                foreach (Element element in new FilteredElementCollector(doc)
                    .OfCategory(category.Value)
                    .WhereElementIsNotElementType())
                {
                    if (element.Location is LocationCurve)
                    {
                        elements.Add(element);
                    }
                }
            }
            return elements;
        }

        private static List<Element> CollectOpeningHostElements(Document linkDoc, List<string> hostTypes)
        {
            var elements = new List<Element>();
            var seen = new HashSet<long>();
            foreach (string key in hostTypes)
            {
                var categories = new List<BuiltInCategory>();
                BuiltInCategory? category = GetOpeningHostCategory(key);
                if (category.HasValue)
                {
                    categories.Add(category.Value);
                }
                if (key == "column")
                {
                    categories.Add(BuiltInCategory.OST_Columns);
                }
                foreach (BuiltInCategory itemCategory in categories.Distinct())
                {
                    foreach (Element element in new FilteredElementCollector(linkDoc)
                        .OfCategory(itemCategory)
                        .WhereElementIsNotElementType())
                    {
                        if (seen.Add(element.Id.Value))
                        {
                            elements.Add(element);
                        }
                    }
                }
            }
            return elements;
        }

        private static XYZ NormalizePlanVector(XYZ vector, XYZ fallback)
        {
            XYZ plan = new XYZ(vector.X, vector.Y, 0);
            if (plan.GetLength() <= 0.000001)
            {
                plan = new XYZ(fallback.X, fallback.Y, 0);
            }
            if (plan.GetLength() <= 0.000001)
            {
                return XYZ.BasisX;
            }
            return plan.Normalize();
        }

        private static XYZ OpeningPlanPoint(XYZ direction, XYZ normal, double along, double offset)
        {
            return new XYZ(
                direction.X * along + normal.X * offset,
                direction.Y * along + normal.Y * offset,
                0
            );
        }

        private static List<XYZ> GetTransformedBoundingBoxCorners(BoundingBoxXYZ box, Autodesk.Revit.DB.Transform transform)
        {
            var points = new List<XYZ>();
            if (box == null)
            {
                return points;
            }
            XYZ[] corners = new XYZ[]
            {
                new XYZ(box.Min.X, box.Min.Y, box.Min.Z),
                new XYZ(box.Min.X, box.Min.Y, box.Max.Z),
                new XYZ(box.Min.X, box.Max.Y, box.Min.Z),
                new XYZ(box.Min.X, box.Max.Y, box.Max.Z),
                new XYZ(box.Max.X, box.Min.Y, box.Min.Z),
                new XYZ(box.Max.X, box.Min.Y, box.Max.Z),
                new XYZ(box.Max.X, box.Max.Y, box.Min.Z),
                new XYZ(box.Max.X, box.Max.Y, box.Max.Z)
            };
            foreach (XYZ corner in corners)
            {
                points.Add(transform.OfPoint(corner));
            }
            return points;
        }

        private static void AddOpeningPlanReferenceLine(
            List<OpeningPlanReference> references,
            string kind,
            string name,
            XYZ start,
            XYZ end,
            double weight,
            bool isAxis)
        {
            XYZ direction = NormalizePlanVector(end - start, XYZ.BasisX);
            double length = new XYZ(end.X - start.X, end.Y - start.Y, 0).GetLength();
            if (length < UnitUtils.ConvertToInternalUnits(10, UnitTypeId.Centimeters))
            {
                return;
            }
            XYZ normal = new XYZ(-direction.Y, direction.X, 0);
            double startAlong = start.DotProduct(direction);
            double endAlong = end.DotProduct(direction);
            double offset = start.DotProduct(normal);
            references.Add(new OpeningPlanReference
            {
                Kind = kind,
                Name = name,
                Start = new XYZ(start.X, start.Y, 0),
                End = new XYZ(end.X, end.Y, 0),
                Direction = direction,
                Normal = normal,
                Offset = offset,
                MinAlong = Math.Min(startAlong, endAlong),
                MaxAlong = Math.Max(startAlong, endAlong),
                Weight = weight,
                IsAxis = isAxis
            });
        }

        private static void AddOpeningEdgeReferencesFromLinearElement(
            List<OpeningPlanReference> references,
            Element element,
            Autodesk.Revit.DB.Transform transform,
            string kind,
            double weight)
        {
            LocationCurve locationCurve = element.Location as LocationCurve;
            if (locationCurve == null)
            {
                return;
            }
            Line line = locationCurve.Curve as Line;
            if (line == null)
            {
                return;
            }

            XYZ start = transform.OfPoint(line.GetEndPoint(0));
            XYZ end = transform.OfPoint(line.GetEndPoint(1));
            XYZ direction = NormalizePlanVector(end - start, XYZ.BasisX);
            XYZ normal = new XYZ(-direction.Y, direction.X, 0);
            List<XYZ> corners = GetTransformedBoundingBoxCorners(element.get_BoundingBox(null), transform);
            if (corners.Count == 0)
            {
                AddOpeningPlanReferenceLine(references, kind, element.Name, start, end, weight, false);
                return;
            }

            double minAlong = double.MaxValue;
            double maxAlong = double.MinValue;
            double minOffset = double.MaxValue;
            double maxOffset = double.MinValue;
            foreach (XYZ corner in corners)
            {
                double along = corner.DotProduct(direction);
                double offset = corner.DotProduct(normal);
                minAlong = Math.Min(minAlong, along);
                maxAlong = Math.Max(maxAlong, along);
                minOffset = Math.Min(minOffset, offset);
                maxOffset = Math.Max(maxOffset, offset);
            }

            XYZ edgeStartA = OpeningPlanPoint(direction, normal, minAlong, minOffset);
            XYZ edgeEndA = OpeningPlanPoint(direction, normal, maxAlong, minOffset);
            XYZ edgeStartB = OpeningPlanPoint(direction, normal, minAlong, maxOffset);
            XYZ edgeEndB = OpeningPlanPoint(direction, normal, maxAlong, maxOffset);
            XYZ edgeStartC = OpeningPlanPoint(direction, normal, minAlong, minOffset);
            XYZ edgeEndC = OpeningPlanPoint(direction, normal, minAlong, maxOffset);
            XYZ edgeStartD = OpeningPlanPoint(direction, normal, maxAlong, minOffset);
            XYZ edgeEndD = OpeningPlanPoint(direction, normal, maxAlong, maxOffset);
            AddOpeningPlanReferenceLine(references, kind, element.Name, edgeStartA, edgeEndA, weight, false);
            AddOpeningPlanReferenceLine(references, kind, element.Name, edgeStartB, edgeEndB, weight, false);
            AddOpeningPlanReferenceLine(references, kind, element.Name, edgeStartC, edgeEndC, weight, false);
            AddOpeningPlanReferenceLine(references, kind, element.Name, edgeStartD, edgeEndD, weight, false);
        }

        private static void AddOpeningColumnReferences(
            List<OpeningPlanReference> references,
            Element element,
            Autodesk.Revit.DB.Transform transform)
        {
            Dictionary<string, object> bounds = SerializeTransformedBoundingBox(element.get_BoundingBox(null), transform);
            if (bounds == null)
            {
                return;
            }
            XYZ min = ReadPoint(bounds, "min");
            XYZ max = ReadPoint(bounds, "max");
            if (max.X <= min.X || max.Y <= min.Y)
            {
                return;
            }
            string name = element.Name;
            double weight = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters);
            AddOpeningPlanReferenceLine(references, "柱邊", name, new XYZ(min.X, min.Y, 0), new XYZ(max.X, min.Y, 0), weight, false);
            AddOpeningPlanReferenceLine(references, "柱邊", name, new XYZ(max.X, min.Y, 0), new XYZ(max.X, max.Y, 0), weight, false);
            AddOpeningPlanReferenceLine(references, "柱邊", name, new XYZ(max.X, max.Y, 0), new XYZ(min.X, max.Y, 0), weight, false);
            AddOpeningPlanReferenceLine(references, "柱邊", name, new XYZ(min.X, max.Y, 0), new XYZ(min.X, min.Y, 0), weight, false);
        }

        private static void AddOpeningGridReference(
            List<OpeningPlanReference> references,
            Grid grid,
            Autodesk.Revit.DB.Transform transform)
        {
            Line line = grid.Curve as Line;
            if (line == null)
            {
                return;
            }
            double axisWeight = UnitUtils.ConvertToInternalUnits(200, UnitTypeId.Centimeters);
            AddOpeningPlanReferenceLine(
                references,
                "軸線",
                grid.Name,
                transform.OfPoint(line.GetEndPoint(0)),
                transform.OfPoint(line.GetEndPoint(1)),
                axisWeight,
                true);
        }

        private static List<OpeningPlanReference> CollectOpeningPlanReferences(Document linkDoc, Autodesk.Revit.DB.Transform linkTransform)
        {
            var references = new List<OpeningPlanReference>();

            foreach (Element wall in new FilteredElementCollector(linkDoc)
                .OfCategory(BuiltInCategory.OST_Walls)
                .WhereElementIsNotElementType())
            {
                AddOpeningEdgeReferencesFromLinearElement(references, wall, linkTransform, "牆邊", 0);
            }

            foreach (Element beam in new FilteredElementCollector(linkDoc)
                .OfCategory(BuiltInCategory.OST_StructuralFraming)
                .WhereElementIsNotElementType())
            {
                AddOpeningEdgeReferencesFromLinearElement(references, beam, linkTransform, "梁邊", 0);
            }

            var seenColumnIds = new HashSet<long>();
            BuiltInCategory[] columnCategories = new BuiltInCategory[]
            {
                BuiltInCategory.OST_StructuralColumns,
                BuiltInCategory.OST_Columns
            };
            foreach (BuiltInCategory category in columnCategories)
            {
                foreach (Element column in new FilteredElementCollector(linkDoc)
                    .OfCategory(category)
                    .WhereElementIsNotElementType())
                {
                    if (seenColumnIds.Add(column.Id.Value))
                    {
                        AddOpeningColumnReferences(references, column, linkTransform);
                    }
                }
            }

            foreach (Grid grid in new FilteredElementCollector(linkDoc).OfClass(typeof(Grid)).Cast<Grid>())
            {
                AddOpeningGridReference(references, grid, linkTransform);
            }

            return references;
        }

        private static List<OpeningPlanReference> CollectOpeningHostPlanReferences(
            Element host,
            Autodesk.Revit.DB.Transform linkTransform,
            string hostKey)
        {
            var references = new List<OpeningPlanReference>();
            if (host == null)
            {
                return references;
            }

            if (hostKey == "wall")
            {
                AddOpeningEdgeReferencesFromLinearElement(references, host, linkTransform, "牆邊", 0);
            }
            else if (hostKey == "beam")
            {
                AddOpeningEdgeReferencesFromLinearElement(references, host, linkTransform, "梁邊", 0);
            }
            else if (hostKey == "column")
            {
                AddOpeningColumnReferences(references, host, linkTransform);
            }

            return references;
        }

        private static Dictionary<string, object> FindNearestParallelOpeningReference(
            List<OpeningPlanReference> references,
            XYZ center,
            XYZ pipeStart,
            XYZ pipeEnd)
        {
            if (references == null || references.Count == 0)
            {
                return null;
            }

            XYZ pipeDirection = NormalizePlanVector(pipeEnd - pipeStart, XYZ.BasisX);
            double minDistance = UnitUtils.ConvertToInternalUnits(2, UnitTypeId.Centimeters);
            double maxDistance = UnitUtils.ConvertToInternalUnits(1000, UnitTypeId.Centimeters);
            double maxOutside = UnitUtils.ConvertToInternalUnits(50, UnitTypeId.Centimeters);
            OpeningPlanReference best = null;
            double bestScore = double.MaxValue;
            double bestSignedDistance = 0;
            double bestOutside = 0;
            double bestAlong = 0;

            foreach (OpeningPlanReference reference in references)
            {
                if (reference == null || reference.Direction == null || reference.Normal == null)
                {
                    continue;
                }
                double parallelScore = Math.Abs(reference.Direction.DotProduct(pipeDirection));
                if (parallelScore < 0.92)
                {
                    continue;
                }
                double signedDistance = center.DotProduct(reference.Normal) - reference.Offset;
                double along = center.DotProduct(reference.Direction);
                double clampedAlong = along;
                double outside = 0;
                if (along < reference.MinAlong)
                {
                    outside = reference.MinAlong - along;
                    clampedAlong = reference.MinAlong;
                }
                else if (along > reference.MaxAlong)
                {
                    outside = along - reference.MaxAlong;
                    clampedAlong = reference.MaxAlong;
                }
                if (outside > maxOutside)
                {
                    continue;
                }

                XYZ closestPoint = OpeningPlanPoint(reference.Direction, reference.Normal, clampedAlong, reference.Offset);
                double distance = new XYZ(center.X - closestPoint.X, center.Y - closestPoint.Y, 0).GetLength();
                if (distance < minDistance || distance > maxDistance)
                {
                    continue;
                }

                double axisPenalty = reference.IsAxis ? UnitUtils.ConvertToInternalUnits(300, UnitTypeId.Centimeters) : 0;
                double score = distance + outside * 0.5 + reference.Weight + axisPenalty;
                if (score < bestScore)
                {
                    best = reference;
                    bestScore = score;
                    bestSignedDistance = signedDistance;
                    bestOutside = outside;
                    bestAlong = clampedAlong;
                }
            }

            if (best == null)
            {
                return null;
            }

            XYZ edgePoint = OpeningPlanPoint(best.Direction, best.Normal, bestAlong, best.Offset);
            return new Dictionary<string, object>
            {
                { "kind", best.Kind },
                { "name", best.Name },
                { "start", SerializePoint(best.Start) },
                { "end", SerializePoint(best.End) },
                { "edge_point", SerializePoint(edgePoint) },
                { "pipe_direction", SerializePoint(best.Direction) },
                { "distance_ft", new XYZ(center.X - edgePoint.X, center.Y - edgePoint.Y, 0).GetLength() },
                { "outside_ft", bestOutside },
                { "is_axis", best.IsAxis }
            };
        }

        private static bool IsReliableOpeningDimensionReference(
            string hostKey,
            Dictionary<string, object> reference,
            out string reason)
        {
            reason = "";
            if (reference == null)
            {
                reason = "同一土建構件找不到可用標註邊";
                return false;
            }

            string kind = reference.ContainsKey("kind") && reference["kind"] != null
                ? reference["kind"].ToString()
                : "";
            bool expectedKind =
                (hostKey == "wall" && kind == "牆邊")
                || (hostKey == "beam" && kind == "梁邊")
                || (hostKey == "column" && kind == "柱邊");

            if (!expectedKind)
            {
                reason = "標註基準不是同一類土建構件邊";
                return false;
            }

            double distanceFt = ReadCandidateDouble(reference, "distance_ft", 0);
            if (distanceFt <= 0)
            {
                reason = "標註距離無效";
                return false;
            }

            double maxDistance = UnitUtils.ConvertToInternalUnits(300, UnitTypeId.Centimeters);
            if (distanceFt > maxDistance)
            {
                reason = "標註基準距離過遠";
                return false;
            }

            reason = "同一土建構件邊";
            return true;
        }

        private static List<Solid> GetElementSolids(Element element)
        {
            Options options = new Options();
            options.DetailLevel = ViewDetailLevel.Fine;
            options.ComputeReferences = false;
            var solids = new List<Solid>();
            try
            {
                GeometryElement geometry = element.get_Geometry(options);
                CollectSolidsFromGeometry(geometry, solids);
            }
            catch
            {
            }
            return solids;
        }

        private static void CollectSolidsFromGeometry(GeometryElement geometry, List<Solid> solids)
        {
            if (geometry == null)
            {
                return;
            }
            foreach (GeometryObject geometryObject in geometry)
            {
                Solid solid = geometryObject as Solid;
                if (solid != null && solid.Volume > 0.000001)
                {
                    solids.Add(solid);
                    continue;
                }
                GeometryInstance instance = geometryObject as GeometryInstance;
                if (instance != null)
                {
                    try
                    {
                        CollectSolidsFromGeometry(instance.GetInstanceGeometry(), solids);
                    }
                    catch
                    {
                    }
                }
            }
        }

        private static bool LineBoundingBoxOverlaps(Line line, BoundingBoxXYZ box, double expandFeet)
        {
            if (box == null)
            {
                return true;
            }
            XYZ a = line.GetEndPoint(0);
            XYZ b = line.GetEndPoint(1);
            double minX = Math.Min(a.X, b.X) - expandFeet;
            double maxX = Math.Max(a.X, b.X) + expandFeet;
            double minY = Math.Min(a.Y, b.Y) - expandFeet;
            double maxY = Math.Max(a.Y, b.Y) + expandFeet;
            double minZ = Math.Min(a.Z, b.Z) - expandFeet;
            double maxZ = Math.Max(a.Z, b.Z) + expandFeet;
            return maxX >= box.Min.X - expandFeet
                && minX <= box.Max.X + expandFeet
                && maxY >= box.Min.Y - expandFeet
                && minY <= box.Max.Y + expandFeet
                && maxZ >= box.Min.Z - expandFeet
                && minZ <= box.Max.Z + expandFeet;
        }

        private static double Cross2D(XYZ a, XYZ b)
        {
            return a.X * b.Y - a.Y * b.X;
        }

        private static bool TryGetPlanLineIntersectionOnSegments(
            Line first,
            Line second,
            double toleranceFeet,
            out XYZ pointOnFirst)
        {
            pointOnFirst = null;
            if (first == null || second == null)
            {
                return false;
            }

            XYZ firstStart = first.GetEndPoint(0);
            XYZ firstEnd = first.GetEndPoint(1);
            XYZ secondStart = second.GetEndPoint(0);
            XYZ secondEnd = second.GetEndPoint(1);
            XYZ firstVector = new XYZ(firstEnd.X - firstStart.X, firstEnd.Y - firstStart.Y, 0);
            XYZ secondVector = new XYZ(secondEnd.X - secondStart.X, secondEnd.Y - secondStart.Y, 0);
            double firstLength = firstVector.GetLength();
            double secondLength = secondVector.GetLength();
            if (firstLength < 0.000001 || secondLength < 0.000001)
            {
                return false;
            }

            XYZ firstDirection = firstVector / firstLength;
            XYZ secondDirection = secondVector / secondLength;
            double denominator = Cross2D(firstDirection, secondDirection);
            if (Math.Abs(denominator) < 0.000001)
            {
                return false;
            }

            XYZ delta = new XYZ(secondStart.X - firstStart.X, secondStart.Y - firstStart.Y, 0);
            double firstAlong = Cross2D(delta, secondDirection) / denominator;
            double secondAlong = Cross2D(delta, firstDirection) / denominator;
            if (firstAlong < -toleranceFeet || firstAlong > firstLength + toleranceFeet)
            {
                return false;
            }
            if (secondAlong < -toleranceFeet || secondAlong > secondLength + toleranceFeet)
            {
                return false;
            }

            double clampedFirstAlong = Math.Max(0, Math.Min(firstLength, firstAlong));
            double ratio = firstLength > 0 ? clampedFirstAlong / firstLength : 0;
            double z = firstStart.Z + (firstEnd.Z - firstStart.Z) * ratio;
            pointOnFirst = new XYZ(
                firstStart.X + firstDirection.X * clampedFirstAlong,
                firstStart.Y + firstDirection.Y * clampedFirstAlong,
                z);
            return true;
        }

        private static XYZ ResolveOpeningCenterLink(
            Element host,
            string hostKey,
            Line mepLineInLink,
            Curve intersectionSegment,
            out string centerSource)
        {
            centerSource = "實體交集中心";
            XYZ fallback = (intersectionSegment.GetEndPoint(0) + intersectionSegment.GetEndPoint(1)) * 0.5;
            if (hostKey != "beam" && hostKey != "wall")
            {
                return fallback;
            }

            LocationCurve hostLocation = host.Location as LocationCurve;
            Line hostLine = hostLocation != null ? hostLocation.Curve as Line : null;
            if (hostLine == null)
            {
                return fallback;
            }

            XYZ centerByLocationCurve = null;
            double toleranceFeet = UnitUtils.ConvertToInternalUnits(150, UnitTypeId.Centimeters);
            if (!TryGetPlanLineIntersectionOnSegments(mepLineInLink, hostLine, toleranceFeet, out centerByLocationCurve))
            {
                return fallback;
            }

            centerSource = "管中心線與結構中心線交點";
            return centerByLocationCurve;
        }

        private static double GetParameterDoubleByName(Element element, string[] names)
        {
            foreach (Parameter parameter in element.Parameters)
            {
                if (parameter == null || parameter.Definition == null || parameter.StorageType != StorageType.Double)
                {
                    continue;
                }
                string parameterName = parameter.Definition.Name ?? "";
                foreach (string name in names)
                {
                    if (string.Equals(parameterName, name, StringComparison.OrdinalIgnoreCase)
                        || parameterName.IndexOf(name, StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        try
                        {
                            return parameter.AsDouble();
                        }
                        catch
                        {
                            return 0;
                        }
                    }
                }
            }
            return 0;
        }

        private static double ApproximateSmallDimension(Element element)
        {
            BoundingBoxXYZ box = element.get_BoundingBox(null);
            if (box == null)
            {
                return 0;
            }
            var values = new List<double>
            {
                Math.Abs(box.Max.X - box.Min.X),
                Math.Abs(box.Max.Y - box.Min.Y),
                Math.Abs(box.Max.Z - box.Min.Z)
            };
            values.Sort();
            return values.Count > 0 ? values[0] : 0;
        }

        private static double[] ApproximateTwoSmallDimensions(Element element)
        {
            BoundingBoxXYZ box = element.get_BoundingBox(null);
            if (box == null)
            {
                return new double[] { 0, 0 };
            }
            var values = new List<double>
            {
                Math.Abs(box.Max.X - box.Min.X),
                Math.Abs(box.Max.Y - box.Min.Y),
                Math.Abs(box.Max.Z - box.Min.Z)
            };
            values.Sort();
            return new double[] { values[0], values[1] };
        }

        private static Dictionary<string, object> GetOpeningSizeInfo(Element mep, string mepKey, double clearanceMm)
        {
            double clearanceFeet = UnitUtils.ConvertToInternalUnits(clearanceMm, UnitTypeId.Millimeters);
            if (mepKey == "pipe")
            {
                double diameter = 0;
                Pipe pipe = mep as Pipe;
                if (pipe != null)
                {
                    Parameter diameterParameter = pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
                    if (diameterParameter != null)
                    {
                        diameter = diameterParameter.AsDouble();
                    }
                }
                if (diameter <= 0)
                {
                    diameter = GetParameterDoubleByName(mep, new string[] { "直徑", "管徑", "Diameter" });
                }
                if (diameter <= 0)
                {
                    diameter = ApproximateSmallDimension(mep);
                }
                double pipeDiameterMm = UnitUtils.ConvertFromInternalUnits(diameter, UnitTypeId.Millimeters);
                double openingDiameter = diameter + clearanceFeet * 2.0;
                double openingDiameterMm = UnitUtils.ConvertFromInternalUnits(openingDiameter, UnitTypeId.Millimeters);
                return new Dictionary<string, object>
                {
                    { "shape", "圓孔" },
                    { "size_text", "Ø" + Math.Round(openingDiameterMm, 1).ToString("0.#") + " mm" },
                    { "diameter_mm", openingDiameterMm },
                    { "pipe_diameter_mm", pipeDiameterMm }
                };
            }

            if (mepKey == "conduit")
            {
                double diameter = GetParameterDoubleByName(mep, new string[] { "直徑", "管徑", "Diameter" });
                if (diameter <= 0)
                {
                    diameter = ApproximateSmallDimension(mep);
                }
                double openingDiameter = diameter + clearanceFeet * 2.0;
                double openingDiameterMm = UnitUtils.ConvertFromInternalUnits(openingDiameter, UnitTypeId.Millimeters);
                return new Dictionary<string, object>
                {
                    { "shape", "圓孔" },
                    { "size_text", "Ø" + Math.Round(openingDiameterMm, 1).ToString("0.#") + " mm" },
                    { "diameter_mm", openingDiameterMm }
                };
            }

            double width = GetParameterDoubleByName(mep, new string[] { "寬度", "Width" });
            double height = GetParameterDoubleByName(mep, new string[] { "高度", "Height" });
            if (width <= 0 || height <= 0)
            {
                double[] dims = ApproximateTwoSmallDimensions(mep);
                if (width <= 0) width = dims[1];
                if (height <= 0) height = dims[0];
            }
            double openingWidthMm = UnitUtils.ConvertFromInternalUnits(width + clearanceFeet * 2.0, UnitTypeId.Millimeters);
            double openingHeightMm = UnitUtils.ConvertFromInternalUnits(height + clearanceFeet * 2.0, UnitTypeId.Millimeters);
            return new Dictionary<string, object>
            {
                { "shape", "矩形孔" },
                { "size_text", Math.Round(openingWidthMm, 1).ToString("0.#") + " x " + Math.Round(openingHeightMm, 1).ToString("0.#") + " mm" },
                { "width_mm", openingWidthMm },
                { "height_mm", openingHeightMm }
            };
        }

        private static string GetMepKey(Element element)
        {
            if (element.Category == null)
            {
                return "";
            }
            long id = element.Category.Id.Value;
            if (id == (long)BuiltInCategory.OST_PipeCurves) return "pipe";
            if (id == (long)BuiltInCategory.OST_Conduit) return "conduit";
            if (id == (long)BuiltInCategory.OST_DuctCurves) return "duct";
            if (id == (long)BuiltInCategory.OST_CableTray) return "cable_tray";
            return "";
        }

        private static string GetHostKey(Element element)
        {
            if (element.Category == null)
            {
                return "";
            }
            long id = element.Category.Id.Value;
            if (id == (long)BuiltInCategory.OST_Walls) return "wall";
            if (id == (long)BuiltInCategory.OST_Floors) return "floor";
            if (id == (long)BuiltInCategory.OST_StructuralFraming) return "beam";
            if (id == (long)BuiltInCategory.OST_StructuralColumns) return "column";
            if (id == (long)BuiltInCategory.OST_Columns) return "column";
            return "";
        }

        private static string GetNearestLevelName(Document doc, XYZ point)
        {
            Level level = new FilteredElementCollector(doc)
                .OfClass(typeof(Level))
                .Cast<Level>()
                .Where(item => item.Elevation <= point.Z + 0.01)
                .OrderByDescending(item => item.Elevation)
                .FirstOrDefault();
            if (level != null)
            {
                return level.Name;
            }
            level = new FilteredElementCollector(doc)
                .OfClass(typeof(Level))
                .Cast<Level>()
                .OrderBy(item => Math.Abs(item.Elevation - point.Z))
                .FirstOrDefault();
            return level != null ? level.Name : "";
        }

        private static string BuildOpeningStatus(string hostKey, Line hostLine, double intersectionLength)
        {
            if (hostKey == "beam" || hostKey == "column")
            {
                return "需確認";
            }
            XYZ direction = (hostLine.GetEndPoint(1) - hostLine.GetEndPoint(0)).Normalize();
            if (hostKey == "wall" && Math.Abs(direction.Z) > 0.25)
            {
                return "需確認";
            }
            if (hostKey == "floor" && Math.Abs(direction.Z) < 0.25)
            {
                return "需確認";
            }
            if (intersectionLength < UnitUtils.ConvertToInternalUnits(1, UnitTypeId.Centimeters))
            {
                return "需確認";
            }
            return "正常";
        }

        private static List<Dictionary<string, object>> ScanOpeningCandidates(
            Document doc,
            RevitLinkInstance linkInstance,
            Document linkDoc,
            List<string> mepTypes,
            List<string> hostTypes,
            double clearanceMm)
        {
            Autodesk.Revit.DB.Transform linkTransform = linkInstance.GetTotalTransform();
            Autodesk.Revit.DB.Transform hostToLink = linkTransform.Inverse;
            var candidates = new List<Dictionary<string, object>>();
            List<Element> mepElements = CollectOpeningMepElements(doc, mepTypes);
            List<Element> hostElements = CollectOpeningHostElements(linkDoc, hostTypes);
            List<OpeningPlanReference> planReferences = CollectOpeningPlanReferences(linkDoc, linkTransform);
            double clearanceFeet = UnitUtils.ConvertToInternalUnits(Math.Max(clearanceMm, 0), UnitTypeId.Millimeters);
            var solidsByHostId = new Dictionary<long, List<Solid>>();

            foreach (Element host in hostElements)
            {
                solidsByHostId[host.Id.Value] = GetElementSolids(host);
            }

            foreach (Element mep in mepElements)
            {
                LocationCurve locationCurve = mep.Location as LocationCurve;
                if (locationCurve == null)
                {
                    continue;
                }
                Curve curve = locationCurve.Curve;
                Line line = Line.CreateBound(
                    hostToLink.OfPoint(curve.GetEndPoint(0)),
                    hostToLink.OfPoint(curve.GetEndPoint(1))
                );
                string mepKey = GetMepKey(mep);
                if (string.IsNullOrWhiteSpace(mepKey))
                {
                    continue;
                }
                Dictionary<string, object> sizeInfo = GetOpeningSizeInfo(mep, mepKey, clearanceMm);

                foreach (Element host in hostElements)
                {
                    if (!LineBoundingBoxOverlaps(line, host.get_BoundingBox(null), clearanceFeet))
                    {
                        continue;
                    }
                    List<Solid> solids = solidsByHostId.ContainsKey(host.Id.Value)
                        ? solidsByHostId[host.Id.Value]
                        : new List<Solid>();
                    foreach (Solid solid in solids)
                    {
                        SolidCurveIntersection intersection = null;
                        try
                        {
                            intersection = solid.IntersectWithCurve(line, new SolidCurveIntersectionOptions());
                        }
                        catch
                        {
                            intersection = null;
                        }
                        if (intersection == null || intersection.SegmentCount == 0)
                        {
                            continue;
                        }
                        for (int index = 0; index < intersection.SegmentCount; index++)
                        {
                            Curve segment = intersection.GetCurveSegment(index);
                            double intersectionLength = segment.Length;
                            string hostKey = GetHostKey(host);
                            string centerSource = "";
                            XYZ centerLink = ResolveOpeningCenterLink(host, hostKey, line, segment, out centerSource);
                            XYZ centerHost = linkTransform.OfPoint(centerLink);
                            string status = BuildOpeningStatus(hostKey, line, intersectionLength);
                            string note = "";
                            if (status == "需確認")
                            {
                                if (hostKey == "beam")
                                {
                                    note = "梁穿越需結構確認";
                                }
                                else if (hostKey == "column")
                                {
                                    note = "柱穿越需結構確認";
                                }
                                else
                                {
                                    note = hostKey == "floor" ? "樓板穿越角度需確認" : "牆體穿越角度需確認";
                                }
                            }
                            Dictionary<string, object> hostBounds = SerializeTransformedBoundingBox(host.get_BoundingBox(null), linkTransform);
                            List<OpeningPlanReference> hostPlanReferences = CollectOpeningHostPlanReferences(host, linkTransform, hostKey);
                            Dictionary<string, object> parallelDimRef = FindNearestParallelOpeningReference(
                                hostPlanReferences,
                                centerHost,
                                curve.GetEndPoint(0),
                                curve.GetEndPoint(1));
                            string dimensionReason = "";
                            bool dimensionReliable = IsReliableOpeningDimensionReference(hostKey, parallelDimRef, out dimensionReason);
                            if (!dimensionReliable)
                            {
                                if (!string.IsNullOrWhiteSpace(note))
                                {
                                    note += "；";
                                }
                                note += "不自動標註：" + dimensionReason;
                            }
                            double dimensionDistanceCm = 0;
                            if (parallelDimRef != null && parallelDimRef.ContainsKey("distance_ft"))
                            {
                                dimensionDistanceCm = UnitUtils.ConvertFromInternalUnits(
                                    ReadCandidateDouble(parallelDimRef, "distance_ft", 0),
                                    UnitTypeId.Centimeters);
                            }
                            candidates.Add(new Dictionary<string, object>
                            {
                                { "status", status },
                                { "system", GetOpeningSystemName(mep, mepKey) },
                                { "mep_type", GetOpeningMepLabel(mepKey) },
                                { "mep_id", mep.Id.Value },
                                { "mep_name", mep.Name },
                                { "host_type", GetOpeningHostLabel(hostKey) },
                                { "host_id", host.Id.Value },
                                { "host_name", host.Name },
                                { "link_id", linkInstance.Id.Value },
                                { "link_name", linkInstance.Name },
                                { "level", GetNearestLevelName(doc, centerHost) },
                                { "center", SerializePoint(centerHost) },
                                { "host_bbox_min", hostBounds != null && hostBounds.ContainsKey("min") ? hostBounds["min"] : null },
                                { "host_bbox_max", hostBounds != null && hostBounds.ContainsKey("max") ? hostBounds["max"] : null },
                                { "parallel_dim_ref", parallelDimRef },
                                { "dimension_is_reliable", dimensionReliable },
                                { "dimension_ref_kind", parallelDimRef != null && parallelDimRef.ContainsKey("kind") ? parallelDimRef["kind"] : "" },
                                { "dimension_ref_name", parallelDimRef != null && parallelDimRef.ContainsKey("name") ? parallelDimRef["name"] : "" },
                                { "dimension_distance_cm", dimensionDistanceCm },
                                { "dimension_note", dimensionReason },
                                { "center_source", centerSource },
                                { "mep_start", SerializePoint(curve.GetEndPoint(0)) },
                                { "mep_end", SerializePoint(curve.GetEndPoint(1)) },
                                { "shape", sizeInfo.ContainsKey("shape") ? sizeInfo["shape"] : "" },
                                { "size_text", sizeInfo.ContainsKey("size_text") ? sizeInfo["size_text"] : "" },
                                { "pipe_diameter_mm", sizeInfo.ContainsKey("pipe_diameter_mm") ? sizeInfo["pipe_diameter_mm"] : 0 },
                                { "note", note },
                                { "intersection_length_mm", UnitUtils.ConvertFromInternalUnits(intersectionLength, UnitTypeId.Millimeters) }
                            });
                        }
                        break;
                    }
                }
            }
            return candidates
                .OrderBy(item => item.ContainsKey("level") ? item["level"].ToString() : "")
                .ThenBy(item => Convert.ToInt64(item["mep_id"]))
                .ThenBy(item => Convert.ToInt64(item["host_id"]))
                .ToList();
        }

        private static View3D GetOrCreateOpeningView(Document doc)
        {
            const string viewName = "SC 開孔定位檢視";
            View3D existing = new FilteredElementCollector(doc)
                .OfClass(typeof(View3D))
                .Cast<View3D>()
                .FirstOrDefault(item => !item.IsTemplate && item.Name == viewName);
            if (existing != null)
            {
                return existing;
            }

            ViewFamilyType viewFamilyType = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewFamilyType))
                .Cast<ViewFamilyType>()
                .FirstOrDefault(item => item.ViewFamily == ViewFamily.ThreeDimensional);
            if (viewFamilyType == null)
            {
                throw new InvalidOperationException("找不到可用的 3D 視圖類型");
            }
            View3D view = View3D.CreateIsometric(doc, viewFamilyType.Id);
            try
            {
                view.Name = viewName;
            }
            catch
            {
                // If name collision happens, Revit will keep its generated name.
            }
            return view;
        }

        private static Dictionary<string, object> ViewOpeningCandidate(
            UIApplication uiApp,
            Dictionary<string, object> payload)
        {
            Document doc = GetActiveProjectDocument(uiApp);
            UIDocument uiDoc = uiApp.ActiveUIDocument;
            Dictionary<string, object> candidate = payload.ContainsKey("candidate")
                ? payload["candidate"] as Dictionary<string, object>
                : null;
            if (candidate == null)
            {
                throw new InvalidOperationException("沒有可檢視的開孔候選資料");
            }

            if (!candidate.ContainsKey("center") || candidate["center"] == null)
            {
                throw new InvalidOperationException("開孔候選資料缺少中心點");
            }
            XYZ center = ReadPoint(candidate, "center");
            double boxSizeCm = ReadDouble(payload, "box_size_cm", 250);
            double halfSize = UnitUtils.ConvertToInternalUnits(Math.Max(boxSizeCm, 50) / 2.0, UnitTypeId.Centimeters);
            View3D view;
            using (Transaction transaction = new Transaction(doc, "SC 開孔 3D 檢視"))
            {
                transaction.Start();
                view = GetOrCreateOpeningView(doc);
                BoundingBoxXYZ box = new BoundingBoxXYZ();
                box.Transform = Autodesk.Revit.DB.Transform.Identity;
                box.Min = new XYZ(center.X - halfSize, center.Y - halfSize, center.Z - halfSize);
                box.Max = new XYZ(center.X + halfSize, center.Y + halfSize, center.Z + halfSize);
                view.IsSectionBoxActive = true;
                view.SetSectionBox(box);
                transaction.Commit();
            }

            var selectionIds = new List<ElementId>();
            long mepId = 0;
            if (candidate.ContainsKey("mep_id"))
            {
                long.TryParse(candidate["mep_id"].ToString(), out mepId);
            }
            if (mepId > 0 && doc.GetElement(new ElementId(mepId)) != null)
            {
                selectionIds.Add(new ElementId(mepId));
            }
            long linkId = 0;
            if (candidate.ContainsKey("link_id"))
            {
                long.TryParse(candidate["link_id"].ToString(), out linkId);
            }
            if (linkId > 0 && doc.GetElement(new ElementId(linkId)) != null)
            {
                selectionIds.Add(new ElementId(linkId));
            }

            try
            {
                uiDoc.RequestViewChange(view);
            }
            catch
            {
                try { uiDoc.ActiveView = view; } catch { }
            }
            try
            {
                uiDoc.Selection.SetElementIds(selectionIds);
            }
            catch
            {
            }
            try
            {
                if (selectionIds.Count > 0)
                {
                    uiDoc.ShowElements(selectionIds);
                }
            }
            catch
            {
            }

            return new Dictionary<string, object>
            {
                { "view_id", view.Id.Value },
                { "view_name", view.Name },
                { "center", SerializePoint(center) },
                { "center_text", "X " + center.X.ToString("0.##") + " / Y " + center.Y.ToString("0.##") + " / Z " + center.Z.ToString("0.##") }
            };
        }

        private static Level FindOpeningLevel(Document doc, Dictionary<string, object> candidate, XYZ center)
        {
            string levelName = candidate.ContainsKey("level") && candidate["level"] != null
                ? candidate["level"].ToString()
                : "";
            if (!string.IsNullOrWhiteSpace(levelName))
            {
                Level namedLevel = new FilteredElementCollector(doc)
                    .OfClass(typeof(Level))
                    .Cast<Level>()
                    .FirstOrDefault(item => string.Equals(item.Name, levelName, StringComparison.OrdinalIgnoreCase));
                if (namedLevel != null)
                {
                    return namedLevel;
                }
            }

            Level nearest = new FilteredElementCollector(doc)
                .OfClass(typeof(Level))
                .Cast<Level>()
                .OrderBy(item => Math.Abs(item.Elevation - center.Z))
                .FirstOrDefault();
            if (nearest == null)
            {
                throw new InvalidOperationException("找不到可用樓層，無法建立預留套管平面");
            }
            return nearest;
        }

        private static string SafeViewNamePart(string value)
        {
            string text = string.IsNullOrWhiteSpace(value) ? "未分層" : value.Trim();
            return Regex.Replace(text, @"[\\/:*?""<>|{}\[\];=]", "_");
        }

        private static ViewPlan GetOrCreateOpeningPlanView(Document doc, Level level, string viewNamePrefix)
        {
            string prefix = string.IsNullOrWhiteSpace(viewNamePrefix) ? "SC 預留套管平面" : viewNamePrefix.Trim();
            string viewName = prefix + " - " + SafeViewNamePart(level.Name);
            ViewPlan existing = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewPlan))
                .Cast<ViewPlan>()
                .FirstOrDefault(item => !item.IsTemplate && item.Name == viewName);
            if (existing != null)
            {
                return existing;
            }

            ViewFamilyType viewFamilyType = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewFamilyType))
                .Cast<ViewFamilyType>()
                .FirstOrDefault(item => item.ViewFamily == ViewFamily.FloorPlan);
            if (viewFamilyType == null)
            {
                throw new InvalidOperationException("找不到可用的樓層平面視圖類型");
            }

            ViewPlan view = ViewPlan.Create(doc, viewFamilyType.Id, level.Id);
            try
            {
                view.Name = viewName;
            }
            catch
            {
            }
            try
            {
                view.Scale = 50;
            }
            catch
            {
            }
            try
            {
                view.DetailLevel = ViewDetailLevel.Fine;
            }
            catch
            {
            }
            return view;
        }

        private static void ClearOpeningMarkersInView(Document doc, ViewPlan view)
        {
            var groupIds = new FilteredElementCollector(doc, view.Id)
                .WhereElementIsNotElementType()
                .OfClass(typeof(Autodesk.Revit.DB.Group))
                .Cast<Autodesk.Revit.DB.Group>()
                .Where(item => item.GroupType != null && item.GroupType.Name.StartsWith("SC 開孔標記", StringComparison.OrdinalIgnoreCase))
                .Select(item => item.Id)
                .ToList();
            if (groupIds.Count > 0)
            {
                doc.Delete(groupIds);
            }

            var ids = new FilteredElementCollector(doc, view.Id)
                .WhereElementIsNotElementType()
                .Where(item => item is DetailCurve || item is TextNote || item is FilledRegion || item is Dimension)
                .Select(item => item.Id)
                .ToList();
            if (ids.Count > 0)
            {
                doc.Delete(ids);
            }
        }

        private static ElementId GetDefaultTextNoteTypeId(Document doc)
        {
            ElementId textTypeId = doc.GetDefaultElementTypeId(ElementTypeGroup.TextNoteType);
            if (textTypeId != ElementId.InvalidElementId)
            {
                return textTypeId;
            }
            TextNoteType textNoteType = new FilteredElementCollector(doc)
                .OfClass(typeof(TextNoteType))
                .Cast<TextNoteType>()
                .FirstOrDefault();
            if (textNoteType == null)
            {
                throw new InvalidOperationException("找不到文字註記類型，無法建立開孔標記文字");
            }
            return textNoteType.Id;
        }

        private static ElementId GetOrCreateOpeningTextNoteTypeId(Document doc)
        {
            const string typeName = "SC 開孔標記文字";
            TextNoteType existing = new FilteredElementCollector(doc)
                .OfClass(typeof(TextNoteType))
                .Cast<TextNoteType>()
                .FirstOrDefault(item => item.Name == typeName);
            if (existing != null)
            {
                return existing.Id;
            }

            TextNoteType source = doc.GetElement(GetDefaultTextNoteTypeId(doc)) as TextNoteType;
            if (source == null)
            {
                source = new FilteredElementCollector(doc)
                    .OfClass(typeof(TextNoteType))
                    .Cast<TextNoteType>()
                    .FirstOrDefault();
            }
            if (source == null)
            {
                throw new InvalidOperationException("找不到文字註記類型，無法建立開孔標記文字");
            }

            TextNoteType duplicated = source.Duplicate(typeName) as TextNoteType;
            try
            {
                Parameter sizeParameter = duplicated.get_Parameter(BuiltInParameter.TEXT_SIZE);
                if (sizeParameter != null && !sizeParameter.IsReadOnly)
                {
                    sizeParameter.Set(UnitUtils.ConvertToInternalUnits(2.5, UnitTypeId.Millimeters));
                }
            }
            catch
            {
            }
            try
            {
                Parameter colorParameter = duplicated.get_Parameter(BuiltInParameter.LINE_COLOR);
                if (colorParameter != null && !colorParameter.IsReadOnly)
                {
                    colorParameter.Set(255);
                }
            }
            catch
            {
            }
            return duplicated.Id;
        }

        private static double[] ResolveOpeningMarkerSizeFeet(Dictionary<string, object> candidate)
        {
            double minSize = UnitUtils.ConvertToInternalUnits(15, UnitTypeId.Centimeters);
            string sizeText = candidate.ContainsKey("size_text") && candidate["size_text"] != null
                ? candidate["size_text"].ToString()
                : "";
            MatchCollection matches = Regex.Matches(sizeText, @"\d+(\.\d+)?");
            string shape = candidate.ContainsKey("shape") && candidate["shape"] != null
                ? candidate["shape"].ToString()
                : "";

            if (shape.Contains("矩") && matches.Count >= 2)
            {
                double widthMm = Convert.ToDouble(matches[0].Value);
                double heightMm = Convert.ToDouble(matches[1].Value);
                double width = UnitUtils.ConvertToInternalUnits(widthMm, UnitTypeId.Millimeters);
                double height = UnitUtils.ConvertToInternalUnits(heightMm, UnitTypeId.Millimeters);
                return new double[] { Math.Max(width, minSize), Math.Max(height, minSize) };
            }
            if (matches.Count >= 1)
            {
                double diameterMm = Convert.ToDouble(matches[0].Value);
                double diameter = UnitUtils.ConvertToInternalUnits(diameterMm, UnitTypeId.Millimeters);
                diameter = Math.Max(diameter, minSize);
                return new double[] { diameter, diameter };
            }
            return new double[] { minSize, minSize };
        }

        private static void ApplyOpeningMarkerOverride(View view, Element element)
        {
            if (view == null || element == null)
            {
                return;
            }
            try
            {
                OverrideGraphicSettings settings = new OverrideGraphicSettings();
                settings.SetProjectionLineColor(new Autodesk.Revit.DB.Color(255, 0, 0));
                settings.SetProjectionLineWeight(6);
                view.SetElementOverrides(element.Id, settings);
            }
            catch
            {
            }
        }

        private static void ApplyOpeningBeamMarkerOverride(View view, Element element)
        {
            if (view == null || element == null)
            {
                return;
            }
            try
            {
                OverrideGraphicSettings settings = new OverrideGraphicSettings();
                settings.SetProjectionLineColor(new Autodesk.Revit.DB.Color(255, 0, 255));
                settings.SetProjectionLineWeight(8);
                view.SetElementOverrides(element.Id, settings);
            }
            catch
            {
            }
        }

        private static void AddOpeningDetailCurve(
            Document doc,
            ViewPlan view,
            Curve curve,
            List<ElementId> createdIds)
        {
            DetailCurve detailCurve = doc.Create.NewDetailCurve(view, curve);
            createdIds.Add(detailCurve.Id);
            ApplyOpeningMarkerOverride(view, detailCurve);
        }

        private static void AddOpeningBeamDetailCurve(
            Document doc,
            ViewPlan view,
            Curve curve,
            List<ElementId> createdIds)
        {
            DetailCurve detailCurve = doc.Create.NewDetailCurve(view, curve);
            createdIds.Add(detailCurve.Id);
            ApplyOpeningBeamMarkerOverride(view, detailCurve);
        }

        private static ElementId GetOrCreateBeamOpeningFilledRegionTypeId(Document doc)
        {
            const string typeName = "SC 開孔梁套管填滿";
            FilledRegionType existing = new FilteredElementCollector(doc)
                .OfClass(typeof(FilledRegionType))
                .Cast<FilledRegionType>()
                .FirstOrDefault(item => item.Name == typeName);
            if (existing != null)
            {
                return existing.Id;
            }

            FilledRegionType source = new FilteredElementCollector(doc)
                .OfClass(typeof(FilledRegionType))
                .Cast<FilledRegionType>()
                .FirstOrDefault();
            if (source == null)
            {
                throw new InvalidOperationException("找不到填滿區域類型，無法建立穿梁套管標記");
            }

            FilledRegionType duplicated = source.Duplicate(typeName) as FilledRegionType;
            try
            {
                FillPatternElement solidPattern = new FilteredElementCollector(doc)
                    .OfClass(typeof(FillPatternElement))
                    .Cast<FillPatternElement>()
                    .FirstOrDefault(item => item.GetFillPattern().IsSolidFill);
                if (solidPattern != null)
                {
                    duplicated.ForegroundPatternId = solidPattern.Id;
                }
                duplicated.ForegroundPatternColor = new Autodesk.Revit.DB.Color(255, 0, 255);
                duplicated.BackgroundPatternColor = new Autodesk.Revit.DB.Color(255, 0, 255);
                duplicated.IsMasking = false;
                duplicated.LineWeight = 8;
            }
            catch
            {
            }
            return duplicated.Id;
        }

        private static XYZ GetOpeningPipeDirection(Dictionary<string, object> candidate)
        {
            if (candidate.ContainsKey("mep_start") && candidate.ContainsKey("mep_end"))
            {
                XYZ start = ReadPoint(candidate, "mep_start");
                XYZ end = ReadPoint(candidate, "mep_end");
                XYZ direction = new XYZ(end.X - start.X, end.Y - start.Y, 0);
                if (direction.GetLength() > 0.000001)
                {
                    return direction.Normalize();
                }
            }
            return XYZ.BasisX;
        }

        private static double ReadCandidateDouble(Dictionary<string, object> candidate, string key, double defaultValue = 0)
        {
            if (!candidate.ContainsKey(key) || candidate[key] == null)
            {
                return defaultValue;
            }
            double parsed;
            return double.TryParse(candidate[key].ToString(), out parsed) ? parsed : defaultValue;
        }

        private static void AddOpeningBeamFilledRegion(
            Document doc,
            ViewPlan view,
            Dictionary<string, object> candidate,
            XYZ center,
            double markerWidth,
            double markerHeight,
            List<ElementId> createdIds)
        {
            XYZ along = GetOpeningPipeDirection(candidate);
            XYZ across = new XYZ(-along.Y, along.X, 0);
            Level level = view.GenLevel;
            double z = level != null ? level.Elevation : center.Z;
            XYZ c = new XYZ(center.X, center.Y, z);
            double hw = markerWidth / 2.0;
            double hh = markerHeight / 2.0;
            XYZ p1 = c - along * hw - across * hh;
            XYZ p2 = c + along * hw - across * hh;
            XYZ p3 = c + along * hw + across * hh;
            XYZ p4 = c - along * hw + across * hh;

            CurveLoop loop = new CurveLoop();
            loop.Append(Line.CreateBound(p1, p2));
            loop.Append(Line.CreateBound(p2, p3));
            loop.Append(Line.CreateBound(p3, p4));
            loop.Append(Line.CreateBound(p4, p1));
            IList<CurveLoop> loops = new List<CurveLoop> { loop };

            FilledRegion region = FilledRegion.Create(doc, GetOrCreateBeamOpeningFilledRegionTypeId(doc), view.Id, loops);
            createdIds.Add(region.Id);
            ApplyOpeningBeamMarkerOverride(view, region);

            AddOpeningBeamDetailCurve(doc, view, Line.CreateBound(p1, p2), createdIds);
            AddOpeningBeamDetailCurve(doc, view, Line.CreateBound(p2, p3), createdIds);
            AddOpeningBeamDetailCurve(doc, view, Line.CreateBound(p3, p4), createdIds);
            AddOpeningBeamDetailCurve(doc, view, Line.CreateBound(p4, p1), createdIds);
        }

        private static bool IsBeamOpeningCandidate(Dictionary<string, object> candidate)
        {
            string hostType = candidate.ContainsKey("host_type") && candidate["host_type"] != null
                ? candidate["host_type"].ToString()
                : "";
            return hostType.Contains("梁");
        }

        private static string ResolveFirePipeInchText(double pipeDiameterMm)
        {
            if (pipeDiameterMm <= 0)
            {
                return "";
            }

            double[] nominalMm = new double[] { 15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150, 200 };
            double[] outerMm = new double[] { 21.3, 26.9, 33.7, 42.4, 48.3, 60.3, 76.1, 88.9, 114.3, 139.7, 168.3, 219.1 };
            string[] inchText = new string[] { "1/2\"", "3/4\"", "1\"", "1 1/4\"", "1 1/2\"", "2\"", "2 1/2\"", "3\"", "4\"", "5\"", "6\"", "8\"" };

            int bestIndex = -1;
            double bestDiff = double.MaxValue;
            for (int i = 0; i < nominalMm.Length; i++)
            {
                double dnDiff = Math.Abs(pipeDiameterMm - nominalMm[i]);
                if (dnDiff < bestDiff)
                {
                    bestDiff = dnDiff;
                    bestIndex = i;
                }

                double odDiff = Math.Abs(pipeDiameterMm - outerMm[i]);
                if (odDiff < bestDiff)
                {
                    bestDiff = odDiff;
                    bestIndex = i;
                }
            }

            return bestIndex >= 0 && bestDiff <= 5.0 ? inchText[bestIndex] : "";
        }

        private static string BuildOpeningConstructionLabel(Dictionary<string, object> candidate)
        {
            string sizeText = candidate.ContainsKey("size_text") && candidate["size_text"] != null
                ? candidate["size_text"].ToString()
                : "";
            string shape = candidate.ContainsKey("shape") && candidate["shape"] != null
                ? candidate["shape"].ToString()
                : "";
            MatchCollection matches = Regex.Matches(sizeText, @"\d+(\.\d+)?");
            string baseText = "";

            if (shape.Contains("矩") && matches.Count >= 2)
            {
                double width = Convert.ToDouble(matches[0].Value);
                double height = Convert.ToDouble(matches[1].Value);
                baseText = Math.Round(width).ToString("0") + "x" + Math.Round(height).ToString("0");
            }
            else if (matches.Count >= 1)
            {
                double diameter = Convert.ToDouble(matches[0].Value);
                baseText = "Ø" + Math.Round(diameter).ToString("0");
            }
            else
            {
                string cleaned = sizeText
                    .Replace(" ", "")
                    .Replace("ｍｍ", "")
                    .Replace("MM", "")
                    .Replace("mm", "");
                baseText = string.IsNullOrWhiteSpace(cleaned) ? "開孔" : cleaned;
            }

            double pipeDiameterMm = ReadCandidateDouble(candidate, "pipe_diameter_mm", 0);
            string inchText = ResolveFirePipeInchText(pipeDiameterMm);
            if (!string.IsNullOrWhiteSpace(inchText) && !shape.Contains("矩"))
            {
                return baseText + "\n" + inchText;
            }
            return baseText;
        }

        private static string FormatOpeningDimensionCm(double lengthFeet)
        {
            double cm = UnitUtils.ConvertFromInternalUnits(Math.Abs(lengthFeet), UnitTypeId.Centimeters);
            if (cm < 10)
            {
                return cm.ToString("0.#");
            }
            return Math.Round(cm).ToString("0");
        }

        private static void AddOpeningDimensionTick(
            Document doc,
            ViewPlan view,
            XYZ point,
            XYZ dimensionDirection,
            double tickLength,
            List<ElementId> createdIds)
        {
            XYZ dir = new XYZ(dimensionDirection.X, dimensionDirection.Y, 0);
            if (dir.GetLength() <= 0.000001)
            {
                return;
            }
            dir = dir.Normalize();
            XYZ perpendicular = new XYZ(-dir.Y, dir.X, 0);
            AddOpeningDetailCurve(doc, view, Line.CreateBound(point - perpendicular * (tickLength / 2.0), point + perpendicular * (tickLength / 2.0)), createdIds);
        }

        private static void AddOpeningDimensionText(
            Document doc,
            ViewPlan view,
            XYZ textPoint,
            string text,
            ElementId textTypeId,
            double rotationRadians,
            List<ElementId> createdIds)
        {
            TextNote note = TextNote.Create(doc, view.Id, textPoint, text, textTypeId);
            createdIds.Add(note.Id);
            ApplyOpeningMarkerOverride(view, note);
            if (Math.Abs(rotationRadians) > 0.000001)
            {
                try
                {
                    ElementTransformUtils.RotateElement(doc, note.Id, Line.CreateBound(textPoint, textPoint + XYZ.BasisZ), rotationRadians);
                }
                catch
                {
                }
            }
        }

        private static void AddOpeningDimensionLine(
            Document doc,
            ViewPlan view,
            XYZ start,
            XYZ end,
            ElementId textTypeId,
            bool rotateText,
            List<ElementId> createdIds)
        {
            XYZ direction = new XYZ(end.X - start.X, end.Y - start.Y, 0);
            double length = direction.GetLength();
            double minLength = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters);
            double maxLength = UnitUtils.ConvertToInternalUnits(2000, UnitTypeId.Centimeters);
            if (length < minLength || length > maxLength)
            {
                return;
            }
            direction = direction.Normalize();
            XYZ perpendicular = new XYZ(-direction.Y, direction.X, 0);
            double tickLength = UnitUtils.ConvertToInternalUnits(4, UnitTypeId.Centimeters);
            double textOffset = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters);

            AddOpeningDetailCurve(doc, view, Line.CreateBound(start, end), createdIds);
            AddOpeningDimensionTick(doc, view, start, direction, tickLength, createdIds);
            AddOpeningDimensionTick(doc, view, end, direction, tickLength, createdIds);

            XYZ midpoint = (start + end) * 0.5;
            XYZ textPoint = midpoint + perpendicular * textOffset;
            AddOpeningDimensionText(doc, view, textPoint, FormatOpeningDimensionCm(length), textTypeId, rotateText ? Math.PI / 2.0 : 0, createdIds);
        }

        private static ElementId ResolveOpeningDimensionTypeId(Document doc, Dictionary<string, object> payload)
        {
            long typeId = ReadLong(payload, "dimension_type_id", 0);
            if (typeId > 0)
            {
                DimensionType selected = doc.GetElement(new ElementId(typeId)) as DimensionType;
                if (selected != null)
                {
                    return selected.Id;
                }
            }
            return ElementId.InvalidElementId;
        }

        private static GraphicsStyle FindOpeningInvisibleLineStyle(Document doc)
        {
            try
            {
                foreach (GraphicsStyle style in new FilteredElementCollector(doc)
                    .OfClass(typeof(GraphicsStyle))
                    .Cast<GraphicsStyle>())
                {
                    if (style.GraphicsStyleCategory == null)
                    {
                        continue;
                    }
                    string name = style.GraphicsStyleCategory.Name ?? "";
                    if (name.IndexOf("不可見", StringComparison.OrdinalIgnoreCase) >= 0
                        || name.IndexOf("Invisible", StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        return style;
                    }
                }
            }
            catch
            {
            }
            return null;
        }

        private static DetailCurve AddOpeningDimensionReferenceCurve(
            Document doc,
            ViewPlan view,
            XYZ point,
            XYZ direction,
            List<ElementId> createdIds)
        {
            XYZ dir = NormalizePlanVector(direction, XYZ.BasisX);
            double halfLength = UnitUtils.ConvertToInternalUnits(6, UnitTypeId.Centimeters);
            DetailCurve curve = doc.Create.NewDetailCurve(
                view,
                Line.CreateBound(point - dir * halfLength, point + dir * halfLength));
            createdIds.Add(curve.Id);
            GraphicsStyle invisibleStyle = FindOpeningInvisibleLineStyle(doc);
            if (invisibleStyle != null)
            {
                try { curve.LineStyle = invisibleStyle; } catch { }
            }
            else
            {
                ApplyOpeningMarkerOverride(view, curve);
            }
            return curve;
        }

        private static bool AddOpeningNativeDimension(
            Document doc,
            ViewPlan view,
            XYZ center,
            XYZ edgePoint,
            XYZ pipeDirection,
            ElementId textTypeId,
            ElementId dimensionTypeId,
            List<ElementId> createdIds)
        {
            XYZ dimensionVector = new XYZ(center.X - edgePoint.X, center.Y - edgePoint.Y, 0);
            double length = dimensionVector.GetLength();
            double minLength = UnitUtils.ConvertToInternalUnits(5, UnitTypeId.Centimeters);
            double maxLength = UnitUtils.ConvertToInternalUnits(2500, UnitTypeId.Centimeters);
            if (length < minLength || length > maxLength)
            {
                return false;
            }

            XYZ pipeDir = NormalizePlanVector(pipeDirection, XYZ.BasisX);
            XYZ edge = new XYZ(edgePoint.X, edgePoint.Y, center.Z);
            XYZ centerPlan = new XYZ(center.X, center.Y, center.Z);
            try
            {
                DetailCurve edgeReferenceCurve = AddOpeningDimensionReferenceCurve(doc, view, edge, pipeDir, createdIds);
                DetailCurve centerReferenceCurve = AddOpeningDimensionReferenceCurve(doc, view, centerPlan, pipeDir, createdIds);
                Reference edgeReference = edgeReferenceCurve.GeometryCurve.Reference;
                Reference centerReference = centerReferenceCurve.GeometryCurve.Reference;
                if (edgeReference == null || centerReference == null)
                {
                    return false;
                }

                ReferenceArray references = new ReferenceArray();
                references.Append(edgeReference);
                references.Append(centerReference);
                Line dimensionLine = Line.CreateBound(edge, centerPlan);
                Dimension dimension = null;
                DimensionType dimensionType = dimensionTypeId != ElementId.InvalidElementId
                    ? doc.GetElement(dimensionTypeId) as DimensionType
                    : null;
                if (dimensionType != null)
                {
                    dimension = doc.Create.NewDimension(view, dimensionLine, references, dimensionType);
                }
                else
                {
                    dimension = doc.Create.NewDimension(view, dimensionLine, references);
                }
                if (dimension != null)
                {
                    createdIds.Add(dimension.Id);
                    return true;
                }
            }
            catch
            {
            }

            AddOpeningDimensionLine(doc, view, edge, centerPlan, textTypeId, Math.Abs(dimensionVector.Y) > Math.Abs(dimensionVector.X), createdIds);
            return false;
        }

        private static bool AddOpeningParallelReferenceDimension(
            Document doc,
            ViewPlan view,
            Dictionary<string, object> reference,
            XYZ center,
            ElementId textTypeId,
            ElementId dimensionTypeId,
            List<ElementId> createdIds)
        {
            if (reference == null || !reference.ContainsKey("edge_point") || reference["edge_point"] == null)
            {
                return false;
            }
            XYZ edgePoint = ReadPoint(reference, "edge_point");
            XYZ pipeDirection = ReadPoint(reference, "pipe_direction");
            return AddOpeningNativeDimension(doc, view, center, edgePoint, pipeDirection, textTypeId, dimensionTypeId, createdIds);
        }

        private static bool AddOpeningHostBoxFallbackDimensions(
            Document doc,
            ViewPlan view,
            Dictionary<string, object> candidate,
            XYZ center,
            double markerWidth,
            double markerHeight,
            ElementId textTypeId,
            List<ElementId> createdIds)
        {
            if (!candidate.ContainsKey("host_bbox_min") || !candidate.ContainsKey("host_bbox_max") || candidate["host_bbox_min"] == null || candidate["host_bbox_max"] == null)
            {
                return false;
            }

            XYZ min = ReadPoint(candidate, "host_bbox_min");
            XYZ max = ReadPoint(candidate, "host_bbox_max");
            if (max.X <= min.X || max.Y <= min.Y)
            {
                return false;
            }

            double z = center.Z;
            double clearance = Math.Max(markerWidth, markerHeight) / 2.0 + UnitUtils.ConvertToInternalUnits(8, UnitTypeId.Centimeters);
            double left = Math.Abs(center.X - min.X);
            double right = Math.Abs(max.X - center.X);
            double bottom = Math.Abs(center.Y - min.Y);
            double top = Math.Abs(max.Y - center.Y);

            double edgeX = left <= right ? min.X : max.X;
            double edgeY = bottom <= top ? min.Y : max.Y;
            double horizontalY = center.Y - clearance;
            double verticalX = center.X + clearance;

            AddOpeningDimensionLine(
                doc,
                view,
                new XYZ(edgeX, horizontalY, z),
                new XYZ(center.X, horizontalY, z),
                textTypeId,
                false,
                createdIds);

            AddOpeningDimensionLine(
                doc,
                view,
                new XYZ(verticalX, edgeY, z),
                new XYZ(verticalX, center.Y, z),
                textTypeId,
                true,
                createdIds);
            return true;
        }

        private static void AddOpeningLocationDimensions(
            Document doc,
            ViewPlan view,
            Dictionary<string, object> candidate,
            XYZ center,
            double markerWidth,
            double markerHeight,
            ElementId textTypeId,
            ElementId dimensionTypeId,
            List<ElementId> createdIds)
        {
            Dictionary<string, object> parallelRef = candidate.ContainsKey("parallel_dim_ref")
                ? candidate["parallel_dim_ref"] as Dictionary<string, object>
                : null;
            bool dimensionReliable = ReadBool(candidate, "dimension_is_reliable", false);
            if (!dimensionReliable || parallelRef == null)
            {
                return;
            }
            AddOpeningParallelReferenceDimension(doc, view, parallelRef, center, textTypeId, dimensionTypeId, createdIds);
        }

        private static int DrawOpeningMarker(
            Document doc,
            ViewPlan view,
            Dictionary<string, object> candidate,
            XYZ center,
            ElementId textTypeId,
            ElementId dimensionTypeId,
            List<ElementId> createdIds)
        {
            Level level = view.GenLevel;
            double z = level != null ? level.Elevation : center.Z;
            XYZ c = new XYZ(center.X, center.Y, z);
            double[] size = ResolveOpeningMarkerSizeFeet(candidate);
            double width = size[0];
            double height = size[1];
            string shape = candidate.ContainsKey("shape") && candidate["shape"] != null
                ? candidate["shape"].ToString()
                : "";
            int before = createdIds.Count;

            if (IsBeamOpeningCandidate(candidate))
            {
                double intersectionLengthMm = ReadCandidateDouble(candidate, "intersection_length_mm", 0);
                double intersectionLength = intersectionLengthMm > 0
                    ? UnitUtils.ConvertToInternalUnits(intersectionLengthMm, UnitTypeId.Millimeters)
                    : 0;
                double extraLength = UnitUtils.ConvertToInternalUnits(20, UnitTypeId.Centimeters);
                double maxBeamMarkerLength = UnitUtils.ConvertToInternalUnits(120, UnitTypeId.Centimeters);
                double beamMarkerLength = intersectionLength > maxBeamMarkerLength
                    ? Math.Max(Math.Max(width, height) + extraLength, Math.Max(width, height) * 2.0)
                    : Math.Max(intersectionLength + extraLength, Math.Max(width, height) * 2.0);
                double beamMarkerHeight = Math.Max(Math.Min(width, height), UnitUtils.ConvertToInternalUnits(10, UnitTypeId.Centimeters));
                AddOpeningBeamFilledRegion(doc, view, candidate, center, beamMarkerLength, beamMarkerHeight, createdIds);
            }
            else if (shape.Contains("矩"))
            {
                double hw = width / 2.0;
                double hh = height / 2.0;
                XYZ p1 = c + new XYZ(-hw, -hh, 0);
                XYZ p2 = c + new XYZ(hw, -hh, 0);
                XYZ p3 = c + new XYZ(hw, hh, 0);
                XYZ p4 = c + new XYZ(-hw, hh, 0);
                AddOpeningDetailCurve(doc, view, Line.CreateBound(p1, p2), createdIds);
                AddOpeningDetailCurve(doc, view, Line.CreateBound(p2, p3), createdIds);
                AddOpeningDetailCurve(doc, view, Line.CreateBound(p3, p4), createdIds);
                AddOpeningDetailCurve(doc, view, Line.CreateBound(p4, p1), createdIds);
                AddOpeningDetailCurve(doc, view, Line.CreateBound(c + new XYZ(-hw, 0, 0), c + new XYZ(hw, 0, 0)), createdIds);
                AddOpeningDetailCurve(doc, view, Line.CreateBound(c + new XYZ(0, -hh, 0), c + new XYZ(0, hh, 0)), createdIds);
            }
            else
            {
                double radius = Math.Max(width, height) / 2.0;
                AddOpeningDetailCurve(doc, view, Arc.Create(c, radius, 0, Math.PI / 2.0, XYZ.BasisX, XYZ.BasisY), createdIds);
                AddOpeningDetailCurve(doc, view, Arc.Create(c, radius, Math.PI / 2.0, Math.PI, XYZ.BasisX, XYZ.BasisY), createdIds);
                AddOpeningDetailCurve(doc, view, Arc.Create(c, radius, Math.PI, Math.PI * 1.5, XYZ.BasisX, XYZ.BasisY), createdIds);
                AddOpeningDetailCurve(doc, view, Arc.Create(c, radius, Math.PI * 1.5, Math.PI * 2.0, XYZ.BasisX, XYZ.BasisY), createdIds);
                AddOpeningDetailCurve(doc, view, Line.CreateBound(c + new XYZ(-radius, 0, 0), c + new XYZ(radius, 0, 0)), createdIds);
                AddOpeningDetailCurve(doc, view, Line.CreateBound(c + new XYZ(0, -radius, 0), c + new XYZ(0, radius, 0)), createdIds);
            }

            AddOpeningLocationDimensions(doc, view, candidate, c, width, height, textTypeId, dimensionTypeId, createdIds);

            string text = BuildOpeningConstructionLabel(candidate);
            double offset = Math.Max(width, height) / 2.0 + UnitUtils.ConvertToInternalUnits(18, UnitTypeId.Centimeters);
            XYZ textPoint = c + new XYZ(offset, offset, 0);
            AddOpeningDetailCurve(doc, view, Line.CreateBound(c, textPoint), createdIds);
            TextNote note = TextNote.Create(doc, view.Id, textPoint, text, textTypeId);
            createdIds.Add(note.Id);
            ApplyOpeningMarkerOverride(view, note);
            return createdIds.Count - before;
        }

        private static Dictionary<string, object> PlaceOpeningMarkers(
            UIApplication uiApp,
            Dictionary<string, object> payload)
        {
            Document doc = GetActiveProjectDocument(uiApp);
            UIDocument uiDoc = uiApp.ActiveUIDocument;
            List<Dictionary<string, object>> candidates = ReadDictionaryList(payload, "candidates");
            if (candidates.Count == 0)
            {
                throw new InvalidOperationException("沒有可放置的開孔候選資料");
            }
            bool clearExisting = ReadBool(payload, "clear_existing", true);
            string viewNamePrefix = payload.ContainsKey("view_name_prefix") && payload["view_name_prefix"] != null
                ? payload["view_name_prefix"].ToString()
                : "SC 預留套管平面";

            ElementId dimensionTypeId = ResolveOpeningDimensionTypeId(doc, payload);
            var viewNames = new SortedSet<string>();
            var clearedViewIds = new HashSet<long>();
            var createdIds = new List<ElementId>();
            var createdIdsByView = new Dictionary<long, List<ElementId>>();
            var viewsById = new Dictionary<long, ViewPlan>();
            ViewPlan firstView = null;
            int placedCount = 0;
            int groupCount = 0;

            using (Transaction transaction = new Transaction(doc, "SC 建立預留套管平面標記"))
            {
                transaction.Start();
                ElementId textTypeId = GetOrCreateOpeningTextNoteTypeId(doc);
                foreach (Dictionary<string, object> candidate in candidates)
                {
                    if (candidate == null || !candidate.ContainsKey("center") || candidate["center"] == null)
                    {
                        continue;
                    }
                    XYZ center = ReadPoint(candidate, "center");
                    Level level = FindOpeningLevel(doc, candidate, center);
                    ViewPlan view = GetOrCreateOpeningPlanView(doc, level, viewNamePrefix);
                    if (firstView == null)
                    {
                        firstView = view;
                    }
                    if (clearExisting && clearedViewIds.Add(view.Id.Value))
                    {
                        ClearOpeningMarkersInView(doc, view);
                    }
                    if (!createdIdsByView.ContainsKey(view.Id.Value))
                    {
                        createdIdsByView[view.Id.Value] = new List<ElementId>();
                        viewsById[view.Id.Value] = view;
                    }
                    List<ElementId> viewCreatedIds = createdIdsByView[view.Id.Value];
                    int beforeCount = viewCreatedIds.Count;
                    DrawOpeningMarker(doc, view, candidate, center, textTypeId, dimensionTypeId, viewCreatedIds);
                    createdIds.AddRange(viewCreatedIds.Skip(beforeCount));
                    viewNames.Add(view.Name);
                    placedCount++;
                }

                foreach (KeyValuePair<long, List<ElementId>> item in createdIdsByView)
                {
                    if (item.Value.Count == 0)
                    {
                        continue;
                    }
                    try
                    {
                        ViewPlan view = viewsById[item.Key];
                        string levelName = view.GenLevel != null ? view.GenLevel.Name : view.Name;
                        Autodesk.Revit.DB.Group group = doc.Create.NewGroup(item.Value);
                        group.GroupType.Name = MakeUniqueGroupTypeName(doc, "SC 開孔標記 - " + SafeViewNamePart(levelName));
                        createdIds.Add(group.Id);
                        groupCount++;
                    }
                    catch
                    {
                    }
                }
                transaction.Commit();
            }

            if (firstView != null)
            {
                try
                {
                    uiDoc.RequestViewChange(firstView);
                }
                catch
                {
                    try { uiDoc.ActiveView = firstView; } catch { }
                }
                try
                {
                    uiDoc.Selection.SetElementIds(createdIds.Take(100).ToList());
                }
                catch
                {
                }
                try
                {
                    if (createdIds.Count > 0)
                    {
                        uiDoc.ShowElements(createdIds.Take(100).ToList());
                    }
                }
                catch
                {
                }
            }

            return new Dictionary<string, object>
            {
                { "placed_count", placedCount },
                { "created_element_count", createdIds.Count },
                { "group_count", groupCount },
                { "view_count", viewNames.Count },
                { "view_names", viewNames.ToList() }
            };
        }

        private static void ProcessRequest(UIApplication uiApp, string requestFile)
        {
            string requestId = Path.GetFileNameWithoutExtension(requestFile);
            string responseFile = Path.Combine(ResponseDir, requestId + ".json");
            string errorFile = Path.Combine(ErrorDir, requestId + ".json");

            try
            {
                var serializer = new JavaScriptSerializer();
                var payload = serializer.Deserialize<Dictionary<string, object>>(
                    File.ReadAllText(requestFile)
                );
                string action = payload.ContainsKey("action")
                    ? payload["action"].ToString()
                    : "read_metadata";

                if (TryDispatchRequest(uiApp, payload, action, responseFile, serializer))
                {
                    return;
                }

                if (!payload.ContainsKey("rfa_path"))
                {
                    throw new InvalidOperationException("缺少 rfa_path");
                }
                string inputPath = payload["rfa_path"].ToString();

                Application app = uiApp.Application;
                Document familyDoc = app.OpenDocumentFile(inputPath);
                Document activeDocument = uiApp.ActiveUIDocument != null
                    ? uiApp.ActiveUIDocument.Document
                    : null;
                try
                {
                    if (!familyDoc.IsFamilyDocument)
                    {
                        throw new InvalidOperationException("輸入檔案不是 Family Document");
                    }

                    FamilyManager manager = familyDoc.FamilyManager;
                    var types = new List<string>();
                    FamilyTypeSetIterator iterator = manager.Types.ForwardIterator();
                    iterator.Reset();
                    while (iterator.MoveNext())
                    {
                        FamilyType familyType = iterator.Current as FamilyType;
                        if (familyType != null && !string.IsNullOrWhiteSpace(familyType.Name))
                        {
                            types.Add(familyType.Name);
                        }
                    }

                    var parameters = new List<string>();
                    var parameterDetails = new List<object>();
                    foreach (FamilyParameter parameter in manager.Parameters)
                    {
                        if (parameter != null && parameter.Definition != null)
                        {
                            parameters.Add(parameter.Definition.Name);
                            parameterDetails.Add(new
                            {
                                name = parameter.Definition.Name,
                                is_instance = parameter.IsInstance,
                                storage_type = parameter.StorageType.ToString(),
                                parameter_group = parameter.Definition.GetGroupTypeId().TypeId,
                                current_value = manager.CurrentType != null && parameter.StorageType == StorageType.String
                                    ? manager.CurrentType.AsString(parameter)
                                    : null
                            });
                        }
                    }

                    var result = new
                    {
                        file_name = Path.GetFileName(inputPath),
                        family_name = !string.IsNullOrWhiteSpace(familyDoc.OwnerFamily.Name)
                            ? familyDoc.OwnerFamily.Name
                            : Path.GetFileNameWithoutExtension(inputPath),
                        revit_category = familyDoc.OwnerFamily.FamilyCategory != null
                            ? familyDoc.OwnerFamily.FamilyCategory.Name
                            : "",
                        family_types = types,
                        family_parameters = parameters,
                        family_parameter_details = parameterDetails
                    };

                    File.WriteAllText(responseFile, serializer.Serialize(result));
                }
                finally
                {
                    if (activeDocument == null || !Object.ReferenceEquals(familyDoc, activeDocument))
                    {
                        familyDoc.Close(false);
                    }
                }
            }
            catch (Exception ex)
            {
                var serializer = new JavaScriptSerializer();
                File.WriteAllText(errorFile, serializer.Serialize(new { error = ex.Message }));
            }
            finally
            {
                File.Delete(requestFile);
            }
        }
    }

    [Autodesk.Revit.Attributes.Transaction(Autodesk.Revit.Attributes.TransactionMode.Manual)]
    public class OpenFamilyArchiveCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            return FamilyClassifierLauncher.Open("--mode=archive", ref message);
        }
    }

    [Autodesk.Revit.Attributes.Transaction(Autodesk.Revit.Attributes.TransactionMode.Manual)]
    public class OpenProjectRecoveryCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            return FamilyClassifierLauncher.Open("--mode=recovery", ref message);
        }
    }

    [Autodesk.Revit.Attributes.Transaction(Autodesk.Revit.Attributes.TransactionMode.Manual)]
    public class OpenPointPlacementCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            return FamilyClassifierLauncher.Open("--mode=placement", ref message);
        }
    }

    [Autodesk.Revit.Attributes.Transaction(Autodesk.Revit.Attributes.TransactionMode.Manual)]
    public class OpenOpeningCheckCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            return FamilyClassifierLauncher.Open("--mode=opening-check", ref message);
        }
    }

    [Autodesk.Revit.Attributes.Transaction(Autodesk.Revit.Attributes.TransactionMode.Manual)]
    public class OpenFireBranchCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            return FamilyClassifierLauncher.Open("--mode=fire-branch", ref message);
        }
    }

    [Autodesk.Revit.Attributes.Transaction(Autodesk.Revit.Attributes.TransactionMode.Manual)]
    public class OpenDrainageCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            return FamilyClassifierLauncher.Open("--mode=drainage", ref message);
        }
    }

    [Autodesk.Revit.Attributes.Transaction(Autodesk.Revit.Attributes.TransactionMode.Manual)]
    public class OpenBackstageCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            return FamilyClassifierLauncher.Open("--mode=backstage", ref message);
        }
    }

    [Autodesk.Revit.Attributes.Transaction(Autodesk.Revit.Attributes.TransactionMode.Manual)]
    public class OpenElementInspectorCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            return FamilyClassifierLauncher.Open("--mode=element-inspector", ref message);
        }
    }

    [Autodesk.Revit.Attributes.Transaction(Autodesk.Revit.Attributes.TransactionMode.Manual)]
    public class OpenParameterAuditCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            return FamilyClassifierLauncher.Open("--mode=parameter-audit", ref message);
        }
    }

    [Autodesk.Revit.Attributes.Transaction(Autodesk.Revit.Attributes.TransactionMode.Manual)]
    public class OpenConnectFittingCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            return FamilyClassifierLauncher.Open("--mode=connect-fitting", ref message);
        }
    }

    [Autodesk.Revit.Attributes.Transaction(Autodesk.Revit.Attributes.TransactionMode.Manual)]
    public class OpenPipingSupportCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            return FamilyClassifierLauncher.Open("--mode=piping-support", ref message);
        }
    }

    public static class FamilyClassifierLauncher
    {
        public static Result Open(string modeArgument, ref string message)
        {
            try
            {
                string projectRoot = ResolveProjectRoot();
                string directExePath = Path.Combine(
                    projectRoot,
                    "RevitFamilyClassifier.exe");
                string exePath = File.Exists(directExePath)
                    ? directExePath
                    : Path.Combine(
                        projectRoot,
                        "dist",
                        "RevitFamilyClassifier",
                        "RevitFamilyClassifier.exe"
                    );
                string guiPath = Path.Combine(projectRoot, "gui_app.py");
                ProcessStartInfo startInfo;
                if (File.Exists(exePath))
                {
                    startInfo = new ProcessStartInfo
                    {
                        FileName = exePath,
                        Arguments = modeArgument,
                        WorkingDirectory = Path.GetDirectoryName(exePath),
                        UseShellExecute = true
                    };
                }
                else if (File.Exists(guiPath))
                {
                    startInfo = new ProcessStartInfo
                    {
                        FileName = "pythonw.exe",
                        Arguments = "\"" + guiPath + "\" " + modeArgument,
                        WorkingDirectory = projectRoot,
                        UseShellExecute = true
                    };
                }
                else
                {
                    message = "SC REVIT GUI was not found. Checked: " + exePath + " and " + guiPath;
                    return Result.Failed;
                }
                Process.Start(startInfo);
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = ex.Message;
                return Result.Failed;
            }
        }

        private static string ResolveProjectRoot()
        {
            string envRoot = Environment.GetEnvironmentVariable("SC_REVIT_HOME");
            if (IsProjectRoot(envRoot))
            {
                return envRoot;
            }

            string assemblyDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            string markerPath = Path.Combine(assemblyDir, "sc_revit_home.txt");
            if (File.Exists(markerPath))
            {
                string markerRoot = File.ReadAllText(markerPath).Trim();
                if (IsProjectRoot(markerRoot))
                {
                    return markerRoot;
                }
            }

            string packageRoot = Path.GetFullPath(Path.Combine(assemblyDir, "..", ".."));
            if (IsProjectRoot(packageRoot))
            {
                return packageRoot;
            }

            string devRoot = @"E:\Desktop\Codex\SC REVIT";
            if (IsProjectRoot(devRoot))
            {
                return devRoot;
            }

            return assemblyDir;
        }

        private static bool IsProjectRoot(string root)
        {
            if (string.IsNullOrWhiteSpace(root) || !Directory.Exists(root))
            {
                return false;
            }

            string exePath = Path.Combine(root, "dist", "RevitFamilyClassifier", "RevitFamilyClassifier.exe");
            string directExePath = Path.Combine(
                root,
                "RevitFamilyClassifier.exe");
            string guiPath = Path.Combine(root, "gui_app.py");
            return File.Exists(directExePath)
                || File.Exists(exePath)
                || File.Exists(guiPath);
        }
    }
}

