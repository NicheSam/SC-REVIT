# 消防支管 M1 活動模型唯讀證據

日期：2026-08-17  
專案：`大甲分局_MEP_sc168jobim`  
活動視圖：`-1. 地下壹層 撒水`（ElementId `13301161`）  
執行方式：BIM Personal Agent Dynamic C# 與 SC REVIT `read_fire_branch_snapshot`，均為唯讀。快照擷取後已完成 DLL 部署並重新開啟 Revit，後續以新版 action 重跑確認。

## 目的

確認目標 Revit 專案目前的實際 Pipe／Pipe Fitting／Sprinkler Connector 圖，作為 M0/M1 的現況基線。這不是建模測試，也不代表新 SC REVIT DLL 已經在 Revit 中載入。

## 唯讀結果

| 項目 | 結果 |
|---|---:|
| 使用者目前選取元素 | 501 |
| 選取 Pipe | 252 |
| 選取 Pipe Fitting | 167 |
| 選取 Sprinkler | 82 |
| Connector 圖元素（展開後） | 501 |
| Connector 關係紀錄（依 Revit AllRefs 展開） | 1,086 |
| 讀取例外 | 0 |
| 建立元素 | 0 |
| 刪除元素 | 0 |

### Pipe 直徑分布

- DN100：22 段
- DN40：98 段
- DN32：24 段
- DN25：66 段
- DN20：42 段

### 管件分布

- 十字：17
- 三通：50
- 變徑：66
- 彎頭（焊接）：2
- 彎頭（螺牙）：32
- 灑水頭：82

## 重要觀察

1. 目前活動選取已同時包含主管、支管、管件及灑水頭；不能把「選取數量」直接當成主管數量。
2. 22 段 DN100、98 段 DN40 及 66 段 DN25 等資料，證明後續主管候選與支管候選必須以 Connector 圖、CAD 路徑證據及管徑規則共同判斷，不能只取單一管徑。
3. 86 條 Connector 參照指向 `配管系統`，這是 Revit 系統擁有者的參照，不是可繼續走訪的 Pipe／Fitting／Sprinkler 元素；M1 Adapter 必須保留此類停止邊界，不能把它誤當成支管或主管。
4. 本次 Dynamic C# 曾遇到 `IsConnected`、`Origin` 只能用於 PhysicalConn 的 Revit API 限制；最終唯讀彙總已移除這兩個非必要讀取，並成功在同一活動模型完成。

## 邊界與下一步

- 本證據沒有建立、刪除、移動或改變任何模型元素。
- 新增的 `read_fire_branch_snapshot` C#／Python 路徑已編譯並完成部署；重新開啟 Revit 後已實際回傳快照。
- 下一步仍只做 M1：用單一路徑案例完成 L／U／雙 L 的 Connector 對照；完成前不進入 CAD Route Graph、SVG 編輯或正式建模。

## 新版 DLL 載入驗證

重新開啟 Revit 後，SC REVIT `read_fire_branch_snapshot` 實際回傳：

- `schema_version`：`fire_branch_revit_snapshot.v1`
- `snapshot_id`：`20260817T082511691Z`
- 主圖元素：419（Pipe 252、Pipe Fitting／Accessory 167）
- Pipe 直徑分布：DN100 22、DN40 98、DN32 24、DN25 66、DN20 42
- Connector 關係：418，全部標記為已連接
- 停止邊界：86 條，指向灑水頭，未把灑水頭誤當成可繼續展開的管路元素
- 建立元素：0
- 刪除元素：0
- 讀取錯誤：0

這證明新版 DLL 已被 Revit 載入，且唯讀 action 可在目標專案執行；尚未進行正式建模。

## 完整快照與形狀分析

- 快照檔案：[fire_branch_revit_snapshot_20260817T082511691Z.json](<E:/Desktop/Codex/SC REVIT/docs/validation/fire_branch_revit_snapshot_20260817T082511691Z.json>)
- 快照契約：`fire_branch_revit_snapshot.v1`，校驗錯誤 0。
- 形狀摘要：[fire_branch_topology_profile_20260817T082511691Z.json](<E:/Desktop/Codex/SC REVIT/docs/validation/fire_branch_topology_profile_20260817T082511691Z.json>)，格式 `fire_branch_topology_profile.v1`。
- 主圖元素：419（Pipe 252、管件／配件 167），元素連通元件 1 個。
- 元素級分支：三通 50、四通 17，含分支的元素級節點共 67 個。
- 管段方向：X 50、Y 60、Z 142；這是目前選取範圍的整體分布，不代表一條單一路徑。
- 判定：`compound_network`（複合路網）。因為目前選取含三通／四通，不能直接標成單一 L、U 或雙 L。
- 停止邊界：86 條，主要指向灑水頭；這些是唯讀展開的終點，不是失敗或刪除。
- 同徑連續候選：DN100 為 22 段／1 個同徑元件；DN40 為 98 段／16 個；DN32 為 24 段／12 個；DN25 為 66 段／30 個；DN20 為 42 段／42 個。這些是候選分組，不是已確認的主管判定。
- 路徑候選形狀：DN100 有 6 條 L、2 條直線；DN40 有 26 條 L、20 條 U、20 條直線；DN32 有 12 條 L；DN25 有 12 條 L、12 條複合折線；DN20 尚未形成同徑連續路徑。這些結果只依目前 Revit Connector 與同徑管件連接整理，仍需 CAD 路徑證據確認主管身分。

形狀分類器只做純資料分析：對於另外提供的有序單一路徑，才會標示 `linear`、`L`、`U` 或 `double_L`；不會自行修改 Connector、管徑、管件或模型。
