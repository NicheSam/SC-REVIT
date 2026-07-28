using Autodesk.Revit.DB;
using Autodesk.Revit.DB.ExtensibleStorage;
using Autodesk.Revit.DB.Plumbing;
using Autodesk.Revit.DB.Structure;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Web.Script.Serialization;

namespace RfaMetadataAddin.Drainage
{
    internal sealed class DrainageConfigurationDocument
    {
        public string SchemaVersion { get; set; }
        public IList<DrainageConfigurationProfile> Profiles { get; set; }

        public DrainageConfigurationDocument()
        {
            SchemaVersion = "sc.drainage.configuration.v3";
            Profiles = new List<DrainageConfigurationProfile>();
        }
    }

    internal static class DrainageConfigurationStore
    {
        private static readonly Guid SchemaGuid =
            new Guid("C264A86D-DB92-4EFA-AE1E-B13DD01D7F7A");
        private const string StorageName = "SC_DRAINAGE_CONFIGURATION";
        private const string JsonFieldName = "ConfigurationJson";

        public static DrainageConfigurationDocument Load(Document document)
        {
            if (document == null)
            {
                throw new ArgumentNullException("document");
            }

            Schema schema = Schema.Lookup(SchemaGuid);
            if (schema == null)
            {
                return new DrainageConfigurationDocument();
            }

            DataStorage storage = FindStorage(document);
            if (storage == null)
            {
                return new DrainageConfigurationDocument();
            }

            Entity entity = storage.GetEntity(schema);
            if (!entity.IsValid())
            {
                return new DrainageConfigurationDocument();
            }

            string json = entity.Get<string>(schema.GetField(JsonFieldName));
            if (string.IsNullOrWhiteSpace(json))
            {
                return new DrainageConfigurationDocument();
            }

            try
            {
                DrainageConfigurationDocument result =
                    new JavaScriptSerializer()
                        .Deserialize<DrainageConfigurationDocument>(json);
                if (result == null)
                {
                    return new DrainageConfigurationDocument();
                }
                if (result.Profiles == null)
                {
                    result.Profiles =
                        new List<DrainageConfigurationProfile>();
                }
                NormalizeConfiguration(document, result);
                return result;
            }
            catch
            {
                return new DrainageConfigurationDocument();
            }
        }

        public static void Save(
            Document document,
            DrainageConfigurationDocument configuration)
        {
            if (document == null)
            {
                throw new ArgumentNullException("document");
            }
            if (configuration == null)
            {
                throw new ArgumentNullException("configuration");
            }
            if (document.IsReadOnly)
            {
                throw new InvalidOperationException(
                    "目前 Revit 專案為唯讀，無法儲存排水管件設定。");
            }

            IList<string> errors = Validate(document, configuration);
            if (errors.Count > 0)
            {
                throw new InvalidOperationException(
                    string.Join(Environment.NewLine, errors));
            }

            Schema schema = GetOrCreateSchema();
            DataStorage storage = FindStorage(document);
            if (storage == null)
            {
                storage = DataStorage.Create(document);
                storage.Name = StorageName;
            }

            configuration.SchemaVersion =
                "sc.drainage.configuration.v3";
            Entity entity = new Entity(schema);
            entity.Set(
                schema.GetField(JsonFieldName),
                new JavaScriptSerializer().Serialize(configuration));
            storage.SetEntity(entity);
        }

        public static DrainageConfigurationProfile ResolveForPipe(
            Document document,
            Pipe pipe,
            double diameterMm)
        {
            return ResolveForPipe(
                document,
                pipe,
                diameterMm,
                null);
        }

