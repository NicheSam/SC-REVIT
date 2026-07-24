using Autodesk.Revit.DB;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

namespace RfaMetadataAddin
{
    public partial class RfaMetadataApplication
    {
        private class DrainageRouteSnapshot
        {
            public string SnapshotId { get; set; }
            public string SnapshotHash { get; set; }
            public DateTime CreatedUtc { get; set; }
            public DateTime ExpiresUtc { get; set; }
            public string DocumentFingerprint { get; set; }
            public long DocumentRevision { get; set; }
            public long MainPipeId { get; set; }
            public string MainPipeUniqueId { get; set; }
            public List<long> FixtureIds { get; set; }
            public Dictionary<long, string> FixtureUniqueIds { get; set; }
            public long PipeTypeId { get; set; }
            public string PipeTypeUniqueId { get; set; }
            public long SystemTypeId { get; set; }
            public string SystemTypeUniqueId { get; set; }
            public long LevelId { get; set; }
            public string LevelUniqueId { get; set; }
            public string DependencyHash { get; set; }
            public double SlopeRatio { get; set; }
            public double DiameterMm { get; set; }
            public string DownstreamMode { get; set; }
            public DrainageRoutingPart JunctionPart { get; set; }
            public DrainageRoutingPart ElbowPart { get; set; }
            public DrainageRoutePolicy RoutePolicy { get; set; }
            public List<DrainagePlan> Plans { get; set; }
        }

        private class DrainageConfirmation
        {
            public string ConfirmationId { get; set; }
            public string SnapshotHash { get; set; }
            public string ActorKind { get; set; }
            public DateTime ExpiresUtc { get; set; }
        }

        private static readonly object DrainageSnapshotLock = new object();
        private static readonly Dictionary<string, DrainageRouteSnapshot> DrainageSnapshots =
            new Dictionary<string, DrainageRouteSnapshot>(StringComparer.Ordinal);
        private static readonly Dictionary<string, DrainageConfirmation> DrainageConfirmations =
            new Dictionary<string, DrainageConfirmation>(StringComparer.Ordinal);

        private static DrainageRouteSnapshot CreateDrainageSnapshot(
            Document document,
            long mainPipeId,
            IEnumerable<long> fixtureIds,
            long pipeTypeId,
            long systemTypeId,
            long levelId,
            double slopeRatio,
            double diameterMm,
            string downstreamMode,
            DrainageRoutingPart junctionPart,
            DrainageRoutingPart elbowPart,
            DrainageRoutePolicy routePolicy,
            List<DrainagePlan> plans)
        {
            DrainageDocumentBinding binding = GetDrainageDocumentBinding(document);
            DateTime now = DateTime.UtcNow;
            var snapshot = new DrainageRouteSnapshot
            {
                SnapshotId = "DPS-" + Guid.NewGuid().ToString("N"),
                CreatedUtc = now,
                ExpiresUtc = now.AddMinutes(20),
                DocumentFingerprint = binding.Fingerprint,
                DocumentRevision = binding.Revision,
                MainPipeId = mainPipeId,
                MainPipeUniqueId = RequireDrainageUniqueId(document, mainPipeId),
                FixtureIds = fixtureIds.OrderBy(id => id).ToList(),
                FixtureUniqueIds = fixtureIds
                    .Distinct()
                    .ToDictionary(
                        id => id,
                        id => RequireDrainageUniqueId(document, id)),
                PipeTypeId = pipeTypeId,
                PipeTypeUniqueId = RequireDrainageUniqueId(document, pipeTypeId),
                SystemTypeId = systemTypeId,
                SystemTypeUniqueId = RequireDrainageUniqueId(document, systemTypeId),
                LevelId = levelId,
                LevelUniqueId = RequireDrainageUniqueId(document, levelId),
                SlopeRatio = slopeRatio,
                DiameterMm = diameterMm,
                DownstreamMode = downstreamMode ?? "auto",
                JunctionPart = junctionPart,
                ElbowPart = elbowPart,
                RoutePolicy = routePolicy,
                Plans = plans
            };
            snapshot.DependencyHash = ComputeDrainageDependencyHash(snapshot);
            snapshot.SnapshotHash = ComputeDrainageSnapshotHash(snapshot);
            lock (DrainageSnapshotLock)
            {
                RemoveExpiredDrainageSnapshots(now);
                DrainageSnapshots[snapshot.SnapshotId] = snapshot;
            }
            return snapshot;
        }

