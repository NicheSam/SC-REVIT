# SC REVIT 實機 SVG 元件轉換驗證（2026-08-21）

## 驗證邊界

本次是「DLL 未部署」前提下的唯讀實機驗證：

- 未部署新的 Revit DLL，也沒有重新啟動 Revit。
- 未建立、刪除、移動或修改任何 Revit 元件；Dynamic C# 回報 `ActualCreatedElementIds=[]`、`ActualDeletedElementIds=[]`。
- 只讀取目前 Revit 活動視圖中既有的管段、管件連接器，以及該視圖唯一的 CAD `ImportInstance`。
- SVG 轉換測試分成兩層：
  1. **元件卡片 SVG**：直接用實機回讀的 ElementId、族群、連接器數量與連接器管徑繪出管、彎頭、三通、四通、變徑。
  2. **既有 SC REVIT 路網 renderer fixture**：用同一批實機 ElementId 建立最小拓樸契約，測試管段、三通、四通、變徑、顏色、方向與 `data-plan-entity-id` 輸出。

因此這份結果可以證明「資料能被轉成結構化 SVG」，但不能把它誤讀成新 DLL 已載入，或 CAD 路徑對位及 Revit 建模已通過。

## 實機環境

| 項目 | 回讀結果 |
|---|---|
| Revit | 2024 |
| 專案 | `大甲分局_MEP_sc168jobim` |
| 活動視圖 | `-1. 地下壹層 撒水`（ViewId `13301161`） |
| 目前選取 | Pipe ElementId `13563852` |
| 唯一 CAD | ImportInstance `13379416`，分類 `自動撒水設備配置圖-地下壹層`，`isLinked=true`，`ownerViewId=13301161` |
| Bridge | Connected，Bridge `0.8.0`，Revit `2024` |
| Dynamic C# | 兩次唯讀回讀均成功，無交易寫入 |

## 元件回讀結果

目前活動視圖的消防元件數量：276 段管、168 個消防管件；其中三通 50、四通 17、變徑 66、彎頭 35。

| 類型 | 實機 ElementId／族群 | 連接器 | 讀到的管徑／幾何 |
|---|---|---:|---|
| 管段 | `13563852`／`FS_消防撒水管` | 2 | DN100，長度 7005.735 mm；端點座標已回讀 |
| 彎頭 | `13563857`／`FS_消防撒水管_彎頭_焊接` | 2 | 兩端 DN100；端點形成 90° 折線 |
| 三通 | `13722992`／`FS_消防撒水管_三通_螺牙` | 3 | 三端皆為 DN40（連接器半徑 20 mm） |
| 四通 | `13563873`／`FS_消防撒水管_十字_焊接` | 4 | 四端皆為 DN100（連接器半徑 50 mm） |
| 變徑 | `13737368`／`FS_消防撒水管_變徑_螺牙` | 2 | DN20 ↔ DN25（連接器半徑 10／12.5 mm） |

## SVG 轉換檢查

| 檢查 | 結果 |
|---|---|
| 元件卡片 SVG XML 可解析 | 通過 |
| 路網 renderer fixture XML 可解析 | 通過 |
| 元件卡片包含 5 類元件 | 通過：Pipe、Elbow、Tee、Cross、Reducer |
| 元件卡片 `data-plan-entity-id` | 5 個，無重複 |
| 路網 renderer 管段 | 6 段，含 DN25、DN32、DN40、DN100；顏色由管徑轉換器輸出 |
| 路網 renderer 接點 | 1 個三通、1 個四通；均有 `data-plan-entity-id` |
| 路網 renderer 變徑 | 1 個 DN40 → DN32；有異徑符號及來源識別碼 |
| 方向欄位 | `data-orientation-source="revit_view"`；方向依目前視圖 right/up |
| SVG 轉換單元測試 | 51 tests passed |

## 產物

- [元件卡片 SVG](./fire_branch_live_component_sheet.svg)：實機回讀資料的五類元件轉換證據。
- [路網 renderer SVG](./fire_branch_live_topology_renderer_fixture.svg)：現有 SC REVIT SVG renderer 的最小拓樸契約測試。
- [實機回讀摘要 JSON](./fire_branch_live_component_readback.json)：文件、視圖、CAD ImportInstance、代表元件與數量。
- [轉換檢查摘要](./conversion_checks.json)：XML、檔案大小及識別碼數量。
- [產生器](./generate_live_svg_validation.py)：本次驗證用腳本，不是 Revit DLL，也不會修改模型。

## 尚未由本次驗證證明的項目

1. 這次沒有重新抽取 DWG 內部線段、文字、顏色與 CAD 路徑，因此沒有宣稱「CAD 路徑對位成功」。
2. 這次沒有呼叫 DLL 的正式建模流程，因此沒有宣稱三通／四通／變徑在 Revit 中可建立並保持系統連通。
3. 路網 renderer fixture 的座標是為了元件轉換契約而正規化的畫布座標；實機 ElementId、族群、連接器與管徑是真實回讀值，不能把畫布位置當成 CAD 實際位置。
4. 目前 Revit 仍維持原本已載入的 DLL；本次沒有部署候選 DLL，所以若要驗證新 DLL 行為，必須另開一個明確的部署／重啟驗證階段。
