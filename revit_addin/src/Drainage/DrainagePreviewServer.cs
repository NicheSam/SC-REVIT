using Autodesk.Revit.DB;
using Autodesk.Revit.DB.DirectContext3D;
using Autodesk.Revit.DB.ExternalService;
using System;
using System.Collections.Generic;
using System.Linq;

namespace RfaMetadataAddin
{
    internal sealed class DrainagePreviewSegment
    {
        public XYZ Start { get; set; }
        public XYZ End { get; set; }
        public bool IsBlocked { get; set; }
        public string Kind { get; set; }
    }

    internal sealed class DrainagePreviewServer : IDirectContext3DServer
    {
        private static readonly TimeSpan PreviewLifetime = TimeSpan.FromMinutes(5);
        private static readonly Guid ServerId =
            new Guid("c274c85d-1917-42c4-9e4a-2b5c9c7c0703");
        private static readonly object SyncRoot = new object();
        private static readonly Dictionary<int, List<DrainagePreviewSegment>> SegmentsByDocument =
            new Dictionary<int, List<DrainagePreviewSegment>>();
        private static readonly Dictionary<int, string> SnapshotByDocument =
            new Dictionary<int, string>();
        private static readonly Dictionary<int, List<DrainagePreviewSegment>> CadPointSegmentsByDocument =
            new Dictionary<int, List<DrainagePreviewSegment>>();
        private static readonly Dictionary<int, string> CadPointSnapshotByDocument =
            new Dictionary<int, string>();
        private static readonly Dictionary<int, DateTime> PreviewExpiresByDocument =
            new Dictionary<int, DateTime>();

        public static void Register()
        {
            MultiServerService service = ExternalServiceRegistry.GetService(
                ExternalServices.BuiltInExternalServices.DirectContext3DService)
                as MultiServerService;
            if (service == null)
            {
                return;
            }
            if (!service.IsRegisteredServerId(ServerId))
            {
                service.AddServer(new DrainagePreviewServer());
            }
            IList<Guid> active = service.GetActiveServerIds();
            if (!active.Contains(ServerId))
            {
                var updated = active.ToList();
                updated.Add(ServerId);
                service.SetActiveServers(updated);
            }
        }

        public static bool IsRegisteredAndActive()
        {
            MultiServerService service = ExternalServiceRegistry.GetService(
                ExternalServices.BuiltInExternalServices.DirectContext3DService)
                as MultiServerService;
            return service != null
                && service.IsRegisteredServerId(ServerId)
                && service.GetActiveServerIds().Contains(ServerId);
        }

        public static void Unregister()
        {
            MultiServerService service = ExternalServiceRegistry.GetService(
                ExternalServices.BuiltInExternalServices.DirectContext3DService)
                as MultiServerService;
            if (service != null && service.IsRegisteredServerId(ServerId))
            {
                service.RemoveServer(ServerId);
            }
            lock (SyncRoot)
            {
                SegmentsByDocument.Clear();
                SnapshotByDocument.Clear();
                CadPointSegmentsByDocument.Clear();
                CadPointSnapshotByDocument.Clear();
                PreviewExpiresByDocument.Clear();
            }
        }

        public static void SetSegments(
            Document document,
            string snapshotId,
            IEnumerable<DrainagePreviewSegment> segments)
        {
            lock (SyncRoot)
            {
                int documentKey = document.GetHashCode();
                CadPointSegmentsByDocument.Remove(documentKey);
                CadPointSnapshotByDocument.Remove(documentKey);
                SegmentsByDocument[documentKey] = segments.ToList();
                SnapshotByDocument[documentKey] = snapshotId;
                PreviewExpiresByDocument[documentKey] = DateTime.UtcNow.Add(PreviewLifetime);
            }
        }

        public static bool Clear(Document document, string snapshotId)
        {
            lock (SyncRoot)
            {
                int documentKey = document.GetHashCode();
                string activeSnapshotId;
                if (!SnapshotByDocument.TryGetValue(
                    documentKey,
                    out activeSnapshotId)
                    || !string.Equals(
                        activeSnapshotId,
                        snapshotId,
                        StringComparison.Ordinal))
                {
                    return false;
                }
                SegmentsByDocument.Remove(documentKey);
                SnapshotByDocument.Remove(documentKey);
                PreviewExpiresByDocument.Remove(documentKey);
                return true;
            }
        }

