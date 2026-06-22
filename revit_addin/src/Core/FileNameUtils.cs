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
        private static string SanitizeFileName(string value)
        {
            string cleaned = string.IsNullOrWhiteSpace(value) ? "未命名族群" : value.Trim();
            foreach (char invalid in Path.GetInvalidFileNameChars())
            {
                cleaned = cleaned.Replace(invalid, '_');
            }
            return cleaned;
        }

        private static string BuildAvailableExportPath(string directory, string fileName)
        {
            string stem = Path.GetFileNameWithoutExtension(fileName);
            string extension = Path.GetExtension(fileName);
            string candidate = Path.Combine(directory, fileName);
            int index = 2;
            while (File.Exists(candidate))
            {
                candidate = Path.Combine(directory, stem + "-回收" + index + extension);
                index++;
            }
            return candidate;
        }
    }
}
