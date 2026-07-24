using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Events;
using Autodesk.Revit.UI;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

namespace RfaMetadataAddin
{
    public partial class RfaMetadataApplication
    {
        private static readonly object DrainageDocumentStateLock = new object();
        private static readonly Dictionary<int, long> DrainageDocumentRevisions =
            new Dictionary<int, long>();
        private static readonly Dictionary<int, string> DrainageUnsavedDocumentNonces =
            new Dictionary<int, string>();
        private static readonly Dictionary<string, DrainageCandidateSetGrant>
            DrainageCandidateSetGrants =
                new Dictionary<string, DrainageCandidateSetGrant>(
                    StringComparer.Ordinal);

        private class DrainageCandidateSetGrant
        {
            public string Token { get; set; }
            public int DocumentKey { get; set; }
            public string DocumentFingerprint { get; set; }
            public long DocumentRevision { get; set; }
            public DateTime ExpiresUtc { get; set; }
            public int MainCandidateCount { get; set; }
            public HashSet<string> PipeKeys { get; set; }
            public HashSet<string> FixtureKeys { get; set; }
        }

        private class DrainageDocumentBinding
        {
            public string Title { get; set; }
            public string PathKind { get; set; }
            public bool IsWorkshared { get; set; }
            public bool IsReadOnly { get; set; }
            public string RevitVersion { get; set; }
            public string Fingerprint { get; set; }
            public long Revision { get; set; }
        }

        private static void InitializeDrainageDocumentState(UIControlledApplication application)
        {
            // DocumentChanged is read-only and fires after commit, undo, or redo.
            // Source: https://help.autodesk.com/cloudhelp/2024/PTB/Revit-API/files/Revit_API_Developers_Guide/Advanced_Topics/Events/Database_Events/Revit_API_Revit_API_Developers_Guide_Advanced_Topics_Events_Database_Events_DocumentChanged_event_html.html
            application.ControlledApplication.DocumentChanged += OnDrainageDocumentChanged;
            application.ControlledApplication.DocumentClosing +=
                OnDrainageDocumentClosing;
        }

        private static void ShutdownDrainageDocumentState(UIControlledApplication application)
        {
            application.ControlledApplication.DocumentChanged -= OnDrainageDocumentChanged;
            application.ControlledApplication.DocumentClosing -=
                OnDrainageDocumentClosing;
        }

        private static void OnDrainageDocumentChanged(
            object sender,
            DocumentChangedEventArgs args)
        {
            Document document = args.GetDocument();
            if (document == null)
            {
                return;
            }
            int key = document.GetHashCode();
            lock (DrainageDocumentStateLock)
            {
                long revision;
                DrainageDocumentRevisions.TryGetValue(key, out revision);
                DrainageDocumentRevisions[key] = revision + 1;
                RemoveDrainageCandidateSetGrantsForDocument(key);
            }
            DrainagePreviewServer.Clear(document);
        }

        private static void OnDrainageDocumentClosing(
            object sender,
            DocumentClosingEventArgs args)
        {
            Document document = args.Document;
            if (document == null)
            {
                return;
            }
            DrainagePreviewServer.Clear(document);
            ClearDrainageSnapshotsForDocument(document);
            int key = document.GetHashCode();
            lock (DrainageDocumentStateLock)
            {
                DrainageDocumentRevisions.Remove(key);
                DrainageUnsavedDocumentNonces.Remove(key);
                RemoveDrainageCandidateSetGrantsForDocument(key);
            }
        }