        public static DrainageConfigurationProfile ResolveForPipe(
            Document document,
            Pipe pipe,
            double diameterMm,
            DrainageSourceRef source)
        {
            if (document == null || pipe == null)
            {
                return null;
            }
            long pipeTypeId = pipe.GetTypeId().Value;
            ElementId targetSystemTypeId =
                ReadSystemTypeId(pipe);
            string targetSystemTypeUniqueId =
                ReadUniqueId(document, targetSystemTypeId);
            string targetClassification =
                ReadSystemClassification(
                    document,
                    targetSystemTypeId);
            return Load(document).Profiles
                .Where(profile => profile != null
                    && profile.PipeTypeId == pipeTypeId
                    && profile.SupportsDiameter(diameterMm)
                    && string.Equals(
                        profile.ProfileKind,
                        "GravityDrainage",
                        StringComparison.Ordinal)
                    && TargetSystemMatches(
                        profile,
                        targetSystemTypeId,
                        targetSystemTypeUniqueId)
                    && SourceMatches(
                        profile,
                        source,
                        targetClassification))
                .OrderBy(profile =>
                    profile.MaximumDiameterMm
                    - profile.MinimumDiameterMm)
                .ThenBy(profile =>
                    profile.TargetSystemTypeId > 0 ? 0 : 1)
                .ThenBy(profile => profile.ProfileId)
                .FirstOrDefault();
        }

        public static IList<string> Validate(
            Document document,
            DrainageConfigurationDocument configuration)
        {
            var errors = new List<string>();
            var profileKeys = new HashSet<string>(
                StringComparer.Ordinal);
            foreach (DrainageConfigurationProfile profile in
                configuration.Profiles
                    ?? new List<DrainageConfigurationProfile>())
            {
                if (profile == null)
                {
                    errors.Add("設定列不可為空。");
                    continue;
                }
                PipeType pipeType = document.GetElement(
                    new ElementId(profile.PipeTypeId)) as PipeType;
                if (pipeType == null
                    || !string.Equals(
                        pipeType.UniqueId,
                        profile.PipeTypeUniqueId,
                        StringComparison.Ordinal))
                {
                    errors.Add(
                        "管類型設定已失效：" + profile.PipeTypeName);
                    continue;
                }
                string profileKey = string.Join(
                    "|",
                    profile.PipeTypeId,
                    profile.TargetSystemTypeId,
                    profile.ProfileKind ?? "");
                if (!profileKeys.Add(profileKey))
                {
                    errors.Add(
                        "同一管類型、系統類型與 Profile 類型只能有一列設定："
                        + pipeType.Name);
                }
                if (!string.Equals(
                    profile.ProfileKind,
                    "GravityDrainage",
                    StringComparison.Ordinal))
                {
                    errors.Add(
                        pipeType.Name
                        + " 目前只支援 GravityDrainage Profile。");
                }
                if (profile.TargetSystemTypeId > 0)
                {
                    PipingSystemType targetSystemType =
                        document.GetElement(
                            new ElementId(
                                profile.TargetSystemTypeId))
                            as PipingSystemType;
                    if (targetSystemType == null
                        || !string.Equals(
                            targetSystemType.UniqueId,
                            profile.TargetSystemTypeUniqueId,
                            StringComparison.Ordinal))
                    {
                        errors.Add(
                            pipeType.Name
                            + " 的目標系統類型設定已失效。");
                    }
                }
                if (profile.SlopePercent < 0.1
                    || profile.SlopePercent > 10.0)
                {
                    errors.Add(
                        pipeType.Name
                        + " 的坡度必須介於 0.1% 與 10% 之間。");
                }
                if (profile.MinimumDiameterMm < 1
                    || profile.MaximumDiameterMm
                        < profile.MinimumDiameterMm)
                {
                    errors.Add(
                        pipeType.Name + " 的適用管徑範圍無效。");
                }
                if (profile.MinimumTangentMm < 25
                    || profile.MinimumTangentMm > 3000)
                {
                    errors.Add(
                        pipeType.Name
                        + " 的最短直管必須介於 25–3000 mm。");
                }
                ValidateFitting(
                    document,
                    profile.WyeTypeId,
                    profile.WyeTypeUniqueId,
                    pipeType.Name + " 的 Y／斜三通",
                    true,
                    errors);
                ValidateFitting(
                    document,
                    profile.OffsetElbowTypeId,
                    profile.OffsetElbowTypeUniqueId,
                    pipeType.Name + " 的 45°／錯層彎頭",
                    true,
                    errors);
                ValidateFitting(
                    document,
                    profile.SanitaryTeeTypeId,
                    profile.SanitaryTeeTypeUniqueId,
                    pipeType.Name + " 的斜 T 三通",
                    false,
                    errors);
                ValidateFitting(
                    document,
                    profile.VerticalToHorizontalElbowTypeId,
                    profile.VerticalToHorizontalElbowTypeUniqueId,
                    pipeType.Name + " 的立管轉水平彎頭",
                    false,
                    errors);
                ValidateFitting(
                    document,
                    profile.ReducerTypeId,
                    profile.ReducerTypeUniqueId,
                    pipeType.Name + " 的變徑",
                    false,
                    errors);
            }
            return errors;
        }