        public static void Clear(Document document)
        {
            lock (SyncRoot)
            {
                int documentKey = document.GetHashCode();
                SegmentsByDocument.Remove(documentKey);
                SnapshotByDocument.Remove(documentKey);
                PreviewExpiresByDocument.Remove(documentKey);
            }
        }

        public static void SetCadPointMarkers(
            Document document,
            string snapshotId,
            IEnumerable<XYZ> centers,
            double radius)
        {
            lock (SyncRoot)
            {
                int documentKey = document.GetHashCode();
                XYZ diagonalA = (XYZ.BasisX + XYZ.BasisY).Normalize();
                XYZ diagonalB = (XYZ.BasisX - XYZ.BasisY).Normalize();
                XYZ[] markerDirections =
                {
                    XYZ.BasisX,
                    XYZ.BasisY,
                    diagonalA,
                    diagonalB
                };
                var previewSegments = new List<DrainagePreviewSegment>();
                foreach (XYZ center in centers)
                {
                    foreach (XYZ direction in markerDirections)
                    {
                        previewSegments.Add(new DrainagePreviewSegment
                        {
                            Start = center - (direction * radius),
                            End = center + (direction * radius),
                            Kind = "cad_point_preview"
                        });
                    }
                }
                SegmentsByDocument.Remove(documentKey);
                SnapshotByDocument.Remove(documentKey);
                CadPointSegmentsByDocument[documentKey] = previewSegments;
                CadPointSnapshotByDocument[documentKey] = snapshotId;
                PreviewExpiresByDocument[documentKey] = DateTime.UtcNow.Add(PreviewLifetime);
            }
        }

        public static bool ClearCadPointMarkers(Document document)
        {
            lock (SyncRoot)
            {
                int documentKey = document.GetHashCode();
                bool removed = CadPointSegmentsByDocument.Remove(documentKey);
                CadPointSnapshotByDocument.Remove(documentKey);
                PreviewExpiresByDocument.Remove(documentKey);
                return removed;
            }
        }

        public Guid GetServerId()
        {
            return ServerId;
        }

        public ExternalServiceId GetServiceId()
        {
            return ExternalServices.BuiltInExternalServices.DirectContext3DService;
        }

        public string GetName()
        {
            return "SC Drainage Route Preview";
        }

        public string GetVendorId()
        {
            return "SC";
        }

        public string GetDescription()
        {
            return "Draws non-model drainage route candidates in the active Revit view.";
        }

        public string GetApplicationId()
        {
            return "SC_REVIT_DRAINAGE";
        }

        public string GetSourceId()
        {
            return ServerId.ToString("D");
        }

        public bool UsesHandles()
        {
            return false;
        }

        public bool CanExecute(View view)
        {
            if (view == null || view.Document == null)
            {
                return false;
            }
            lock (SyncRoot)
            {
                List<DrainagePreviewSegment> segments;
                int documentKey = view.Document.GetHashCode();
                PruneExpiredLocked(documentKey);
                List<DrainagePreviewSegment> markerSegments;
                return (SegmentsByDocument.TryGetValue(documentKey, out segments)
                        && segments.Count > 0)
                    || (CadPointSegmentsByDocument.TryGetValue(documentKey, out markerSegments)
                        && markerSegments.Count > 0);
            }
        }

        public Outline GetBoundingBox(View view)
        {
            List<DrainagePreviewSegment> segments = GetSegments(view);
            segments.AddRange(GetCadPointSegments(view));
            if (segments.Count == 0)
            {
                return null;
            }
            IEnumerable<XYZ> points = segments.SelectMany(
                item => new[] { item.Start, item.End });
            return new Outline(
                new XYZ(
                    points.Min(point => point.X),
                    points.Min(point => point.Y),
                    points.Min(point => point.Z)),
                new XYZ(
                    points.Max(point => point.X),
                    points.Max(point => point.Y),
                    points.Max(point => point.Z)));
        }

        public bool UseInTransparentPass(View view)
        {
            return false;
        }

