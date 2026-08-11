# SC REVIT v0.5.3

本版將近期點位放置、消防支管、預覽顯示與安裝部署修正整合為可供其他 Revit 2024 使用者一鍵安裝或覆蓋更新的版本。

## 消防支管

- 支援同側、異側、同高程與高程差等不同主管交接拓樸，分別建立 Tee、Cross、支管與垂直短管。
- 新建消防管使用使用者選定的 System Type、Pipe Type、樓層與管徑。
- 幾何建立、系統類型統一與最終驗證改為多交易的原子流程；任一步驟失敗時完整回復。
- 系統類型改以實際連通的 `MEPSystem` 為單位處理，涵蓋主管、新建支管與已連接灑水頭。
- 新增缺少 Connector、缺少系統、錯誤系統及系統改型例外的詳細診斷。
- 修正消防支管建立後幾何存在但 Revit MEP 系統未正確連通的問題。

## CAD 點位與預覽

- 點位座標加入自動單位與模型距離判斷，降低毫米／英尺或異常遠距座標造成的不可見問題。
- 點位與消防支管螢光預覽改用 DirectContext3D 顯示，避免留下正式 ModelCurve。
- 建立新預覽、取消、關閉工具或完成放置時，自動清除 SC REVIT 建立的暫存預覽。
- 清除未使用的 `SC_preview_points_*` 群組類型與既有暫存模型線，不影響使用者群組。
- 增加灑水頭周圍 CAD 路徑抽取與影子核對診斷。

## GUI、效能與部署

- GUI 與 Revit DLL 同步更新，避免混用新 GUI 與舊 DLL。
- 改善 GUI 與 Revit 間的背景通訊及 request 恢復流程，降低工具結束後持續卡頓的風險。
- `Install_SC_REVIT.bat` 可用於首次安裝及覆蓋更新，會檢查 Revit／SC REVIT 是否關閉。
- 安裝包會驗證 payload SHA-256，部署固定 DLL 路徑並寫入唯一 Revit 2024 manifest。
- 提供診斷收集與解除安裝工具。

## 安裝或更新

1. 關閉 Revit 2024 與所有 SC REVIT 視窗。
2. 完整解壓縮 `SC_REVIT_v0.5.3_installer.zip`。
3. 執行 `Install_SC_REVIT.bat`。
4. 看到 `Installed SC REVIT successfully.` 後重新開啟 Revit 2024。

首次載入未簽章外掛時，請確認來源為本 GitHub Release，再選擇 Revit 的「永遠載入」。