        public static IList<string> ValidateForSave(
            Document document,
            DrainageConfigurationDocument configuration)
        {
            IList<string> errors = Validate(document, configuration);
            if (errors.Count > 0)
            {
                return errors;
            }
            if (document.IsModifiable)
            {
                errors.Add(
                    "管件幾何檢查必須在儲存交易開始前執行。");
                return errors;
            }

            foreach (DrainageConfigurationProfile profile in
                configuration.Profiles
                    ?? new List<DrainageConfigurationProfile>())
            {
                ProbeFitting(
                    document,
                    profile.WyeTypeId,
                    profile.PipeTypeName + " 的 Y／斜三通",
                    3,
                    45,
                    false,
                    profile.MinimumDiameterMm,
                    profile.MaximumDiameterMm,
                    errors);
                ProbeFitting(
                    document,
                    profile.OffsetElbowTypeId,
                    profile.PipeTypeName + " 的 45°／錯層彎頭",
                    2,
                    45,
                    false,
                    profile.MinimumDiameterMm,
                    profile.MaximumDiameterMm,
                    errors);
                if (profile.SanitaryTeeTypeId > 0)
                {
                    ProbeFitting(
                        document,
                        profile.SanitaryTeeTypeId,
                        profile.PipeTypeName + " 的斜 T 三通",
                        3,
                        45,
                        false,
                        profile.MinimumDiameterMm,
                        profile.MaximumDiameterMm,
                        errors);
                }
                if (profile.VerticalToHorizontalElbowTypeId > 0)
                {
                    ProbeFitting(
                        document,
                        profile.VerticalToHorizontalElbowTypeId,
                        profile.PipeTypeName + " 的立管轉水平彎頭",
                        2,
                        45,
                        false,
                        profile.MinimumDiameterMm,
                        profile.MaximumDiameterMm,
                        errors);
                }
                if (profile.ReducerTypeId > 0)
                {
                    ProbeFitting(
                        document,
                        profile.ReducerTypeId,
                        profile.PipeTypeName + " 的變徑",
                        2,
                        0,
                        true,
                        profile.MinimumDiameterMm,
                        profile.MaximumDiameterMm,
                        errors);
                }
            }
            return errors;
        }

        private static void NormalizeConfiguration(
            Document document,
            DrainageConfigurationDocument configuration)
        {
            bool migratedFromV2 = !string.Equals(
                configuration.SchemaVersion,
                "sc.drainage.configuration.v3",
                StringComparison.Ordinal);
            foreach (DrainageConfigurationProfile profile in
                configuration.Profiles
                    ?? new List<DrainageConfigurationProfile>())
            {
                if (profile == null)
                {
                    continue;
                }
                if (string.IsNullOrWhiteSpace(profile.ProfileId))
                {
                    profile.ProfileId =
                        "DCP-" + Guid.NewGuid().ToString("N");
                }
                if (string.IsNullOrWhiteSpace(profile.ProfileKind))
                {
                    profile.ProfileKind = "GravityDrainage";
                }
                if (string.IsNullOrWhiteSpace(profile.RoutePreference))
                {
                    profile.RoutePreference =
                        "PreserveOutletThenFewestFittings";
                }
                if (profile.MinimumTangentMm <= 0)
                {
                    profile.MinimumTangentMm = 80.0;
                }
                if (profile.MinimumDiameterMm <= 0)
                {
                    profile.MinimumDiameterMm = 25.0;
                }
                if (profile.MaximumDiameterMm <= 0)
                {
                    profile.MaximumDiameterMm = 300.0;
                }
                if (profile.SlopePercent <= 0)
                {
                    profile.SlopePercent = 1.0;
                }
                if (profile.AllowedSourceSystemClassifications == null)
                {
                    profile.AllowedSourceSystemClassifications = "";
                }
                if (profile.AllowedSourceSystemTypeUniqueIds == null)
                {
                    profile.AllowedSourceSystemTypeUniqueIds = "";
                }
                if (migratedFromV2)
                {
                    profile.AllowBidirectionalFlow = true;
                    profile.AllowUndefinedFlow = true;
                    profile.AllowInFlow = false;
                }
                PipeType pipeType = document.GetElement(
                    new ElementId(profile.PipeTypeId)) as PipeType;
                if (pipeType != null)
                {
                    profile.PipeTypeUniqueId = pipeType.UniqueId;
                    profile.PipeTypeName = pipeType.Name;
                }
            }
            configuration.SchemaVersion =
                "sc.drainage.configuration.v3";
        }

