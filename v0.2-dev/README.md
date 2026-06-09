# SC REVIT v0.2-dev

`v0.2-dev` 是一個 Revit 族群庫分類、專案族群回收與 Revit 輔助放置流程的開發中原型。

## 適合誰使用

本專案適合以下角色：

- BIM 管理者
- Revit 自動化開發者
- 機電 BIM 協調人員
- 公司內部工具開發者
- 需要維護 Revit 族群庫與專案族群品質的團隊

## 架構

SC REVIT 分成兩個部分：

```text
Python GUI
  -> 建立流程 request
  -> 寫入 queue 檔案

Revit Add-in
  -> 監聽 queue request
  -> 使用 Revit API
  -> 寫入 response 檔案

Python GUI
  -> 讀取 response
  -> 分類、顯示、匯出或進入下一步流程
```

執行時產生的 queue 資料不包含在原始碼版本中。

## GUI 模式

`gui_app.py` 支援多種模式：

| 模式 | 指令 | 用途 |
| --- | --- | --- |
| 族群歸檔 | `python gui_app.py` | 分類並歸檔 Revit 族群 |
| 專案回收 | `python gui_app.py --mode=recovery` | 掃描專案族群並準備回收資料 |
| 點位放置 | `python gui_app.py --mode=placement` | 批量點位放置原型 |
| 消防支管 | `python gui_app.py --mode=fire-branch` | 消防支管建立原型 |
| 開孔檢查 | `python gui_app.py --mode=opening-check` | 開孔位置檢查原型 |

## 功能

- 族群庫根目錄驗證。
- 規則式族群分類。
- 低信心或分類衝突項目的人工複核流程。
- 重複族群名稱檢查。
- 公司標準參數模板預覽。
- 專案族群掃描與回收流程。
- XLSX 相容匯出工具。
- Revit add-in 原始碼，用於 metadata 與 queue 處理。

## 重要檔案

| 路徑 | 用途 |
| --- | --- |
| `gui_app.py` | 主要桌面 GUI |
| `classifier.py` | 分類邏輯 |
| `rules.json` | 分類路由、規則、門檻與 fallback path |
| `naming_rules.py` | 命名與預計名稱邏輯 |
| `library_validator.py` | 族群庫資料夾驗證 |
| `parameter_templates/` | 各系統標準參數模板 |
| `queue_protocol.py` | request / response queue 檔案協定 |
| `revit_addin/` | Revit C# add-in 原始碼 |
| `revit_bridge/` | metadata bridge 原始碼 |

## 分類模型

分類器會評估以下資訊：

- Revit built-in category
- Revit category 顯示名稱
- family name
- type name
- file name
- `rules.json` 中的關鍵字
- preferred categories
- rule priority

當信心分數足夠時，工具會建議目的路徑；當信心不足、分類衝突或資料不完整時，應進入人工複核。

## 環境需求

- Windows
- Python 3.10 或更新版本
- Tkinter
- Autodesk Revit 2024
- .NET Framework compiler
- Revit API references：

```text
C:\Program Files\Autodesk\Revit 2024\RevitAPI.dll
C:\Program Files\Autodesk\Revit 2024\RevitAPIUI.dll
```

## 建置 Revit Add-in

```powershell
cd revit_addin
.\build.ps1
```

建置後會產生：

```text
revit_addin\bin\RfaMetadataAddin.dll
```

編譯後 DLL 由本機建置產生，不屬於原始碼版本。

## 啟動 GUI

在 `v0.2-dev` 資料夾中執行：

```powershell
python gui_app.py
```

其他模式：

```powershell
python gui_app.py --mode=recovery
python gui_app.py --mode=placement
python gui_app.py --mode=fire-branch
python gui_app.py --mode=opening-check
```

## 基本使用方式：族群歸檔

1. 建置 Revit add-in。
2. 啟動 Revit 2024。
3. 執行 `python gui_app.py`。
4. 選擇族群庫根目錄。
5. 確認 Revit listener 狀態。
6. 選擇或匯入 `.rfa` 檔案。
7. 讓工具向 Revit 要求 metadata。
8. 檢查建議分類與預計名稱。
9. 人工處理低信心或分類衝突項目。
10. 歸檔或匯出複核後結果。

## 基本使用方式：專案族群回收

1. 在 Revit 開啟目標專案模型。
2. 啟動專案回收模式：

```powershell
python gui_app.py --mode=recovery
```

3. 執行專案族群掃描。
4. 檢查專案族群與分類建議。
5. 對可回收項目進行人工複核。
6. 匯出或納入後續歸檔流程。

## 注意事項與限制

- 此版本是開發版，不是穩定發行版。
- 請先在複製的族群檔或備份模型上測試。
- Revit add-in 會使用 Revit API，必須在目標 Revit 環境中驗證。
- runtime queue、generated responses、compiled DLL、log 與 build output 不屬於原始碼版本。
- 現有規則資料中部分中文內容可能需要再做編碼清理。

## 後續規劃

- 參數模板 GUI 編輯器。
- 更完整的低信心分類複核流程。
- 專案族群回收結果匯出強化。
- 點位放置、消防支管、開孔檢查模式的端到端驗證。

