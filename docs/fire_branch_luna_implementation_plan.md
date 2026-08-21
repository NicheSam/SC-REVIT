# SC REVIT 消防支管後續開發實做計畫（Luna 交接版）

## 執行進度（2026-08-17）

### 2026-08-20 M2–M4 實作批次

- 活動 Revit 已接受本批次的 `topology_only` 可回復沙盒；本輪不重開 Revit、不重新部署 DLL。驗證證據如下：批次 `20260820-180056`、文件 `大甲分局_MEP_sc168jobim`、主管 `13740034`、兩顆試點 `13599867`／`13599868`。
- 沙盒結果：套用 `fire_branch_topology_plan.v5`（plan ID `sandbox-topology-20260820-m2m4`）的 2 段 DN25 計畫管段；建立 1 條 feeder 與 2 條 branch，`failed=[]`；`verification_status=verified`；`model_restored=true`、`restoration_verified=true`、`rollback_status=verified`、`residual_created_element_ids=[]`。
- 本次只驗證 M2–M4 的主管／支管／接頭幾何與計畫識別碼，`sandbox_scope=topology_only`、`sprinkler_connectivity_assessed=false`；因此不能把這筆結果解讀成灑水頭 Connector 已連通，也不批准正式建立。
- 活動模型完整驗證記錄：`docs/validation/fire_branch_m2_m4_topology_only_20260820.md`。

- 已新增 `fire_branch_topology_plan.v5`：完整保存主管、支管、接頭、異徑、來源模式、revision、parent hash、SHA-256，以及供 SVG／建模一對一引用的 `plan_entity_id`。
- M2 已加入 `fire_branch_route_candidate_decision.v1`：先判斷是否到達目標灑水頭，再比較 CAD 連續覆蓋、管徑／拓樸證據、雜訊交點、轉折與長度；完整候選與淘汰原因會保留，不以單一黑箱分數取代證據。Revit 預覽回傳的 `cad_route_assignments` 也會被轉成每顆灑水頭的候選決策，保留 Revit 權威選擇並標記 Python 排序是否一致。
- M3 已讓 SVG 管段、異徑與接頭輸出 `data-plan-entity-id`，並在產生計畫時檢查識別碼缺漏／重複；全批次與單顆試點的計畫都保留 `plan_entity_id`。C# 建模前會要求 `fire_branch_topology_plan.v5`、plan ID、plan hash 及各項目 ID，建模回報也會回傳管段、接頭、異徑的識別碼與拓樸計畫 identity，畫面與建模可用同一個計畫項目對應。
- M2–M4 沙盒提供 `sandbox_scope=topology_only`：只建立並驗證計畫指定的主管／支管／接頭幾何，明確跳過既有灑水頭垂管與 Connector 路徑，回報 `sprinkler_connectivity_assessed=false`；此模式只允許 `test_fire_branch_pipes`，且必須完整回復，不得用於正式建立。活動 Revit 已於批次 `20260820-180056` 實際通過此模式。
- M4 已支援版本化命令 `change_segment_diameter`、`change_junction_type`、`change_reducer_sizes`、`choose_route_candidate`、`choose_main_continuation`、`mark_reviewed`；命令必須帶計畫識別碼、revision、hash、目標 ID 與原因，舊版 `set_*` 僅保留相容性。
- SVG 與 Revit ExecutionPlan 已改為接受同一份已審查拓樸計畫；建模端不得重新產生另一份管徑計畫。
- 路網畫布已加入有限修正：管段管徑、接頭類型、異徑前後尺寸、版本記錄及 Undo／Redo；舊 hash 修改會被拒絕，修正後必須重新預檢。
- GUI 已分為「CAD 智慧管徑」與「無 CAD／統一管徑」；CAD 模式不再顯示人工管徑，無 CAD 模式以 Adapter 套用統一管徑並共用同一建模核心。
- 已修正無 CAD 模式的端到端契約：GUI、queue request 與 Revit DLL 都會傳遞 `source_mode=uniform`，並只在此模式復用穩定版「最近主管投影」路徑；CAD 模式仍保留 CAD 證據優先，不互相降級。
- Revit 沙盒加入專用 failure preprocessor：可忽略警告會寫入診斷後自動處理；真正錯誤會自動回復，避免停在模態視窗等待人工操作。
- Python 全套 267 項測試通過，包含本批次 M2–M4 契約測試；活動模型唯讀預覽也已通過 CAD 對位（matched、覆蓋率 100%、1474 個 CAD 錨點、12 顆灑水頭均有路徑候選），`fire_branch_topology_plan.v5` 驗證為 valid。修正內容包含異徑前後管段方向與選取主管管徑 fallback，避免有效的 CAD 變徑被反向判定。歷史沙盒批次 `20260820-170852` 曾在既有 `CreateFireDropWithTransition` 的 DN25 灑水頭垂管建立失敗並回復；本次已用獨立 `topology_only` 邊界完成 M2–M4 幾何驗證，灑水頭端最後一段管仍沿用既有穩定連接路徑，本輪未修改該邏輯，也未重開或部署 Revit。
- 2026-08-21 M3/M4 UI/UX 稽核與改版：消防主畫面統一 11pt／30px 可讀基準，將目前模式、計畫狀態、分析摘要、結果表與主要動作分層；新增撒水頭／管段／異徑選取回饋及完整分析報告分頁。路網圖將有限修正控制項分組，加入計畫檢查、畫布單擊選取與拖曳防誤選；詳細稽核與限制見 `docs/validation/fire_branch_m3_m4_uiux_audit_20260821.md`。本輪只改 GUI／計畫編輯器，未部署 DLL 或重開 Revit。
- 2026-08-20 BIM Agent 唯讀稽核與沙盒分開記錄：原活動模型的 12 顆灑水頭未連接是既有模型基線；本批次新鮮預覽與拓樸計畫已通過，但沙盒的兩顆試點在既有 DN25 垂管建立階段失敗並回復。下一個完成門檻是只針對既有灑水頭垂管／Connector 路徑做小範圍診斷與回歸，不得把這個穩定邏輯問題混入 M2–M4 CAD／拓樸契約修正。