        private static bool TargetSystemMatches(
            DrainageConfigurationProfile profile,
            ElementId targetSystemTypeId,
            string targetSystemTypeUniqueId)
        {
            if (profile.TargetSystemTypeId <= 0
                && string.IsNullOrWhiteSpace(
                    profile.TargetSystemTypeUniqueId))
            {
                return true;
            }
            return targetSystemTypeId != null
                && targetSystemTypeId
                    != ElementId.InvalidElementId
                && profile.TargetSystemTypeId
                    == targetSystemTypeId.Value
                && string.Equals(
                    profile.TargetSystemTypeUniqueId,
                    targetSystemTypeUniqueId,
                    StringComparison.Ordinal);
        }

        private static bool SourceMatches(
            DrainageConfigurationProfile profile,
            DrainageSourceRef source,
            string targetClassification)
        {
            if (source == null || source.ConnectorRef == null)
            {
                return true;
            }
            DrainageConnectorRef connector = source.ConnectorRef;
            if (connector.FlowDirection == FlowDirectionType.In
                && !profile.AllowInFlow)
            {
                return false;
            }
            if (connector.FlowDirection
                    == FlowDirectionType.Bidirectional
                && !profile.AllowBidirectionalFlow)
            {
                return false;
            }
            if (!connector.FlowDirectionKnown
                && !profile.AllowUndefinedFlow)
            {
                return false;
            }

            ISet<string> allowedSystemTypes =
                ParseList(
                    profile.AllowedSourceSystemTypeUniqueIds);
            if (allowedSystemTypes.Count > 0
                && !allowedSystemTypes.Contains(
                    connector.SystemTypeUniqueId ?? ""))
            {
                return false;
            }

            ISet<string> allowedClassifications =
                ParseList(
                    profile.AllowedSourceSystemClassifications);
            if (allowedClassifications.Count > 0)
            {
                return allowedClassifications.Contains(
                    connector.SystemClassification ?? "");
            }

            return string.IsNullOrWhiteSpace(
                    connector.SystemClassification)
                || string.IsNullOrWhiteSpace(targetClassification)
                || string.Equals(
                    connector.SystemClassification,
                    targetClassification,
                    StringComparison.OrdinalIgnoreCase);
        }

        private static ISet<string> ParseList(string value)
        {
            return new HashSet<string>(
                (value ?? "")
                    .Split(new[] { ',', ';', '\r', '\n' },
                        StringSplitOptions.RemoveEmptyEntries)
                    .Select(item => item.Trim())
                    .Where(item => item.Length > 0),
                StringComparer.OrdinalIgnoreCase);
        }

        private static ElementId ReadSystemTypeId(Element element)
        {
            Parameter parameter = element == null
                ? null
                : element.get_Parameter(
                    BuiltInParameter
                        .RBS_PIPING_SYSTEM_TYPE_PARAM);
            return parameter == null
                ? ElementId.InvalidElementId
                : parameter.AsElementId();
        }

        private static string ReadUniqueId(
            Document document,
            ElementId elementId)
        {
            Element element = document == null
                || elementId == null
                || elementId == ElementId.InvalidElementId
                    ? null
                    : document.GetElement(elementId);
            return element == null ? "" : element.UniqueId;
        }

