# SC REVIT v0.5.2-distribution-safe

這是以 `v0.5.1-drainage-dev` 排水功能為基準的部署安全修正版，不改動排水路徑求解邏輯。

## 穩定性修正

- Agent listener 預設停用；Revit Ribbon 人工功能仍可使用。
- listener 每秒最多檢查一次，heartbeat 每三秒最多寫入一次。
- 每輪最多處理一筆 Agent request。
- Revit 啟動時會隔離前一次留下的 request，避免崩潰後重複執行。
- 保留 in-flight request 診斷資訊，方便定位異常中止的工作。

## 安裝修正

- Revit 或 SC REVIT 執行中時拒絕覆寫安裝。
- DLL 改用固定路徑 `%LOCALAPPDATA%\SCRevit\Revit2024\RfaMetadataAddin.dll`。
- manifest 精簡為一個 `Application` 項目，移除開發用 Self Test Command。
- 覆寫 manifest 前自動備份。
- 新增 Agent 啟用／停用、診斷收集與解除安裝工具。
- 所有安裝檔案納入 SHA-256 payload 驗證。

## 安裝

1. 關閉 Revit 2024 與 SC REVIT。
2. 完整解壓縮安裝 ZIP。
3. 執行 `Install_SC_REVIT.bat`。
4. 第一次開啟 Revit 時，確認來源後選擇「永遠載入」。
5. 一般排水建模不需要啟用 Agent。

## 未簽章狀態

本版尚未使用程式碼簽章憑證。第一次由 Revit 載入時仍需要人工選擇「永遠載入」；Windows SmartScreen 或防毒軟體也可能顯示提醒。
