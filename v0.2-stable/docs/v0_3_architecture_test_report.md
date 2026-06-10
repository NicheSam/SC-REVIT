# SC REVIT v0.3 架構整理測試報告

日期：2026-06-09

## 測試目標

確認 CAD 點位、開孔定位、消防支管、族庫治理在新版 C# handler 架構下可以由新版路由接管，不依賴舊版 client 匯入或舊路由優先執行。

## 測試項目

| 項目 | 結果 | 備註 |
|---|---|---|
| Python compileall | 通過 | 全專案 Python 語法檢查通過 |
| Python 模組匯入 | 通過 | `sc_revit.*`、GUI、相容層皆可匯入 |
| C# build | 通過 | `revit_addin/src/**/*.cs` 自動編譯成功 |
| Revit DLL 部署 | 通過 | manifest 指向最新 AppData DLL |
| GUI exe 打包 | 通過 | `dist/RevitFamilyClassifier/RevitFamilyClassifier.exe` 已重建 |
| PyInstaller 模組收錄 | 通過 | 正式 exe 收錄 `sc_revit.*` |
| 舊 client 打包檢查 | 通過 | 正式 exe 未收錄 `point_placement_client.py` / `opening_check_client.py` |
| Queue protocol action | 通過 | Python 產生 19 個 action |
| C# handler action | 通過 | C# handler 覆蓋 19 個 action |
| Dispatcher 優先順序 | 通過 | `TryDispatchRequest` 位於舊 action 區塊之前 |
| Runtime queue 狀態 | 通過 | 無 pending request；舊 response/error 僅為歷史檔 |
| Revit 執行狀態 | 通過 | 測試時 Revit 未執行，下次啟動會載入新 DLL |

## 新版 Handler 覆蓋範圍

| Handler | Action 數量 |
|---|---:|
| `FamilyLibraryHandler.cs` | 4 |
| `CadPointHandler.cs` | 7 |
| `OpeningHandler.cs` | 4 |
| `FireBranchHandler.cs` | 4 |
| 合計 | 19 |

## 目前保留的風險

- `RfaMetadataApplication.cs` 內仍保留舊 action 區塊作為回退保險。
- 實際執行會先走新版 dispatcher；舊區塊目前不應被觸發。
- 尚未在 Revit UI 內逐一執行實機功能煙霧測試。

## 實機測試建議

下次開啟 Revit 後，建議依序測：

1. 族庫歸檔：讀取 RFA → 分類 → 入庫。
2. 專案回收：掃描目前專案族群 → 匯出一個可回收族群。
3. CAD 點位：讀取 CAD Link → 掃描圖塊 → 產生預覽點。
4. 開孔定位：讀取土建 Link → 掃描候選 → 建立平面標記。
5. 消防支管：選主管 → 框選灑水頭 → 產生螢光預覽 → 建立支管。

若任一項失敗，優先檢查 `runtime/queue/errors` 對應 JSON。

## 2026-06-09 Revit 實機煙霧測試與舊區塊清理

### Revit session 內測試：通過

在 Revit 已開啟狀態下，透過 queue 直接觸發 listener，以下 action 回應正常：

| Action | 結果 | 摘要 |
|---|---|---|
| `list_point_placement_context` | 通過 | CAD 來源 9、樓層 8 |
| `list_opening_context` | 通過 | 土建 Link 1、標註型式 18 |
| `list_fire_branch_context` | 通過 | 樓層 8、管類型 24、系統類型 32 |
| `scan_project_families` | 通過 | 專案族群 623 |
| `list_cad_block_names` with invalid id | 通過 | 正確回傳受控錯誤：找不到指定 CAD 來源 |
| `scan_cad_block_points` with invalid id | 通過 | 正確回傳受控錯誤：找不到指定 CAD 來源 |
| `view_opening_candidate` with empty candidate | 通過 | 正確回傳受控錯誤：開孔候選資料缺少中心點 |

### 舊區塊清理：完成

已刪除 `RfaMetadataApplication.cs` 內舊 action block：19 個。

清理後狀態：

- `RfaMetadataApplication.cs` 內舊 `if (action == ...)` 數量：0。
- C# handler action 合約：19/19 通過。
- C# build：通過。
- Python compileall：通過。
- Manifest 已部署到：`C:\Users\User\AppData\Local\RfaMetadataAddin\RfaMetadataAddin.117406c27723.dll`。

### 尚待確認

Revit 正在執行時不會 hot reload 新 DLL。因此清理後版本需要重開 Revit 才能完成最後一次 post-clean 實機 queue 測試。