- M0：已建立唯讀快照契約測試；活動模型成功案例基線已在目標 Revit 內擷取。
- M1：已加入 `read_fire_branch_snapshot` 只讀請求、C# Connector 展開器及 Python 契約驗證；並以 BIM Agent 在活動模型完成 Connector 唯讀彙總。
- 驗證：Python 全套 211 項測試通過；Revit 2024 DLL 編譯通過（本輪另以獨立暫存輸出驗證）；BIM Agent 唯讀 Connector 彙總成功且建立／刪除數均為 0；完整快照契約與形狀分析測試通過。
- 部署：已完成來源 DLL、GUI 與 Revit 2024 manifest 部署；重新開啟 Revit 後 `read_fire_branch_snapshot` 已實際回傳 `fire_branch_revit_snapshot.v1`。
- M1 補充：活動模型已封存為完整 `fire_branch_revit_snapshot.v1` fixture，並產生唯讀 `fire_branch_topology_profile.v1`；目前選取被判定為複合路網，不直接冒充單一 L／U／雙 L。另已輸出同徑路徑候選，供下一步以 CAD 證據確認主管。
- M2 部分完成：已從活動文件讀取 28 個 CAD ImportInstance 的座標狀態；28 個匯入物都有幾何，但目前選取範圍只與 4 個匯入物相交，讀到 25 條 CAD 線段。獨立比對只有 6/110 個平面模型管段有幾何候選支持，文字／圖層／顏色尚未完成同一座標契約配對，因此暫不判定 CAD 已吻合。
- M2 規則修正：CAD 線段長度不再作為 Revit 管段等長的必要條件；新增唯讀 `cad_route_graph` 正規化原型，保留碎片來源、圖層與顏色，將容許範圍內的端點合併、真正交叉切成節點，超出容許範圍的空隙保留為斷線證據。CAD 幾何展開也改用與 issue100 點位放置相同的 `ImportInstance.GetTotalTransform()` 座標鏈；尚待重新載入 DLL 後重跑活動模型 M2。
- M1/M2 修正：同徑路徑候選不再重複同一個 PipeId；211 項 Python 測試通過。
- 尚未完成：以單一路徑案例完成 L／U／雙 L 的實際 Connector 對照與正式建模。

## 1. 文件目的

本文件把已確認的功能方向轉成可分階段執行、可驗證、可停止的實做計畫。Luna 應依階段交付，不得一次同時修改主管辨識、拓樸、SVG、灑水頭垂管、避梁與正式建模。

本計畫涵蓋：

