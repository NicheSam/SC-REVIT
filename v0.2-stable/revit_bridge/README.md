# Revit Bridge

這個模組負責在 Revit API 環境中讀取 `.rfa`，並把分類器需要的中繼資料輸出成 JSON。

## 預計輸出

```json
{
  "file_name": "Smoke Detector Ceiling.rfa",
  "family_name": "煙霧偵測器",
  "revit_category": "Fire Alarm Devices",
  "family_types": ["天花型"],
  "family_parameters": ["Manufacturer", "Model"]
}
```

## 模組邊界

- 只負責讀取，不負責分類
- 只輸出 JSON，不直接搬移檔案
- 由外部分類器呼叫

## 待接上的 Revit API 流程

1. 開啟 RFA
2. 確認 `Document.IsFamilyDocument`
3. 讀取 `OwnerFamily.FamilyCategory.Name`
4. 透過 `FamilyManager` 取得型別與參數
5. 輸出 JSON
