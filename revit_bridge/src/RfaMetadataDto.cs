using System.Collections.Generic;

namespace RfaMetadataBridge
{
    public sealed class RfaMetadataDto
    {
        public string file_name { get; set; }
        public string family_name { get; set; }
        public string revit_category { get; set; }
        public List<string> family_types { get; set; }
        public List<string> family_parameters { get; set; }

        public RfaMetadataDto()
        {
            file_name = "";
            family_name = "";
            revit_category = "";
            family_types = new List<string>();
            family_parameters = new List<string>();
        }
    }
}
