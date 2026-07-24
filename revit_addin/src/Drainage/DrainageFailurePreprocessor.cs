using Autodesk.Revit.DB;
using System.Collections.Generic;
using System.Linq;

namespace RfaMetadataAddin
{
    internal sealed class DrainageFailurePreprocessor : IFailuresPreprocessor
    {
        private readonly List<string> _failures = new List<string>();

        public IList<string> Failures
        {
            get { return _failures.AsReadOnly(); }
        }

        public FailureProcessingResult PreprocessFailures(
            FailuresAccessor failuresAccessor)
        {
            IList<FailureMessageAccessor> messages =
                failuresAccessor.GetFailureMessages();
            foreach (FailureMessageAccessor message in messages)
            {
                _failures.Add(
                    message.GetFailureDefinitionId().Guid.ToString("D")
                    + ": "
                    + message.GetDescriptionText());
            }
            return messages.Count == 0
                ? FailureProcessingResult.Continue
                : FailureProcessingResult.ProceedWithRollBack;
        }

        public string Summarize()
        {
            return string.Join(" | ", _failures.Distinct());
        }
    }
}
