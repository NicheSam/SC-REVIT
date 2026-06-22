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
        private static bool TryHandleBackstageAction(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            if (action == "sync_tracked_elements")
            {
                Document syncDoc = GetActiveProjectDocument(uiApp);
                string syncBatchId = payload.ContainsKey("batch_id") && payload["batch_id"] != null
                    ? payload["batch_id"].ToString()
                    : "";
                var tracked = ReadTrackedElements(payload);
                var existing = new List<long>();
                var missing = new List<long>();
                var unknown = new List<long>();
                var documentMismatch = new List<long>();
                var relinked = new List<object>();
                var elementStates = new List<object>();

                foreach (TrackedElementRequest item in tracked)
                {
                    if (!MatchesTrackedDocument(syncDoc, item))
                    {
                        documentMismatch.Add(item.ElementId.Value);
                        elementStates.Add(new
                        {
                            element_id = item.ElementId.Value,
                            unique_id = item.UniqueId,
                            status = "document_mismatch",
                            group_status = ""
                        });
                        continue;
                    }

                    Element element = syncDoc.GetElement(item.ElementId);
                    bool idChanged = false;
                    if (element == null && !String.IsNullOrWhiteSpace(item.UniqueId))
                    {
                        element = syncDoc.GetElement(item.UniqueId);
                        idChanged = element != null && element.Id != item.ElementId;
                    }
                    if (element == null)
                    {
                        missing.Add(item.ElementId.Value);
                    }
                    else if (IsSafeBackstageDeleteTarget(element))
                    {
                        existing.Add(element.Id.Value);
                        string groupStatus = ResolveGroupStatus(syncDoc, element, item);
                        elementStates.Add(new
                        {
                            element_id = element.Id.Value,
                            old_element_id = item.ElementId.Value,
                            unique_id = element.UniqueId,
                            status = "exists",
                            group_status = groupStatus
                        });
                        if (idChanged)
                        {
                            relinked.Add(new
                            {
                                old_element_id = item.ElementId.Value,
                                element_id = element.Id.Value,
                                unique_id = element.UniqueId
                            });
                        }
                    }
                    else
                    {
                        unknown.Add(item.ElementId.Value);
                    }
                }

                File.WriteAllText(
                    responseFile,
                    serializer.Serialize(new
                    {
                        action = action,
                        batch_id = syncBatchId,
                        document_title = syncDoc.Title,
                        document_path = syncDoc.PathName,
                        requested_count = tracked.Count,
                        existing_count = existing.Count,
                        missing_count = missing.Count,
                        unknown_count = unknown.Count,
                        document_mismatch_count = documentMismatch.Count,
                        existing_element_ids = existing,
                        missing_element_ids = missing,
                        unknown_element_ids = unknown,
                        document_mismatch_element_ids = documentMismatch,
                        relinked_elements = relinked,
                        element_states = elementStates
                    })
                );
                return true;
            }

            if (action != "delete_tracked_elements")
            {
                return false;
            }

            Document doc = GetActiveProjectDocument(uiApp);
            string batchId = payload.ContainsKey("batch_id") && payload["batch_id"] != null
                ? payload["batch_id"].ToString()
                : "";
            var elementIds = ReadElementIds(payload);

            var deleted = new List<long>();
            var failed = new List<object>();
            var ungrouped = new List<long>();
            using (Transaction transaction = new Transaction(doc, "SC 刪除批次產物"))
            {
                transaction.Start();
                foreach (ElementId groupId in CollectSafeManagedGroupIds(doc, elementIds))
                {
                    Autodesk.Revit.DB.Group group = doc.GetElement(groupId) as Autodesk.Revit.DB.Group;
                    if (group == null)
                    {
                        continue;
                    }
                    try
                    {
                        group.UngroupMembers();
                        ungrouped.Add(groupId.Value);
                    }
                    catch (Exception ex)
                    {
                        failed.Add(new { element_id = groupId.Value, reason = "Unable to ungroup SC managed group: " + ex.Message });
                    }
                }

                foreach (ElementId id in elementIds.Distinct(new ElementIdComparer()))
                {
                    Element element = doc.GetElement(id);
                    if (element == null)
                    {
                        failed.Add(new { element_id = id.Value, reason = "Element not found" });
                        continue;
                    }
                    try
                    {
                        if (!IsSafeBackstageDeleteTarget(element))
                        {
                            failed.Add(new { element_id = id.Value, reason = "Skipped protected source or definition element" });
                            continue;
                        }
                        ICollection<ElementId> removed = doc.Delete(id);
                        if (removed != null && removed.Count > 0)
                        {
                            deleted.Add(id.Value);
                        }
                        else
                        {
                            failed.Add(new { element_id = id.Value, reason = "Revit returned no deleted elements" });
                        }
                    }
                    catch (Exception ex)
                    {
                        failed.Add(new { element_id = id.Value, reason = ex.Message });
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
                    requested_count = elementIds.Count,
                    ungrouped_group_ids = ungrouped,
                    deleted_count = deleted.Count,
                    deleted_element_ids = deleted,
                    failed = failed
                })
            );
            return true;
        }

        private static List<ElementId> ReadElementIds(Dictionary<string, object> payload)
        {
            var elementIds = new List<ElementId>();
            IEnumerable rawIds = payload.ContainsKey("element_ids") ? payload["element_ids"] as IEnumerable : null;
            if (rawIds == null)
            {
                return elementIds;
            }
            foreach (object raw in rawIds)
            {
                if (raw == null)
                {
                    continue;
                }
                long value;
                if (long.TryParse(raw.ToString(), out value) && value > 0)
                {
                    elementIds.Add(new ElementId(value));
                }
            }
            return elementIds;
        }

        private class TrackedElementRequest
        {
            public ElementId ElementId { get; set; }
            public string UniqueId { get; set; }
            public string DocumentTitle { get; set; }
            public string DocumentPath { get; set; }
            public long GroupId { get; set; }
            public string GroupName { get; set; }
        }

        private static List<TrackedElementRequest> ReadTrackedElements(Dictionary<string, object> payload)
        {
            var items = new List<TrackedElementRequest>();
            IEnumerable rawProducts = payload.ContainsKey("products") ? payload["products"] as IEnumerable : null;
            if (rawProducts != null)
            {
                foreach (object raw in rawProducts)
                {
                    Dictionary<string, object> product = raw as Dictionary<string, object>;
                    if (product == null)
                    {
                        continue;
                    }
                    long elementId = ReadLong(product, "element_id", 0);
                    if (elementId <= 0)
                    {
                        continue;
                    }
                    items.Add(new TrackedElementRequest
                    {
                        ElementId = new ElementId(elementId),
                        UniqueId = ReadString(product, "unique_id"),
                        DocumentTitle = ReadString(product, "document_title"),
                        DocumentPath = ReadString(product, "document_path"),
                        GroupId = ReadLong(product, "group_id", 0),
                        GroupName = ReadString(product, "group_name")
                    });
                }
            }
            if (items.Count > 0)
            {
                return items;
            }
            return ReadElementIds(payload)
                .Distinct(new ElementIdComparer())
                .Select(id => new TrackedElementRequest
                {
                    ElementId = id,
                    UniqueId = "",
                    DocumentTitle = "",
                    DocumentPath = "",
                    GroupId = 0,
                    GroupName = ""
                })
                .ToList();
        }

        private static string ReadString(Dictionary<string, object> payload, string key)
        {
            return payload.ContainsKey(key) && payload[key] != null ? payload[key].ToString() : "";
        }

        private static bool MatchesTrackedDocument(Document doc, TrackedElementRequest item)
        {
            if (!String.IsNullOrWhiteSpace(item.DocumentPath) && !String.IsNullOrWhiteSpace(doc.PathName))
            {
                return String.Equals(item.DocumentPath, doc.PathName, StringComparison.OrdinalIgnoreCase);
            }
            if (!String.IsNullOrWhiteSpace(item.DocumentTitle))
            {
                return String.Equals(item.DocumentTitle, doc.Title, StringComparison.OrdinalIgnoreCase);
            }
            return true;
        }

        private static string ResolveGroupStatus(Document doc, Element element, TrackedElementRequest item)
        {
            if (item.GroupId <= 0 && String.IsNullOrWhiteSpace(item.GroupName))
            {
                return "";
            }
            if (element == null || element.GroupId == ElementId.InvalidElementId)
            {
                return "detached";
            }
            Autodesk.Revit.DB.Group group = doc.GetElement(element.GroupId) as Autodesk.Revit.DB.Group;
            if (group == null || group.GroupType == null)
            {
                return "detached";
            }
            if (item.GroupId > 0 && group.Id.Value == item.GroupId)
            {
                return "intact";
            }
            if (!String.IsNullOrWhiteSpace(item.GroupName)
                && String.Equals(group.GroupType.Name, item.GroupName, StringComparison.OrdinalIgnoreCase))
            {
                return "intact";
            }
            return "regrouped";
        }

        private static bool IsSafeBackstageDeleteTarget(Element element)
        {
            if (element == null)
            {
                return false;
            }
            if (element is ElementType)
            {
                return false;
            }
            if (element is ImportInstance)
            {
                return false;
            }
            if (element is RevitLinkInstance)
            {
                return false;
            }
            if (element is Level)
            {
                return false;
            }
            if (element is View)
            {
                return false;
            }
            if (element is Autodesk.Revit.DB.Group)
            {
                return false;
            }
            string typeName = element.GetType().Name;
            if (typeName.IndexOf("Link", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return false;
            }
            if (typeName.IndexOf("Import", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return false;
            }
            return true;
        }

        private static List<ElementId> CollectSafeManagedGroupIds(Document doc, IEnumerable<ElementId> elementIds)
        {
            var groupIds = new List<ElementId>();
            foreach (ElementId id in elementIds.Distinct(new ElementIdComparer()))
            {
                Element element = doc.GetElement(id);
                if (element == null || element.GroupId == ElementId.InvalidElementId)
                {
                    continue;
                }
                Autodesk.Revit.DB.Group group = doc.GetElement(element.GroupId) as Autodesk.Revit.DB.Group;
                if (group == null || !IsScManagedGroup(group))
                {
                    continue;
                }
                groupIds.Add(group.Id);
            }
            return groupIds.Distinct(new ElementIdComparer()).ToList();
        }

        private static bool IsScManagedGroup(Autodesk.Revit.DB.Group group)
        {
            if (group == null || group.GroupType == null)
            {
                return false;
            }
            string name = group.GroupType.Name ?? "";
            return name.StartsWith("SC_", StringComparison.OrdinalIgnoreCase)
                || name.StartsWith("SC ", StringComparison.OrdinalIgnoreCase);
        }

        private class ElementIdComparer : IEqualityComparer<ElementId>
        {
            public bool Equals(ElementId x, ElementId y)
            {
                if (Object.ReferenceEquals(x, y)) return true;
                if (x == null || y == null) return false;
                return x.Value == y.Value;
            }

            public int GetHashCode(ElementId obj)
            {
                return obj == null ? 0 : obj.Value.GetHashCode();
            }
        }
    }
}
