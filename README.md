# SC REVIT

SC REVIT 是一套 Revit 2024 MEP 輔助工具集，目前聚焦在族群庫治理、CAD 點位轉 Revit 元件、開孔協調、消防支管輔助、後台紀錄，以及 MEP 小工具。

## 給使用者安裝

請不要使用 GitHub 的 `Code > Download ZIP` 當作安裝包；那是原始碼。

一般使用者應該到 GitHub Releases 下載：

```text
SC_REVIT_<version>_installer.zip
```

下載後：

1. 解壓縮 ZIP。
2. 執行 `Install_SC_REVIT.bat`。
3. 安裝完成後重新啟動 Revit 2024。
4. 在 Revit Ribbon 開啟 `SC 族群工具`。

安裝腳本會把程式複製到 `%LOCALAPPDATA%\SC_REVIT`，部署 Revit add-in DLL，寫入 Revit 2024 addin manifest，並設定 `SC_REVIT_HOME`。

## 目前功能

- 族群歸檔：讀取 RFA metadata，依規則建議分類，支援人工確認與族群庫入庫。
- 專案回收：掃描專案內族群，準備回收與整理。
- CAD 點位放置：讀取 CAD/DWG block 點位，產生預覽並批量放置 Revit 族群。
- SC 後台：記錄工具操作、建立結果、模型回查與清理工作流。
- 開孔定位：掃描 MEP 與建築連結物件，產生開孔候選與標記。
- 消防支管建立：以主管與撒水頭選取為基礎，建立初版支管。
- 元件身份檢查：判斷選取元件是否具備後台追蹤與回查所需身份資料。
- SC 參數健檢：檢查 SC_ 參數缺漏與空值。
- 管線斷點檢查：診斷 pipe / duct / conduit 連接狀態，僅對可修復 pipe 執行自動修復。
- 管支撐預覽：依選取 pipe 產生支撐候選點與預覽標記。

## 開發者打包 Release

在開發機執行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\package_release.ps1 -Version "v0.4-dev"
```

腳本會重建 Revit add-in、重建 GUI exe，並輸出：

```text
release\SC_REVIT_v0.4-dev_installer.zip
```

將這個 ZIP 上傳到 GitHub Releases，供使用者下載。

## 開發執行

需要 Revit 2024 與 Python。一般開發流程：

```powershell
python gui_app.py
```

只更新 Revit add-in：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\update_revit_addin.ps1
```

完整本機重建與安裝：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_or_update.ps1
```

## 架構

- `gui_app.py`：主要桌面 GUI。
- `sc_revit/`：Python 端模組邊界與 queue client。
- `queue_protocol.py`：Python 與 Revit add-in 的 request contract。
- `revit_addin/src/`：Revit 2024 add-in 與各工具 handler。
- `installer/`：使用者安裝腳本。
- `tools/package_release.ps1`：release installer 打包腳本。
- `docs/`：模組邊界與測試紀錄。

## 注意事項

- Revit add-in 不會 hot reload；更新或安裝後請重新啟動 Revit。
- 自動修改模型前請先在測試模型或可回復版本驗證。
- 目前主要支援 Revit 2024。
