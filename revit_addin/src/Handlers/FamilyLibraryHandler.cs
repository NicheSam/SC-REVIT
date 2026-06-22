using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Web.Script.Serialization;

namespace RfaMetadataAddin
{
    public partial class RfaMetadataApplication
    {
        private static readonly HashSet<string> FamilyLibraryActions = new HashSet<string>(StringComparer.Ordinal)
        {
            "scan_project_families",
            "export_project_families",
            "add_missing_string_parameters",
            "set_string_parameter_values"
        };

        private static bool TryHandleFamilyLibraryAction(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            if (!FamilyLibraryActions.Contains(action))
            {
                return false;
            }

            if (action == "scan_project_families")
            {
                HandleScanProjectFamilies(uiApp, action, responseFile, serializer);
                return true;
            }

            if (action == "export_project_families")
            {
                HandleExportProjectFamilies(uiApp, payload, action, responseFile, serializer);
                return true;
            }

            if (action == "add_missing_string_parameters" || action == "set_string_parameter_values")
            {
                HandleFamilyParameterAction(uiApp, payload, action, responseFile, serializer);
                return true;
            }

            return false;
        }

        private static Document GetActiveNonFamilyProjectDocument(UIApplication uiApp)
        {
            Document projectDoc = uiApp.ActiveUIDocument != null
                ? uiApp.ActiveUIDocument.Document
                : null;
            if (projectDoc == null)
            {
                throw new InvalidOperationException("目前沒有開啟 Revit 專案");
            }
            if (projectDoc.IsFamilyDocument)
            {
                throw new InvalidOperationException("目前開啟的是族群文件，不是專案文件");
            }
            return projectDoc;
        }

        private static void HandleScanProjectFamilies(
            UIApplication uiApp,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            Document projectDoc = GetActiveNonFamilyProjectDocument(uiApp);

            var placedTypeIds = new Dictionary<long, int>();
            foreach (Element element in new FilteredElementCollector(projectDoc)
                .WhereElementIsNotElementType()
                .ToElements())
            {
                ElementId typeId = element.GetTypeId();
                if (typeId == null || typeId == ElementId.InvalidElementId)
                {
                    continue;
                }
                long key = typeId.Value;
                placedTypeIds[key] = placedTypeIds.ContainsKey(key)
                    ? placedTypeIds[key] + 1
                    : 1;
            }

            var items = new List<object>();
            foreach (Family family in new FilteredElementCollector(projectDoc)
                .OfClass(typeof(Family))
                .Cast<Family>()
                .OrderBy(item => item.Name))
            {
                var symbolIds = family.GetFamilySymbolIds();
                int instanceCount = symbolIds.Sum(symbolId =>
                {
                    long key = symbolId.Value;
                    return placedTypeIds.ContainsKey(key) ? placedTypeIds[key] : 0;
                });
                string categoryName = family.FamilyCategory != null
                    ? family.FamilyCategory.Name
                    : "";

                string status = "可回收";
                if (family.IsInPlace)
                {
                    status = "不可回收：就地族群";
                }
                else if (!family.IsEditable)
                {
                    status = "不可回收：不可編輯";
                }

                items.Add(new
                {
                    family_id = family.Id.Value,
                    family_name = family.Name,
                    revit_category = categoryName,
                    symbol_count = symbolIds.Count,
                    instance_count = instanceCount,
                    is_used = instanceCount > 0,
                    is_in_place = family.IsInPlace,
                    is_editable = family.IsEditable,
                    can_recover = family.IsEditable && !family.IsInPlace,
                    status = status
                });
            }

            File.WriteAllText(
                responseFile,
                serializer.Serialize(new
                {
                    action = action,
                    project_title = projectDoc.Title,
                    project_path = projectDoc.PathName,
                    families = items
                })
            );
        }

