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
            SchemaVersion = "sc.drainage.configuration.v2";
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
                "sc.drainage.configuration.v2";
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
            if (document == null || pipe == null)
            {
                return null;
            }
            long pipeTypeId = pipe.GetTypeId().Value;
            return Load(document).Profiles
                .Where(profile => profile != null
                    && profile.PipeTypeId == pipeTypeId
                    && profile.SupportsDiameter(diameterMm))
                .OrderBy(profile =>
                    profile.MaximumDiameterMm
                    - profile.MinimumDiameterMm)
                .FirstOrDefault();
        }

        public static IList<string> Validate(
            Document document,
            DrainageConfigurationDocument configuration)
        {
            var errors = new List<string>();
            var pipeTypeIds = new HashSet<long>();
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
                if (!pipeTypeIds.Add(profile.PipeTypeId))
                {
                    errors.Add(
                        "同一管類型只能有一列設定："
                        + pipeType.Name);
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
                    profile.MinimumDiameterMm,
                    profile.MaximumDiameterMm,
                    errors);
                ProbeFitting(
                    document,
                    profile.OffsetElbowTypeId,
                    profile.PipeTypeName + " 的 45°／錯層彎頭",
                    2,
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
                        profile.MinimumDiameterMm,
                        profile.MaximumDiameterMm,
                        errors);
                }
            }
            return errors;
        }

        private static void ProbeFitting(
            Document document,
            long elementId,
            string label,
            int expectedConnectorCount,
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
                        expectedConnectorCount))
                    {
                        errors.Add(
                            label
                            + "的連接器角度不是 45° 排水接管幾何。");
                        return;
                    }
                    if (!SupportsDiameter(
                        document,
                        connectors,
                        minimumDiameterMm)
                        || !SupportsDiameter(
                            document,
                            connectors,
                            maximumDiameterMm))
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
            int expectedConnectorCount)
        {
            if (expectedConnectorCount == 2)
            {
                return IsAngleNear(
                    connectors[0],
                    connectors[1],
                    45,
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
                        45,
                        2))
                    {
                        return true;
                    }
                }
            }
            return false;
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