        private static string ReadSystemClassification(
            Document document,
            ElementId systemTypeId)
        {
            PipingSystemType systemType = document == null
                || systemTypeId == null
                || systemTypeId == ElementId.InvalidElementId
                    ? null
                    : document.GetElement(systemTypeId)
                        as PipingSystemType;
            return systemType == null
                ? ""
                : systemType.SystemClassification.ToString();
        }

        private static void ProbeFitting(
            Document document,
            long elementId,
            string label,
            int expectedConnectorCount,
            double expectedAngleDegrees,
            bool isReducer,
            double minimumDiameterMm,
            double maximumDiameterMm,
            IList<string> errors)
        {
            FamilySymbol symbol = document.GetElement(
                new ElementId(elementId)) as FamilySymbol;
            if (symbol == null)
            {
                return;
            }

            using (var probe = new Transaction(
                document,
                "SC 排水管件設定檢查"))
            {
                try
                {
                    if (probe.Start() != TransactionStatus.Started)
                    {
                        errors.Add(label + "無法啟動幾何檢查。");
                        return;
                    }
                    if (!symbol.IsActive)
                    {
                        symbol.Activate();
                        document.Regenerate();
                    }
                    FamilyInstance instance =
                        document.Create.NewFamilyInstance(
                            XYZ.Zero,
                            symbol,
                            StructuralType.NonStructural);
                    document.Regenerate();
                    List<Connector> connectors =
                        GetEndConnectors(instance);
                    if (connectors.Count != expectedConnectorCount
                        || connectors.Any(item =>
                            item.Domain != Domain.DomainPiping
                            || item.Shape
                                != ConnectorProfileType.Round))
                    {
                        errors.Add(
                            label
                            + "必須有 "
                            + expectedConnectorCount
                            + " 個圓形管路端連接器。");
                        return;
                    }
                    if (!HasExpectedAngles(
                            connectors,
                            expectedConnectorCount,
                            expectedAngleDegrees))
                    {
                        errors.Add(
                            label
                            + "的連接器角度不是 "
                            + expectedAngleDegrees.ToString("0.#")
                            + "° 設定幾何。");
                        return;
                    }
                    bool supportsRange = isReducer
                        ? SupportsReducerDiameterRange(
                            document,
                            connectors,
                            minimumDiameterMm,
                            maximumDiameterMm)
                        : SupportsDiameter(
                                document,
                                connectors,
                                minimumDiameterMm)
                            && SupportsDiameter(
                                document,
                                connectors,
                                maximumDiameterMm);
                    if (!supportsRange)
                    {
                        errors.Add(
                            label
                            + "無法涵蓋設定的管徑範圍 "
                            + minimumDiameterMm.ToString("0.#")
                            + "–"
                            + maximumDiameterMm.ToString("0.#")
                            + " mm。");
                    }
                }
                catch (Exception ex)
                {
                    errors.Add(
                        label
                        + "無法放置或檢查："
                        + ex.Message);
                }
                finally
                {
                    if (probe.GetStatus()
                        == TransactionStatus.Started)
                    {
                        probe.RollBack();
                    }
                }
            }
        }

        private static List<Connector> GetEndConnectors(
            FamilyInstance instance)
        {
            if (instance == null
                || instance.MEPModel == null
                || instance.MEPModel.ConnectorManager == null)
            {
                return new List<Connector>();
            }
            return instance.MEPModel.ConnectorManager.Connectors
                .Cast<Connector>()
                .Where(item =>
                    item.ConnectorType == ConnectorType.End)
                .ToList();
        }

        private static bool HasExpectedAngles(
            IList<Connector> connectors,
            int expectedConnectorCount,
            double expectedAngleDegrees)
        {
            if (expectedConnectorCount == 2)
            {
                return IsAngleNear(
                    connectors[0],
                    connectors[1],
                    expectedAngleDegrees,
                    2);
            }
            for (int first = 0; first < connectors.Count; first++)
            {
                for (int second = first + 1;
                    second < connectors.Count;
                    second++)
                {
                    if (!IsAngleNear(
                        connectors[first],
                        connectors[second],
                        0,
                        2))
                    {
                        continue;
                    }
                    int branch = 3 - first - second;
                    if (IsAngleNear(
                        connectors[first],
                        connectors[branch],
                        expectedAngleDegrees,
                        2))
                    {
                        return true;
                    }
                }
            }
            return false;
        }

