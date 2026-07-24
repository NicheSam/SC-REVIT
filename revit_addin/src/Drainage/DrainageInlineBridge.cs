using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using System;
using System.Collections.Generic;
using System.IO;
using System.Web.Script.Serialization;

namespace RfaMetadataAddin
{
    public partial class RfaMetadataApplication
    {
        internal static Dictionary<string, object>
            ExecuteDrainageActionInline(
                UIApplication uiApplication,
                string action,
                Dictionary<string, object> payload)
        {
            if (uiApplication == null)
            {
                throw new ArgumentNullException("uiApplication");
            }
            var serializer = new JavaScriptSerializer();
            string responseFile = Path.Combine(
                Path.GetTempPath(),
                "sc-drainage-inline-"
                    + Guid.NewGuid().ToString("N")
                    + ".json");
            try
            {
                HandleDrainageAction(
                    uiApplication,
                    payload ?? new Dictionary<string, object>(),
                    action,
                    responseFile,
                    serializer);
                if (!File.Exists(responseFile))
                {
                    throw new InvalidOperationException(
                        "排水核心沒有回傳執行結果。");
                }
                return serializer.Deserialize<
                    Dictionary<string, object>>(
                        File.ReadAllText(responseFile));
            }
            finally
            {
                if (File.Exists(responseFile))
                {
                    File.Delete(responseFile);
                }
            }
        }

        internal static Dictionary<string, object>
            GetDrainageDocumentIdentityInline(Document document)
        {
            if (document == null)
            {
                throw new ArgumentNullException("document");
            }
            var serializer = new JavaScriptSerializer();
            return serializer.Deserialize<
                Dictionary<string, object>>(
                    serializer.Serialize(
                        SerializeDrainageDocumentRef(document)));
        }

        internal static Dictionary<string, object>
            ConfirmDrainageSnapshotInline(
                Document document,
                string snapshotId,
                string snapshotHash,
                string actorKind)
        {
            DrainageRouteSnapshot snapshot =
                RequireDrainageSnapshot(
                    document,
                    snapshotId,
                    snapshotHash);
            DrainageConfirmation confirmation =
                ConfirmDrainageSnapshot(
                    snapshot,
                    "human");
            return new Dictionary<string, object>
            {
                { "confirmation_id", confirmation.ConfirmationId },
                { "snapshot_id", snapshot.SnapshotId },
                { "snapshot_hash", snapshot.SnapshotHash }
            };
        }
    }
}