        private static DrainageCandidateSetGrant
            IssueDrainageCandidateSetGrant(
                Document document,
                IList<Element> pipes,
                IList<Element> fixtures,
                int mainCandidateCount)
        {
            DrainageDocumentBinding binding =
                GetDrainageDocumentBinding(document);
            DateTime now = DateTime.UtcNow;
            var grant = new DrainageCandidateSetGrant
            {
                Token = "DCT-" + Guid.NewGuid().ToString("N"),
                DocumentKey = document.GetHashCode(),
                DocumentFingerprint = binding.Fingerprint,
                DocumentRevision = binding.Revision,
                ExpiresUtc = now.AddMinutes(10),
                MainCandidateCount = mainCandidateCount,
                PipeKeys = new HashSet<string>(
                    (pipes ?? new List<Element>())
                        .Where(item => item != null)
                        .Select(GetDrainageCandidateElementKey),
                    StringComparer.Ordinal),
                FixtureKeys = new HashSet<string>(
                    (fixtures ?? new List<Element>())
                        .Where(item => item != null)
                        .Select(GetDrainageCandidateElementKey),
                    StringComparer.Ordinal)
            };
            lock (DrainageDocumentStateLock)
            {
                RemoveExpiredDrainageCandidateSetGrants(now);
                DrainageCandidateSetGrants[grant.Token] = grant;
            }
            return grant;
        }

        private static void RequireDrainageCandidateSetGrant(
            Document document,
            string token,
            Element mainPipe,
            IList<Element> fixtures)
        {
            if (string.IsNullOrWhiteSpace(token))
            {
                throw new InvalidOperationException(
                    "CANDIDATE_SET_TOKEN_REQUIRED");
            }
            DrainageCandidateSetGrant grant;
            lock (DrainageDocumentStateLock)
            {
                RemoveExpiredDrainageCandidateSetGrants(DateTime.UtcNow);
                if (!DrainageCandidateSetGrants.TryGetValue(
                    token,
                    out grant))
                {
                    throw new InvalidOperationException(
                        "CANDIDATE_SET_TOKEN_INVALID_OR_EXPIRED");
                }
            }
            DrainageDocumentBinding binding =
                GetDrainageDocumentBinding(document);
            if (grant.DocumentKey != document.GetHashCode()
                || !string.Equals(
                    grant.DocumentFingerprint,
                    binding.Fingerprint,
                    StringComparison.Ordinal)
                || grant.DocumentRevision != binding.Revision)
            {
                throw new InvalidOperationException(
                    "CANDIDATE_SET_DOCUMENT_MISMATCH");
            }
            if (mainPipe == null
                || grant.MainCandidateCount != 1
                || !grant.PipeKeys.Contains(
                    GetDrainageCandidateElementKey(mainPipe)))
            {
                throw new InvalidOperationException(
                    grant.MainCandidateCount != 1
                        ? "MAIN_CANDIDATE_NOT_UNIQUE"
                        : "MAIN_NOT_IN_CANDIDATE_SET");
            }
            foreach (Element fixture
                in fixtures ?? new List<Element>())
            {
                if (fixture == null
                    || !grant.FixtureKeys.Contains(
                        GetDrainageCandidateElementKey(fixture)))
                {
                    throw new InvalidOperationException(
                        "FIXTURE_NOT_IN_CANDIDATE_SET");
                }
            }
        }

        private static string GetDrainageCandidateElementKey(
            Element element)
        {
            return element.Id.Value
                + "|"
                + (element.UniqueId ?? "");
        }

        private static void RemoveExpiredDrainageCandidateSetGrants(
            DateTime now)
        {
            foreach (string token in DrainageCandidateSetGrants
                .Where(item => now > item.Value.ExpiresUtc)
                .Select(item => item.Key)
                .ToList())
            {
                DrainageCandidateSetGrants.Remove(token);
            }
        }

        private static void RemoveDrainageCandidateSetGrantsForDocument(
            int documentKey)
        {
            foreach (string token in DrainageCandidateSetGrants
                .Where(item => item.Value.DocumentKey == documentKey)
                .Select(item => item.Key)
                .ToList())
            {
                DrainageCandidateSetGrants.Remove(token);
            }
        }

