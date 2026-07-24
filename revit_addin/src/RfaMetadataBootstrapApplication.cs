using Autodesk.Revit.UI;
using System;
using System.IO;
using System.Text;

namespace RfaMetadataAddin
{
    public sealed class RfaMetadataBootstrapApplication : IExternalApplication
    {
        private IExternalApplication _inner;

        public Result OnStartup(UIControlledApplication application)
        {
            try
            {
                DeletePreviousFault();
                _inner = new RfaMetadataApplication();
                Result result = _inner.OnStartup(application);
                if (result != Result.Succeeded)
                {
                    WriteFault(
                        "inner_startup_returned_" + result);
                }
                return result;
            }
            catch (Exception ex)
            {
                WriteFault("bootstrap_exception\r\n" + ex);
                return Result.Failed;
            }
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            if (_inner == null)
            {
                return Result.Succeeded;
            }
            try
            {
                return _inner.OnShutdown(application);
            }
            catch (Exception ex)
            {
                WriteFault("bootstrap_shutdown_exception\r\n" + ex);
                return Result.Failed;
            }
        }

        private static void WriteFault(string message)
        {
            try
            {
                string directory = Path.Combine(
                    Environment.GetFolderPath(
                        Environment.SpecialFolder.LocalApplicationData),
                    "RevitFamilyClassifier",
                    "runtime",
                    "queue",
                    "errors");
                Directory.CreateDirectory(directory);
                File.WriteAllText(
                    Path.Combine(directory, "bootstrap_fault.txt"),
                    message ?? "",
                    Encoding.UTF8);
            }
            catch
            {
                // Do not mask the original startup failure.
            }
        }

        private static void DeletePreviousFault()
        {
            try
            {
                string directory = Path.Combine(
                    Environment.GetFolderPath(
                        Environment.SpecialFolder.LocalApplicationData),
                    "RevitFamilyClassifier",
                    "runtime",
                    "queue",
                    "errors");
                foreach (string name in new[]
                {
                    "bootstrap_fault.txt",
                    "startup_fault.txt",
                    "startup_fault.json"
                })
                {
                    string path = Path.Combine(directory, name);
                    if (File.Exists(path))
                    {
                        File.Delete(path);
                    }
                }
            }
            catch
            {
                // A stale diagnostic must not block startup.
            }
        }
    }
}
