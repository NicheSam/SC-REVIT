using System;
using System.Collections.Generic;
using System.IO;
using System.Web.Script.Serialization;

namespace RfaMetadataBridge
{
    internal static class Program
    {
        private static int Main(string[] args)
        {
            if (args.Length != 1)
            {
                Console.Error.WriteLine("請提供一個 RFA 檔案路徑");
                return 1;
            }

            string path = args[0];
            if (!File.Exists(path))
            {
                Console.Error.WriteLine("指定的 RFA 檔案不存在");
                return 1;
            }

            if (!string.Equals(Path.GetExtension(path), ".rfa", StringComparison.OrdinalIgnoreCase))
            {
                Console.Error.WriteLine("指定檔案不是 .rfa");
                return 1;
            }

            // 這裡先保留橋接器的輸出契約；
            // 真正的 Revit API 讀取會在下一步接上。
            var payload = new RfaMetadataDto
            {
                file_name = Path.GetFileName(path),
                family_name = Path.GetFileNameWithoutExtension(path),
                revit_category = "",
                family_types = new List<string>(),
                family_parameters = new List<string>()
            };

            Console.OutputEncoding = System.Text.Encoding.UTF8;
            Console.WriteLine(new JavaScriptSerializer().Serialize(payload));
            return 0;
        }
    }
}
