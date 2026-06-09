# Revit Add-in

這個模組是真正讀取 `.rfa` 的 Revit 端橋接器，並在 Revit 啟動後常駐監聽佇列。

## 工作方式

1. Revit 啟動後載入 `RfaMetadataApplication`
2. 外部分類器把請求寫入 `runtime\queue\requests`
3. Add-in 在 `Idling` 事件中自動拾取請求
4. Add-in 使用 Revit API 開啟 RFA
5. 讀取：
   - `OwnerFamily.Name`
   - `OwnerFamily.FamilyCategory.Name`
   - `FamilyManager.Types`
   - `FamilyManager.Parameters`
6. 輸出 JSON 到 `runtime\queue\responses`

正式安裝時，`.addin` manifest 會由外部分類器依照當前電腦的實際路徑動態產生，不依賴固定磁碟位置。

## 官方 API 對應

- `Application.OpenDocumentFile(...)`
- `Document.IsFamilyDocument`
- `Document.OwnerFamily.FamilyCategory`
- `Document.FamilyManager`