        private static DrainageRouteSnapshot RequireDrainageSnapshot(
            Document document,
            string snapshotId,
            string snapshotHash)
        {
            DrainageRouteSnapshot snapshot;
            lock (DrainageSnapshotLock)
            {
                RemoveExpiredDrainageSnapshots(DateTime.UtcNow);
                if (string.IsNullOrWhiteSpace(snapshotId)
                    || !DrainageSnapshots.TryGetValue(snapshotId, out snapshot))
                {
                    throw new InvalidOperationException("SNAPSHOT_NOT_FOUND");
                }
            }
            if (!string.Equals(snapshot.SnapshotHash, snapshotHash, StringComparison.Ordinal))
            {
                throw new InvalidOperationException("SNAPSHOT_HASH_MISMATCH");
            }
            DrainageDocumentBinding binding = GetDrainageDocumentBinding(document);
            if (!string.Equals(
                snapshot.DocumentFingerprint,
                binding.Fingerprint,
                StringComparison.Ordinal))
            {
                throw new InvalidOperationException("DOCUMENT_MISMATCH");
            }
            if (snapshot.DocumentRevision != binding.Revision)
            {
                throw new InvalidOperationException("STALE_SNAPSHOT");
            }
            RequireDrainageElementIdentity(
                document,
                snapshot.MainPipeId,
                snapshot.MainPipeUniqueId);
            RequireDrainageElementIdentity(
                document,
                snapshot.PipeTypeId,
                snapshot.PipeTypeUniqueId);
            RequireDrainageElementIdentity(
                document,
                snapshot.SystemTypeId,
                snapshot.SystemTypeUniqueId);
            RequireDrainageElementIdentity(
                document,
                snapshot.LevelId,
                snapshot.LevelUniqueId);
            foreach (KeyValuePair<long, string> fixture in snapshot.FixtureUniqueIds)
            {
                RequireDrainageElementIdentity(
                    document,
                    fixture.Key,
                    fixture.Value);
            }
            if (!string.Equals(
                snapshot.DependencyHash,
                ComputeDrainageDependencyHash(snapshot),
                StringComparison.Ordinal))
            {
                throw new InvalidOperationException("DEPENDENCY_HASH_MISMATCH");
            }
            if (DateTime.UtcNow > snapshot.ExpiresUtc)
            {
                throw new InvalidOperationException("SNAPSHOT_EXPIRED");
            }
            return snapshot;
        }

