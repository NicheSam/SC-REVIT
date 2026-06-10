# SC REVIT v0.3 模組化邊界

本次整理目的：為 v0.3 工作流系統做準備，但不改變既有使用流程與按鈕操作。

## 現行策略

- 前台操作維持原本手感：族庫治理、CAD 點位、開孔定位、消防支管仍各自從自己的頁面進入。
- 底層開始建立模組邊界：新功能應優先放進 `sc_revit/*`，舊檔案只保留相容匯出。
- Revit C# 端目前仍集中在 `revit_addin/src/RfaMetadataApplication.cs`。這是下一階段要拆的主要風險點。

## Python 模組邊界

| 模組 | 目錄 | 職責 | 不應該包含 |
|---|---|---|---|
| core | `sc_revit/core` | Queue 等共用基礎、action 合約 | 各專業功能判斷 |
| family_library | `sc_revit/family_library` | 族庫分類、命名、入庫、重複檢查、族群治理 | CAD 點位、開孔、消防支管邏輯 |
| cad_points | `sc_revit/cad_points` | CAD/DWG 圖塊讀取、座標轉換、點位放置請求 | 族庫治理、開孔碰撞、管路連接 |
| openings | `sc_revit/openings` | 開孔掃描、3D 檢視、平面標記、XLSX 匯出資料來源 | CAD 點位放置、消防支管建置 |
| fire_branch | `sc_revit/fire_branch` | 消防支管預覽、主管/灑水頭選取、支管生成請求 | 開孔標記、族庫入庫 |
| project_recovery | `sc_revit/project_recovery` | 專案族群回收與匯出 | 族庫分類規則本身 |
| parameters | `sc_revit/parameters` | 參數模板、參數寫入請求 | 點位/開孔/支管幾何邏輯 |

## Revit action 所屬模組

| 模組 | actions |
|---|---|
| family_library | `scan_project_families`, `export_project_families`, `add_missing_string_parameters`, `set_string_parameter_values` |
| cad_points | `list_point_placement_context`, `list_cad_block_names`, `scan_cad_block_points`, `transform_dwg_block_points`, `create_dwg_preview_markers`, `place_cad_block_points`, `place_dwg_block_points` |
| fire_branch | `list_fire_branch_context`, `read_fire_branch_selection`, `create_fire_branch_preview`, `create_fire_branch_pipes` |
| openings | `list_opening_context`, `scan_opening_candidates`, `view_opening_candidate`, `place_opening_markers` |

## v0.3 後台工作流原則

後台管理可以共用，但業務邏輯不能共用。

可共用：
- `SC_BatchId`
- Result Log
- 產物追蹤
- 批次選取/刪除/匯出
- 狀態檢查

不可共用：
- 族庫分類規則
- CAD 圖塊座標判讀
- 開孔碰撞/定位邏輯
- 消防支管路由與管配件邏輯

## 下一階段建議

1. 先拆 C#：把 `RfaMetadataApplication.cs` 的 action handler 移到獨立 Handler 類別。
2. 再拆 GUI：把 `gui_app.py` 的各頁籤拆成 `gui/tabs/*`。
3. 最後導入 v0.3 後台：新增批次與產物管理，不改各功能前台流程。

## 2026-06-09 C# 第一、第二階段整理

已完成：

- `RfaMetadataApplication.cs` 改為 `partial class`，保留 Revit `IExternalApplication` 主入口。
- 新增 `revit_addin/src/Core/RequestDispatcher.cs` 作為 C# action 分派入口。
- 新增 `revit_addin/src/Handlers/FamilyLibraryHandler.cs`，優先處理以下 action：
  - `scan_project_families`
  - `export_project_families`
  - `add_missing_string_parameters`
  - `set_string_parameter_values`
- `build.ps1` 已改為自動編譯 `revit_addin/src/**/*.cs`，後續新增 Handler 不需要再手動修改 source 清單。

暫時策略：

- CAD 點位、開孔、消防支管仍保留在原檔，不在本階段搬移。
- 舊的族庫/參數 action 區塊暫時保留為回退保險，但實際執行會先進入新 dispatcher。
- 後續第三、四、五階段確認穩定後，再刪除舊區塊並搬移其餘 handler。

## 2026-06-09 C# 第三、四、五階段整理

已完成：

- 新增 `revit_addin/src/Handlers/CadPointHandler.cs`，接管 CAD 點位相關 action：
  - `list_point_placement_context`
  - `list_cad_block_names`
  - `scan_cad_block_points`
  - `transform_dwg_block_points`
  - `create_dwg_preview_markers`
  - `place_cad_block_points`
  - `place_dwg_block_points`
- 新增 `revit_addin/src/Handlers/OpeningHandler.cs`，接管開孔定位相關 action：
  - `list_opening_context`
  - `scan_opening_candidates`
  - `view_opening_candidate`
  - `place_opening_markers`
- 新增 `revit_addin/src/Handlers/FireBranchHandler.cs`，接管消防支管相關 action：
  - `list_fire_branch_context`
  - `read_fire_branch_selection`
  - `create_fire_branch_preview`
  - `create_fire_branch_pipes`
- `RequestDispatcher.cs` 現已接管全部 v0.3 已知 queue action。

驗證：

- C# build 成功。
- Revit Addin manifest 已更新到 AppData 最新部署 DLL。
- Python/C# action 合約檢查通過：19/19。
- Python compileall 通過。

暫時策略：

- 舊 `RfaMetadataApplication.cs` 內的 action 區塊仍保留為回退保險。
- 目前實際執行路徑會先走 dispatcher 與 handler。
- 下一輪清理可移除舊 action 區塊，並開始把大型 helper 依模組拆分。

## 2026-06-09 Helper 第一、第二階段整理

已完成：

- 新增 `revit_addin/src/Core/JsonPayloadReader.cs`
  - `ReadLong`
  - `ReadInt`
  - `ReadDouble`
  - `ReadBool`
  - `ReadStringList`
  - `ReadDictionaryList`
- 新增 `revit_addin/src/Core/RevitDocumentUtils.cs`
  - `GetActiveProjectDocument`
  - `CountByCategory`
  - `GetLinkPath`
  - `GetOpeningLinks`
  - `GetOpeningDimensionTypes`
  - `GetAvailablePipeDiameters`
- 新增 `revit_addin/src/Core/GeometrySerializationUtils.cs`
  - `ReadPoint`
  - `SerializePoint`
  - `SerializeTransformedBoundingBox`
- 新增 `revit_addin/src/Core/FileNameUtils.cs`
  - `SanitizeFileName`
  - `BuildAvailableExportPath`

驗證：

- C# build 成功。
- Python compileall 成功。
- C# action 合約檢查通過：19/19。
- Revit manifest 已部署到：`C:\Users\User\AppData\Local\RfaMetadataAddin\RfaMetadataAddin.f5aa4dda21e9.dll`。

尚未執行：

- Revit queue context 實機測試。原因：整理完成時 Revit 未執行。下次開啟 Revit 後需重跑四個 context：
  - `list_point_placement_context`
  - `list_opening_context`
  - `list_fire_branch_context`
  - `scan_project_families`
