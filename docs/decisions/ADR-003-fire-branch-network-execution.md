# ADR-003：消防支管路網的唯一建模執行方式

## 狀態

部分由 ADR-004 取代，2026-08-17。ADR-004 取代「直接四通相鄰驗證」及執行交點來源；其餘垂管凍結與 Connector 生命週期規則仍有效。

## 問題

先前的建模流程同時讓拓樸分析與 Revit Routing Preferences 決定變徑位置。當雙側支管管徑不同時，程式把不同管徑的兩端直接交給 `NewCrossFitting`，Revit 可能自動加入變徑；程式又在四通外側建立另一組變徑。結果包含：

- 四通以較小支管為出口，形成小轉大。
- `BreakCurve`、改管徑或建立管件後仍使用舊的 `Pipe`／`Connector` 包裝物件，產生 `referenced object is not valid`。
- 四通修改意外改動已確認成功的 DN25 垂管與灑水頭連接流程。
- 程式碼契約測試通過，但未約束整批路網的實際建立順序與直接連線。

專案已保留一份使用者確認可完成整批建立及灑水頭系統連通的基準 DLL。該基準只剩四通變徑方向錯誤，因此垂管、灑水頭與非四通行為不得在本次修正中改動。

## 官方 API 邊界

- `PlumbingUtils.BreakCurve` 成功時回傳新管段的 `ElementId`，失敗時可能回傳 `InvalidElementId`。
- `NewCrossFitting` 的四個 Connector 必須分屬不同管段、屬於相同 Domain，且由 Pipe 或 FlexPipe 擁有；必要時 Revit 可能自動加入 Transition。
- `NewTeeFitting` 的第三個 Connector 明確是支管端。
- `RoutingPreferenceManager.GetMEPPartId` 應在建立前以實際管徑條件確認可用管件。
- `Regenerate` 後，原有 API 包裝物件可能失效；後續操作只可使用保存的 `ElementId` 重新取得元素與 Connector。

參考：

- [Revit 2024 Routing Preferences](https://help.autodesk.com/cloudhelp/2024/ENU/Revit-API/files/Revit_API_Developers_Guide/Discipline_Specific_Functionality/MEP_Engineering/Revit_API_Revit_API_Developers_Guide_Discipline_Specific_Functionality_MEP_Engineering_Routing_Preferences_html.html)
- [Revit 2024 Transactions](https://help.autodesk.com/cloudhelp/2024/ENU/Revit-API/files/Revit_API_Developers_Guide/Basic_Interaction_with_Revit_Elements/Revit_API_Revit_API_Developers_Guide_Basic_Interaction_with_Revit_Elements_Transactions_html.html)
- [Revit 2024 Regeneration](https://help.autodesk.com/cloudhelp/2024/ENU/Revit-API/files/Revit_API_Developers_Guide/Basic_Interaction_with_Revit_Elements/Transactions/Revit_API_Revit_API_Developers_Guide_Basic_Interaction_with_Revit_Elements_Transactions_Getting_Element_Geometry_and_AnalyticalModel_html.html)

## 決策

### 1. 拓樸計畫是唯一真實來源

SVG 與 Revit 建模都使用同一份 `topology_plan`。執行層不得重新推測四通出口管徑、變徑方向或變徑位置。

每個四通節點至少包含：

- 主管管徑。
- 兩側支管共同出口管徑。
- 兩側原始支管管徑。
- 各側變徑距離與方向。

### 2. 四通只接共同管徑端

以 DN100 主管、DN40 與 DN32 雙側支管為例：

1. 兩側支管先在四通外側切分。
2. 靠近四通的短管都設為 DN40。
3. DN32 側在短管外側建立明確的 DN40→DN32 變徑。
4. 主管在交點切成兩段。
5. `NewCrossFitting` 只接 DN100、DN100、DN40、DN40 四個端點。
6. 四個管端都必須直接引用同一個四通，不接受 Revit 額外插入未列於計畫的管件路徑。

### 3. Connector 不跨越模型變更邊界

以下任一動作後，原 `Pipe`、`FamilyInstance`、`Connector` 只視為失效候選：

- `BreakCurve`
- 改管徑
- `NewTransitionFitting`
- `NewTeeFitting`
- `NewCrossFitting`
- `Regenerate`
- 子交易 Commit 或 Rollback

跨階段只保存 `ElementId` 與拓樸幾何意圖。每一階段開始時由 `Document.GetElement` 重新取得元素，再重新找 Connector。

### 4. 固定建立順序

1. 唯讀前置檢查：文件、主管、系統、樓層、管類型、所有計畫管徑及 Routing Preferences。
2. 建立水平支管幾何並套用沿程管徑。
3. 依既有成功基準建立三通出口短管、落水變徑、DN25 落水段及灑水頭連接。
4. 建立四通外移變徑，得到兩個共同管徑端。
5. 依主管方向依序處理交點：切主管、重新取得四管段、建立直接四通。
6. 完成所有實體連線後才統一系統類型。
7. 由主管做實體 Connector 圖遍歷，確認所有計畫灑水頭可達，並核對未連接管端、管徑與系統類型。
8. 完整成功時，沙盒模式 Rollback；正式模式 Assimilate 為一個 Undo。局部失敗的保留或復原依 ADR-006，由使用者在 Revit 內明確決定。

### 5. 成功基準凍結

四通重作期間，下列方法以來源雜湊鎖定，避免修改四通時再次破壞垂管：

- `TryConnectCompletedDropToSprinkler`
- `CreateFireDropWithTransition`

若確實需要修改，必須另立議題、更新基準並重新完成 Revit 整批驗證，不能混入四通修正。

## 專案實測設定

2026-08-17 由 BIM Agent 唯讀檢查 PipeType `13166389`（`FS_消防撒水管`）：

- Crosses 規則：2 組。
- Transitions 規則：2 組。
- Junctions 規則：2 組。
- DN100 × DN100 × DN40 × DN40：可解析為 `FS_消防撒水管_十字_焊接`（ElementId 13163460）。
- DN40→DN32、DN32→DN25、DN40→DN25：可解析為 `FS_消防撒水管_變徑_螺牙`（ElementId 13161948）。

## 驗證門檻

- 程式契約：四通只能使用兩組共線 Connector；禁止重新引入不對稱 Connector 排序。
- 回歸保護：成功基準的垂管方法來源雜湊不變。
- 編譯：Revit 2024 DLL 成功建立。
- Revit 沙盒：整批建立完成、四通方向正確、每個灑水頭由主管可達、沙盒完整回復。
- 正式部署：只在 Revit 關閉後進行，並核對來源與部署 DLL SHA-256。
