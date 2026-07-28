# Revit 排水影片「同步斜率」機制逆向與工程規格

## 結論

影片沒有提供足夠證據證明存在一顆可讀名稱為「同步斜率」的外掛按鈕。
目前能直接確認的是：

1. 約 `07:08` 出現 Revit 原生管道繪製／修改狀態的坡度控制，畫面選定
   `1.0000%`，下拉選項可見 `0.0000%`、`1.0000%`、`2.0000%`、
   `57.7350%`、`100.0000%`。
2. 約 `06:15` 至 `06:57`，影片逐一選取短支管、主管旁的支管及接管後的
   管段；屬性面板可讀到 `坡度 1.0000%` 與端點／中心線高程。
3. 畫面最後仍保有管段、彎頭及接入主管的管件拓撲，但影片未顯示同一
   ElementId／UniqueId 的完整操作前後資料，無法判定外掛是移動既有元素、
   刪除重建，或只是以原生坡度設定新建管段。
4. 約 `04:30` 的字幕「這時候有另外兩個功能」後，畫面主要是多選一組支管
   與彎頭、複製／重組及接管示範；沒有看到坡度欄位或坡度變更。因此不能把
   這一段直接認定為「同步斜率」。

所以，本文件把影片內容定義為：

> 影片可觀察到的「1% 坡度建模、選管與接管後保持拓撲」行為，以及由此可
> 工程化的斜率同步候選規格。

這不是對影片內部算法的還原，也不是證明影片作者實作了下述所有機制。

## 證據分級

- **直接證據**：畫面、字幕或 Revit UI 可直接讀取。
- **合理推論**：能解釋畫面，但影片未顯示內部資料或命令狀態。
- **未知**：影片不足以判斷，不得當成需求已確認。

## 可重現時間點

| 時間碼 | 畫面事件 | 證據等級 | 判讀 |
|---|---|---|---|
| `04:30` | 字幕：「這時候有另外兩個功能」 | 直接證據 | 只確認後續另有兩種操作，不確認名稱 |
| `04:31` | 一組末端支管／彎頭呈藍色；屬性面板顯示已選取多個元素，數量約 6 | 直接證據 | 操作範圍不只單一 Pipe，可能包含 Pipe Fitting |
| `04:32–04:48` | 三組器具支管被依序選取、取消選取，最後展示接管結果 | 直接證據 | 沒有坡度 UI，排除為「已證實的同步斜率命令」 |
| `06:15` | 一支短管呈藍色；屬性面板可見坡度 `1.0000%` 及數個高程欄位 | 直接證據 | 只證明目前所選 Pipe 為 1%，不證明此刻有修改坡度 |
| `06:22` | 同區另一支短管被選取；長度／端點高程與前一支不同 | 直接證據 | 是不同元素的屬性，不可當成同一元素變更前後 |
| `06:29` | 主管旁多支短支管，單支被選取 | 直接證據 | 有逐支處理的畫面，但來源／目標角色未顯示 |
| `06:36` | 多支短支管出現藍色選取狀態 | 直接證據 | 支援「批次或多選」推論，但未顯示完成鍵 |
| `06:43` | 一支接到主管／立管附近管件的斜支管被選取 | 直接證據 | 顯示接管後仍可選取 Pipe |
| `06:50` | 支管及接頭呈橘色預選／高亮 | 直接證據 | 只證明游標指向相連元素，不證明拓撲遍歷算法 |
| `06:57` | 視角回到多組完成接管的管線 | 直接證據 | 外觀上連接仍存在 |
| `07:04` | 一支較長管段被選取／進入繪製相關狀態 | 直接證據 | 尚未看到坡度選項 |
| `07:08` | Revit 原生坡度下拉展開，選定 `1.0000%` | 直接證據 | 這是本片最明確的坡度 UI 證據 |
| `07:08` | 同一畫面可見向上／向下斜升控制與偏移欄位 | 直接證據 | 表示坡度有方向與參考高程語意，不只是無號百分比 |
| `07:13–07:28` | 檢查三支管的開放端、管身與端部 | 直接證據 | 沒有可讀的同步命令名稱，也沒有失敗訊息 |

時間碼來自 YouTube 播放器顯示。影片內有剪接與快速視角變換，因此上述時間碼
適合重現畫面，不應用來推算每個滑鼠事件的精確耗時。

## GUI 與命令狀態逆向