1. 直線、L 型、U 型、雙 L 型及含彎頭／異徑的複合主管辨識。
2. 依 CAD 幾何與管徑證據產生複合支管路徑。
3. SVG 拓樸檢查與有限度人工修正。
4. 拓樸計畫直接驅動 Revit 預檢、沙盒與正式建模。
5. 無 CAD 底圖時的統一管徑舊版模式。
6. 第一版支管自動避梁。

本文件不授權直接部署。每階段必須先提供測試證據，再由使用者決定是否進入下一階段或部署。

## 2. 開發位置與基線邊界

### 2.1 唯一開發來源

- 唯一開發目錄：`E:\Desktop\Codex\SC REVIT`
- Git 紀錄／發布 staging：`E:\Desktop\Codex\PushGithub\SC REVIT`
- 不得在 staging 直接開發。
- 不得自動把兩個目錄互相覆蓋或同步。
- 要發布時，另做明確的差異審查、排除測試產物，再同步到 staging。

### 2.2 開始前必做基線封存

Luna 在修改任何程式前必須產出一份基線紀錄：

- 開發目錄重要檔案 SHA-256。
- 本機部署 DLL SHA-256、檔案版本與時間。
- Revit manifest 實際載入路徑。
- 現有 Python 測試結果。
- 一次目前可成功建立的消防支管案例：request ID、完整 request payload、topology plan、response payload、建立元素 ID、Undo／回復結果。
- 把「現行成功的灑水頭垂管連接」做成不可退化的回歸資料。

如果無法取得成功案例，先標為「缺少活動模型基線」，不得宣稱後續修改沒有破壞既有流程。

### 2.3 禁止順手修改的穩定區

在複合主管及 SVG 階段，不得修改：

- 已能工作的灑水頭位置與選取方式。
- 已能工作的垂管建立與灑水頭 Connector 連接路徑。
- 排水工具共用的 Connector／Pipe 建立函式。
- 點位預覽的清理生命週期。
- 其他 Ribbon 工具與圖示。

若新功能確實需要改動穩定區，必須另開變更項目，先說明原因、影響面及回歸測試，不得混在當期提交內。

## 3. 核心架構原則

### 3.1 唯一真實來源

資料只能依下列單向流程前進：

```text
RevitSnapshot
  -> TopologyPlan
  -> PlanRevision（如使用者在 SVG 修正）
  -> ExecutionPlan
  -> Revit Preflight
  -> Revit Sandbox
  -> Revit Commit
```

- SVG 只顯示 `TopologyPlan`，不得自行重算拓樸。
- Revit 建模只執行 `ExecutionPlan`，不得再依距離、方向或管徑重新猜測。
- 預檢、沙盒與正式建立必須使用同一個 plan ID、revision 與 SHA-256。
- 任一上游資料改變，舊預檢結果立即失效。

### 3.2 深模組與介面

應建立少數但功能完整的模組，避免 GUI、Python Worker、C# Handler 各自保留一套判斷。

| 模組 | 對外介面 | 內部責任 |
|---|---|---|
| `FireBranchSnapshotReader`（C#） | `Read(seed, selection, view)` | 讀取主管 Connector 圖、管件、灑水頭、CAD 轉換、樓層、管型、系統、Routing Preferences 與短線限制 |
| `FireBranchPlanner`（Python） | `Plan(snapshot, settings)` | 主管判斷、CAD Route Graph、支管候選、管徑、交點、變徑及待確認項目 |
| `FireBranchPlanEditor`（Python） | `Apply(plan, editCommand)` | 只接受允許的修正命令、產生新 revision、重跑拓樸驗證 |
| `FireBranchExecutionCompiler`（Python） | `Compile(plan, capabilities)` | 把已確認拓樸轉成有順序與相依關係的建置操作，不做新判斷 |
| `FireBranchExecutionEngine`（C#） | `Validate/Execute(executionPlan, mode)` | 依操作順序建立、連接、驗證、保存證據或提交 |
| `FireBranchDiagramRenderer`（Python/GUI） | `Render(plan)` | 依 plan 畫 SVG；顏色、線粗、文字及管件位置均來自 plan |
| `StructuralObstacleQuery`（C#） | `Query(branchSegments, beamScope)` | 共用 Revit Link 座標及 Solid 相交能力，回傳梁障礙，不決定避讓路徑 |

介面資料必須可序列化與版本化。不得讓 Python 保存 Revit API 物件，也不得讓 C# 依 GUI 顯示文字反向推測拓樸。

