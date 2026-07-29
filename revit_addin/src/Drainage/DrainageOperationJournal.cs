using Autodesk.Revit.DB;
using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

namespace RfaMetadataAddin
{
    public partial class RfaMetadataApplication
    {
        private class DrainageOperationRecord
        {
            public string SchemaVersion { get; set; }
            public string OperationId { get; set; }
            public string IdempotencyKey { get; set; }
            public string SnapshotId { get; set; }
            public string SnapshotHash { get; set; }
            public string DocumentFingerprint { get; set; }
            public long DocumentRevision { get; set; }
            public string DocumentTitle { get; set; }
            public string DocumentPathKind { get; set; }
            public string DependencyHash { get; set; }
            public string ConfirmationId { get; set; }
            public string ConfirmationActorKind { get; set; }
            public string InitiatorSurface { get; set; }
            public string ToolContractVersion { get; set; }
            public string AssemblyModuleVersionId { get; set; }
            public string AssemblySha256 { get; set; }
            public string RequestToolName { get; set; }
            public string ActorKind { get; set; }
            public string AddinVersion { get; set; }
            public string Status { get; set; }
            public string Error { get; set; }
            public string UpdatedAtUtc { get; set; }
            public Dictionary<string, object> Result { get; set; }
            public Dictionary<string, object> ValidationEvidence { get; set; }
        }

        private static readonly object DrainageOperationLock = new object();
        private static readonly string DrainageOperationDir = Path.Combine(
            Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData),
            "RevitFamilyClassifier",
            "runtime",
            "queue",
            "operations");
        private static readonly Regex DrainageOperationIdPattern = new Regex(
            "^DOP-[A-Za-z0-9_-]{8,80}$",
            RegexOptions.CultureInvariant);

        private static DrainageOperationRecord BeginDrainageOperation(
            string operationId,
            string idempotencyKey,
            DrainageRouteSnapshot snapshot,
            Document document,
            DrainageConfirmation confirmation,
            string initiatorSurface,
            out bool createdNew)
        {
            createdNew = false;
            ValidateDrainageOperationIdentity(operationId, idempotencyKey);
            Directory.CreateDirectory(DrainageOperationDir);
            lock (DrainageOperationLock)
            {
                DrainageOperationRecord keyOwner =
                    FindDrainageOperationByIdempotencyKey(
                        snapshot.DocumentFingerprint,
                        idempotencyKey);
                if (keyOwner != null
                    && !string.Equals(
                        keyOwner.OperationId,
                        operationId,
                        StringComparison.Ordinal))
                {
                    throw new InvalidOperationException(
                        "IDEMPOTENCY_KEY_REUSED");
                }
                DrainageOperationRecord existing = ReadDrainageOperation(operationId);
                if (existing != null)
                {
                    if (!string.Equals(
                        existing.IdempotencyKey,
                        idempotencyKey,
                        StringComparison.Ordinal)
                        || !string.Equals(
                            existing.SnapshotHash,
                            snapshot.SnapshotHash,
                            StringComparison.Ordinal))
                    {
                        throw new InvalidOperationException("IDEMPOTENCY_CONFLICT");
                    }
                    return existing;
                }
                var record = new DrainageOperationRecord
                {
                    SchemaVersion = "sc.drainage.operation.v2",
                    OperationId = operationId,
                    IdempotencyKey = idempotencyKey,
                    SnapshotId = snapshot.SnapshotId,
                    SnapshotHash = snapshot.SnapshotHash,
                    DocumentFingerprint = snapshot.DocumentFingerprint,
                    DocumentRevision = snapshot.DocumentRevision,
                    DocumentTitle = document.Title,
                    DocumentPathKind = document.IsModelInCloud
                        ? "cloud"
                        : string.IsNullOrWhiteSpace(document.PathName)
                            ? "unsaved"
                            : "local",
                    DependencyHash = snapshot.DependencyHash,
                    ConfirmationId = confirmation.ConfirmationId,
                    ConfirmationActorKind = confirmation.ActorKind,
                    InitiatorSurface = initiatorSurface,
                    ToolContractVersion = "1.4.0",
                    AssemblyModuleVersionId = typeof(
                        RfaMetadataApplication)
                        .Assembly.ManifestModule.ModuleVersionId
                        .ToString("D"),
                    AssemblySha256 =
                        ComputeDrainageAssemblySha256(),
                    RequestToolName = initiatorSurface == "agent"
                        ? "drainage.commit_confirmed_snapshot"
                        : "gui.create_drainage_pipes",
                    AddinVersion = "0.5.0-drainage-dev",
                    Status = "committing",
                    Error = "",
                    UpdatedAtUtc = DateTime.UtcNow.ToString("o"),
                    Result = null
                };
                WriteDrainageOperation(record);
                createdNew = true;
                return record;
            }
        }