### 可確認

- `07:08` 的坡度欄位位於 Revit 管道繪製／修改的原生 contextual ribbon，
  不是本專案 GUI。
- 坡度值為 `1.0000%`。
- 可見向上／向下的斜升方向控制。
- 屬性面板在選取 Pipe 時顯示坡度與多個端點／中心線高程。

### 合理推論

- 使用者可能先以 1% 建立或延伸管，再讓接管管段沿相同排水方向下降。
- `06:15–06:57` 的逐支選取可能是接入主管命令的批次輸入，而不是一個獨立
  的坡度同步命令。
- 完成後管件仍在畫面中，表示結果至少在視覺上保持連接。

### 未知

- 外掛按鈕是否真的名為「同步斜率」。
- 該功能位於 Ribbon、split button 子項或鍵盤快捷鍵。
- 來源管與目標管的選取先後。
- 使用者是否先選來源 Pipe，再連續選多個目標 Pipe。
- Enter 是否完成多選、Esc 是否只取消當前目標或結束整個命令。
- 哪一端是基準端／固定端。
- 固定端是由 FlowDirection、較低高程、已連接 connector，或使用者點選決定。
- 坡度變更時，是移動上游端、下游端、整支 Pipe，還是重建 Pipe。
- 彎頭／斜 T／Y 是沿用、移動或刪除重建。
- Undo 是一筆、逐支一筆，或由 Revit 原生命令自行管理。
- 影片沒有顯示錯誤對話框，無法從影片列出實際失敗條件。

## 不可由畫面投影推定的事項

影片主要使用旋轉後的 3D 視圖。畫面上「向左、向右、向上、向下」不能直接
當成 Revit 世界座標或排水流向。工程實作必須使用：

- `LocationCurve.Curve` 的 XYZ 端點。
- connector 的 `Origin`、`BasisZ`、`Domain`、`ConnectorType`。
- 主管的實際 3D 曲線與水平投影長度。
- 已確認的下游端及有號坡度。

不得以螢幕像素方向、目前 ViewDirection 或 3D 視角判斷坡度方向。

## Revit 2024 工程語意

### 建議功能定義

「同步斜率」應明確定義成：

> 讀取來源 Pipe 的有號坡度與排水方向，在保持指定目標 Pipe 固定 connector
> 的前提下，重新計算目標可動端 XYZ；必要時在受控範圍內重建彎頭，完成後
> 驗證物理 connector 拓撲及沿下游方向單調下降。

這與「把 `RBS_PIPE_SLOPE` 設成相同值」不同。坡度應是端點幾何的結果，
參數只用來讀回與驗證。

### 前置條件

最小 MVP 建議只接受：

- Revit 2024 可修改文件。
- 剛性圓形 Pipe，`LocationCurve.Curve` 為直線。
- 一支來源 Pipe。
- 一支或多支互不相連的目標 Pipe，或一條沒有分支的局部 Pipe chain。
- 來源坡度可由兩端 XYZ 與已知下游方向解析。
- 每個目標只有一個固定端。
- 相同或明確允許的 System Type、Pipe Type 與直徑。
- 目標未 pinned、不在 Link／Group，且工作共享可借用。
- 受控範圍內沒有 Tee、Cross、Y、斜 T、reducer 或設備固定 connector。
- 可使用已驗證 FamilySymbol 重建中間 45° elbow。

影片展示了含支管及主管接點的完整情境，但沒有證明任意既有分支網路可安全
重新計坡。因此分支點應先留在接幹管功能，不納入同步斜率 MVP。

## 資料模型

```text
SlopeSyncRequest
  document_fingerprint
  source_pipe_unique_id
  target_pipe_unique_ids[]
  requested_fixed_end_mode
  explicit_fixed_connector_signature?
  execution_mode: preview | commit

SignedSlopeSource
  slope_ratio
  downstream_endpoint_index
  downstream_resolution
  source_endpoints_xyz[2]
  source_connector_signatures[2]

PipeSnapshot
  element_id
  unique_id
  type_id
  system_type_id
  level_id
  diameter
  endpoints_xyz[2]
  connector_signatures[]
  physical_connections[]
  slope_readback

FittingSnapshot
  unique_id
  family_symbol_id
  connector_signatures[]
  connector_role_map
  transform

SlopeSyncPlan
  source
  targets[]
  fixed_connector_by_target
  proposed_endpoints_by_target
  fittings_to_preserve[]
  fittings_to_rebuild[]
  topology_hash_before
  validation_requirements[]
  rejection_codes[]
```

