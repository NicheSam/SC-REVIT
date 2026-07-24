# 排水功能 Agent Gateway

## 目的

GUI 與 Agent 不各自實作排水邏輯。兩者共用
`DrainageApplicationService`，最後都進入同一組 Revit queue action。
Agent 只能送出結構化參數，不能傳入 C#、任意命令或未預覽的建模資料。

## 工具

| 工具 | 風險 | 用途 |
|---|---|---|
| `drainage.get_context` | readOnly | 讀取文件指紋、版本、Pipe/System/Level 與 routing profile |
| `drainage.inspect_current_selection` | readOnly | 讀取目前主管與潔具選取 |
| `drainage.search_targets` | readOnly | 在目前視圖或文件列出候選，不替 Agent 決定設計意圖 |
| `drainage.recommend_configuration` | readOnly | 依目前選取、Routing Preference、同文件人工設定與有限筆成功紀錄排序管件配置 |
| `drainage.preview` | readOnly | 建立不可變 route snapshot 並在 Revit 畫布顯示候選 |
| `drainage.clear_preview` | readOnly | 清除 DirectContext3D 預覽，不刪除模型元素 |
| `drainage.request_human_confirmation` | confirmation | 在 Revit 開啟綁定 snapshot hash 的人工確認 |
| `drainage.commit_confirmed_snapshot` | modelMutation | 只提交已由人確認的 snapshot；operation idempotent |
| `drainage.get_operation` | readOnly | 依 operation id 查詢持久化結果 |
| `drainage.validate_operation` | readOnly | 從已提交 operation 取回結果並驗證 |

完整 JSON Schema 可用下列命令取得：

```powershell
python -m sc_revit.drainage.agent_cli --describe
```

Gateway contract 版本為 `1.3.0`。CLI 與 MCP 的成功／失敗都使用
`contract_version`、`status`、`tool_name` 與 `result`／`error` envelope；
失敗包含穩定 code、例外類型、訊息與 `retryable`。
排水選取、型別身分、輸入範圍、preflight、路徑幾何與 fitting 建立的
主要失敗由 Revit 端直接加上 domain code；Python 只負責保留該 code，
不以翻譯後的中文句子猜下一步。

## MCP 啟動

本版本已提供 stdio MCP server，而不是只有概念性 CLI：

```powershell
python -m sc_revit.drainage.mcp_server
```

主機設定範例位於 `docs/drainage_mcp_config.example.json`。Server 支援
`initialize`、`ping`、`tools/list`、`tools/call`，工具清單直接由
`AGENT_TOOL_SCHEMAS` 產生，因此 GUI／CLI／MCP 不會各自維護建模邏輯。
每個 stdio session 必須先完成 `initialize`，再送出
`notifications/initialized`；未初始化的工具呼叫會以 `-32002` 拒絕。
目前只宣告 MCP `2025-06-18`，錯誤 JSON 會回 `-32700`，不會終止
server。每個工具有獨立、封閉且以 `oneOf` 區分成功／失敗的
`outputSchema`。commit 的 `destructiveHint=true`，因為它會分割主管且
目前沒有跨 operation rollback 工具。

## 強制流程

1. `get_context`，確認 Revit 2024、文件指紋與可提交政策。
2. `inspect_current_selection`，或以 `search_targets` 列出候選；搜尋結果
   同時包含 ElementId 與 UniqueId。搜尋可用 explicit ElementId、
   PipeType、SystemType 與 Level 篩選；若主管候選不是恰好一條，結果為
   `blocked` 並回 `MAIN_CANDIDATE_AMBIGUOUS`／`MAIN_CANDIDATE_NOT_FOUND`。
   成功或 blocked 結果都會簽發短效 `candidate_set_token`，token 綁定
   文件 fingerprint/revision、伺服器計算的主管候選總數與回傳元素。
   preview 只接受伺服器記錄為恰好一條主管的 token；所選器具必須是
   該 token 的成員。
3. 可先呼叫 `recommend_configuration`。此工具不掃描全模型，只接受目前
   明確選取的主管，並依尺寸相容的 Routing Preference、同文件保存的人
   工配置與最多 200 筆 committed operation 排序。只有單一候選、同文件
   人工配置或具優勢的成功使用比例才允許自動採用；其餘回
   `requires_human_choice=true`。
4. `preview` 必須對主管、每個器具、PipeType、SystemType、Level、
   Junction 與 45° Elbow 同時傳 ElementId 與 UniqueId；固定 1% 時傳
   `slope_ratio: 0.01`。若 selection source 是 `search_result`，也必須
   回傳同一個 candidate-set token。Agent 另須回傳只有高信心
   recommendation 才會簽發、有效 5 分鐘的 `DCR-*` token；token 綁定
   文件、主管、管徑及 Pipe/System/Level/Junction/Elbow。低信心候選
   不會取得 token，必須先由人在 GUI 明確保存配置。C# 端會再次核對所有
   身分與集合。DCR grant 只存在同一個 stdio MCP server 行程記憶體，
   不落地成可被同使用者程序偽造的核准檔案。
5. 檢查 `status`、issues、routing profile、流向與畫布預覽。
6. 呼叫 confirmation action；Revit 內部會顯示不可由字串取代的
   `TaskDialog`，必須由人按 Yes，才簽發綁定 snapshot hash 的短效 token。
7. Agent 以穩定的 `operation_id` 與 `idempotency_key` 呼叫
   `commit_confirmed_snapshot`。
