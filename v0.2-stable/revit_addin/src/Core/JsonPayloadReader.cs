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
        private static long ReadLong(Dictionary<string, object> payload, string key, long defaultValue = 0)
        {
            if (!payload.ContainsKey(key) || payload[key] == null)
            {
                return defaultValue;
            }
            long parsed;
            return long.TryParse(payload[key].ToString(), out parsed) ? parsed : defaultValue;
        }

        private static int ReadInt(Dictionary<string, object> payload, string key, int defaultValue = 0)
        {
            if (!payload.ContainsKey(key) || payload[key] == null)
            {
                return defaultValue;
            }
            int parsed;
            return int.TryParse(payload[key].ToString(), out parsed) ? parsed : defaultValue;
        }

        private static double ReadDouble(Dictionary<string, object> payload, string key, double defaultValue = 0)
        {
            if (!payload.ContainsKey(key) || payload[key] == null)
            {
                return defaultValue;
            }
            double parsed;
            return double.TryParse(payload[key].ToString(), out parsed) ? parsed : defaultValue;
        }

        private static bool ReadBool(Dictionary<string, object> payload, string key, bool defaultValue = false)
        {
            if (!payload.ContainsKey(key) || payload[key] == null)
            {
                return defaultValue;
            }
            bool parsed;
            if (bool.TryParse(payload[key].ToString(), out parsed))
            {
                return parsed;
            }
            int intValue;
            if (int.TryParse(payload[key].ToString(), out intValue))
            {
                return intValue != 0;
            }
            return defaultValue;
        }

        private static List<string> ReadStringList(Dictionary<string, object> payload, string key)
        {
            var values = new List<string>();
            if (!payload.ContainsKey(key) || payload[key] == null)
            {
                return values;
            }
            ArrayList raw = payload[key] as ArrayList;
            if (raw != null)
            {
                foreach (object item in raw)
                {
                    if (item != null && !string.IsNullOrWhiteSpace(item.ToString()))
                    {
                        values.Add(item.ToString());
                    }
                }
                return values;
            }
            string single = payload[key].ToString();
            if (!string.IsNullOrWhiteSpace(single))
            {
                values.Add(single);
            }
            return values;
        }

        private static List<Dictionary<string, object>> ReadDictionaryList(Dictionary<string, object> payload, string key)
        {
            var values = new List<Dictionary<string, object>>();
            if (!payload.ContainsKey(key) || payload[key] == null)
            {
                return values;
            }
            ArrayList raw = payload[key] as ArrayList;
            if (raw != null)
            {
                foreach (object item in raw)
                {
                    Dictionary<string, object> dict = item as Dictionary<string, object>;
                    if (dict != null)
                    {
                        values.Add(dict);
                    }
                }
                return values;
            }
            Dictionary<string, object> single = payload[key] as Dictionary<string, object>;
            if (single != null)
            {
                values.Add(single);
            }
            return values;
        }
    }
}