Connector signature 至少包含 owner UniqueId、Origin、BasisZ、Domain、
ConnectorType、直徑。不能只保存 connector 集合索引。

## 固定端與有號坡度

### 固定端候選規則

依安全性排序：

1. 使用者明確點選的 endpoint connector。
2. 唯一連到設備、主管或編輯範圍外元素的實體 connector。
3. 已確認的下游 connector。
4. 只有一端 connected 時，固定 connected 端。

以下情況不可自動猜測：

- 兩端都 connected 且兩個邊界都不可移動。
- 兩端都開放，沒有下游證據。
- connector FlowDirection 未提供有效方向，且兩端高程相同。
- 目標屬於 cycle 或分支網路。

### 幾何計算

對非垂直直管，以固定端 `F` 與可動端目前 XY `Mxy` 計算：

```text
horizontal_run = hypot(M.x - F.x, M.y - F.y)
delta_z = horizontal_run * slope_ratio
```

新可動端高程由「固定端是上游或下游」決定：

```text
固定下游端：Z(movable_upstream) = Z(fixed_downstream) + delta_z
固定上游端：Z(movable_downstream) = Z(fixed_upstream) - delta_z
```

`slope_ratio` 是正的大小；方向由拓撲與下游端另外保存。不得用畫面左右方向
決定正負號。

## 演算法候選

### 候選 A：單一直管端點調整

適用於兩端開放，或只有一個固定 connector 的單一直管。

1. 建立來源與目標快照。
2. 解析來源有號坡度及目標固定端。
3. 保留目標可動端 XY，重新計算 Z。
4. 在 `SubTransaction` 中設定新的 `LocationCurve.Curve`。
5. `Document.Regenerate()`。
6. 重新解析 connector，而不是沿用舊 connector 物件。
7. 驗證坡度、端點、短管容差及 topology hash。
8. 任一失敗即 rollback。

這是最適合作為第一個 Revit 2024 探針的方案。

### 候選 B：無分支 Pipe chain 重建

適用於中間只有已驗證 45° elbow 的局部鏈。

1. 固定唯一邊界 connector。
2. 沿拓撲排序 Pipe 與 elbow。
3. 依水平累積距離計算各節點 Z。
4. 在單一 `TransactionGroup` 中重建必要 Pipe／elbow。
5. 每段完成後 regenerate、重配 connector signature。
6. 驗證 elbow 角度、takeout、物理連通及坡度單調性。
7. 全部通過後 `Assimilate()`，形成一次 Undo。

此方案比 A 風險高，需先經實機探針。

### 候選 C：只在接幹管建立新路徑時繼承坡度

不編輯任意既有網路。把來源或使用者指定的 1% 坡度輸入現有
`DrainagePlan`，由接幹管求解器建立新支管、45° 路段及 junction。

這最接近目前專案已實作的能力，也最符合影片 `06:15–06:57` 顯示的
「支管接入主管後保持 1%」外觀。它不等於獨立的既有管同步斜率工具。

## Enter、Esc 與 Undo 規格

影片沒有直接證據，以下是建議工程契約。

### 單次命令模式

- 選來源 Pipe 後，進入多目標選取。
- Enter／Revit Finish：提交目前有效目標集合。
- 第一次 Esc：取消目前尚未完成的選取。
- 第二次 Esc 或沒有已選目標時 Esc：結束命令，不修改模型。
- `OperationCanceledException` 應轉成 `USER_CANCELLED`，不能顯示為程式錯誤。
- Preview 階段不得修改正式 Pipe。
- Commit 全部置於一個 `TransactionGroup`；成功後 `Assimilate()`，讓使用者
  一次 Undo 撤回整批同步。
- 單一目標失敗時，預設整批 rollback；若未來提供「略過失敗項」，必須在
  UI 明示部分成功，不能靜默留下混合狀態。

### 跨手動編輯工作階段

若功能要像既有評估文件一樣允許使用者中途手動修改，就不能保持 transaction
開啟。Begin、使用者編輯、Finish 是不同 Undo 項目，Cancel 必須依快照反向
重建。這是另一種產品語意，不能和單次「同步斜率」命令混用。

## 拒絕碼

