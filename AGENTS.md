# SC REVIT 專案規則

## 專案邊界

- `E:\Desktop\Codex\SC REVIT` 是唯一開發來源。
- `E:\Desktop\Codex\PushGithub\SC REVIT` 僅供 Git 紀錄、發布與 Release 包裝。
- 不得直接在 `PushGithub\SC REVIT` 開發或以其內容覆蓋開發版。
- 只有使用者要求發布時，才將經過驗證的內容同步到發布副本。

## 溝通語言

- 預設以繁體中文回覆。
- 程式碼識別字、Revit API 名稱、檔案名稱及必要技術名詞保留原文。

## Agent skills

### Issue tracker

議題使用 GitHub Issues，目標儲存庫為 `NicheSam/SC-REVIT`。
詳細規則請參閱 `docs/agents/issue-tracker.md`。

### Triage labels

使用預設 triage 標籤：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。
詳細規則請參閱 `docs/agents/triage-labels.md`。

### Domain docs

本專案採用 single-context 領域文件結構。
詳細規則請參閱 `docs/agents/domain.md`。

## Revit 開發與部署

- Revit 開啟時，不得強制覆蓋或替換已載入的 DLL。
- 編譯、測試、部署及 Revit 實際執行是不同驗證階段，不得混為一談。
- 正式部署前，應確認 Revit 已關閉。
- 部署後應核對 `.addin` manifest 指向位置、來源 DLL 與部署 DLL 雜湊。
- 無法完成 Revit 實際操作測試時，必須明確標示仍需現場驗證。

### 消防支管完整驗證門檻

- 拓樸計畫是 SVG 預覽與 Revit 建模的唯一共同來源；建模端不得另行推算交點、方向、管徑或管件配置。
- 配件所需的短管長度、變徑位置及留設距離不得使用固定毫米數。拓樸只記錄 `fit_to_routing_parts` 等配置意圖，建模時依目前 Pipe Type 的 Routing Preferences、實際選中配件幾何與 `Application.ShortCurveTolerance` 求得最近可行位置。
- 四通應先以共同管徑建立並完成 `Regenerate`，再於各支管出口分別建立必要的異徑；驗證應檢查完整 MEP 路徑，不得要求所有管段直接連到四通。
- 不得因修正主管或四通流程而改動已通過的灑水頭垂管流程；若必須跨越此邊界，應先新增針對垂管的回歸測試並說明原因。
- 每次消防支管建模修改在部署前，必須先於目標 Revit 模型執行可回復沙盒，且同時證明：所有計畫四通成功、異徑方向正確、沒有零長度或異常長管、全部灑水頭可由主管到達、沙盒元素完整回復。
- 單元測試、合約測試、編譯成功及 DLL 雜湊一致都不能取代上述 Revit 沙盒結果。沙盒未全部通過時，不得部署，也不得把未驗證版本交由使用者反覆試錯。

## 模型修改原則

- 修改模型前先讀取目前文件、選取元素、視圖、系統類型及相關設定。
- 適用時先執行唯讀分析、預覽或沙盒測試。
- 模型修改必須在適當的 Revit API context 與 Transaction 中執行。
- 拓樸計畫未通過時應在模型修改前中止。
- 測試模式成功時完整 Rollback。建模已開始後若只有局部管件或接管失敗，不得自動整批回退；應以中文列出成功數、失敗數與未連接範圍，讓使用者選擇「保留成功部分」或「全部復原」。
- 正式模式完整成功時提交為單一 Undo。局部失敗只有在使用者明確選擇保留後才能提交成功部分；關閉提示、取消或選擇全部復原時必須完整 Rollback。前置資料、拓樸計畫或交易本身無效仍屬致命錯誤，直接中止並回復。
- 使用者可見的錯誤必須先提供中文原因與影響範圍；英文例外、ElementId 與技術代碼保留於技術資訊及完整診斷，不得作為唯一說明。
- 完成後回報建立、修改、刪除的元素及使用者可用的 Undo 範圍。

## 檔案修改原則

- 修改前先檢查最小相關檔案範圍或 diff。
- 保留既有編碼、換行、縮排及無關內容。
- 不得覆蓋使用者尚未提交或與目前任務無關的修改。
- 修改後檢查差異、測試結果及中文亂碼。
