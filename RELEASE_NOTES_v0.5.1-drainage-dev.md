# SC REVIT v0.5.1-drainage-dev

這是以 `snapshot-676ce995fd74` 為排水功能基準的完整安裝修正版。

## 修正內容

- 提供不需要 Python、PyInstaller、Visual Studio 或 .NET SDK 的完整安裝包。
- 修正 SC REVIT 桌面程式啟動時可能覆寫既有 Revit manifest／DLL 的問題。
- 開發者建置流程遇到 DLL、GUI 或 manifest 安裝失敗時會立即停止，不再繼續執行後續步驟。
- 安裝前驗證 payload 內 DLL、GUI 與版本檔 SHA-256，避免損壞或混用舊檔。
- 安裝完成後再次核對來源 DLL、部署 DLL 與 manifest。

## 安裝

1. 下載 `SC_REVIT_v0.5.1-drainage-dev_installer.zip`，不要下載 GitHub 自動產生的 Source code ZIP。
2. 解壓縮完整 ZIP。
3. 關閉 Revit 2024 與 SC REVIT。
4. 執行 `Install_SC_REVIT.bat`。
5. 安裝完成後重新開啟 Revit 2024。

## 驗證基準

- 排水 DLL：`RfaMetadataAddin.676ce995fd74.dll`
- DLL SHA-256：`676CE995FD74D043116817E324D1830A691E10BF4CC2E6389059DEA4BB132CBE`
- 目標版本：Autodesk Revit 2024
- 狀態：開發預覽，應先使用測試模型驗證。