        public void RenderScene(View view, DisplayStyle displayStyle)
        {
            List<DrainagePreviewSegment> segments = GetSegments(view);
            segments.AddRange(GetCadPointSegments(view));
            if (segments.Count == 0)
            {
                return;
            }
            const int verticesPerSegment = 2;
            int vertexCount = segments.Count * verticesPerSegment;
            int indexCount = segments.Count * 2;
            using (var vertexBuffer = new VertexBuffer(
                vertexCount * VertexPositionColored.GetSizeInFloats()))
            using (var indexBuffer = new IndexBuffer(
                indexCount * IndexLine.GetSizeInShortInts()))
            using (var vertexFormat = new VertexFormat(VertexFormatBits.PositionColored))
            using (var effect = new EffectInstance(VertexFormatBits.PositionColored))
            {
                vertexBuffer.Map(vertexCount * VertexPositionColored.GetSizeInFloats());
                VertexStreamPositionColored vertexStream =
                    vertexBuffer.GetVertexStreamPositionColored();
                foreach (DrainagePreviewSegment segment in segments)
                {
                    ColorWithTransparency color;
                    if (segment.IsBlocked)
                    {
                        color = new ColorWithTransparency(220, 50, 47, 0);
                    }
                    else if (segment.Kind == "main_downstream")
                    {
                        color = new ColorWithTransparency(42, 161, 152, 0);
                    }
                    else if (segment.Kind == "junction")
                    {
                        color = new ColorWithTransparency(203, 75, 22, 0);
                    }
                    else if (segment.Kind == "cad_point_preview")
                    {
                        color = new ColorWithTransparency(0, 255, 80, 0);
                    }
                    else if (segment.Kind == "fire_branch_preview")
                    {
                        color = new ColorWithTransparency(0, 255, 255, 0);
                    }
                    else
                    {
                        color = new ColorWithTransparency(38, 139, 210, 0);
                    }
                    vertexStream.AddVertex(
                        new VertexPositionColored(segment.Start, color));
                    vertexStream.AddVertex(
                        new VertexPositionColored(segment.End, color));
                }
                vertexBuffer.Unmap();

                indexBuffer.Map(indexCount * IndexLine.GetSizeInShortInts());
                IndexStreamLine indexStream = indexBuffer.GetIndexStreamLine();
                for (int index = 0; index < segments.Count; index++)
                {
                    indexStream.AddLine(new IndexLine(index * 2, index * 2 + 1));
                }
                indexBuffer.Unmap();
                DrawContext.FlushBuffer(
                    vertexBuffer,
                    vertexCount,
                    indexBuffer,
                    indexCount,
                    vertexFormat,
                    effect,
                    PrimitiveType.LineList,
                    0,
                    segments.Count);
            }
        }

        private static void PruneExpiredLocked(int documentKey)
        {
            DateTime expiresUtc;
            if (PreviewExpiresByDocument.TryGetValue(documentKey, out expiresUtc)
                && DateTime.UtcNow >= expiresUtc)
            {
                SegmentsByDocument.Remove(documentKey);
                SnapshotByDocument.Remove(documentKey);
                CadPointSegmentsByDocument.Remove(documentKey);
                CadPointSnapshotByDocument.Remove(documentKey);
                PreviewExpiresByDocument.Remove(documentKey);
            }
        }

        private static List<DrainagePreviewSegment> GetSegments(View view)
        {
            lock (SyncRoot)
            {
                List<DrainagePreviewSegment> segments;
                if (view == null || view.Document == null)
                {
                    return new List<DrainagePreviewSegment>();
                }
                int documentKey = view.Document.GetHashCode();
                PruneExpiredLocked(documentKey);
                return SegmentsByDocument.TryGetValue(documentKey, out segments)
                    ? segments.ToList()
                    : new List<DrainagePreviewSegment>();
            }
        }

        private static List<DrainagePreviewSegment> GetCadPointSegments(View view)
        {
            lock (SyncRoot)
            {
                List<DrainagePreviewSegment> segments;
                if (view == null || view.Document == null)
                {
                    return new List<DrainagePreviewSegment>();
                }
                int documentKey = view.Document.GetHashCode();
                PruneExpiredLocked(documentKey);
                return CadPointSegmentsByDocument.TryGetValue(documentKey, out segments)
                    ? segments.ToList()
                    : new List<DrainagePreviewSegment>();
            }
        }
    }
}