        private static object SerializeDrainageDocumentRef(Document document)
        {
            DrainageDocumentBinding binding = GetDrainageDocumentBinding(document);
            return new
            {
                title = binding.Title,
                path_kind = binding.PathKind,
                is_workshared = binding.IsWorkshared,
                is_read_only = binding.IsReadOnly,
                revit_version = binding.RevitVersion,
                fingerprint = binding.Fingerprint,
                revision = binding.Revision
            };
        }

        private static DrainageDocumentBinding GetDrainageDocumentBinding(Document document)
        {
            string pathKind;
            string identity;
            ResolveDrainageDocumentIdentity(document, out pathKind, out identity);
            return new DrainageDocumentBinding
            {
                Title = document.Title,
                PathKind = pathKind,
                IsWorkshared = document.IsWorkshared,
                IsReadOnly = document.IsReadOnly,
                RevitVersion = document.Application.VersionNumber,
                Fingerprint = ComputeDrainageDocumentFingerprint(
                    document.Application.VersionNumber,
                    pathKind,
                    identity,
                    document.IsWorkshared),
                Revision = GetDrainageDocumentRevision(document)
            };
        }

        private static void RequireDrainageCommitDocumentPolicy(Document document)
        {
            DrainageDocumentBinding binding = GetDrainageDocumentBinding(document);
            if (binding.IsReadOnly)
            {
                throw new InvalidOperationException("DOCUMENT_READ_ONLY");
            }
            if (string.Equals(binding.PathKind, "unsaved", StringComparison.Ordinal))
            {
                throw new InvalidOperationException("UNSAVED_DOCUMENT_NOT_SUPPORTED");
            }
            if (binding.IsWorkshared
                || string.Equals(binding.PathKind, "cloud", StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "WORKSHARED_OR_CLOUD_COMMIT_NOT_SUPPORTED");
            }
        }

        private static long GetDrainageDocumentRevision(Document document)
        {
            int key = document.GetHashCode();
            lock (DrainageDocumentStateLock)
            {
                long revision;
                return DrainageDocumentRevisions.TryGetValue(key, out revision)
                    ? revision
                    : 0;
            }
        }

        private static void ResolveDrainageDocumentIdentity(
            Document document,
            out string pathKind,
            out string identity)
        {
            if (document.IsModelInCloud)
            {
                ModelPath cloudPath = document.GetCloudModelPath();
                pathKind = "cloud";
                identity = cloudPath.GetProjectGUID().ToString("D")
                    + "|"
                    + cloudPath.GetModelGUID().ToString("D");
                return;
            }
            if (document.IsWorkshared)
            {
                ModelPath centralPath = document.GetWorksharingCentralModelPath();
                pathKind = "workshared";
                identity = centralPath == null
                    ? document.PathName
                    : ModelPathUtils.ConvertModelPathToUserVisiblePath(centralPath);
                return;
            }
            if (!string.IsNullOrWhiteSpace(document.PathName))
            {
                pathKind = "local";
                identity = document.PathName;
                return;
            }

            pathKind = "unsaved";
            int key = document.GetHashCode();
            lock (DrainageDocumentStateLock)
            {
                string nonce;
                if (!DrainageUnsavedDocumentNonces.TryGetValue(key, out nonce))
                {
                    nonce = Guid.NewGuid().ToString("N");
                    DrainageUnsavedDocumentNonces[key] = nonce;
                }
                identity = nonce;
            }
        }

        private static string ComputeDrainageDocumentFingerprint(
            string revitVersion,
            string pathKind,
            string identity,
            bool isWorkshared)
        {
            string material = string.Join(
                "|",
                revitVersion ?? "",
                pathKind ?? "",
                (identity ?? "").Trim().ToUpperInvariant(),
                isWorkshared ? "workshared" : "standalone");
            using (SHA256 sha = SHA256.Create())
            {
                byte[] digest = sha.ComputeHash(Encoding.UTF8.GetBytes(material));
                return "sha256:" + BitConverter.ToString(digest).Replace("-", "").ToLowerInvariant();
            }
        }
    }
}