## 4. 資料契約

### 4.1 `fire_branch_revit_snapshot.v1`

至少包含：

- `document_fingerprint`、`active_view_id`、`view_transform`、擷取時間。
- `seed_main_pipe_id`、使用者選取 ID。
- `main_graph.nodes[]`：Connector／管件節點、位置、方向、直徑、domain、system、owner ID。
- `main_graph.edges[]`：Pipe 或 fitting、兩端節點、實際連通、長度、管徑、局部方向、中心高程。
- `sprinklers[]`：ElementId、固定位置、Connector 位置／方向／直徑／系統需求。
- `cad_imports[]`：ImportInstance ID、來源、可見性、總轉換矩陣、單位。
- `revit_capabilities`：可用 Pipe Size、Pipe Type、System Type、Level、Routing Preferences、可用彎頭／三通／四通／異徑、`ShortCurveTolerance`。
- `height_settings`：支管距離樓層高度與現行管頂／管中心／管底基準。

快照只描述目前 Revit 狀態，不包含建置決策。

### 4.2 `fire_branch_topology_plan.v5`

至少包含：

- `plan_id`、`revision`、`schema`、`snapshot_hash`、`plan_hash`。
- `mode`：`cad_evidence` 或 `uniform_no_cad`。
- `main_run`：主管節點、段、彎頭、異徑及選擇證據。
- `routes[]`：每排支管由主管接入點到各灑水頭的完整順序。
- `segments[]`：穩定 ID、起終點、方向、長度、管徑、來源證據、前後節點。
- `junctions[]`：三通／四通／彎頭，明確記錄各方向 port 與管徑。
- `reducers[]`：上游／下游管徑、所在 segment、方向、預計插入區間。
- `sprinkler_drops[]`：水平支管接點、垂管、灑水頭 Connector 需求；灑水頭位置不得變動。
- `beam_bypasses[]`：梁 ID、Link ID、進入／下降／梁下／上升／離開點、管徑、淨距與狀態。
- `evidence[]`：CAD 幾何、圖層、線色、鄰近文字及配對信心。
- `review_items[]`：原因、候選、影響元素、允許的修正種類。
- `validation`：拓樸是否封閉、是否存在零長度、斷線、重疊、方向錯誤、非法管徑跳變。

### 4.3 `fire_branch_plan_edit.v1`

SVG 只能送出結構化命令：

- `change_segment_diameter`
- `change_junction_type`
- `change_reducer_sizes`
- `choose_main_continuation`
- `choose_route_candidate`
- `mark_reviewed`

每個命令必須帶：`plan_id`、`expected_revision`、`expected_hash`、`target_id`、修改前後值與原因。修改成功後建立新 revision，禁止直接覆寫舊 plan。

第一版不允許使用者自由拖曳節點或畫任意新路徑。這類修改已超出「小幅校正」，應回到 CAD／演算法修正。

### 4.4 `fire_branch_execution_plan.v4`

每個 operation 必須有穩定 ID、類型、輸入、預期輸出、前置相依 operation ID 及驗證條件。建議順序：

1. 讀取並鎖定既有主管／灑水頭參照。
2. 建立主管切分點。
3. 先建立與大管徑一致的三通／四通主體。
4. 建立較小支管及所需異徑，不得把小管徑反向套到主管主體。
5. 建立水平支管與一般彎頭。
6. 建立避梁下降、梁下、上升段及四個 90° 彎頭。
7. 呼叫既有穩定垂管／灑水頭連接路徑。
8. Regenerate。
9. 驗證整條 MEP 可達性、管徑順序、Connector 連通及異常長短管。

Execution Engine 只能依 operation 執行；如果 operation 缺資料，回報計畫不完整，不得臨時補猜。

## 5. 主管辨識演算法

### 5.1 圖的來源

使用者選取一段主管作為種子。Revit 端從實際 Connector 與管件展開，不再用「平行於第一段」或純端點距離建立假圖。

### 5.2 展開規則

- 只沿同一 Piping domain、相容系統且實際連通的 Pipe／Fitting 展開。
- 彎頭、直接及主管沿線異徑可繼續。
- 遇到灑水頭、設備或不同系統時停止。
- 經三通／四通時，出口排序採字典序，不用不透明加權分數：
  1. CAD 主管路徑證據是否連續完整。
  2. 是否同系統且實際連通。
  3. 是否同管徑且最接近進入方向。
  4. 若管徑不同，選最大管徑作主管延續。
  5. 仍同分時選轉折最小者。
