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
            "create_fire_branch_preview",
            "create_fire_branch_pipes"
        };

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

            if (action == "create_fire_branch_preview")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                long mainPipeId = ReadLong(payload, "main_pipe_id");
                                long selectedLevelId = ReadLong(payload, "level_id", 0);
                                double branchOffsetCm = ReadDouble(payload, "branch_offset_cm", 0);
                                string heightReference = payload.ContainsKey("height_reference") && payload["height_reference"] != null
                                    ? payload["height_reference"].ToString()
                                    : "管中心";
                                ArrayList sprinklerIdsRaw = payload.ContainsKey("sprinkler_ids")
                                    ? payload["sprinkler_ids"] as ArrayList
                                    : null;

                                Pipe mainPipe = doc.GetElement(new ElementId(mainPipeId)) as Pipe;
                                if (mainPipe == null)
                                {
                                    throw new InvalidOperationException("找不到指定主管");
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
                                LocationCurve mainCurve = mainPipe.Location as LocationCurve;
                                if (mainCurve == null || sprinklers.Count == 0)
                                {
                                    throw new InvalidOperationException("沒有可用的主管或撒水頭資料");
                                }

                                XYZ mainStart = mainCurve.Curve.GetEndPoint(0);
                                XYZ mainEnd = mainCurve.Curve.GetEndPoint(1);
                                XYZ mainDirection = NormalizeXY(mainEnd - mainStart);
                                double mainZ = (mainStart.Z + mainEnd.Z) * 0.5;
                                ElementId levelId = selectedLevelId > 0 ? new ElementId(selectedLevelId) : GetPipeLevelId(doc, mainPipe);
                                Level branchLevel = doc.GetElement(levelId) as Level;
                                double previewDiameterFeet = UnitUtils.ConvertToInternalUnits(25, UnitTypeId.Millimeters);
                                double branchZ = ResolvePipeCenterZ(branchLevel, mainZ, branchOffsetCm, previewDiameterFeet, heightReference);
                                List<XYZ> sprinklerPoints = sprinklers.Select(item => GetFamilyConnectionPoint(item)).ToList();
                                XYZ branchDirection = new XYZ(-mainDirection.Y, mainDirection.X, 0);
                                double averageSide = sprinklerPoints.Average(point => DotXY(point - mainStart, branchDirection));
                                if (averageSide < 0)
                                {
                                    branchDirection = branchDirection.Negate();
                                }
                                double rowTolerance = UnitUtils.ConvertToInternalUnits(20, UnitTypeId.Centimeters);
                                double extension = 0;
                                List<FireBranchItem> sprinklerData = sprinklers
                                    .Select((sprinkler, index) => new FireBranchItem
                                    {
                                        Sprinkler = sprinkler,
                                        Point = sprinklerPoints[index],
                                        MainParameter = DotXY(sprinklerPoints[index] - mainStart, mainDirection),
                                        BranchParameter = DotXY(sprinklerPoints[index] - mainStart, branchDirection)
                                    })
                                    .OrderBy(item => item.MainParameter)
                                    .ToList();
                                var rows = new List<List<FireBranchItem>>();
                                foreach (FireBranchItem item in sprinklerData)
                                {
                                    if (rows.Count == 0 || Math.Abs(item.MainParameter - rows.Last().Average(row => row.MainParameter)) > rowTolerance)
                                    {
                                        rows.Add(new List<FireBranchItem>());
                                    }
                                    rows.Last().Add(item);
                                }

                                var createdElementIds = new List<ElementId>();
                                string batchId = DateTime.Now.ToString("yyyyMMdd-HHmmss");
                                long previewGroupId = 0;
                                string previewGroupName = "";
                                using (Transaction transaction = new Transaction(doc, "SC 消防支管螢光預覽"))
                                {
                                    transaction.Start();
                                    SketchPlane sketchPlane = SketchPlane.Create(
                                        doc,
                                        Plane.CreateByNormalAndOrigin(XYZ.BasisZ, new XYZ(0, 0, branchZ))
                                    );
                                    OverrideGraphicSettings overrides = new OverrideGraphicSettings();
                                    overrides.SetProjectionLineColor(new Autodesk.Revit.DB.Color(255, 120, 0));
                                    overrides.SetProjectionLineWeight(8);
                                    foreach (var row in rows)
                                    {
                                        double rowMain = row.Average(item => item.MainParameter);
                                        double rowMin = Math.Min(0, row.Min(item => item.BranchParameter)) - extension;
                                        double rowMax = Math.Max(0, row.Max(item => item.BranchParameter)) + extension;
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
                                        ModelCurve branchCurve = doc.Create.NewModelCurve(Line.CreateBound(branchStart, branchEnd), sketchPlane);
                                        createdElementIds.Add(branchCurve.Id);
                                        try { doc.ActiveView.SetElementOverrides(branchCurve.Id, overrides); } catch { }
                                        foreach (FireBranchItem item in row)
                                        {
                                            XYZ center = new XYZ(item.Point.X, item.Point.Y, branchZ);
                                            double size = UnitUtils.ConvertToInternalUnits(15, UnitTypeId.Centimeters);
                                            ModelCurve crossA = doc.Create.NewModelCurve(Line.CreateBound(center + new XYZ(-size, 0, 0), center + new XYZ(size, 0, 0)), sketchPlane);
                                            ModelCurve crossB = doc.Create.NewModelCurve(Line.CreateBound(center + new XYZ(0, -size, 0), center + new XYZ(0, size, 0)), sketchPlane);
                                            createdElementIds.Add(crossA.Id);
                                            createdElementIds.Add(crossB.Id);
                                            try
                                            {
                                                doc.ActiveView.SetElementOverrides(crossA.Id, overrides);
                                                doc.ActiveView.SetElementOverrides(crossB.Id, overrides);
                                            }
                                            catch { }
                                        }
                                    }
                                    if (createdElementIds.Count > 0)
                                    {
                                        Autodesk.Revit.DB.Group group = doc.Create.NewGroup(createdElementIds);
                                        previewGroupName = MakeUniqueGroupTypeName(doc, "SC_fire_branch_preview_" + batchId);
                                        group.GroupType.Name = previewGroupName;
                                        previewGroupId = group.Id.Value;
                                    }
                                    transaction.Commit();
                                }

                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        batch_id = batchId,
                                        segment_count = createdElementIds.Count,
                                        group_id = previewGroupId,
                                        group_name = previewGroupName
                                    })
                                );
                                return;
                            }

            if (action == "create_fire_branch_pipes")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                long mainPipeId = ReadLong(payload, "main_pipe_id");
                                long pipeTypeId = ReadLong(payload, "pipe_type_id");
                                long systemTypeId = ReadLong(payload, "system_type_id");
                                long selectedLevelId = ReadLong(payload, "level_id", 0);
                                double diameterMm = ReadDouble(payload, "diameter_mm", 25);
                                double branchOffsetCm = ReadDouble(payload, "branch_offset_cm", 0);
                                long previewGroupId = ReadLong(payload, "preview_group_id", 0);
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

                                Pipe mainPipe = doc.GetElement(new ElementId(mainPipeId)) as Pipe;
                                PipeType pipeType = doc.GetElement(new ElementId(pipeTypeId)) as PipeType;
                                PipingSystemType systemType = doc.GetElement(new ElementId(systemTypeId)) as PipingSystemType;
                                if (mainPipe == null)
                                {
                                    throw new InvalidOperationException("找不到指定主管");
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

                                LocationCurve mainCurve = mainPipe.Location as LocationCurve;
                                if (mainCurve == null)
                                {
                                    throw new InvalidOperationException("主管沒有有效管線");
                                }
                                XYZ mainStart = mainCurve.Curve.GetEndPoint(0);
                                XYZ mainEnd = mainCurve.Curve.GetEndPoint(1);
                                XYZ mainDirection = NormalizeXY(mainEnd - mainStart);
                                double mainZ = (mainStart.Z + mainEnd.Z) * 0.5;
                                double diameterFeet = UnitUtils.ConvertToInternalUnits(diameterMm, UnitTypeId.Millimeters);
                                ElementId levelId = selectedLevelId > 0 ? new ElementId(selectedLevelId) : GetPipeLevelId(doc, mainPipe);
                                if (levelId == ElementId.InvalidElementId)
                                {
                                    throw new InvalidOperationException("無法建立支管幾何方向");
                                }
                                Level branchLevel = doc.GetElement(levelId) as Level;
                                double branchZ = ResolvePipeCenterZ(branchLevel, mainZ, branchOffsetCm, diameterFeet, heightReference);

                                List<XYZ> sprinklerPoints = sprinklers.Select(item => GetFamilyConnectionPoint(item)).ToList();
                                double extension = 0;
                                double rowTolerance = UnitUtils.ConvertToInternalUnits(20, UnitTypeId.Centimeters);
                                XYZ branchDirection = new XYZ(-mainDirection.Y, mainDirection.X, 0);
                                double averageSide = sprinklerPoints.Average(point => DotXY(point - mainStart, branchDirection));
                                if (averageSide < 0)
                                {
                                    branchDirection = branchDirection.Negate();
                                }
                                List<FireBranchItem> sprinklerData = sprinklers
                                    .Select((sprinkler, index) => new FireBranchItem
                                    {
                                        Sprinkler = sprinkler,
                                        Point = sprinklerPoints[index],
                                        MainParameter = DotXY(sprinklerPoints[index] - mainStart, mainDirection),
                                        BranchParameter = DotXY(sprinklerPoints[index] - mainStart, branchDirection)
                                    })
                                    .OrderBy(item => item.MainParameter)
                                    .ToList();
                                var rows = new List<List<FireBranchItem>>();
                                foreach (FireBranchItem item in sprinklerData)
                                {
                                    if (rows.Count == 0 || Math.Abs(item.MainParameter - rows.Last().Average(row => row.MainParameter)) > rowTolerance)
                                    {
                                        rows.Add(new List<FireBranchItem>());
                                    }
                                    rows.Last().Add(item);
                                }

                                var createdIds = new List<ElementId>();
                                var created = new List<object>();
                                var failed = new List<object>();
                                string batchId = DateTime.Now.ToString("yyyyMMdd-HHmmss");
                                long deletedPreviewGroupId = 0;

                                using (Transaction transaction = new Transaction(doc, "SC \u6d88\u9632\u652f\u7ba1\u5efa\u7acb"))
                                {
                                    transaction.Start();
                                    var mainSegments = new List<Pipe> { mainPipe };
                                    foreach (var row in rows)
                                    {
                                        double rowMain = row.Average(item => item.MainParameter);
                                        double rowMin = Math.Min(0, row.Min(item => item.BranchParameter)) - extension;
                                        double rowMax = Math.Max(0, row.Max(item => item.BranchParameter)) + extension;
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

                                        Pipe feeder = null;
                                        if (mainTie.DistanceTo(branchTie) > 0.01)
                                        {
                                            feeder = CreateFirePipe(doc, systemType.Id, pipeType.Id, levelId, mainTie, branchTie, diameterFeet);
                                            if (feeder != null)
                                            {
                                                createdIds.Add(feeder.Id);
                                                created.Add(new { element_id = feeder.Id.Value, kind = "feeder" });
                                                TryCreateTeeAtPoint(doc, mainSegments, feeder, mainTie);
                                            }
                                        }

                                        Pipe branch = CreateFirePipe(doc, systemType.Id, pipeType.Id, levelId, branchStart, branchEnd, diameterFeet);
                                        var branchSegments = new List<Pipe>();
                                        if (branch != null)
                                        {
                                            createdIds.Add(branch.Id);
                                            created.Add(new { element_id = branch.Id.Value, kind = "branch" });
                                            branchSegments.Add(branch);
                                            if (feeder != null)
                                            {
                                                bool feederConnectedToBranch = TryConnectPipeToRun(doc, branchSegments, feeder, branchTie);
                                                if (!feederConnectedToBranch)
                                                {
                                                    failed.Add(new { row = rowMain, reason = "支管與主管垂直連接管未能建立有效配件連接" });
                                                }
                                            }
                                            if (feeder == null)
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
                                                    connectorCreated = TryCreateTeeAtPoint(doc, mainSegments, branch, mainTie);
                                                }
                                                if (!connectorCreated)
                                                {
                                                    failed.Add(new { row = rowMain, reason = "主管與支管未能建立有效 Tee/Cross 配件連接" });
                                                }
                                            }
                                        }

                                        foreach (var item in row)
                                        {
                                            try
                                            {
                                                XYZ sprinklerPoint = item.Point;
                                                XYZ tapPoint = new XYZ(sprinklerPoint.X, sprinklerPoint.Y, branchZ);
                                                Connector sprinklerConnector = FindConnectorNear(item.Sprinkler, sprinklerPoint);
                                                Pipe drop = CreateFirePipeFromConnector(doc, systemType.Id, pipeType.Id, levelId, sprinklerConnector, tapPoint, diameterFeet);
                                                if (drop == null)
                                                {
                                                    drop = CreateFirePipe(doc, systemType.Id, pipeType.Id, levelId, tapPoint, sprinklerPoint, diameterFeet);
                                                }
                                                if (drop != null)
                                                {
                                                    createdIds.Add(drop.Id);
                                                    created.Add(new { element_id = drop.Id.Value, kind = "drop", sprinkler_id = item.Sprinkler.Id.Value });
                                                    if (branchSegments.Count > 0)
                                                    {
                                                        bool dropConnectedToBranch = TryConnectPipeToRun(doc, branchSegments, drop, tapPoint);
                                                        if (!dropConnectedToBranch)
                                                        {
                                                            failed.Add(new { sprinkler_id = item.Sprinkler.Id.Value, reason = "垂直短管未能與水平支管建立有效 Tee/彎頭連接" });
                                                        }
                                                    }
                                                    bool connectedToSprinkler = sprinklerConnector != null && sprinklerConnector.IsConnected;
                                                    if (!connectedToSprinkler)
                                                    {
                                                        connectedToSprinkler = TryConnectElements(doc, drop, sprinklerPoint, item.Sprinkler, sprinklerPoint);
                                                    }
                                                    if (!connectedToSprinkler)
                                                    {
                                                        failed.Add(new { sprinkler_id = item.Sprinkler.Id.Value, reason = "垂直短管未能連接到撒水頭 connector" });
                                                    }
                                                }
                                            }
                                            catch (Exception ex)
                                            {
                                                failed.Add(new { sprinkler_id = item.Sprinkler.Id.Value, reason = ex.Message });
                                            }
                                        }
                                    }

                                    if (deletePreviewAfterCreate && previewGroupId > 0)
                                    {
                                        Element previewGroup = doc.GetElement(new ElementId(previewGroupId));
                                        if (previewGroup != null)
                                        {
                                            doc.Delete(previewGroup.Id);
                                            deletedPreviewGroupId = previewGroupId;
                                        }
                                    }

                                    transaction.Commit();
                                }

                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        batch_id = batchId,
                                        created = created,
                                        failed = failed,
                                        deleted_preview_group_id = deletedPreviewGroupId
                                    })
                                );
                                return;
                            }

            throw new InvalidOperationException("Unsupported fire branch action: " + action);
        }
    }
}