        private static bool SupportsReducerDiameterRange(
            Document document,
            IList<Connector> connectors,
            double minimumDiameterMm,
            double maximumDiameterMm)
        {
            if (connectors == null || connectors.Count != 2)
            {
                return false;
            }
            double minimumRadius =
                UnitUtils.ConvertToInternalUnits(
                    minimumDiameterMm / 2.0,
                    UnitTypeId.Millimeters);
            double maximumRadius =
                UnitUtils.ConvertToInternalUnits(
                    maximumDiameterMm / 2.0,
                    UnitTypeId.Millimeters);
            try
            {
                connectors[0].Radius = maximumRadius;
                connectors[1].Radius = minimumRadius;
                document.Regenerate();
                double tolerance =
                    UnitUtils.ConvertToInternalUnits(
                        0.5,
                        UnitTypeId.Millimeters);
                return Math.Abs(
                        connectors[0].Radius
                            - maximumRadius) <= tolerance
                    && Math.Abs(
                        connectors[1].Radius
                            - minimumRadius) <= tolerance;
            }
            catch
            {
                return false;
            }
        }

        private static bool IsAngleNear(
            Connector first,
            Connector second,
            double expectedDegrees,
            double toleranceDegrees)
        {
            XYZ firstAxis = first.CoordinateSystem.BasisZ.Normalize();
            XYZ secondAxis = second.CoordinateSystem.BasisZ.Normalize();
            double dot = Math.Abs(firstAxis.DotProduct(secondAxis));
            dot = Math.Max(-1, Math.Min(1, dot));
            double degrees = Math.Acos(dot) * 180.0 / Math.PI;
            return Math.Abs(degrees - expectedDegrees)
                <= toleranceDegrees;
        }

        private static bool SupportsDiameter(
            Document document,
            IList<Connector> connectors,
            double diameterMm)
        {
            double radius = UnitUtils.ConvertToInternalUnits(
                diameterMm / 2.0,
                UnitTypeId.Millimeters);
            try
            {
                foreach (Connector connector in connectors)
                {
                    connector.Radius = radius;
                }
                document.Regenerate();
                double tolerance = UnitUtils.ConvertToInternalUnits(
                    0.5,
                    UnitTypeId.Millimeters);
                return connectors.All(connector =>
                    Math.Abs(connector.Radius - radius)
                        <= tolerance);
            }
            catch
            {
                return false;
            }
        }

        private static void ValidateFitting(
            Document document,
            long elementId,
            string uniqueId,
            string label,
            bool required,
            IList<string> errors)
        {
            if (elementId <= 0 || string.IsNullOrWhiteSpace(uniqueId))
            {
                if (required)
                {
                    errors.Add(label + "尚未設定。");
                }
                return;
            }
            FamilySymbol symbol = document.GetElement(
                new ElementId(elementId)) as FamilySymbol;
            if (symbol == null
                || symbol.Category == null
                || symbol.Category.Id.Value
                    != (long)BuiltInCategory.OST_PipeFitting
                || !string.Equals(
                    symbol.UniqueId,
                    uniqueId,
                    StringComparison.Ordinal))
            {
                errors.Add(label + "不是有效的管配件類型。");
            }
        }

        private static DataStorage FindStorage(Document document)
        {
            return new FilteredElementCollector(document)
                .OfClass(typeof(DataStorage))
                .Cast<DataStorage>()
                .FirstOrDefault(item =>
                    string.Equals(
                        item.Name,
                        StorageName,
                        StringComparison.Ordinal));
        }

        private static Schema GetOrCreateSchema()
        {
            Schema schema = Schema.Lookup(SchemaGuid);
            if (schema != null)
            {
                return schema;
            }
            var builder = new SchemaBuilder(SchemaGuid);
            builder.SetSchemaName("SCDrainageConfiguration");
            builder.SetDocumentation(
                "Project-scoped SC drainage fitting and slope configuration.");
            builder.AddSimpleField(JsonFieldName, typeof(string));
            return builder.Finish();
        }
    }
}