- 仍有多解就建立 `review_item`，不得猜測。

### 5.3 停止與安全邊界

- 以已訪問 Connector／ElementId 防止循環，不用固定搜尋深度當主要停止條件。
- 不跨越不同文件、未載入 Link 或無法證明連通的幾何接近管段。
- 不把灑水支管或立管因「管徑較大」就自動併入主管；最大管徑只在同一候選交點內作後順位判斷。

## 6. CAD Route Graph 與支管選擇

### 6.1 圖形建置

- 使用既有 DWG 到 Revit 的座標轉換，不得另寫第二套對位方法。
- 將管路線端點、交點、轉折點、主管接入點與灑水頭投影點統一吸附成圖節點。
- 吸附容差必須由 DWG 單位、模型尺度與既有對位殘差推導並記錄，不得散落硬編碼。
- 幾何交叉必須切成真節點；SVG 不得為排版把同一交點錯開。

### 6.2 管徑證據優先序

1. 管徑文字直接配對。
2. 線段實際顏色。
3. 圖層／ByLayer 備援。
4. 中文全圖規則，例如「未標註之管徑均為 1 吋」。
5. 都無證據才標記待確認，不可靜默套值。

文字配對需先辨認關鍵語意與管徑格式，再依距離、方向、引線／延伸線及路徑區域關係配對；不能單純把最近文字套給最近線。

### 6.3 候選路徑比較

按下列順序比較，不以單一加權分數掩蓋原因：

1. 是否從主管接入點完整到達目標灑水頭。
2. 是否覆蓋 CAD 連續路徑與中間轉折。
3. 管徑證據是否連續且無矛盾。
4. 交點、方向與灑水頭排列是否合理。
5. 是否穿越非管路雜訊。
6. 轉折數。
7. 路徑長度與幾何距離。

即使使用者只選末端灑水頭，也要沿完整 CAD Route Graph 保留中途管徑、交點與其他必需路徑段，不能退化成單一直線／單一管徑。

## 7. SVG 拓樸編輯介面

### 7.1 顯示要求

- 方向與 Revit 目前視圖東西南北一致。
- 線粗依實際管徑顯示。
- 每段顯示英吋／DN、長度、證據來源及信心狀態。
- 三通、四通、彎頭、異徑與避梁段需有不同且簡單的符號。
- 主管與支管明確區分。
- 待確認、衝突、預檢失敗、沙盒失敗分色，不得只寫技術代碼。
- 支援滾輪縮放、拖曳平移、全圖、適合視窗與可靠文字大小。
- 雙擊項目時，透過 Revit ExternalEvent 聚焦對應模型範圍；不能依賴滑鼠先移回 Revit 才處理。

### 7.2 編輯後驗證

每次修正依序執行：

1. 產生新 plan revision。
2. 純拓樸檢查。
3. Revit Routing Preferences／幾何空間預檢。
4. 可回復沙盒建立。
5. 通過後才顯示「可正式建立」。

SVG 不保證 Revit 一定可建；只有相同 revision 的沙盒通過才可正式建立。

## 8. 無 CAD／統一管徑模式

GUI 新增獨立頁籤「無 CAD／統一管徑」，主頁保留 CAD 智慧模式。

此模式：

- 不讀取 CAD 管徑文字、顏色或圖層。
- 使用者指定單一水平支管管徑。
- 仍使用 Revit Connector 主管圖、相同 TopologyPlan／ExecutionPlan、相同預檢與沙盒。
- 高度維持現行「支管距離樓層高度」及管頂／中心／底基準。
- 灑水頭末端尺寸依實際 Connector 與 Routing Preferences 處理，不硬鎖 DN20 或 DN25。
- 不複製舊版整套建模程式，只把「管徑來源策略」換成固定值 Adapter。

## 9. 第一版自動避梁

### 9.1 範圍

只處理「計畫中的消防支管」與「本機或連結模型中的結構梁」。

不處理：

- 主管避讓。
- 其他 MEP 碰撞。
- 樓板、牆、柱、建築設備碰撞。
- 45° 繞梁方案。
- 自動搬動灑水頭。

### 9.2 障礙查詢

從既有開孔定位功能抽取可共用的 `StructuralObstacleQuery`：