8. timeout 時不得重送新 operation；先以原 operation id 呼叫
   `get_operation`。
9. committed 後呼叫 `validate_operation`。

## 安全邊界

- snapshot 綁定文件 fingerprint、revision、Pipe/System/Level、routing
  profile、route policy、幾何計畫、碰撞證據與 issues。
- route policy `1.1.0` 包含 45° 側接公差、周向仰角範圍、最短
  tangent、多接點間距、既有管中心線淨距與雙 45° 中段面外偏移上限；
  預覽後不可在 commit 改寫。
- 文件在 preview 後發生 commit、undo 或 redo，會回報 `STALE_SNAPSHOT`。
- 現階段 commit 僅允許本機已儲存、非唯讀、非 workshared/cloud 文件。
- 確認者必須在 Revit `TaskDialog` 明確核准；僅傳
  `actor_kind: human` 不會繞過對話框。
- operation journal 落地保存；`(document fingerprint, idempotency key)`
  全域唯一。相同 operation 可查詢，衝突 key 會被拒絕。
- operation journal schema v2 保存 document revision/title/path kind、
  dependency hash、confirmation ID/actor、initiator surface、Agent contract
  版本、add-in 版本及 assembly module version ID；validator 結果會回寫
  `validation_evidence`。
- 建立元素寫入 operation lineage。若 Revit transaction 已提交但 journal
  尚未完成即中斷，`get_operation` 會回報
  `committed_recovery_required`，禁止重複建立並要求人工驗證。
- operation 查詢與驗證強制綁目前 document fingerprint；正式 validator
  不接受沒有 operation lineage 的 raw element 清單。正常提交產物會以
  UniqueId 重解，並核對 ElementId、TypeId、Type UniqueId 及 exact
  operation metadata。
- 任何 Revit warning/error、connector graph 斷裂、主管連續性失敗、
  逆坡、局部升高、錯誤 Y/45° 配件或最短中心線不足都 rollback。
- 壁掛出口在尚未量得實際 45° fitting takeout 前會回報
  takeout 相關阻擋碼，不得提交；量測證據可來自既有 fitting instance，
  或在 rollback-only Transaction 中建立同型 FamilySymbol 探針。
- routing rule 的 family 名稱不構成合格證據；Agent／GUI 必須明確選取
  rule，並由 connector geometry、目標管徑、takeout 與建立後 TypeId
  共同驗證。
- operation journal 將人工確認者與發起介面拆開：確認者固定來自
  Revit `TaskDialog`，發起介面記為 `agent` 或 `human_gui`。

目前已是可執行的本機 typed CLI 與 stdio MCP server。尚未完成的是特定
Agent host 的安裝／管理介面註冊；該步只應引用 MCP 設定，不得另寫一套
建模邏輯。

正式多步 Agent 流程限定使用同一個 stdio MCP session。typed CLI 用於
`--describe`、schema 驗證與單步診斷，不宣稱可跨獨立 process 保存
`DCR-*` recommendation grant。

## 已知邊界

- `search_targets` 是候選列舉，不是自動設計意圖推定。preview 會要求
  `target_selection.main_candidate_count=1`；server-issued candidate-set
  token 只能證明 Agent 沒有替換搜尋集合，不能替代下游方向、配件選擇
  或設計意圖的判斷。
- 現有碰撞預檢是 Pipe 中心線、半徑與淨距的保守篩檢；尚不是所有
  MEP／結構實體的 Solid clash。
- `VENT_PATH_RISK` 目前來自周向角與局部升高規則；尚未建立完整管冠
  空氣通道的實體分析。
- 尚未提供 operation rollback 工具；因此 commit 正確標示為
  `modelMutation`，不可宣稱 Agent 有專用自動回復能力。
- `committed_recovery_required` 已能阻止逾時後重複建模，但 journal
  中斷後的自動重建驗證證據尚不完整；此狀態仍需人工模型稽核。

## 官方依據

- Autodesk Revit API 2024 `DocumentChanged`：transaction commit、undo、
  redo 後觸發，適合維護外部同步版本。
  <https://help.autodesk.com/cloudhelp/2024/PTB/Revit-API/files/Revit_API_Developers_Guide/Advanced_Topics/Events/Database_Events/Revit_API_Revit_API_Developers_Guide_Advanced_Topics_Events_Database_Events_DocumentChanged_event_html.html>
- Autodesk Revit API 2024 Routing Preferences：PipeType 的 Elbows、
  Junctions 等規則與尺寸條件必須由 `RoutingPreferenceManager` 取得。
  <https://help.autodesk.com/cloudhelp/2024/ESP/Revit-API/files/Revit_API_Developers_Guide/Discipline_Specific_Functionality/MEP_Engineering/Revit_API_Revit_API_Developers_Guide_Discipline_Specific_Functionality_MEP_Engineering_Routing_Preferences_html.html>
- Autodesk Revit API 2024 Transactions：所有文件修改必須在 transaction
  內完成。
  <https://help.autodesk.com/cloudhelp/2024/ESP/Revit-API/files/Revit_API_Developers_Guide/Basic_Interaction_with_Revit_Elements/Revit_API_Revit_API_Developers_Guide_Basic_Interaction_with_Revit_Elements_Transactions_html.html>
- MCP 2025-06-18 Tools：server 宣告 tools capability；`tools/list` 提供
  input/output schema；`tools/call` 的 structuredContent 必須符合
  outputSchema，並同時保留 text content 供舊 client 使用。
  <https://modelcontextprotocol.io/specification/2025-06-18/server/tools>
