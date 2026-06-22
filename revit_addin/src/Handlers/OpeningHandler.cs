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
        private static readonly HashSet<string> OpeningActions = new HashSet<string>(StringComparer.Ordinal)
        {
            "list_opening_context",
            "scan_opening_candidates",
            "view_opening_candidate",
            "place_opening_markers"
        };

        private static bool TryHandleOpeningAction(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            if (!OpeningActions.Contains(action))
            {
                return false;
            }

            HandleOpeningAction(uiApp, payload, action, responseFile, serializer);
            return true;
        }

        private static void HandleOpeningAction(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            if (action == "list_opening_context")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                var links = GetOpeningLinks(doc);
                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        links = links,
                                        pipe_count = CountByCategory(doc, BuiltInCategory.OST_PipeCurves),
                                        conduit_count = CountByCategory(doc, BuiltInCategory.OST_Conduit),
                                        duct_count = CountByCategory(doc, BuiltInCategory.OST_DuctCurves),
                                        cable_tray_count = CountByCategory(doc, BuiltInCategory.OST_CableTray),
                                        dimension_types = GetOpeningDimensionTypes(doc)
                                    })
                                );
                                return;
                            }

            if (action == "scan_opening_candidates")
                            {
                                Document doc = GetActiveProjectDocument(uiApp);
                                long linkId = ReadLong(payload, "link_id", 0);
                                RevitLinkInstance link = doc.GetElement(new ElementId(linkId)) as RevitLinkInstance;
                                if (link == null)
                                {
                                    throw new InvalidOperationException("找不到指定的土建 Link");
                                }
                                Document linkDoc = link.GetLinkDocument();
                                if (linkDoc == null)
                                {
                                    throw new InvalidOperationException("土建 Link 尚未載入，無法掃描");
                                }
                                List<string> mepTypes = ReadStringList(payload, "mep_types");
                                if (mepTypes.Count == 0)
                                {
                                    mepTypes.AddRange(new string[] { "pipe", "conduit", "duct", "cable_tray" });
                                }
                                List<string> hostTypes = ReadStringList(payload, "host_types");
                                if (hostTypes.Count == 0)
                                {
                                    hostTypes.AddRange(new string[] { "wall", "floor" });
                                }
                                double clearanceMm = ReadDouble(payload, "clearance_mm", 50);
                                var candidates = ScanOpeningCandidates(doc, link, linkDoc, mepTypes, hostTypes, clearanceMm);
                                int normalCount = candidates.Count(item => item.ContainsKey("status") && item["status"].ToString() == "正常");
                                int reviewCount = candidates.Count(item => item.ContainsKey("status") && item["status"].ToString() == "需確認");
                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        link_id = link.Id.Value,
                                        link_name = link.Name,
                                        clearance_mm = clearanceMm,
                                        normal_count = normalCount,
                                        review_count = reviewCount,
                                        candidates = candidates
                                    })
                                );
                                return;
                            }

            if (action == "view_opening_candidate")
                            {
                                var result = ViewOpeningCandidate(uiApp, payload);
                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        view_id = result["view_id"],
                                        view_name = result["view_name"],
                                        center = result["center"],
                                        center_text = result["center_text"]
                                    })
                                );
                                return;
                            }

            if (action == "place_opening_markers")
                            {
                                var result = PlaceOpeningMarkers(uiApp, payload);
                                File.WriteAllText(
                                    responseFile,
                                    serializer.Serialize(new
                                    {
                                        action = action,
                                        placed_count = result["placed_count"],
                                        created_element_count = result["created_element_count"],
                                        group_count = result["group_count"],
                                        view_count = result["view_count"],
                                        view_names = result["view_names"]
                                    })
                                );
                                return;
                            }

            throw new InvalidOperationException("Unsupported opening action: " + action);
        }
    }
}