- 使用 Link `GetTotalTransform` 與 inverse transform。
- 取得梁 Solid 與支管中心線的相交區間。
- 回傳 host/link element ID、梁外框、實際 Solid 相交範圍、梁底高程與座標轉換證據。

開孔定位與消防避梁只共用查詢模組；兩者的業務判斷不可混在同一 Handler。

### 9.3 避梁幾何

- 採四個 90° 彎頭：下降、梁下水平、上升、回原高度。
- 全程同管徑，不變徑。
- 管頂到梁底預設淨距 5 cm，GUI 保留可輸入欄位。
- 梁下管中心高程：`梁底高程 - 使用者淨距 - 管外半徑 - 保溫厚度（如有）`。
- 下降與回升位置由實際彎頭／管件長度、ShortCurveTolerance、梁投影範圍及安全淨距推導，不使用固定 50 mm、100 mm 等魔術數字。
- 相鄰梁的避讓區間重疊或無足夠回升距離時，合併成一次下繞。
- 離開最後一根梁後回到原支管高度並繼續原拓樸。

### 9.4 必須轉人工確認的情況

- Link 未載入或座標轉換無法驗證。
- 取不到有效梁 Solid。
- 梁下空間不足以容納管徑、淨距及四個彎頭。
- 支管本身斜向／斜坡，第一版演算法無法可靠處理。
- 下繞後會穿越樓板、牆或其他已納入安全檢查的結構。
- 多梁區間找不到可回到原高程的合法位置。

人工確認時只能保留原計畫並標示障礙，不能自行建立穿梁管。

## 10. Revit 預檢、沙盒與正式建立

### 10.1 對外動作收斂

Revit 端新增或整理成三個主要請求，不持續增加零碎 action：

- `read_fire_branch_snapshot`
- `validate_fire_branch_plan`，`mode=preflight|sandbox`
- `execute_fire_branch_plan`，`mode=commit`

舊 action 暫由 Adapter 轉成新契約，確認 GUI 全部遷移後再移除。

### 10.2 Preflight

只讀檢查：

- plan 與目前 document／view／element 是否仍一致。
- Pipe Type、System Type、Level、尺寸與 Routing Preferences 是否存在。
- 每個三通／四通／異徑／彎頭是否有可行族型與足夠幾何空間。
- 所有灑水頭 Connector 需求是否可滿足。
- operation 相依順序是否完整。

### 10.3 Sandbox

- 在 TransactionGroup 內按 ExecutionPlan 建立。
- 逐 operation 保存元素 ID、Connector 配對、實際尺寸及錯誤。
- 測試模式即使局部失敗，也保留診斷證據到 payload／artifact；模型本身最後完整 Rollback。
- 沙盒通過條件：所有要求的三通／四通與異徑方向正確、無零長度／異常長管、所有選定灑水頭從指定主管可達、模型完整回復。

### 10.4 Commit

- 只接受通過相同 plan revision 沙盒的計畫。
- 建立後再驗證一次實際 MEP 路徑。
- 若屬可保留的局部問題，顯示中文問題清單，讓使用者選「保留成功部分」或「全部復原」。
- 嚴重錯誤（文件已變、plan 過期、主管參照失效、交易不一致）不得保留半成品。
- 成功提交必須可由一次 Revit Undo 復原。

## 11. 錯誤與紀錄

### 11.1 GUI 中文錯誤格式

每個問題至少顯示：

- 發生在哪一排／哪一段／哪個管件。
- 使用者可理解的原因。
- 已成功建立與失敗數量。
- 模型影響與是否可保留。
- 建議動作。
- 可展開的技術資訊：operation ID、ElementId、Connector、例外與 payload 位置。

禁止只顯示 `connector_verification_failed` 或被截斷的 ID 串。

### 11.2 儲存分層

- `request_summary`：固定格式 GUI 摘要，維持大小上限。
- `request_payload`：完整輸入，不截斷。
- `response_payload`：完整結果與診斷，不截斷。
- `topology_plan`：獨立、版本化、含 revision 與 SHA-256。
- 常查欄位：計畫版本、雜湊、管段數、三通／四通數、避梁數、失敗數。
- 大型附件：獨立 artifact 或 JSON 檔，資料庫存路徑、大小與 SHA-256。

任何摘要截斷不得影響重現或診斷。

## 12. 分階段實做與驗收門檻

### M0：鎖定基線與契約測試

工作：

