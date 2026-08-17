# ADR-006：消防支管局部失敗保留與中文診斷

日期：2026-08-17

狀態：採用

## 背景

消防支管為整批路網建模。先前只要一個四通、異徑或灑水頭接管失敗，就會回復整批交易。這會同時刪除已成功建立的部分與現場診斷證據，使使用者看不到成果，也無法直接比較成功與失敗位置。

既有錯誤視窗主要顯示英文內部代碼及 ElementId，不能直接說明問題位置、影響數量與可採取的動作。

## 決策

1. 失敗分為兩層：
   - 前置資料、拓樸計畫、必要 Revit 設定或交易無效屬致命錯誤，建模前中止或完整回復。
   - 建模已開始後，單一四通、異徑、管段或灑水頭接管失敗屬局部失敗。
2. 發生局部失敗時，在 `TransactionGroup` 結束前顯示 Revit `TaskDialog`，以中文摘要成功元素數、問題數及未連接灑水頭數。
3. 使用者選擇「保留成功部分」時，以 `TransactionGroup.Assimilate()` 合併為一個 Revit Undo，回應標記為 `partial_success`，並保存完整失敗 payload 與保留元素 ElementId。
4. 使用者選擇「全部復原」、取消或關閉視窗時，以 `TransactionGroup.RollBack()` 回復本批次全部變更。
5. GUI 必須先顯示中文原因與影響範圍；英文例外、技術代碼與 ElementId 保留在技術資訊，供除錯與重播使用。
6. 保留成功部分不等於驗證通過。GUI 不得開放正式提交捷徑，必須重新分析及測試後才能再進行完整建立。

## 影響

- 局部失敗不再自動抹除可用成果與現場證據。
- 使用者對是否保留半成品有最終決定權，程式不得靜默提交。
- 一次 Undo 可取消整批保留結果，不需要逐一尋找元素。
- 四通、垂管、管徑與拓樸演算法不因本決策而改變。

## 驗證門檻

- 模擬局部失敗時必須出現中文雙選項。
- 選擇保留後，成功元素仍存在、回應為 `partial_success`，且可用一次 Undo 移除。
- 選擇全部復原或取消後，不得殘留本批次建立元素。
- 完整成功的沙盒仍自動回復；完整成功的正式建立仍提交為單一 Undo。
- 失敗回應必須包含中文摘要及原始技術代碼。

## 官方依據

- Autodesk Revit 2024 API Developers Guide — Revit-style Task Dialogs：可使用命令連結呈現單一步驟選項並取得使用者選擇。
  https://help.autodesk.com/cloudhelp/2024/ESP/Revit-API/files/Revit_API_Developers_Guide/Introduction/Add_In_Integration/Revit_API_Revit_API_Developers_Guide_Introduction_Add_In_Integration_Revit_style_Task_Dialogs_html.html
- Autodesk Revit 2024 API Developers Guide — Transactions：`TransactionGroup` 可將已完成的內部交易合併為單一 Undo，或整組回復。
  https://help.autodesk.com/cloudhelp/2024/FRA/Revit-API/files/Revit_API_Developers_Guide/Basic_Interaction_with_Revit_Elements/Revit_API_Revit_API_Developers_Guide_Basic_Interaction_with_Revit_Elements_Transactions_html.html
