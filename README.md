# SC REVIT

SC REVIT 是一套 Revit 2024 MEP 輔助工具集，目前以安裝包形式提供測試使用。  
目前請使用 GitHub Releases 下載安裝包，不要使用 GitHub 的 `Code > Download ZIP`。

## 下載安裝包

最新版測試安裝包：

[下載 SC_REVIT_v0.4.1-dev_installer.zip](https://github.com/NicheSam/SC-REVIT/releases/download/v0.4.1-dev/SC_REVIT_v0.4.1-dev_installer.zip)

Release 頁面：

[SC REVIT v0.4.1-dev installer](https://github.com/NicheSam/SC-REVIT/releases/tag/v0.4.1-dev)

## 環境需求

- Windows 10 / 11
- Autodesk Revit 2024
- 可寫入使用者資料夾：
  - `%LOCALAPPDATA%`
  - `%APPDATA%\Autodesk\Revit\Addins\2024`
- 可執行 PowerShell 腳本
- 安裝後需要重新啟動 Revit

不需要安裝 Python、Visual Studio 或自行編譯原始碼。

## 安裝方式

1. 下載 `SC_REVIT_v0.4.1-dev_installer.zip`。
2. 解壓縮 ZIP。
3. 執行 `Install_SC_REVIT.bat`。
4. 等待安裝完成。
5. 重新啟動 Revit 2024。
6. 在 Revit Ribbon 找到 `SC 族群工具`。

安裝腳本會自動：

- 複製 SC REVIT 到 `%LOCALAPPDATA%\SC_REVIT`
- 部署 Revit add-in DLL 到 `%LOCALAPPDATA%\RfaMetadataAddin`
- 寫入 Revit 2024 addin manifest
- 設定 `SC_REVIT_HOME`

如果安裝時 Revit 正在執行，請關閉並重新開啟 Revit，外掛才會載入新版 DLL。

## 更新方式

目前沒有自動更新器。更新時請照以下流程：

1. 關閉 Revit。
2. 關閉所有 SC REVIT 視窗。
3. 到 GitHub Releases 下載新版 installer ZIP。
4. 解壓縮新版 ZIP。
5. 再次執行 `Install_SC_REVIT.bat`。
6. 重新啟動 Revit 2024。

新版安裝會覆蓋：

- `%LOCALAPPDATA%\SC_REVIT`
- `%LOCALAPPDATA%\RfaMetadataAddin`
- Revit 2024 addin manifest

通常不需要手動移除舊版。

## 基本使用方式

安裝完成並重新啟動 Revit 後，開啟 `SC 族群工具` Ribbon。  
目前主要工具包含：

- `族群歸檔`：整理與歸檔 Revit 族群。
- `專案回收`：掃描專案內族群，準備回收整理。
- `批量點位放置`：從 CAD / DWG block 點位批量放置 Revit 元件。
- `SC 後台`：查看工具操作紀錄、建立結果與後續管理狀態。
- `開孔定位`：檢查 MEP 與建築連結物件，產生開孔候選。
- `消防支管建立`：依候選主管與撒水頭位置，輔助建立垂直於最近主管的消防支管。
- `身份檢查`：檢查選取元件是否具備後台追蹤所需身份資料。
- `參數健檢`：檢查 SC_ 參數缺漏與空值。
- `斷點檢查`：診斷 pipe / duct / conduit 連接狀態，只對可修復 pipe 執行自動修復。
- `管支撐預覽`：依選取 pipe 產生支撐候選點預覽。

建議第一次使用時先測：

1. 開啟 Revit 2024。
2. 確認 `SC 族群工具` Ribbon 出現。
3. 開啟 `SC 後台`，確認 GUI 能啟動。
4. 在模型中選一個元件，執行 `身份檢查`。
5. 若要測 CAD 點位，請確認模型中已有 CAD Link 或 DWG 來源。

## 常見問題

### 看不到 Ribbon

- 確認已重新啟動 Revit。
- 重新執行 `Install_SC_REVIT.bat`。
- 確認目前使用的是 Revit 2024。

### Windows 跳出安全警告

目前安裝包未做程式碼簽章，Windows SmartScreen 或防毒軟體可能提醒。  
請確認檔案是從本 repo 的 GitHub Releases 下載。

### 點工具後沒有資料

部分工具依賴目前 Revit 模型狀態。  
例如 CAD 點位需要模型中有 CAD Link / DWG，管線檢查需要先選取 pipe / duct / conduit。

## 給開發者

這個 public repo 目前主要用來提供安裝包與版本說明。  
完整開發 source 不一定會公開在此 repo。

開發者打包新版 installer 時，請使用專案內的 release 打包腳本產生 installer ZIP，再上傳到 GitHub Releases。
