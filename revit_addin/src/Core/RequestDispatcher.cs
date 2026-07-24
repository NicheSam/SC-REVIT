using Autodesk.Revit.UI;
using System.Collections.Generic;
using System.Web.Script.Serialization;

namespace RfaMetadataAddin
{
    public partial class RfaMetadataApplication
    {
        private static bool TryDispatchRequest(
            UIApplication uiApp,
            Dictionary<string, object> payload,
            string action,
            string responseFile,
            JavaScriptSerializer serializer)
        {
            if (TryHandleBackstageAction(uiApp, payload, action, responseFile, serializer))
            {
                return true;
            }

            if (TryHandleFamilyLibraryAction(uiApp, payload, action, responseFile, serializer))
            {
                return true;
            }

            if (TryHandleOpeningAction(uiApp, payload, action, responseFile, serializer))
            {
                return true;
            }

            if (TryHandleCadPointAction(uiApp, payload, action, responseFile, serializer))
            {
                return true;
            }

            if (TryHandleFireBranchAction(uiApp, payload, action, responseFile, serializer))
            {
                return true;
            }

            if (TryHandleDrainageAction(uiApp, payload, action, responseFile, serializer))
            {
                return true;
            }

            if (TryHandleMepToolsAction(uiApp, payload, action, responseFile, serializer))
            {
                return true;
            }

            return false;
        }
    }
}
