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
        private static Document GetActiveProjectDocument(UIApplication uiApp)
        {
            Document doc = uiApp.ActiveUIDocument != null
                ? uiApp.ActiveUIDocument.Document
                : null;
            if (doc == null)
            {
                throw new InvalidOperationException("目前沒有開啟 Revit 專案");
            }
            if (doc.IsFamilyDocument)
            {
                throw new InvalidOperationException("目前開啟的是族群文件，不是專案文件");
            }
            return doc;
        }

        private static int CountByCategory(Document doc, BuiltInCategory category)
        {
            return new FilteredElementCollector(doc)
                .OfCategory(category)
                .WhereElementIsNotElementType()
                .GetElementCount();
        }

        private static string GetLinkPath(Document doc, RevitLinkInstance linkInstance)
        {
            try
            {
                ExternalFileReference reference = ExternalFileUtils.GetExternalFileReference(
                    doc,
                    linkInstance.GetTypeId()
                );
                if (reference != null)
                {
                    ModelPath modelPath = reference.GetAbsolutePath();
                    if (modelPath != null)
                    {
                        return ModelPathUtils.ConvertModelPathToUserVisiblePath(modelPath);
                    }
                }
            }
            catch
            {
            }
            return "";
        }

        private static List<object> GetOpeningLinks(Document doc)
        {
            var links = new List<object>();
            foreach (RevitLinkInstance link in new FilteredElementCollector(doc)
                .OfClass(typeof(RevitLinkInstance))
                .Cast<RevitLinkInstance>()
                .OrderBy(item => item.Name))
            {
                Document linkDoc = null;
                try
                {
                    linkDoc = link.GetLinkDocument();
                }
                catch
                {
                    linkDoc = null;
                }
                string title = linkDoc != null ? linkDoc.Title : "未載入";
                string path = GetLinkPath(doc, link);
                links.Add(new
                {
                    element_id = link.Id.Value,
                    name = link.Name,
                    title = title,
                    path = path,
                    is_loaded = linkDoc != null,
                    display_name = link.Name + " | ID " + link.Id.Value + " | " + title
                });
            }
            return links;
        }

        private static List<Dictionary<string, object>> GetOpeningDimensionTypes(Document doc)
        {
            return new FilteredElementCollector(doc)
                .OfClass(typeof(DimensionType))
                .Cast<DimensionType>()
                .OrderBy(item => item.Name)
                .Select(item => new Dictionary<string, object>
                {
                    { "element_id", item.Id.Value },
                    { "name", item.Name },
                    { "display_name", item.Name + " | ID " + item.Id.Value }
                })
                .ToList();
        }

        private static List<object> GetAvailablePipeDiameters(Document doc)
        {
            var values = new SortedSet<double>();
            foreach (Pipe pipe in new FilteredElementCollector(doc).OfClass(typeof(Pipe)).Cast<Pipe>())
            {
                Parameter diameter = pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
                if (diameter != null && diameter.AsDouble() > 0)
                {
                    values.Add(Math.Round(UnitUtils.ConvertFromInternalUnits(diameter.AsDouble(), UnitTypeId.Millimeters), 3));
                }
            }

            return values
                .Select(value => new { value_mm = value, label = value.ToString("0.##") + " mm" })
                .Cast<object>()
                .ToList();
        }
    }
}
