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
        private static readonly HashSet<string> CadPointActions = new HashSet<string>(StringComparer.Ordinal)
        {
            "list_point_placement_context",
            "get_cad_import_path",
            "list_cad_block_names",
            "scan_cad_block_points",
            "transform_dwg_block_points",
            "create_dwg_preview_markers",
            "place_cad_block_points",
            "place_dwg_block_points"
        };

        private static bool TryHandleCadPointAction(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            if (!CadPointActions.Contains(action))
            {
                return false;
            }

            HandleCadPointAction(uiApp, payload, action, responseFile, serializer);
            return true;
        }

        private static void HandleCadPointAction(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            if (action == "list_point_placement_context")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                bool includeCadPaths = ReadBool(payload, "include_paths", false);

                                var cadImports = new List<object>();
                                var importRows = new FilteredElementCollector(doc)
                                    .OfClass(typeof(ImportInstance))
                                    .Cast<ImportInstance>()
                                    .Select(importInstance => new
                                    {
                                        Instance = importInstance,
                                        Name = GetCadImportTypeName(doc, importInstance)
                                    })
                                    .OrderBy(item => item.Name)
                                    .ToList();

                                foreach (var row in importRows)
                                {
                                    ImportInstance importInstance = row.Instance;
                                    string cadName = row.Name;
                                    string cadPath = includeCadPaths ? GetCadImportPath(doc, importInstance) : "";
                                    string sourceKind = importInstance.IsLinked ? "連結" : "匯入";
                                    cadImports.Add(new
                                    {
                                        element_id = importInstance.Id.Value,
                                        name = cadName,
                                        path = cadPath,
                                        revit_name = importInstance.Name,
                                        is_linked = importInstance.IsLinked,
                                        display_name = cadName + " | ID " + importInstance.Id.Value + " | " + sourceKind,
                                        owner_view_id = importInstance.OwnerViewId != ElementId.InvalidElementId
                                            ? importInstance.OwnerViewId.Value
                                            : 0
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

                                var symbols = new List<object>();
                                foreach (FamilySymbol symbol in new FilteredElementCollector(doc)
                                    .OfClass(typeof(FamilySymbol))
                                    .Cast<FamilySymbol>()
                                    .Where(item => item.Category != null)
                                    .OrderBy(item => item.Category.Name)
                                    .ThenBy(item => item.FamilyName)
                                    .ThenBy(item => item.Name))
                                {
                                    symbols.Add(new
                                    {
                                        element_id = symbol.Id.Value,
                                        category = symbol.Category.Name,
                                        family_name = symbol.FamilyName,
                                        type_name = symbol.Name,
                                        display_name = symbol.Category.Name + " | " + symbol.FamilyName + " : " + symbol.Name
                                    });
                                }

                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        cad_imports = cadImports,
                                        levels = levels,
                                        family_symbols = symbols
                                    })
                                );
                                return;
                            }

            if (action == "get_cad_import_path")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                long importId = ReadLong(payload, "import_id");
                                ImportInstance importInstance = doc.GetElement(new ElementId(importId)) as ImportInstance;
                                if (importInstance == null)
                                {
                                    throw new InvalidOperationException("找不到指定 CAD 來源");
                                }
                                string cadName = GetCadImportTypeName(doc, importInstance);
                                string cadPath = GetCadImportPath(doc, importInstance);
                                string linkedStatus = "";
                                bool pathExists = false;
                                try
                                {
                                    ExternalFileReference reference = ExternalFileUtils.GetExternalFileReference(
                                        doc,
                                        importInstance.GetTypeId()
                                    );
                                    if (reference != null)
                                    {
                                        linkedStatus = reference.GetLinkedFileStatus().ToString();
                                    }
                                }
                                catch
                                {
                                    linkedStatus = "";
                                }
                                if (!string.IsNullOrWhiteSpace(cadPath))
                                {
                                    try
                                    {
                                        pathExists = File.Exists(cadPath);
                                    }
                                    catch
                                    {
                                        pathExists = false;
                                    }
                                }
                                bool usable = !importInstance.IsLinked || (linkedStatus != "NotFound" && pathExists);
                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        import_id = importId,
                                        name = cadName,
                                        path = cadPath,
                                        is_linked = importInstance.IsLinked,
                                        linked_status = linkedStatus,
                                        path_exists = pathExists,
                                        usable = usable
                                    })
                                );
                                return;
                            }

            if (action == "list_cad_block_names")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                long importId = ReadLong(payload, "import_id");
                                ImportInstance importInstance = doc.GetElement(new ElementId(importId)) as ImportInstance;
                                if (importInstance == null)
                                {
                                    throw new InvalidOperationException("找不到指定 CAD 來源");
                                }
                                List<Dictionary<string, object>> points = ScanCadBlockPoints(
                                    doc,
                                    importInstance,
                                    "",
                                    100000
                                );
                                var blocks = points
                                    .GroupBy(point => point.ContainsKey("block_name") ? point["block_name"].ToString() : "")
                                    .Where(group => !string.IsNullOrWhiteSpace(group.Key))
                                    .OrderBy(group => group.Key)
                                    .Select(group => new
                                    {
                                        block_name = group.Key,
                                        count = group.Count()
                                    })
                                    .ToList();
                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        import_id = importId,
                                        blocks = blocks
                                    })
                                );
                                return;
                            }

            if (action == "scan_cad_block_points")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                long importId = ReadLong(payload, "import_id");
                                string blockFilter = payload.ContainsKey("block_filter") && payload["block_filter"] != null
                                    ? payload["block_filter"].ToString()
                                    : "";
                                int limit = ReadInt(payload, "limit", 10);
                                ImportInstance importInstance = doc.GetElement(new ElementId(importId)) as ImportInstance;
                                if (importInstance == null)
                                {
                                    throw new InvalidOperationException("找不到指定 CAD 來源");
                                }
                                List<Dictionary<string, object>> points = ScanCadBlockPoints(
                                    doc,
                                    importInstance,
                                    blockFilter,
                                    limit
                                );
                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        import_id = importId,
                                        block_filter = blockFilter,
                                        points = points
                                    })
                                );
                                return;
                            }

            if (action == "transform_dwg_block_points")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                long importId = ReadLong(payload, "import_id");
                                int limit = ReadInt(payload, "limit", 10);
                                ImportInstance importInstance = doc.GetElement(new ElementId(importId)) as ImportInstance;
                                if (importInstance == null)
                                {
                                    throw new InvalidOperationException("找不到指定 CAD 來源");
                                }
                                List<Dictionary<string, object>> rawPoints = ReadPointPayload(payload);
                                List<Dictionary<string, object>> points = TransformDwgBlockPoints(
                                    importInstance,
                                    rawPoints,
                                    limit
                                );
                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        import_id = importId,
                                        points = points
                                    })
                                );
                                return;
                            }

            if (action == "create_dwg_preview_markers")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                long importId = ReadLong(payload, "import_id");
                                long levelId = ReadLong(payload, "level_id");
                                double offsetMm = ReadDouble(payload, "offset_mm", 0);
                                double markerSizeMm = ReadDouble(payload, "marker_size_mm", 180);
                                ImportInstance importInstance = doc.GetElement(new ElementId(importId)) as ImportInstance;
                                Level level = doc.GetElement(new ElementId(levelId)) as Level;
                                if (importInstance == null)
                                {
                                    throw new InvalidOperationException("找不到指定 CAD 來源");
                                }
                                if (level == null)
                                {
                                    throw new InvalidOperationException("找不到指定樓層");
                                }
                                List<Dictionary<string, object>> rawPoints = ReadPointPayload(payload);
                                List<Dictionary<string, object>> points = TransformDwgBlockPoints(
                                    importInstance,
                                    rawPoints,
                                    rawPoints.Count
                                );
                                double offsetFeet = UnitUtils.ConvertToInternalUnits(offsetMm, UnitTypeId.Millimeters);
                                double sizeFeet = UnitUtils.ConvertToInternalUnits(markerSizeMm, UnitTypeId.Millimeters);
                                double z = level.Elevation + offsetFeet;
                                string batchId = DateTime.Now.ToString("yyyyMMdd-HHmmss");
                                long groupId = 0;
                                string groupName = "";
                                XYZ groupOrigin = XYZ.Zero;
                                var createdElementIds = new List<ElementId>();

                                using (Transaction transaction = new Transaction(doc, "SC 批量點位螢光預覽"))
                                {
                                    transaction.Start();
                                    SketchPlane sketchPlane = SketchPlane.Create(
                                        doc,
                                        Plane.CreateByNormalAndOrigin(XYZ.BasisZ, new XYZ(0, 0, z))
                                    );
                                    OverrideGraphicSettings overrides = new OverrideGraphicSettings();
                                    overrides.SetProjectionLineColor(new Autodesk.Revit.DB.Color(0, 255, 80));
                                    overrides.SetProjectionLineWeight(8);
                                    foreach (Dictionary<string, object> point in points)
                                    {
                                        double x = Convert.ToDouble(point["x"]);
                                        double y = Convert.ToDouble(point["y"]);
                                        XYZ center = new XYZ(x, y, z);
                                        Line lineA = Line.CreateBound(
                                            center + new XYZ(-sizeFeet, 0, 0),
                                            center + new XYZ(sizeFeet, 0, 0)
                                        );
                                        Line lineB = Line.CreateBound(
                                            center + new XYZ(0, -sizeFeet, 0),
                                            center + new XYZ(0, sizeFeet, 0)
                                        );
                                        ModelCurve curveA = doc.Create.NewModelCurve(lineA, sketchPlane);
                                        ModelCurve curveB = doc.Create.NewModelCurve(lineB, sketchPlane);
                                        createdElementIds.Add(curveA.Id);
                                        createdElementIds.Add(curveB.Id);
                                        try
                                        {
                                            doc.ActiveView.SetElementOverrides(curveA.Id, overrides);
                                            doc.ActiveView.SetElementOverrides(curveB.Id, overrides);
                                        }
                                        catch
                                        {
                                            // Some views do not allow overrides; the model curves are still visible.
                                        }
                                    }
                                    if (createdElementIds.Count == 0)
                                    {
                                        throw new InvalidOperationException("沒有建立任何螢光預覽點");
                                    }
                                    Autodesk.Revit.DB.Group group = doc.Create.NewGroup(createdElementIds);
                                    groupId = group.Id.Value;
                                    groupName = MakeUniqueGroupTypeName(doc, "SC_preview_points_" + batchId);
                                    try
                                    {
                                        group.GroupType.Name = groupName;
                                    }
                                    catch
                                    {
                                        groupName = group.GroupType != null ? group.GroupType.Name : groupName;
                                    }
                                    LocationPoint groupLocation = group.Location as LocationPoint;
                                    groupOrigin = groupLocation != null ? groupLocation.Point : XYZ.Zero;
                                    transaction.Commit();
                                }

                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        batch_id = batchId,
                                        group_id = groupId,
                                        group_name = groupName,
                                        group_origin = SerializePoint(groupOrigin),
                                        marker_count = points.Count,
                                        points = points.Take(10).ToList()
                                    })
                                );
                                return;
                            }

            if (action == "place_cad_block_points")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                long importId = ReadLong(payload, "import_id");
                                long symbolId = ReadLong(payload, "symbol_id");
                                long levelId = ReadLong(payload, "level_id");
                                string blockFilter = payload.ContainsKey("block_filter") && payload["block_filter"] != null
                                    ? payload["block_filter"].ToString()
                                    : "";
                                int limit = ReadInt(payload, "limit", 10);
                                double offsetMm = ReadDouble(payload, "offset_mm", 0);
                                double toleranceMm = ReadDouble(payload, "duplicate_tolerance_mm", 10);

                                ImportInstance importInstance = doc.GetElement(new ElementId(importId)) as ImportInstance;
                                FamilySymbol symbol = doc.GetElement(new ElementId(symbolId)) as FamilySymbol;
                                Level level = doc.GetElement(new ElementId(levelId)) as Level;
                                if (importInstance == null)
                                {
                                    throw new InvalidOperationException("找不到指定 CAD 來源");
                                }
                                if (symbol == null)
                                {
                                    throw new InvalidOperationException("找不到指定 Revit 族群類型");
                                }
                                if (level == null)
                                {
                                    throw new InvalidOperationException("找不到指定樓層");
                                }

                                List<Dictionary<string, object>> points = ScanCadBlockPoints(
                                    doc,
                                    importInstance,
                                    blockFilter,
                                    limit
                                );
                                double offsetFeet = UnitUtils.ConvertToInternalUnits(offsetMm, UnitTypeId.Millimeters);
                                double toleranceFeet = UnitUtils.ConvertToInternalUnits(toleranceMm, UnitTypeId.Millimeters);
                                string batchId = DateTime.Now.ToString("yyyyMMdd-HHmmss");
                                var created = new List<object>();
                                var duplicates = new List<object>();
                                var failed = new List<object>();

                                using (Transaction transaction = new Transaction(doc, "SC \u6279\u91cf\u9ede\u4f4d\u653e\u7f6e"))
                                {
                                    transaction.Start();
                                    if (!symbol.IsActive)
                                    {
                                        symbol.Activate();
                                        doc.Regenerate();
                                    }
                                    foreach (Dictionary<string, object> point in points)
                                    {
                                        try
                                        {
                                            double x = Convert.ToDouble(point["x"]);
                                            double y = Convert.ToDouble(point["y"]);
                                            double z = level.Elevation + offsetFeet;
                                            XYZ location = new XYZ(x, y, z);
                                            if (IsDuplicatePoint(doc, symbol, level, location, toleranceFeet))
                                            {
                                                duplicates.Add(point);
                                                continue;
                                            }
                                            FamilyInstance instance = doc.Create.NewFamilyInstance(
                                                location,
                                                symbol,
                                                level,
                                                StructuralType.NonStructural
                                            );
                                            ApplyVerticalPlacement(doc, instance, symbol, level, offsetFeet, z);
                                            double rotationDegrees = Convert.ToDouble(point["rotation_degrees"]);
                                            if (Math.Abs(rotationDegrees) > 0.0001)
                                            {
                                                Line axis = Line.CreateBound(location, location + XYZ.BasisZ);
                                                ElementTransformUtils.RotateElement(
                                                    doc,
                                                    instance.Id,
                                                    axis,
                                                    rotationDegrees * Math.PI / 180.0
                                                );
                                            }
                                            created.Add(new
                                            {
                                                element_id = instance.Id.Value,
                                                block_name = point["block_name"],
                                                x = x,
                                                y = y,
                                                z = z,
                                                batch_id = batchId
                                            });
                                        }
                                        catch (Exception ex)
                                        {
                                            failed.Add(new
                                            {
                                                block_name = point.ContainsKey("block_name") ? point["block_name"] : "",
                                                reason = ex.Message
                                            });
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
                                        duplicates = duplicates,
                                        failed = failed
                                    })
                                );
                                return;
                            }

            if (action == "place_dwg_block_points")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                long importId = ReadLong(payload, "import_id");
                                long symbolId = ReadLong(payload, "symbol_id");
                                long levelId = ReadLong(payload, "level_id");
                                double offsetMm = ReadDouble(payload, "offset_mm", 0);
                                double toleranceMm = ReadDouble(payload, "duplicate_tolerance_mm", 10);

                                ImportInstance importInstance = doc.GetElement(new ElementId(importId)) as ImportInstance;
                                FamilySymbol symbol = doc.GetElement(new ElementId(symbolId)) as FamilySymbol;
                                Level level = doc.GetElement(new ElementId(levelId)) as Level;
                                if (importInstance == null)
                                {
                                    throw new InvalidOperationException("找不到指定 CAD 來源");
                                }
                                if (symbol == null)
                                {
                                    throw new InvalidOperationException("找不到指定 Revit 族群類型");
                                }
                                if (level == null)
                                {
                                    throw new InvalidOperationException("找不到指定樓層");
                                }

                                List<Dictionary<string, object>> rawPoints = ReadPointPayload(payload);
                                List<Dictionary<string, object>> points = TransformDwgBlockPoints(
                                    importInstance,
                                    rawPoints,
                                    rawPoints.Count
                                );
                                long previewGroupId = ReadLong(payload, "preview_group_id", 0);
                                XYZ correction = XYZ.Zero;
                                Autodesk.Revit.DB.Group previewGroup = null;
                                if (previewGroupId > 0)
                                {
                                    previewGroup = doc.GetElement(new ElementId(previewGroupId)) as Autodesk.Revit.DB.Group;
                                    if (previewGroup != null)
                                    {
                                        LocationPoint previewLocation = previewGroup.Location as LocationPoint;
                                        if (previewLocation != null)
                                        {
                                            XYZ previewOrigin = ReadPoint(payload, "preview_origin");
                                            XYZ rawCorrection = previewLocation.Point - previewOrigin;
                                            correction = new XYZ(rawCorrection.X, rawCorrection.Y, 0);
                                        }
                                    }
                                }
                                double offsetFeet = UnitUtils.ConvertToInternalUnits(offsetMm, UnitTypeId.Millimeters);
                                double toleranceFeet = UnitUtils.ConvertToInternalUnits(toleranceMm, UnitTypeId.Millimeters);
                                string batchId = DateTime.Now.ToString("yyyyMMdd-HHmmss");
                                var created = new List<object>();
                                var duplicates = new List<object>();
                                var failed = new List<object>();
                                var createdElementIds = new List<ElementId>();
                                long groupId = 0;
                                string groupName = "";

                                using (Transaction transaction = new Transaction(doc, "SC DWG \u6279\u91cf\u9ede\u4f4d\u653e\u7f6e"))
                                {
                                    transaction.Start();
                                    if (!symbol.IsActive)
                                    {
                                        symbol.Activate();
                                        doc.Regenerate();
                                    }
                                    foreach (Dictionary<string, object> point in points)
                                    {
                                        try
                                        {
                                            double x = Convert.ToDouble(point["x"]);
                                            double y = Convert.ToDouble(point["y"]);
                                            double z = level.Elevation + offsetFeet;
                                            XYZ location = new XYZ(x, y, z) + correction;
                                            if (IsDuplicatePoint(doc, symbol, level, location, toleranceFeet))
                                            {
                                                duplicates.Add(point);
                                                continue;
                                            }
                                            FamilyInstance instance = doc.Create.NewFamilyInstance(
                                                location,
                                                symbol,
                                                level,
                                                StructuralType.NonStructural
                                            );
                                            ApplyVerticalPlacement(doc, instance, symbol, level, offsetFeet, z);
                                            double rotationDegrees = Convert.ToDouble(point["rotation_degrees"]);
                                            if (Math.Abs(rotationDegrees) > 0.0001)
                                            {
                                                Line axis = Line.CreateBound(location, location + XYZ.BasisZ);
                                                ElementTransformUtils.RotateElement(
                                                    doc,
                                                    instance.Id,
                                                    axis,
                                                    rotationDegrees * Math.PI / 180.0
                                                );
                                            }
                                            created.Add(new
                                            {
                                                element_id = instance.Id.Value,
                                                block_name = point["block_name"],
                                                x = x,
                                                y = y,
                                                z = z,
                                                batch_id = batchId
                                            });
                                            createdElementIds.Add(instance.Id);
                                        }
                                        catch (Exception ex)
                                        {
                                            failed.Add(new
                                            {
                                                block_name = point.ContainsKey("block_name") ? point["block_name"] : "",
                                                reason = ex.Message
                                            });
                                        }
                                    }
                                    if (createdElementIds.Count > 0)
                                    {
                                        Autodesk.Revit.DB.Group group = doc.Create.NewGroup(createdElementIds);
                                        groupId = group.Id.Value;
                                        groupName = MakeUniqueGroupTypeName(
                                            doc,
                                            "SC_\u6279\u91cf\u9ede\u4f4d_" + batchId + "_" + SanitizeGroupName(symbol.FamilyName)
                                        );
                                        try
                                        {
                                            group.GroupType.Name = groupName;
                                        }
                                        catch
                                        {
                                            groupName = group.GroupType != null ? group.GroupType.Name : groupName;
                                        }
                                    }
                                    if (previewGroup != null)
                                    {
                                        bool deletePreview = !payload.ContainsKey("delete_preview_after_place")
                                            || payload["delete_preview_after_place"] == null
                                            || payload["delete_preview_after_place"].ToString().ToLowerInvariant() != "false";
                                        if (deletePreview)
                                        {
                                            doc.Delete(previewGroup.Id);
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
                                        group_id = groupId,
                                        group_name = groupName,
                                        correction = SerializePoint(correction),
                                        created = created,
                                        duplicates = duplicates,
                                        failed = failed
                                    })
                                );
                                return;
                            }

            throw new InvalidOperationException("Unsupported cad point action: " + action);
        }
    }
}