- 建立現行成功案例 fixture。
- 為既有 `fire_branch_topology_plan.v3` 與 execution plan 寫入相容讀取測試。
- 記錄部署 DLL 與來源 SHA。
- 補齊 request／response／topology plan 完整保存測試。

驗收：既有 Python 測試全過；同管徑成功案例資料可重播；沒有修改建模行為。

### M1：RevitSnapshot 與複合主管圖（只讀）

工作：

- 新增 `FireBranchSnapshotReader`。
- 以實際 Connector 展開直線、L、U、雙 L、含主管異徑案例。
- GUI 仍使用舊建模，不切換正式流程。

驗收：在活動模型輸出主管圖；Element／Connector 關係與 Revit 實際一致；不建立任何元素。

### M2：CAD Route Graph 與候選比較（只分析）

工作：

- 重用既有 CAD 對位結果。
- 建立真交點與完整路徑。
- 輸出每個候選被選／被淘汰原因。

驗收：末端單選仍保留中途轉折與管徑；CAD 相同配置產生一致拓樸；无模型寫入。

**2026-08-21 完成狀態：** 目前活動視圖唯一 CAD（ImportInstance `13379416`）與選取主管 `13563852` 已完成唯讀 Route Graph 驗證：579 條消防 CAD 線段正規化為 875 節點／578 管段／92 個交點，選取主管所在連通區含 101 管段；50 顆灑水頭可由該連通區到達，368 顆被明確標記為其他 CAD 連通區，1 顆超出 500 mm 平面容差。每個節點／管段保留來源 fragment、圖層與顏色，候選路徑保留邊 ID 與未採用原因。驗證過程為唯讀，沒有模型寫入。完整證據見 `docs/validation/fire_branch_m2_route_graph_20260821.md`。此完成判定只涵蓋「活動視圖唯一 CAD＋目前選取主管」範圍，不代表多主管自動選擇、SVG 編輯或 Revit 建模已完成。

### M3：TopologyPlan v5 與 SVG 同源

工作：

- 新 schema、舊版 Adapter 與 plan hash。
- SVG 改為只讀 v5 plan。
- 移除 SVG 自行修正位置／交點的判斷。

驗收：plan 與 SVG 的 segment／junction／reducer ID 一一對應；相交處不因排版變三通。

### M4：有限 SVG 編輯

工作：

- 實作結構化 edit commands、revision、Undo／Redo。
- 有多顆灑水頭候選時，SVG 視窗以灑水頭為單位列出候選，採用結果寫回同一份拓樸計畫；不直接拖曳幾何。
- 編輯後重跑純拓樸驗證。

驗收：舊 hash 的修改被拒絕；不合法編輯不可進預檢；自由拖曳不在本階段。

### M5：ExecutionPlan 與 Revit 預檢／沙盒

工作：

- 建立 ExecutionCompiler 與 ExecutionEngine。
- C# 移除主管／四通／變徑的二次判斷。
- 用 Adapter 呼叫既有穩定灑水頭垂管路徑。

驗收：SVG、ExecutionPlan 與 Revit 實際結果使用同一 revision；完整沙盒同時證明管件、管徑、可達性、長度與回復。

### M6：無 CAD／統一管徑頁籤

工作：

- GUI 分頁。
- 新增固定管徑來源 Adapter。
- 共用 M5 建模核心。

驗收：不讀 CAD 也可建立；不複製建模引擎；高度設定保持既有方式。

### M7：StructuralObstacleQuery（只讀）

工作：

- 從開孔定位抽取 Link／Solid 查詢模組。
- 僅回傳梁與支管交會資料。

驗收：連結與本機梁座標正確；不建立管；開孔定位原功能回歸通過。

### M8：避梁 TopologyPlan 與 SVG 預覽

工作：

- 產生四彎頭避梁路徑、相鄰梁區間合併、動態淨距。
- SVG 加平面與簡化剖面資訊。

驗收：主管不變、灑水頭不動、管徑不變；每個避梁點可追溯到梁 ID 與計算依據。

### M9：避梁 Revit 沙盒與正式建立

工作：

- ExecutionCompiler 加入 bypass operations。
- 以實際 Routing Preferences 建四彎頭。

驗收：至少涵蓋單梁、連續梁、空間不足與 Link 梁；全通過才允許 commit。

### M10：整合、遷移與發布

工作：