        private static void CompleteDrainageOperation(
            DrainageOperationRecord record,
            Dictionary<string, object> result)
        {
            lock (DrainageOperationLock)
            {
                record.Status = "committed";
                record.Error = "";
                record.Result = result;
                record.UpdatedAtUtc = DateTime.UtcNow.ToString("o");
                WriteDrainageOperation(record);
            }
        }

        private static void FailDrainageOperation(
            DrainageOperationRecord record,
            Exception error)
        {
            if (record == null)
            {
                return;
            }
            lock (DrainageOperationLock)
            {
                record.Status = "rolled_back";
                record.Error = error == null ? "unknown" : error.Message;
                record.Result = null;
                record.UpdatedAtUtc = DateTime.UtcNow.ToString("o");
                WriteDrainageOperation(record);
            }
        }

        private static void RecordDrainageValidation(
            DrainageOperationRecord record,
            Dictionary<string, object> validationEvidence)
        {
            if (record == null || validationEvidence == null)
            {
                return;
            }
            lock (DrainageOperationLock)
            {
                record.ValidationEvidence = validationEvidence;
                record.UpdatedAtUtc = DateTime.UtcNow.ToString("o");
                WriteDrainageOperation(record);
            }
        }

        private static DrainageOperationRecord RequireDrainageOperation(string operationId)
        {
            if (string.IsNullOrWhiteSpace(operationId)
                || !DrainageOperationIdPattern.IsMatch(operationId))
            {
                throw new InvalidOperationException("INVALID_OPERATION_ID");
            }
            DrainageOperationRecord record;
            lock (DrainageOperationLock)
            {
                record = ReadDrainageOperation(operationId);
            }
            if (record == null)
            {
                throw new InvalidOperationException("OPERATION_NOT_FOUND");
            }
            return record;
        }

        private static DrainageOperationRecord RequireDrainageOperationForDocument(
            Document document,
            string operationId)
        {
            DrainageOperationRecord record = RequireDrainageOperation(operationId);
            string fingerprint = GetDrainageDocumentBinding(document).Fingerprint;
            if (string.IsNullOrWhiteSpace(record.DocumentFingerprint)
                || !string.Equals(
                    record.DocumentFingerprint,
                    fingerprint,
                    StringComparison.Ordinal))
            {
                throw new InvalidOperationException("DOCUMENT_MISMATCH");
            }
            return record;
        }

        private static DrainageOperationRecord FindDrainageOperationByIdempotencyKey(
            string documentFingerprint,
            string idempotencyKey)
        {
            if (!Directory.Exists(DrainageOperationDir))
            {
                return null;
            }
            foreach (string path in Directory.GetFiles(
                DrainageOperationDir,
                "DOP-*.json"))
            {
                DrainageOperationRecord record;
                try
                {
                    record = new JavaScriptSerializer()
                        .Deserialize<DrainageOperationRecord>(
                            File.ReadAllText(path));
                }
                catch
                {
                    continue;
                }
                if (record != null
                    && string.Equals(
                        record.DocumentFingerprint,
                        documentFingerprint,
                        StringComparison.Ordinal)
                    && string.Equals(
                        record.IdempotencyKey,
                        idempotencyKey,
                        StringComparison.Ordinal))
                {
                    return record;
                }
            }
            return null;
        }

