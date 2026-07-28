# Revit 2024 排水管暫時移除斜率功能評估

## 結論

此功能**技術上可行，但只能做成有範圍與拒絕條件的「斜率編輯工作階段」**，不能承諾任意排水網路一鍵去坡、任意編輯後再完整還原。

目前不建議立刻併入排水接幹管主流程。應先完成現有路徑求解、高程容差與立管走法修正，再獨立製作探針與 MVP。原因不是介面工作量，而是暫時去坡會同時改變管段端點、管件位置、connector 拓撲與接管高程；若把這些變更當成單純設定 `RBS_PIPE_SLOPE`，容易留下斷線、反坡或錯誤管件。

建議分兩階段：

1. 先做唯讀「可編輯性檢查」與 Revit 2024 實機探針，不修改正式模型。
2. 探針通過後，只實作無分支局部管路的 MVP；斜 T、Y、主管分割與多分支網路先拒絕。

## 官方能力與限制

### Revit 本身支援延後套用坡度

Revit 2024 的 Slope Editor 可對整個系統、部分系統或單一管段套用坡度，官方也明確指出可以先完成配置，再延後套用坡度。這證明「先平面編輯，再重新計坡」符合 Revit 的產品邏輯，但不代表外掛能直接呼叫同一套內部求解器。

