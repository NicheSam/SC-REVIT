# 排水 GUI 與 Agent 配置判斷

## 人用流程

日常操作固定為：

`Revit 選取 1 段主管與衛生器具 → 預覽路徑 → 建立排水管`

排水頁開啟時會背景讀取目前選取、專案 Pipe/System/Level、主管
Routing Preference 與已保存配置。主畫面只保留坡度、支管管徑、配置
摘要、下游翻轉、預覽與建立。Pipe Type、System Type、斜 T/Y、45°
彎頭及公司容差集中在「編輯配置」，不要求每次重選。

主管下游預設自動偵測。畫布預覽會顯示下游箭頭；只有使用者認為方向
錯誤時才按「翻轉下游」。工程數值預設收合，主要結果只顯示器具、坡度
與阻擋原因。

## Agent 判斷

`drainage.recommend_configuration` 使用固定成本證據，不掃描全模型：

1. 目前明確選取的唯一主管，取得其 Pipe Type、System Type 與 Level。
2. 該 Pipe Type 對本次管徑有效的 Routing Preference 順序。
3. 相同 document fingerprint 的人工保存配置。
4. 相同 document fingerprint、近似管徑、最多 200 筆 committed
   operation 的管件使用次數與比例。

只有下列情況允許 `auto_select_allowed=true`：

- 尺寸相容候選只有一個。
- 同文件已有人工保存選擇。
- 同文件成功紀錄至少使用 3 次、占比至少 70%，且領先第二名至少 25%。

其他情況仍回傳排序、使用次數、比例及判斷理由，但
`requires_human_choice=true`。Routing Preference 的第一順位可作候選，
不能單獨構成 Agent 自動建立的充分證據。GUI 會清空 Junction／Elbow 並
禁止預覽，直到使用者在「編輯配置」明確儲存；Agent 則不會取得
`DCR-*` recommendation token，因此也無法呼叫 preview。高信心 token
只保存在同一個 stdio MCP server 行程 5 分鐘，不落地為可偽造檔案。

## 共用邊界

GUI 與 Agent 最終都以 ElementId＋UniqueId 指定 Pipe/System/Level、
Junction 與 Elbow，並進入同一個 `DrainageApplicationService`、不可變
snapshot、Revit TaskDialog confirmation、commit 與 validator。人用 GUI
的短流程不會降低 Agent 的證據與安全要求。

## 官方依據

- Autodesk Revit 2024 的 Ribbon `PushButtonData` 會啟動指定
  `IExternalCommand`；SC REVIT 的排水按鈕依此連至 `OpenDrainageCommand`。
  <https://help.autodesk.com/cloudhelp/2024/ENU/Revit-API/files/Revit_API_Developers_Guide/Introduction/Add_In_Integration/Revit_API_Revit_API_Developers_Guide_Introduction_Add_In_Integration_Ribbon_Panels_and_Controls_html.html>
- Autodesk Revit 2024 的 `RoutingPreferenceManager` 管理 Pipe 的
  Junction、Elbow 等規則；尺寸條件與規則順序是候選依據，但建立後仍需
  核對實際 Family/Type。
  <https://help.autodesk.com/cloudhelp/2024/ESP/Revit-API/files/Revit_API_Developers_Guide/Discipline_Specific_Functionality/MEP_Engineering/Revit_API_Revit_API_Developers_Guide_Discipline_Specific_Functionality_MEP_Engineering_Routing_Preferences_html.html>
