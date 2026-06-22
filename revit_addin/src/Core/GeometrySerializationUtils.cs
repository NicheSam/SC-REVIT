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
        private static XYZ ReadPoint(Dictionary<string, object> payload, string key)
        {
            Dictionary<string, object> point = payload.ContainsKey(key)
                ? payload[key] as Dictionary<string, object>
                : null;
            if (point == null)
            {
                return XYZ.Zero;
            }
            double x = point.ContainsKey("x") ? Convert.ToDouble(point["x"]) : 0;
            double y = point.ContainsKey("y") ? Convert.ToDouble(point["y"]) : 0;
            double z = point.ContainsKey("z") ? Convert.ToDouble(point["z"]) : 0;
            return new XYZ(x, y, z);
        }

        private static Dictionary<string, object> SerializePoint(XYZ point)
        {
            return new Dictionary<string, object>
            {
                { "x", point.X },
                { "y", point.Y },
                { "z", point.Z }
            };
        }

        private static Dictionary<string, object> SerializeTransformedBoundingBox(BoundingBoxXYZ box, Autodesk.Revit.DB.Transform transform)
        {
            if (box == null)
            {
                return null;
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

            double minX = double.MaxValue;
            double minY = double.MaxValue;
            double minZ = double.MaxValue;
            double maxX = double.MinValue;
            double maxY = double.MinValue;
            double maxZ = double.MinValue;
            foreach (XYZ corner in corners)
            {
                XYZ point = transform.OfPoint(corner);
                minX = Math.Min(minX, point.X);
                minY = Math.Min(minY, point.Y);
                minZ = Math.Min(minZ, point.Z);
                maxX = Math.Max(maxX, point.X);
                maxY = Math.Max(maxY, point.Y);
                maxZ = Math.Max(maxZ, point.Z);
            }

            return new Dictionary<string, object>
            {
                { "min", SerializePoint(new XYZ(minX, minY, minZ)) },
                { "max", SerializePoint(new XYZ(maxX, maxY, maxZ)) }
            };
        }
    }
}