        private static DrainageOperationRecord ReconcileDrainageOperation(
            Document document,
            DrainageOperationRecord record)
        {
            if (record == null
                || !string.Equals(
                    record.Status,
                    "committing",
                    StringComparison.Ordinal))
            {
                return record;
            }
            string marker = ":operation=" + record.OperationId;
            var recoveredPipes = new List<long>();
            var recoveredFittings = new List<long>();
            foreach (Element element in new FilteredElementCollector(document)
                .WhereElementIsNotElementType())
            {
                Parameter comments = element.get_Parameter(
                    BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
                string value = comments != null && comments.HasValue
                    ? comments.AsString() ?? ""
                    : "";
                if (!value.Contains(marker))
                {
                    continue;
                }
                if (element is Autodesk.Revit.DB.Plumbing.Pipe)
                {
                    recoveredPipes.Add(element.Id.Value);
                }
                else if (element is FamilyInstance)
                {
                    recoveredFittings.Add(element.Id.Value);
                }
            }
            lock (DrainageOperationLock)
            {
                if (recoveredPipes.Count > 0 || recoveredFittings.Count > 0)
                {
                    record.Status = "committed_recovery_required";
                    record.Error =
                        "MODEL_COMMITTED_JOURNAL_INCOMPLETE";
                    record.Result = new Dictionary<string, object>
                    {
                        { "action", "create_drainage_pipes" },
                        { "operation_id", record.OperationId },
                        { "initiator_surface", record.InitiatorSurface },
                        { "confirmation_id", record.ConfirmationId },
                        { "confirmation_actor_kind", record.ConfirmationActorKind },
                        { "tool_contract_version", record.ToolContractVersion },
                        { "assembly_module_version_id", record.AssemblyModuleVersionId },
                        { "dependency_hash", record.DependencyHash },
                        { "addin_version", record.AddinVersion },
                        { "snapshot_id", record.SnapshotId },
                        { "snapshot_hash", record.SnapshotHash },
                        { "document", SerializeDrainageDocumentRef(document) },
                        { "created_element_ids", recoveredPipes },
                        { "fitting_element_ids", recoveredFittings },
                        { "recovered", true },
                        { "requires_manual_validation", true }
                    };
                    record.UpdatedAtUtc = DateTime.UtcNow.ToString("o");
                    WriteDrainageOperation(record);
                    return record;
                }
                DateTime updated;
                if (DateTime.TryParse(
                    record.UpdatedAtUtc,
                    null,
                    System.Globalization.DateTimeStyles.RoundtripKind,
                    out updated)
                    && DateTime.UtcNow - updated.ToUniversalTime()
                        > TimeSpan.FromSeconds(30))
                {
                    record.Status = "unknown";
                    record.Error =
                        "NO_OPERATION_ELEMENTS_FOUND_AFTER_COMMITTING_STATE";
                    record.UpdatedAtUtc = DateTime.UtcNow.ToString("o");
                    WriteDrainageOperation(record);
                }
            }
            return record;
        }

        private static DrainageOperationRecord ReadDrainageOperation(string operationId)
        {
            string path = GetDrainageOperationPath(operationId);
            if (!File.Exists(path))
            {
                return null;
            }
            DrainageOperationRecord record = new JavaScriptSerializer()
                .Deserialize<DrainageOperationRecord>(
                    File.ReadAllText(path));
            return NormalizeDrainageOperationRecord(record);
        }

        private static DrainageOperationRecord
            NormalizeDrainageOperationRecord(
            DrainageOperationRecord record)
        {
            if (record == null)
            {
                return null;
            }
            bool legacy = !string.Equals(
                record.SchemaVersion,
                "sc.drainage.operation.v2",
                StringComparison.Ordinal);
            if (string.IsNullOrWhiteSpace(record.SchemaVersion))
            {
                record.SchemaVersion =
                    "sc.drainage.operation.v1";
            }
            record.DocumentTitle = record.DocumentTitle
                ?? (legacy ? "legacy-unavailable" : "");
            record.DocumentPathKind = record.DocumentPathKind
                ?? (legacy ? "legacy-unavailable" : "");
            record.DependencyHash = record.DependencyHash
                ?? (legacy ? "legacy-unavailable" : "");
            record.ConfirmationId = record.ConfirmationId
                ?? (legacy ? "legacy-unavailable" : "");
            record.ConfirmationActorKind =
                record.ConfirmationActorKind
                ?? (legacy ? "human" : "");
            record.InitiatorSurface = record.InitiatorSurface
                ?? record.ActorKind
                ?? (legacy ? "legacy-unavailable" : "");
            record.ToolContractVersion =
                record.ToolContractVersion
                ?? (legacy ? "legacy-1.0.0" : "");
            record.AssemblyModuleVersionId =
                record.AssemblyModuleVersionId
                ?? (legacy ? "legacy-unavailable" : "");
            record.AssemblySha256 = record.AssemblySha256
                ?? (legacy ? "legacy-unavailable" : "");
            record.RequestToolName = record.RequestToolName
                ?? (legacy ? "legacy-unavailable" : "");
            return record;
        }

        private static string ComputeDrainageAssemblySha256()
        {
            try
            {
                string path = typeof(RfaMetadataApplication)
                    .Assembly.Location;
                using (FileStream stream = File.OpenRead(path))
                using (SHA256 sha = SHA256.Create())
                {
                    return "sha256:" + BitConverter.ToString(
                        sha.ComputeHash(stream))
                        .Replace("-", "")
                        .ToLowerInvariant();
                }
            }
            catch
            {
                return "sha256:unavailable";
            }
        }

        private static void WriteDrainageOperation(DrainageOperationRecord record)
        {
            Directory.CreateDirectory(DrainageOperationDir);
            string path = GetDrainageOperationPath(record.OperationId);
            string temporaryPath = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            File.WriteAllText(
                temporaryPath,
                new JavaScriptSerializer().Serialize(record));
            if (File.Exists(path))
            {
                File.Replace(temporaryPath, path, null);
            }
            else
            {
                File.Move(temporaryPath, path);
            }
        }

        private static string GetDrainageOperationPath(string operationId)
        {
            return Path.Combine(DrainageOperationDir, operationId + ".json");
        }

        private static void ValidateDrainageOperationIdentity(
            string operationId,
            string idempotencyKey)
        {
            if (string.IsNullOrWhiteSpace(operationId)
                || !DrainageOperationIdPattern.IsMatch(operationId))
            {
                throw new InvalidOperationException("INVALID_OPERATION_ID");
            }
            if (string.IsNullOrWhiteSpace(idempotencyKey)
                || idempotencyKey.Length < 12
                || idempotencyKey.Length > 120)
            {
                throw new InvalidOperationException("INVALID_IDEMPOTENCY_KEY");
            }
        }
    }
}
