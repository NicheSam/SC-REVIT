using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Plumbing;
using System;
using System.Collections.Generic;

namespace RfaMetadataAddin.Drainage
{
    internal enum DrainageFailureCode
    {
        None,
        SourceNotSupported,
        SourceConnectorMissing,
        SourceConnectorAmbiguous,
        SourceConnectorConnected,
        TargetNotFound,
        TargetAmbiguous,
        TargetDownstreamUnresolved,
        ConfigurationMissing,
        ConfigurationInvalid,
        RouteNotFound,
        RouteBlocked,
        MinimumTangentViolation,
        FittingPlacementFailed,
        JunctionDirectionInvalid,
        SlopeValidationFailed,
        TopologyValidationFailed,
        CommitFailed
    }

    internal enum DrainageSourceKind
    {
        PlumbingFixture,
        Standpipe
    }

    internal sealed class DrainageSourceRef
    {
        public Element SourceElement { get; set; }
        public Connector SourceConnector { get; set; }
        public DrainageSourceKind Kind { get; set; }
        public XYZ PickPoint { get; set; }

        public ElementId ElementId
        {
            get { return SourceElement == null ? ElementId.InvalidElementId : SourceElement.Id; }
        }

        public string UniqueId
        {
            get { return SourceElement == null ? "" : SourceElement.UniqueId; }
        }
    }

    internal sealed class DrainageTargetRef
    {
        public Pipe MainPipe { get; set; }
        public double Score { get; set; }
        public double DistanceFeet { get; set; }
        public string Resolution { get; set; }
        public bool RequiresUserConfirmation { get; set; }
        public IList<string> Evidence { get; set; }

        public DrainageTargetRef()
        {
            Evidence = new List<string>();
        }
    }

    internal sealed class DrainageConfigurationProfile
    {
        public string ProfileId { get; set; }
        public long PipeTypeId { get; set; }
        public string PipeTypeUniqueId { get; set; }
        public string PipeTypeName { get; set; }
        public long SanitaryTeeTypeId { get; set; }
        public string SanitaryTeeTypeUniqueId { get; set; }
        public long WyeTypeId { get; set; }
        public string WyeTypeUniqueId { get; set; }
        public long VerticalToHorizontalElbowTypeId { get; set; }
        public string VerticalToHorizontalElbowTypeUniqueId { get; set; }
        public long OffsetElbowTypeId { get; set; }
        public string OffsetElbowTypeUniqueId { get; set; }
        public double SlopePercent { get; set; }
        public double MinimumDiameterMm { get; set; }
        public double MaximumDiameterMm { get; set; }
        public bool Enabled { get; set; }

        public DrainageConfigurationProfile()
        {
            ProfileId = "DCP-" + Guid.NewGuid().ToString("N");
            SlopePercent = 1.0;
            MinimumDiameterMm = 25.0;
            MaximumDiameterMm = 300.0;
            Enabled = true;
        }

        public bool SupportsDiameter(double diameterMm)
        {
            return Enabled
                && diameterMm >= MinimumDiameterMm
                && diameterMm <= MaximumDiameterMm;
        }
    }

    internal sealed class DrainageRouteRequest
    {
        public DrainageSourceRef Source { get; set; }
        public DrainageTargetRef Target { get; set; }
        public DrainageConfigurationProfile Configuration { get; set; }
        public double DiameterMm { get; set; }
        public string DownstreamMode { get; set; }
        public string ActorKind { get; set; }
        public string IdempotencyKey { get; set; }
    }

    internal sealed class DrainageRoutePlan
    {
        public string RouteHash { get; set; }
        public string RouteKind { get; set; }
        public DrainageRouteRequest Request { get; set; }
        public IDictionary<string, object> PreviewPayload { get; set; }
        public IList<string> Issues { get; set; }
        public bool ReadyToCreate { get; set; }

        public DrainageRoutePlan()
        {
            Issues = new List<string>();
        }
    }

    internal sealed class DrainageExecutionResult
    {
        public bool Succeeded { get; set; }
        public DrainageFailureCode FailureCode { get; set; }
        public string Message { get; set; }
        public string RouteHash { get; set; }
        public string OperationId { get; set; }
        public IList<ElementId> CreatedElementIds { get; set; }

        public DrainageExecutionResult()
        {
            FailureCode = DrainageFailureCode.None;
            CreatedElementIds = new List<ElementId>();
        }

        public static DrainageExecutionResult Failed(
            DrainageFailureCode failureCode,
            string message)
        {
            return new DrainageExecutionResult
            {
                Succeeded = false,
                FailureCode = failureCode,
                Message = message ?? ""
            };
        }
    }
}