| 拒絕碼 | 條件 |
|---|---|
| `SOURCE_PIPE_INVALID` | 來源不是可讀的剛性直管 |
| `SOURCE_SLOPE_UNRESOLVED` | 無法解析來源坡度大小 |
| `SOURCE_DOWNSTREAM_UNRESOLVED` | 無法解析來源有號方向 |
| `TARGET_PIPE_INVALID` | 目標不是支援的 Pipe |
| `TARGET_VERTICAL_UNSUPPORTED` | 目標為垂直管，水平坡度無定義 |
| `TARGET_NONLINEAR_UNSUPPORTED` | 目標 LocationCurve 不是 Line |
| `FIXED_END_UNRESOLVED` | 不能唯一決定固定端 |
| `MULTIPLE_FIXED_BOUNDARIES` | 兩端皆為不可移動邊界 |
| `BRANCH_TOPOLOGY_UNSUPPORTED` | 編輯範圍含 Tee／Y／Cross／斜 T |
| `REDUCER_UNSUPPORTED` | 編輯範圍含變徑 |
| `FITTING_REBUILD_UNRESOLVED` | 找不到已驗證 fitting symbol／connector role |
| `SYSTEM_TYPE_MISMATCH` | 系統類型不相容 |
| `DIAMETER_MISMATCH` | 管徑或 connector 尺寸不相容 |
| `ELEMENT_NOT_EDITABLE` | pinned、Group、Link、Design Option 或 ownership 問題 |
| `CONSTRAINT_LOCKED` | 尺寸、對齊或全域參數鎖定 |
| `SHORT_CURVE_VIOLATION` | 新管段低於 ShortCurveTolerance／最短切管長度 |
| `FITTING_ANGLE_OUT_OF_RANGE` | 彎頭角度無法由指定族建立 |
| `REGENERATION_FAILED` | `Document.Regenerate()` 失敗 |
| `CONNECTIVITY_DRIFT` | 完成後物理 connector 關係與計畫不符 |
| `SIGNED_SLOPE_MISMATCH` | 坡度值正確但下游方向相反 |
| `TOPOLOGY_HASH_MISMATCH` | 執行前模型已變更 |
| `USER_CANCELLED` | 使用者取消，模型不得留下部分修改 |

## 驗證規格

完成後必須驗證：

- 來源 Pipe 未被意外修改。
- 固定 connector 的 XYZ 在容差內不變。
- 目標水平投影長度與預期一致。
- `abs(delta_z / horizontal_run)` 等於來源坡度。
- 沿確認下游方向 Z 單調下降。
- `RBS_PIPE_SLOPE` 讀回與幾何坡度一致；不把參數值當唯一證據。
- 每個預期 connector 都是物理 piping connection。
- 沒有新增孤立 fitting、短管、反坡或多餘主管切口。
- fitting FamilySymbol、角度、run／branch connector role 符合計畫。
- `Document.Regenerate()` 後 topology hash 與計畫一致。
- Undo 一次可回到執行前狀態。

## 測試案例

1. 開放直管，固定端 0，同步為 1%；水平距離 1000 mm，另一端高差應為
   10 mm。
2. 同一案例固定端 1；結果應反向計算，但下游仍下降。
3. 旋轉 3D 視圖後重跑；XYZ 結果必須完全相同，證明沒有使用畫面投影。
4. 來源 1%、目標 0%，同步後讀回及幾何均為 1%。
5. 來源與目標方向相反；應依下游資料處理，不可只複製無號百分比。
6. 目標垂直管；拒絕 `TARGET_VERTICAL_UNSUPPORTED`。
7. 兩端都接到不可移動設備；拒絕 `MULTIPLE_FIXED_BOUNDARIES`。
8. 兩 Pipe 加一個已驗證 45° elbow 的無分支鏈；探針驗證平整、同步及復原。
9. 編輯範圍含 Y／斜 T；MVP 拒絕，不移動主管 junction。
10. 模型含 pinned、Group、工作共享無 ownership；各自回傳明確拒絕碼。
11. 人為製造 ShortCurveTolerance；整個 TransactionGroup rollback。
12. regenerate 後 connector 對應改變；以 signature 重配，不使用舊 index。
13. 多目標第 3 支失敗；預設整批 rollback，前兩支不得殘留。
14. 選取後 Esc；模型 hash 不變。
15. 成功同步多支後一次 Undo；所有 Pipe／fitting 回復。

