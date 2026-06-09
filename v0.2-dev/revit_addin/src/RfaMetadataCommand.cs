using Autodesk.Revit.Attributes;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using System;
using System.Collections.Generic;
using System.IO;
using System.Web.Script.Serialization;

namespace RfaMetadataAddin
{
    [Transaction(TransactionMode.Manual)]
    public class RfaMetadataCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            try
            {
                string inputPath = Environment.GetEnvironmentVariable("RFA_METADATA_INPUT");
                string outputPath = Environment.GetEnvironmentVariable("RFA_METADATA_OUTPUT");

                if (string.IsNullOrWhiteSpace(inputPath) || string.IsNullOrWhiteSpace(outputPath))
                {
                    message = "缺少 RFA_METADATA_INPUT 或 RFA_METADATA_OUTPUT 環境變數";
                    return Result.Failed;
                }

                if (!File.Exists(inputPath))
                {
                    message = "指定的 RFA 檔案不存在";
                    return Result.Failed;
                }

                Application app = commandData.Application.Application;
                Document familyDoc = app.OpenDocumentFile(inputPath);
                Document activeDocument = commandData.Application.ActiveUIDocument != null
                    ? commandData.Application.ActiveUIDocument.Document
                    : null;

                try
                {
                    if (!familyDoc.IsFamilyDocument)
                    {
                        message = "指定檔案不是 Family Document";
                        return Result.Failed;
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

                    var payload = new
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

                    string json = new JavaScriptSerializer().Serialize(payload);
                    File.WriteAllText(outputPath, json);
                    return Result.Succeeded;
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
                message = ex.Message;
                return Result.Failed;
            }
        }
    }
}