- 移除已無呼叫的舊重算路徑。
- 更新 README、操作手冊、版本紀錄與安裝包。
- 同步至 staging 前做差異、機密、測試產物與安裝檔檢查。

驗收：本機來源、部署 DLL、安裝包 DLL SHA 可追溯；Revit 需重開時明確標示；Release 含安裝資產及完整版本說明。

## 13. 測試矩陣

### 13.1 純程式測試

- 直線／L／U／雙 L 主管。
- 三通／四通同徑及異徑主管延續。
- 主管候選 CAD 證據優先。
- 單選末端仍保留完整路徑。
- 文字 > 線色 > 圖層 > 全圖規則。
- 真交點切分與 SVG 同源。
- edit revision／hash 衝突。
- 相鄰梁避讓區間合併。
- 無 CAD 固定管徑 Adapter。

### 13.2 Revit 契約測試

- Snapshot 完整性。
- Routing Preferences 與可用管徑。
- Connector 方向與 owner 對應。
- Execution operation 依賴順序。
- request／response／plan 不截斷。

### 13.3 活動模型沙盒測試

每次可能影響建模的修改都要在同一活動模型完成：

- 所有計畫四通／三通成功。
- 大管主體、支管小管及異徑方向正確。
- 無零長度、過短或異常長管。
- 所有指定灑水頭從指定主管可達。
- 灑水頭位置不變。
- 沙盒完整回復，正式模式一次 Undo 可復原。

純 Python 測試與 DLL 編譯成功不能替代這一層證據。

## 14. 效能與生命週期邊界

- GUI 不在 UI thread 做 DWG 全圖解析、Solid 交集或大型 SVG 排版。
- Snapshot、plan 與 artifact 以 document fingerprint、view、CAD hash、settings hash 快取。
- Revit 文件、視圖、CAD、選取或設定改變時，相關快取失效。
- Worker／listener 必須可取消並在視窗關閉後釋放；不得留下造成電腦持續卡頓的輪詢程序。
- 預覽與 DirectContext3D 資源在更新、取消、視窗關閉及文件關閉時自動清理。
- 不以「永不停止」的 Connector 圖搜尋換取完整性；用 visited set、系統邊界與可取消工作控制。

## 15. 明確不在本輪範圍

- 主管自動避梁。
- 其他 MEP 碰撞避讓。
- 自由手繪 SVG 路徑。
- 自動移動灑水頭。
- 45° 避梁或多方案成本最佳化。
- 多樓層自動穿越與立管系統設計。
- 自動修改使用者既有主管的系統、管型或管徑。
- 把 SVG 當成 Revit 幾何的替代品。

## 16. Luna 的執行規則

1. 先閱讀專案 `AGENTS.md` 與本文件。
2. 一次只執行一個里程碑；開始下一階段前先交付上一階段證據。
3. 修改前先查看最小相關檔案與 diff，不整檔重寫。
4. 新舊契約過渡必須用 Adapter，不得同時維護兩套業務判斷。
5. 未經使用者要求，不部署 DLL、不更新 staging、不推 GitHub、不建立 Release。
6. Revit 開啟時不得覆寫已載入 DLL；GUI 可熱更新的部分與需重開 Revit 的 DLL 必須分開說明。
7. 發現本文件與實際程式矛盾時，先提出證據與影響，不可自行選一個版本繼續。
8. 不以固定數字代替配件需求；距離由實際配件幾何、Routing Preferences、管徑、ShortCurveTolerance 與使用者淨距推導。
9. 不因局部失敗抹除診斷證據；測試模型仍完整 Rollback，完整 payload／artifact 必須保存。
10. 每次交付需列出：修改檔案、未修改穩定區、測試、活動模型證據、剩餘風險及是否需要重開 Revit。

## 17. 建議給 Luna 的第一個任務

只執行 M0 與 M1，不做 GUI、SVG、避梁或正式建模修改：

> 在 `E:\Desktop\Codex\SC REVIT` 建立消防支管現況基線與 `fire_branch_revit_snapshot.v1`。使用 Revit 實際 Connector／管件關係，從使用者選定主管種子輸出直線、L、U、雙 L 及含異徑主管圖。不得修改既有灑水頭垂管建立程式，不得部署。交付 schema、Adapter、單元測試、活動模型只讀輸出、來源與本機部署 DLL 雜湊差異，以及下一階段是否具備條件的結論。

完成 M1 前，不開始 CAD Route Graph 或 SVG 編輯器。