每個實機案例應記錄 Revit 2024 build、RVT 測試模型、ElementId、UniqueId、
執行前後端點、connector signature、topology hash 與 journal。

## 與「斜率編輯工作階段」評估的對照

對照文件：
`docs/drainage_temporary_slope_edit_assessment.md`

| 面向 | 本影片可觀察行為／同步斜率候選 | 既有斜率編輯工作階段 |
|---|---|---|
| 主要目的 | 讓目標管採用來源／指定的 1% 坡度 | 暫時平整，允許手動編輯，再恢復坡度 |
| 影片證據 | 原生 1% 坡度 UI、選管、接管後外觀 | 影片未顯示 Begin／Finish／Cancel |
| 固定端 | 影片未知；工程上必須明確 | 文件建議固定下游端 |
| 生命週期 | 建議單一 preview／commit 命令 | 跨多次使用者手動編輯的持久工作階段 |
| Undo | 建議整批一次 Undo | Begin、手動編輯、Finish 分屬不同 Undo |
| 快照 | 單次命令可只保存 transaction 內快照 | 必須 DataStorage／Extensible Storage 持久快照 |
| 拓撲範圍 | MVP 單管或無分支 chain | MVP 同樣建議無分支局部 chain |
| 相同風險 | 固定端、connector 重配、管件重建、反坡 | 相同 |

兩者底層幾何與驗證可共用，但產品狀態機不同。不能因影片出現 1% 坡度欄位，
就認定影片實作了「暫時去坡再恢復」。

## 與現有接幹管功能的對照

現有 `DrainageHandler` 已具備：

- `slope_ratio` 輸入及 1% 驗證。
- 主管下游解析：使用者指定、connector flow、幾何坡度。
- 依 XYZ、45° takeout、最短直管及 junction 設定建立新路徑。
- 軸向直接、單 45°、雙 45°等路由候選。
- 有界來源高程補償。
- 建立後的坡度、管件及 topology 驗證。

現有接幹管功能與同步斜率的差異：

| 能力 | 現有接幹管 | 同步斜率候選 |
|---|---|---|
| 操作對象 | 從器具／支管 connector 建立新路徑接主管 | 修改既有目標 Pipe／Pipe chain |
| 坡度來源 | GUI／Agent 輸入 `slope_ratio` | 來源 Pipe 或明確輸入 |
| 固定端 | 主管 tie 與來源 connector 共同約束 | 必須指定目標 Pipe 的固定 connector |
| 拓撲 | 可建立、切主管及放置 junction | MVP 不應修改含分支 junction 的既有網路 |
| 幾何策略 | 建立新 Pipe／fitting | 移動端點或受控重建既有 chain |
| Undo／取消 | 單次預覽與建立 | 單次同步可共用；跨編輯工作階段則不同 |

可共用的模組：

- downstream resolver。
- signed slope 幾何驗證。
- connector signature／topology hash。
- fitting profile、takeout 及 ShortCurveTolerance 檢查。
- TransactionGroup／SubTransaction rollback。
- 預覽與拒絕碼呈現。

不可直接共用的部分：

- `DrainagePlan` 的「建立新支管」不能直接當成「修改既有管」。
- 現有有界來源高程補償只接受特定未連接近水平來源 Pipe；不等於任意 connected
  target 的坡度同步。
- 現有接幹管允許處理 Y／斜 T junction；同步斜率 MVP 應把 junction 當成
  編輯邊界，而不是移動它。

## 建議決策

1. 不把 `04:30` 的「另外兩個功能」登記成已確認的同步斜率按鈕。
2. 把 `07:08` 登記為 Revit 原生 1% 坡度設定證據。
3. 現階段先實作唯讀 `AnalyzeSlopeSync`：
   - 回報來源有號坡度。
   - 標示每個目標固定端與預計可動端。
   - 回報建議新高程、拓撲邊界及拒絕碼。
4. 第一個寫入探針只支援單一無分支直管，固定端由使用者明確指定。
5. 探針通過後，再支援中間只有已驗證 45° elbow 的無分支 chain。
6. 含 Y／斜 T／主管分割的情境繼續交給現有接幹管建立流程，不納入同步斜率
   MVP。
7. 「斜率編輯工作階段」維持獨立工作項；不得與單次同步命令合併成模糊的
   Begin／Finish 狀態。