- [Use the Slope Editor](https://help.autodesk.com/cloudhelp/2024/ENU/Revit-MEPEng/files/GUID-E5193479-D580-4CEC-BAA9-18260417D283.htm)
- [Draw Sloped Pipes](https://help.autodesk.com/cloudhelp/2024/ENU/Revit-MEPEng/files/GUID-23F109EE-7230-4CB5-B0DC-C03AF2FF1A49.htm)

官方文件亦說明，連接不同高程管線時可以選擇直接連接，或依目前坡度加入垂直段。這與本專案目前的「保留來源方向、必要時加入垂直／45°路段」規則一致。

### API 可讀寫幾何，但坡度不能只當成一個參數

本機 Revit 2024 `RevitAPI.xml` 確認：

- `LocationCurve.Curve` 可讀寫曲線型元素的位置曲線。
- `ParameterTypeId.RbsPipeSlope` 存在。
- 一般參數只有在 `Parameter.IsReadOnly == false` 時才可 `Set`。

官方並未保證所有 Pipe 的 `RBS_PIPE_SLOPE` 都可直接寫入，也未保證直接改此參數會自動重建相連管件。因此工程上應把坡度視為**端點高程所形成的幾何結果**，`RBS_PIPE_SLOPE` 只用來讀回與驗證，不作為唯一寫入機制。

- [Parameters](https://help.autodesk.com/cloudhelp/2024/CHS/Revit-API/files/Revit_API_Developers_Guide/Basic_Interaction_with_Revit_Elements/Parameters/Revit_API_Revit_API_Developers_Guide_Basic_Interaction_with_Revit_Elements_Parameters_Parameter_html.html)
- [Built-In Parameters](https://help.autodesk.com/cloudhelp/2024/ENU/Revit-API/files/Revit_API_Developers_Guide/Basic_Interaction_with_Revit_Elements/Parameters/Revit_API_Revit_API_Developers_Guide_Basic_Interaction_with_Revit_Elements_Parameters_Built_In_Parameters_html.html)

### Connector 與管件必須一起處理

Revit connector 的 `AllRefs` 同時包含物理與邏輯連接，遍歷拓撲時必須再檢查 connector type。`ConnectTo` 可能自動產生 fitting，也可能因 domain、方向、位置或既有連線而失敗。

Revit 2024 API 能建立 elbow、tee 與 transition fitting，但每一種都有 connector domain、擁有者、角度、距離及 tolerance 限制。特別是：

- 彎頭建立可能因角度、距離或 tolerance 失敗。
- Tee 的第三個 connector 必須是支口。
- Transition 需要同 domain，且 connector 必須符合建立條件。
- `PlumbingUtils.BreakCurve` 會新增一段 Pipe；分割後不能假設原 ElementId 或 connector index 仍代表原本拓撲。

- [Connectors](https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API/files/Revit_API_Developers_Guide/Discipline_Specific_Functionality/MEP_Engineering/Revit_API_Revit_API_Developers_Guide_Discipline_Specific_Functionality_MEP_Engineering_Connectors_html.html)  
  註：Autodesk 公開搜尋目前導向新版頁面；本次另以本機 Revit 2024 `RevitAPI.xml` 核對 `Connector.AllRefs`、`Connector.ConnectTo` 與 fitting 方法簽章。
- [MEP Element Creation](https://help.autodesk.com/cloudhelp/2024/ENU/Revit-API/files/Revit_API_Developers_Guide/Discipline_Specific_Functionality/MEP_Engineering/Revit_API_Revit_API_Developers_Guide_Discipline_Specific_Functionality_MEP_Engineering_MEP_Element_Creation_html.html)

### TransactionGroup 無法跨越任意手動編輯

Revit 的模型修改必須在 API transaction 中執行。`TransactionGroup.Assimilate()` 可以把群組內已完成的 transactions 合成一次 Undo，`RollBack()` 可以撤回群組內的 transactions；但 group 必須在所有內層 transaction 關閉後結束。

因此不應在「開始去坡」命令中保持一個 TransactionGroup，等待使用者任意編輯數分鐘後再關閉。開始、使用者編輯、完成會是不同的 Revit 操作：

- 「開始斜率編輯」是一筆 Undo。
- 使用者的手動編輯各自進入 Undo。
- 「完成並恢復斜率」是另一筆 Undo。

取消工作階段不能靠仍開啟的 TransactionGroup；必須依快照執行反向重建。這也表示取消可能無法保留使用者在同一範圍內的其他無關修改。

- [Transactions](https://help.autodesk.com/cloudhelp/2024/ENU/Revit-API/files/Revit_API_Developers_Guide/Basic_Interaction_with_Revit_Elements/Revit_API_Revit_API_Developers_Guide_Basic_Interaction_with_Revit_Elements_Transactions_html.html)

## 為什麼「暫時設為 0%」不是單純操作

假設一組已連接管路的上下游邊界高程不同，所有中間管段不可能在保持兩端連接的同時全部變成 0%。系統必須至少採取其中一種作法：

1. 移動其中一個邊界。
2. 暫時斷開邊界 connector。
3. 加入暫時垂直段或轉接段。
4. 建立一份可編輯副本，原管路保持不動。

第一種可能拖動主管或設備；第二、三種會讓正式模型暫時處於非最終狀態；第四種最安全，但使用者編輯的是副本，完成時仍要把差異投影回正式 MEP 拓撲。

因此這個功能的正確語意不是「清除坡度參數」，而是：

> 固定指定的下游基準點，暫時把受控範圍轉成可編輯幾何；完成後依使用者修改後的平面路徑、原坡度方向與坡度值，重新計算每個端點高程並重建 connector 拓撲。

「恢復原斜率」應指恢復原**坡度值、流向與固定端**，不是把所有 XYZ 恢復到編輯前，否則使用者的編輯會被消除。

## 建議工作流程

### 1. 開始斜率編輯

使用者選取一段 Pipe，外掛沿實體 piping connector 建立局部拓撲圖，但只擴展到明確邊界：

- 開放端。
- 設備 connector。
- 斜 T／Y／Tee／Cross。
- 變徑。
- 主管分割接點。
- 使用者指定的停止點。

畫布顯示預計納入的管段及固定下游端。使用者確認後才建立工作階段。

開始前檢查：

- Document 可修改，元素未 pinned。
- 元素不在 Group、Link、不可編輯 Design Option。
- Worksharing 元素可借用。
- 所有 Pipe 都是剛性 Pipe，不是 FlexPipe 或 fabrication part。
- 拓撲沒有 cycle。
- 只有一個可判定的下游固定端。
- connector、管徑、系統與 FamilySymbol 可完整解析。
- 沒有外掛不支援的附件、管件或受約束尺寸。

### 2. 建立暫存快照

快照不可只存 ElementId。每個元素至少記錄：

- Document fingerprint、工作階段 ID、建立時間與狀態。
- ElementId、UniqueId、Category、TypeId、SystemTypeId、LevelId。
- Pipe 的原始 `LocationCurve` 端點、直徑、坡度值、坡度方向、固定端。
- connector 簽章：owner UniqueId、Origin、BasisZ、Domain、ConnectorType、直徑與 FlowDirection。
- 每條物理連線的兩端 connector 簽章。
- fitting 的 FamilySymbol、位置、旋轉／transform、connector 對應。
- elbow 實際角度。
- 斜 T／Y 的 main-in、main-out、branch connector 映射及下游方向。
- transition 兩端尺寸方向。
- 主管被分割前後的 segment 關係與 junction 位置。
- insulation／lining、常用 instance parameter、tag／dimension 相依性清單。
- 進入編輯模式前的拓撲 hash 與幾何 hash。

Connector index 不應作為唯一識別。重生、分割或重建後，connector 必須依 owner、Origin、BasisZ、尺寸與 domain 重新解析。

工作階段應存入專案 DataStorage／Extensible Storage，而不是只存在記憶體；否則 Revit 當機、外掛重載或模型關閉後無法辨識尚未完成的去坡狀態。

### 3. 暫時平整

只平整可計坡的非垂直 Pipe。垂直落管仍保持垂直，不把它改成水平。

MVP 建議固定下游端高程，將相鄰非垂直段依拓撲向上游展開為 0%，必要時重建中間 elbow。若上游邊界無法移動，應拒絕，而不是拉動設備或主管。

每次幾何修改後需 `Document.Regenerate()`，再重新讀 connector。官方說明 commit 會自動 regenerate，也可在 transaction 內主動 regenerate；若 regeneration 失敗，該 transaction 必須中止，不能忽略後繼續讀模型。

### 4. 使用者編輯

Ribbon 顯示持續狀態：

- `完成並恢復1%`
- `取消並還原`
- `檢查工作階段`

模型儲存或關閉前若工作階段尚未完成，應顯示警告。不能只靠記憶體中的旗標。

### 5. 完成並恢復斜率

先比較目前拓撲與快照：

- 若只有 Pipe 長度、XY端點與允許的 elbow 數量改變，可繼續。
- 若增刪了 branch fitting、變徑、設備連接或主管分割，視為 topology drift，MVP 拒絕自動完成。

以固定下游 connector 為基準，沿拓撲向上游計算：

`Z(upstream) = Z(downstream) + horizontal_run × slope_ratio`

每段建立後立即驗證：

- 有號坡度及沿流向單調下降。
- 垂直段仍為垂直。
- elbow 角度與 FamilySymbol。
- 斜 T／Y 支口朝主管下游。
- transition 的大／小徑方向。
- 最短直管與 fitting takeout。
- 所有預期 connector 物理連通。
- 無循環、孤立 fitting、短管或反坡。

整個「完成」命令可放在單一 TransactionGroup 中；任一項失敗便 rollback，保留仍處於暫時平整狀態的編輯成果，讓使用者修正，不留下半套恢復結果。

## MVP 範圍

### 建議納入

- 使用者明確選取的局部範圍，不掃描整個系統。
- 一條無分支、無循環的 Pipe chain。
- 一個固定下游端。
- 剛性圓管。
- 相同 Pipe Type、System Type 與管徑。
- 非垂直段套用同一坡度，預設1%。
- 中間只允許已驗證的45° elbow。
- 允許既有垂直段，但垂直段不參與1%水平坡度計算。
- Begin／Finish／Cancel 三個明確狀態。
- DataStorage 快照、超時／過期提示及拓撲 hash。

### MVP 拒絕條件

- 斜 T、Y、Tee、Cross 或任何分支點位於編輯範圍內。
- 主管分割點位於編輯範圍內。
- 變徑、偏心 reducer 或不同管徑。
- 多個固定邊界，且其高程與目標坡度無法同時滿足。
- 已連接設備會被移動。
- FlowDirection／下游方向不明。
- cycle、ring 或同一節點有多條下游路徑。
- FlexPipe、fabrication part、linked element。
- Group、pinned、受全域參數／尺寸／鎖定約束控制的元素。
- 工作共享中不可借用的元素。
- connector 或 fitting FamilySymbol 無法穩定重建。
- tag、dimension、insulation 或其他相依元素會因刪除重建而失效，但沒有對應保存策略。
- 快照後拓撲已漂移。
- 已有另一個未完成的斜率編輯工作階段。

## 第二階段才考慮的範圍

- 支管接入斜 T／Y及主管分割。
- 變徑與偏心變徑。
- 多分支樹狀網路。
- 多個坡度區段。
- 自動保留 tag、dimension、insulation 與工作共享 ownership。
- 模型重開後繼續或取消工作階段。

整網處理不建議作為預設。網路越大，坡度重新分配越可能同時受到多個固定高程、設備接口與主管接點約束；這是約束求解問題，不是單純批次改參數。

## 實作前必做 Revit 2024 探針

正式開發前，需在測試模型用獨立測試命令確認：

1. 讀取水平、1%斜管、垂直管的 `RBS_PIPE_SLOPE`、`StorageType`、`IsReadOnly` 與 `UserModifiable`。
2. 只改 `LocationCurve.Curve` 的單一端點，觀察相連 elbow、transition 與 tee 是否移動、斷線或報錯。
3. 對兩段管＋45° elbow 測試平整與恢復。
4. 對含 reducer 的路段測試 connector 尺寸與方向是否保持。
5. 對含斜 T／Y與已分割主管的路段測試 ElementId、UniqueId、connector 集合及 TypeId 是否改變。
6. 驗證 `Document.Regenerate()` 後重新解析 connector 的必要性。
7. 驗證失敗 transaction rollback 後沒有短管、孤立 fitting 或主管殘留切口。
8. 測試 save、close、reopen 後能否偵測未完成工作階段。
9. 測試 Worksharing、pinned、Group、Design Option 與有 tag／dimension 的案例。

探針應記錄實際 Revit 2024 build、模型、元素 ID、前後拓撲 hash 與 journal，不能只以畫面看起來正確作結論。

## 建議決策

**現在：不併入主功能。**先修正排水接幹管既有的立管垂直段與坡度高程容差。

**下一個獨立工作項：**建立唯讀分析器與可回滾探針，確認 Revit 2024 對現有專案管型、SP 彎頭、斜 T／Y與變徑族的實際行為。

**探針通過後：**實作局部無分支管鏈 MVP。若使用者選取範圍包含斜 T／Y、主管分割或變徑，明確回報不支援，不自動擴大處理範圍。

這個順序能解決「斜管難以再次編輯」的真實痛點，同時避免把尚未受控的拓撲重建風險帶進目前的接幹管命令。
