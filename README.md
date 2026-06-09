# SC REVIT

SC REVIT 是一套 Revit 族群管理與自動化工具，用於族群分類、族群庫驗證、專案族群回收與 Revit 輔助放置流程。

它由 Python 桌面 GUI 與 Revit add-in 組成。GUI 負責操作流程、規則判斷與結果整理；Revit add-in 負責透過 Revit API 讀取模型與族群資料。

## 解決的問題

Revit 族群庫在長期維護後常見以下問題：

- 族群來自不同專案、廠商或版本，資料夾分類不一致。
- Revit Category 不一定符合公司內部分類規則。
- 專案模型中有可回收的族群，但尚未納入正式庫。
- 公司標準參數難以一致套用。
- CAD 點位資料需要轉換成 Revit 放置流程。

SC REVIT 透過分類規則、人工複核與 Revit add-in queue 機制，協助建立更可維護的族群治理流程。

## 目前版本

| 版本 | 資料夾 | 狀態 |
| --- | --- | --- |
| v0.2-dev | `v0.2-dev/` | 開發中原型 |

## 主要功能

- 驗證 Revit 族群庫根目錄。
- 依 Revit category、族群名稱、型別名稱、檔名與規則權重分類 `.rfa`。
- 建議 HVAC、給排水、消防、電力、弱電、照明、建築、結構與製圖類族群路徑。
- 偵測重複族群名稱。
- 預覽公司標準參數。
- 掃描 Revit 專案內族群，支援回收流程。
- 支援批量點位放置、消防支管與開孔定位等原型流程。
- 透過 queue 機制與 Revit add-in 溝通。

## 專案結構

```text
SC REVIT/
  v0.2-dev/
    gui_app.py
    classifier.py
    rules.json
    parameter_templates/
    revit_addin/
    revit_bridge/
    docs/
```

## 開始使用

請閱讀 [v0.2-dev/README.md](v0.2-dev/README.md)，裡面包含環境需求、Revit add-in 建置方式、GUI 模式與使用範例。

## 狀態

本專案仍在開發中。請先用測試族群與備份模型驗證，再套用到正式 Revit 內容。