        private static DrainageConfirmation ConfirmDrainageSnapshot(
            DrainageRouteSnapshot snapshot,
            string actorKind)
        {
            if (snapshot == null)
            {
                throw new InvalidOperationException("SNAPSHOT_NOT_FOUND");
            }
            if (!string.Equals(
                actorKind,
                "human",
                StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("HUMAN_CONFIRMATION_REQUIRED");
            }
            var confirmation = new DrainageConfirmation
            {
                ConfirmationId = "DPC-" + Guid.NewGuid().ToString("N"),
                SnapshotHash = snapshot.SnapshotHash,
                ActorKind = "human",
                ExpiresUtc = DateTime.UtcNow.AddMinutes(5)
            };
            lock (DrainageSnapshotLock)
            {
                DrainageConfirmations[confirmation.ConfirmationId] = confirmation;
            }
            return confirmation;
        }

        private static DrainageConfirmation RequireDrainageConfirmation(
            DrainageRouteSnapshot snapshot,
            string confirmationId)
        {
            DrainageConfirmation confirmation;
            lock (DrainageSnapshotLock)
            {
                if (string.IsNullOrWhiteSpace(confirmationId)
                    || !DrainageConfirmations.TryGetValue(confirmationId, out confirmation))
                {
                    throw new InvalidOperationException("CONFIRMATION_REQUIRED");
                }
            }
            if (DateTime.UtcNow > confirmation.ExpiresUtc)
            {
                throw new InvalidOperationException("CONFIRMATION_EXPIRED");
            }
            if (!string.Equals(
                confirmation.SnapshotHash,
                snapshot.SnapshotHash,
                StringComparison.Ordinal))
            {
                throw new InvalidOperationException("CONFIRMATION_SNAPSHOT_MISMATCH");
            }
            if (!string.Equals(
                confirmation.ActorKind,
                "human",
                StringComparison.Ordinal))
            {
                throw new InvalidOperationException("HUMAN_CONFIRMATION_REQUIRED");
            }
            return confirmation;
        }

        private static string ComputeDrainageSnapshotHash(DrainageRouteSnapshot snapshot)
        {
            var material = new StringBuilder();
            material.Append(snapshot.DocumentFingerprint).Append('|');
            material.Append(snapshot.DocumentRevision).Append('|');
            material.Append(snapshot.DependencyHash).Append('|');
            material.Append(snapshot.MainPipeId).Append('|');
            material.Append(string.Join(",", snapshot.FixtureIds)).Append('|');
            material.Append(snapshot.PipeTypeId).Append('|');
            material.Append(snapshot.SystemTypeId).Append('|');
            material.Append(snapshot.LevelId).Append('|');
            material.Append(snapshot.SlopeRatio.ToString("R", CultureInfo.InvariantCulture)).Append('|');
            material.Append(snapshot.DiameterMm.ToString("R", CultureInfo.InvariantCulture)).Append('|');
            material.Append(snapshot.DownstreamMode).Append('|');
            material.Append(snapshot.JunctionPart == null ? 0 : snapshot.JunctionPart.PartId.Value).Append('|');
            material.Append(snapshot.ElbowPart == null ? 0 : snapshot.ElbowPart.PartId.Value).Append('|');
            AppendDrainageRoutePolicy(material, snapshot.RoutePolicy);
            foreach (DrainagePlan plan in snapshot.Plans.OrderBy(item => item.SourceElement.Id.Value))
            {
                material.Append(plan.SourceElement.Id.Value).Append(':');
                AppendDrainagePoint(material, plan.ConnectorPoint);
                AppendDrainagePoint(material, plan.ConnectorStubEnd);
                AppendDrainagePoint(material, plan.BranchStart);
                AppendDrainagePoint(material, plan.MainTie);
                material.Append(plan.RouteKind).Append(':');
                material.Append(plan.HasDoubleFortyFive).Append(':');
                material.Append(plan.StubTangentLength.HasValue
                    ? plan.StubTangentLength.Value.ToString(
                        "R",
                        CultureInfo.InvariantCulture)
                    : "").Append(':');
                material.Append(plan.MiddleTangentLength.HasValue
                    ? plan.MiddleTangentLength.Value.ToString(
                        "R",
                        CultureInfo.InvariantCulture)
                    : "").Append(':');
                material.Append(plan.BranchTangentLength.HasValue
                    ? plan.BranchTangentLength.Value.ToString(
                        "R",
                        CultureInfo.InvariantCulture)
                    : "").Append(':');
                material.Append(plan.FirstElbowAngleDegrees.ToString(
                    "R",
                    CultureInfo.InvariantCulture)).Append(':');
                material.Append(plan.SecondElbowAngleDegrees.ToString(
                    "R",
                    CultureInfo.InvariantCulture)).Append(':');
                material.Append(plan.MiddleLateralOffset.ToString(
                    "R",
                    CultureInfo.InvariantCulture)).Append(':');
                material.Append(plan.DownstreamEndpointIndex).Append(':');
                material.Append(string.Join(
                    ",",
                    plan.CollisionElementIds ?? new List<long>())).Append(':');
                material.Append(string.Join(",", plan.Issues ?? new List<string>())).Append('|');
            }
            using (SHA256 sha = SHA256.Create())
            {
                byte[] digest = sha.ComputeHash(Encoding.UTF8.GetBytes(material.ToString()));
                return "sha256:" + BitConverter.ToString(digest).Replace("-", "").ToLowerInvariant();
            }
        }

        private static string ComputeDrainageDependencyHash(
            DrainageRouteSnapshot snapshot)
        {
            var material = new StringBuilder();
            material.Append(snapshot.MainPipeUniqueId).Append('|');
            material.Append(snapshot.PipeTypeUniqueId).Append('|');
            material.Append(snapshot.SystemTypeUniqueId).Append('|');
            material.Append(snapshot.LevelUniqueId).Append('|');
            foreach (KeyValuePair<long, string> fixture in
                snapshot.FixtureUniqueIds.OrderBy(item => item.Key))
            {
                material.Append(fixture.Key).Append('=').Append(fixture.Value).Append('|');
            }
            AppendDrainageRoutingPart(material, snapshot.JunctionPart);
            AppendDrainageRoutingPart(material, snapshot.ElbowPart);
            foreach (DrainagePlan plan in snapshot.Plans.OrderBy(
                item => item.SourceElement.Id.Value))
            {
                material.Append(plan.SourceElement.Id.Value).Append(':');
                AppendDrainagePoint(material, plan.ConnectorPoint);
                AppendDrainagePoint(material, plan.ConnectorAxis);
                material.Append(plan.FixtureConnector.IsConnected).Append(':');
                material.Append(plan.OutletOrientation).Append(':');
                material.Append(plan.DownstreamResolution).Append(':');
                material.Append(plan.SideEntryAngleDegrees.ToString(
                    "R",
                    CultureInfo.InvariantCulture)).Append(':');
                material.Append(plan.RadialEntryAngleDegrees.ToString(
                    "R",
                    CultureInfo.InvariantCulture)).Append('|');
            }
            using (SHA256 sha = SHA256.Create())
            {
                byte[] digest = sha.ComputeHash(
                    Encoding.UTF8.GetBytes(material.ToString()));
                return "sha256:"
                    + BitConverter.ToString(digest).Replace("-", "").ToLowerInvariant();
            }
        }

        private static void AppendDrainageRoutingPart(
            StringBuilder material,
            DrainageRoutingPart part)
        {
            if (part == null)
            {
                material.Append("missing|");
                return;
            }
            material.Append(part.PartId.Value).Append(':');
            material.Append(part.PartUniqueId).Append(':');
            material.Append(part.FamilyName).Append(':');
            material.Append(part.Name).Append(':');
            material.Append(part.RuleOrder).Append(':');
            material.Append(part.MeasuredTakeoutMm.HasValue
                ? part.MeasuredTakeoutMm.Value.ToString(
                    "R",
                    CultureInfo.InvariantCulture)
                : "unresolved").Append(':');
            material.Append(part.MeasuredRunTakeoutMm.HasValue
                ? part.MeasuredRunTakeoutMm.Value.ToString(
                    "R",
                    CultureInfo.InvariantCulture)
                : "unresolved").Append(':');
            material.Append(part.TakeoutEvidenceElementId.HasValue
                ? part.TakeoutEvidenceElementId.Value
                : 0).Append(':');
            material.Append(part.TakeoutGeometryHash).Append('|');
        }

        private static void AppendDrainageRoutePolicy(
            StringBuilder material,
            DrainageRoutePolicy policy)
        {
            if (policy == null)
            {
                material.Append("missing-policy|");
                return;
            }
            material.Append(policy.PolicyId).Append(':');
            material.Append(policy.PolicyVersion).Append(':');
            material.Append(policy.SideEntryAngleDegrees.ToString("R", CultureInfo.InvariantCulture)).Append(':');
            material.Append(policy.SideEntryToleranceDegrees.ToString("R", CultureInfo.InvariantCulture)).Append(':');
            material.Append(policy.RadialMinimumDegrees.ToString("R", CultureInfo.InvariantCulture)).Append(':');
            material.Append(policy.RadialMaximumDegrees.ToString("R", CultureInfo.InvariantCulture)).Append(':');
            material.Append(policy.RadialToleranceDegrees.ToString("R", CultureInfo.InvariantCulture)).Append(':');
            material.Append(policy.MinimumTangentMm.ToString("R", CultureInfo.InvariantCulture)).Append(':');
            material.Append(policy.MinimumJunctionSpacingMm.ToString("R", CultureInfo.InvariantCulture)).Append(':');
            material.Append(policy.CollisionClearanceMm.ToString("R", CultureInfo.InvariantCulture)).Append(':');
            material.Append(policy.MaximumDouble45LateralOffsetMm.ToString("R", CultureInfo.InvariantCulture)).Append('|');
        }

        private static string RequireDrainageUniqueId(
            Document document,
            long elementId)
        {
            Element element = document.GetElement(new ElementId(elementId));
            if (element == null)
            {
                throw new InvalidOperationException(
                    "DEPENDENCY_ELEMENT_NOT_FOUND:" + elementId);
            }
            return element.UniqueId;
        }

        private static void RequireDrainageElementIdentity(
            Document document,
            long elementId,
            string expectedUniqueId)
        {
            Element element = document.GetElement(new ElementId(elementId));
            if (element == null
                || !string.Equals(
                    element.UniqueId,
                    expectedUniqueId,
                    StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "DEPENDENCY_IDENTITY_MISMATCH:" + elementId);
            }
        }

        private static void AppendDrainagePoint(StringBuilder material, XYZ point)
        {
            XYZ value = point ?? XYZ.Zero;
            material.Append(value.X.ToString("R", CultureInfo.InvariantCulture)).Append(',');
            material.Append(value.Y.ToString("R", CultureInfo.InvariantCulture)).Append(',');
            material.Append(value.Z.ToString("R", CultureInfo.InvariantCulture)).Append(';');
        }

        private static void RemoveExpiredDrainageSnapshots(DateTime now)
        {
            foreach (string key in DrainageSnapshots
                .Where(item => now > item.Value.ExpiresUtc)
                .Select(item => item.Key)
                .ToList())
            {
                DrainageSnapshots.Remove(key);
            }
            foreach (string key in DrainageConfirmations
                .Where(item => now > item.Value.ExpiresUtc)
                .Select(item => item.Key)
                .ToList())
            {
                DrainageConfirmations.Remove(key);
            }
        }

        private static void ClearDrainageSnapshotsForDocument(Document document)
        {
            string fingerprint = GetDrainageDocumentBinding(document).Fingerprint;
            lock (DrainageSnapshotLock)
            {
                var removedHashes = new HashSet<string>(
                    DrainageSnapshots
                        .Where(item => string.Equals(
                            item.Value.DocumentFingerprint,
                            fingerprint,
                            StringComparison.Ordinal))
                        .Select(item => item.Value.SnapshotHash));
                foreach (string key in DrainageSnapshots
                    .Where(item => removedHashes.Contains(item.Value.SnapshotHash))
                    .Select(item => item.Key)
                    .ToList())
                {
                    DrainageSnapshots.Remove(key);
                }
                foreach (string key in DrainageConfirmations
                    .Where(item => removedHashes.Contains(item.Value.SnapshotHash))
                    .Select(item => item.Key)
                    .ToList())
                {
                    DrainageConfirmations.Remove(key);
                }
            }
        }

        private static DrainageRouteSnapshot RequireDrainageSnapshotForClear(
            Document document,
            string snapshotId,
            string snapshotHash,
            string expectedDocumentFingerprint,
            long expectedDocumentRevision)
        {
            DrainageRouteSnapshot snapshot;
            lock (DrainageSnapshotLock)
            {
                RemoveExpiredDrainageSnapshots(DateTime.UtcNow);
                if (string.IsNullOrWhiteSpace(snapshotId)
                    || !DrainageSnapshots.TryGetValue(
                        snapshotId,
                        out snapshot))
                {
                    throw new InvalidOperationException(
                        "SNAPSHOT_NOT_FOUND");
                }
            }
            if (!string.Equals(
                snapshot.SnapshotHash,
                snapshotHash,
                StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "SNAPSHOT_HASH_MISMATCH");
            }
            string fingerprint =
                GetDrainageDocumentBinding(document).Fingerprint;
            if (string.IsNullOrWhiteSpace(
                    expectedDocumentFingerprint)
                || !string.Equals(
                    expectedDocumentFingerprint,
                    snapshot.DocumentFingerprint,
                    StringComparison.Ordinal)
                || !string.Equals(
                    expectedDocumentFingerprint,
                    fingerprint,
                    StringComparison.Ordinal)
                || !string.Equals(
                snapshot.DocumentFingerprint,
                fingerprint,
                StringComparison.Ordinal))
            {
                throw new InvalidOperationException("DOCUMENT_MISMATCH");
            }
            if (snapshot.DocumentRevision != expectedDocumentRevision)
            {
                throw new InvalidOperationException(
                    "SNAPSHOT_DOCUMENT_REVISION_MISMATCH");
            }
            return snapshot;
        }

        private static void RemoveDrainageSnapshot(
            string snapshotId,
            string snapshotHash)
        {
            lock (DrainageSnapshotLock)
            {
                DrainageSnapshots.Remove(snapshotId);
                foreach (string key in DrainageConfirmations
                    .Where(item => string.Equals(
                        item.Value.SnapshotHash,
                        snapshotHash,
                        StringComparison.Ordinal))
                    .Select(item => item.Key)
                    .ToList())
                {
                    DrainageConfirmations.Remove(key);
                }
            }
        }

        private static string ReadDrainageString(
            Dictionary<string, object> payload,
            string key)
        {
            return payload != null
                && payload.ContainsKey(key)
                && payload[key] != null
                ? payload[key].ToString()
                : "";
        }
    }
}