        private static void HandleExportProjectFamilies(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            Document projectDoc = GetActiveNonFamilyProjectDocument(uiApp);

            string outputDir = payload.ContainsKey("output_dir")
                ? payload["output_dir"].ToString()
                : "";
            if (string.IsNullOrWhiteSpace(outputDir))
            {
                throw new InvalidOperationException("尚未提供匯出資料夾");
            }
            Directory.CreateDirectory(outputDir);

            var requestedIds = new HashSet<long>();
            IEnumerable rawIds = payload.ContainsKey("family_ids")
                ? payload["family_ids"] as IEnumerable
                : new object[0];
            if (rawIds != null)
            {
                foreach (object rawId in rawIds)
                {
                    long parsed;
                    if (rawId != null && long.TryParse(rawId.ToString(), out parsed))
                    {
                        requestedIds.Add(parsed);
                    }
                }
            }
            if (!requestedIds.Any())
            {
                throw new InvalidOperationException("尚未選擇要回收的族群");
            }

            var exported = new List<object>();
            var skipped = new List<object>();
            foreach (Family family in new FilteredElementCollector(projectDoc)
                .OfClass(typeof(Family))
                .Cast<Family>()
                .Where(item => requestedIds.Contains(item.Id.Value))
                .OrderBy(item => item.Name))
            {
                if (family.IsInPlace || !family.IsEditable)
                {
                    skipped.Add(new
                    {
                        family_id = family.Id.Value,
                        family_name = family.Name,
                        reason = family.IsInPlace ? "就地族群不可回收" : "族群不可編輯"
                    });
                    continue;
                }

                Document familyDocForExport = null;
                try
                {
                    familyDocForExport = projectDoc.EditFamily(family);
                    string safeName = SanitizeFileName(family.Name);
                    string outputPath = BuildAvailableExportPath(outputDir, safeName + ".rfa");
                    SaveAsOptions saveAsOptions = new SaveAsOptions
                    {
                        OverwriteExistingFile = true,
                        MaximumBackups = 1
                    };
                    familyDocForExport.SaveAs(outputPath, saveAsOptions);
                    DeleteNumberedBackups(outputPath);
                    exported.Add(new
                    {
                        family_id = family.Id.Value,
                        family_name = family.Name,
                        file_path = outputPath,
                        file_name = Path.GetFileName(outputPath)
                    });
                }
                catch (Exception ex)
                {
                    skipped.Add(new
                    {
                        family_id = family.Id.Value,
                        family_name = family.Name,
                        reason = ex.Message
                    });
                }
                finally
                {
                    if (familyDocForExport != null)
                    {
                        familyDocForExport.Close(false);
                    }
                }
            }

            File.WriteAllText(
                responseFile,
                serializer.Serialize(new
                {
                    action = action,
                    output_dir = outputDir,
                    exported = exported,
                    skipped = skipped
                })
            );
        }

        private static void HandleFamilyParameterAction(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
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
                if (action == "add_missing_string_parameters")
                {
                    IEnumerable requested = payload.ContainsKey("parameters")
                        ? payload["parameters"] as IEnumerable
                        : new object[0];
                    if (requested == null)
                    {
                        requested = new object[0];
                    }
                    var existingNames = new HashSet<string>(
                        manager.Parameters
                            .Cast<FamilyParameter>()
                            .Where(p => p != null && p.Definition != null)
                            .Select(p => p.Definition.Name)
                    );
                    var added = new List<string>();
                    using (Transaction transaction = new Transaction(familyDoc, "Add SC Parameters"))
                    {
                        transaction.Start();
                        foreach (object item in requested)
                        {
                            var parameterPayload = item as Dictionary<string, object>;
                            if (parameterPayload == null || !parameterPayload.ContainsKey("name"))
                            {
                                continue;
                            }
                            string name = parameterPayload["name"].ToString();
                            if (string.IsNullOrWhiteSpace(name) || existingNames.Contains(name))
                            {
                                continue;
                            }
                            manager.AddParameter(
                                name,
                                GroupTypeId.IdentityData,
                                SpecTypeId.String.Text,
                                false
                            );
                            existingNames.Add(name);
                            added.Add(name);
                        }
                        transaction.Commit();
                    }
                    familyDoc.Save();
                    DeleteNumberedBackups(inputPath);
                    File.WriteAllText(
                        responseFile,
                        serializer.Serialize(new
                        {
                            action = action,
                            added_parameters = added
                        })
                    );
                    return;
                }

                if (action == "set_string_parameter_values")
                {
                    var values = payload.ContainsKey("values")
                        ? payload["values"] as Dictionary<string, object>
                        : new Dictionary<string, object>();
                    var updated = new List<string>();
                    using (Transaction transaction = new Transaction(familyDoc, "Set SC Parameter Values"))
                    {
                        transaction.Start();
                        FamilyTypeSetIterator familyTypeIterator = manager.Types.ForwardIterator();
                        familyTypeIterator.Reset();
                        while (familyTypeIterator.MoveNext())
                        {
                            FamilyType familyType = familyTypeIterator.Current as FamilyType;
                            if (familyType == null)
                            {
                                continue;
                            }
                            manager.CurrentType = familyType;
                            foreach (KeyValuePair<string, object> pair in values)
                            {
                                FamilyParameter parameter = manager.get_Parameter(pair.Key);
                                if (parameter == null || parameter.StorageType != StorageType.String)
                                {
                                    continue;
                                }
                                familyType.AsString(parameter);
                                manager.Set(parameter, pair.Value != null ? pair.Value.ToString() : "");
                                if (!updated.Contains(pair.Key))
                                {
                                    updated.Add(pair.Key);
                                }
                            }
                        }
                        transaction.Commit();
                    }
                    familyDoc.Save();
                    DeleteNumberedBackups(inputPath);
                    File.WriteAllText(
                        responseFile,
                        serializer.Serialize(new
                        {
                            action = action,
                            updated_parameters = updated
                        })
                    );
                    return;
                }
            }
            finally
            {
                if (activeDocument == null || !Object.ReferenceEquals(familyDoc, activeDocument))
                {
                    familyDoc.Close(false);
                }
            }
        }
    }
}
