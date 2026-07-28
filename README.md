# SC REVIT

SC REVIT 是一套 Revit 2024 MEP 輔助工具集，目前以安裝包形式提供測試使用。  
目前請使用 GitHub Releases 下載安裝包，不要使用 GitHub 的 `Code > Download ZIP`。

目前倉庫原始碼版本為 `v0.5.0-drainage-dev`；GitHub Releases 中可直接安裝的版本仍為 `v0.4.1-dev`。

## v0.5.0-drainage-dev 開發狀態

本開發版新增 Revit 2024 排水接入幹管工作流程，包括：

- 以開放 piping connector 作為支管來源。
- 依序選取支管與目標主管。
- 立管使用來源側雙 45°、徑向管段及平面 45° 接入。
- 支援不同管徑與專案管件設定。
- 建立後檢查管件角度、接入方向、管段長度與拓撲。

目前立管路型已完成實機驗證；坡度同步及不同情境下的坡度編輯仍在調整。`v0.5.0-drainage-dev` 提供開發預覽安裝包，僅建議用於測試模型，不應直接用於正式專案。

## 排水操作手冊

使用排水工具前，請先閱讀 [SC REVIT v0.5.0 排水建模操作手冊](docs/SC_REVIT_v0.5.0_drainage_user_guide.html)。

手冊包含：

- SC REVIT 全部 16 個 Ribbon 命令的實際圖示與用途。
- 管件設定欄位與第一次設定順序。
- 「來源 → 主管」的正確選取流程。
- 立管雙 45°、徑向管段、平面 45°與斜 T／Y 的預期路型。
- 管中心對齊、45度對接、向下45°與垂直向下的使用邊界。
- 常見失敗碼、模型檢查與測試驗收清單。

### 排水 Ribbon 快速對照

| 圖示 | 按鈕 | 用途 |
| --- | --- | --- |
| <img src="docs/user-guide-assets/drainage_connect.png" width="44" alt=""> | 排水接入幹管 | 依序選取來源與主管，建立並驗證完整接管。 |
| <img src="docs/user-guide-assets/drainage_settings.png" width="44" alt=""> | 管件設定 | 設定 Pipe Type、System Type、管件、管徑與坡度。 |
| <img src="docs/user-guide-assets/align_centerline.png" width="44" alt=""> | 管中心對齊 | 依基準管局部高程對齊其他管段中心線。 |
| <img src="docs/user-guide-assets/connect_45.png" width="44" alt=""> | 45度對接 | 以一段 45°斜管連接兩個開放管端。 |
| <img src="docs/user-guide-assets/down_45.png" width="44" alt=""> | 向下45° | 只在單 45°路型可行時接入指定主管。 |
| <img src="docs/user-guide-assets/vertical_down.png" width="44" alt=""> | 垂直向下 | 延伸到基準管局部中心線高程，不接入基準管。 |

## 下載安裝包

最新排水開發預覽版：

[下載 SC_REVIT_v0.5.0-drainage-dev_installer.zip](https://github.com/NicheSam/SC-REVIT/releases/download/v0.5.0-drainage-dev/SC_REVIT_v0.5.0-drainage-dev_installer.zip)

[SC REVIT v0.5.0-drainage-dev Release](https://github.com/NicheSam/SC-REVIT/releases/tag/v0.5.0-drainage-dev)

前一個一般測試版：

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

1. 下載所需版本的 `SC_REVIT_*_installer.zip`。
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
- `排水接入幹管`：依序選取開放支管端與目標主管，建立符合專案設定的排水接管。
- `管件設定`：依 Pipe Type 設定斜 T／Y、45°彎頭、變徑及排水坡度。

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

這個 public repo 同時保存可下載安裝版的版本說明，以及目前公開的開發原始碼。  
`v0.5.0-drainage-dev` 尚未升格為正式安裝版本，使用前請自行建置並在測試模型驗證。

開發者打包新版 installer 時，請使用專案內的 release 打包腳本產生 installer ZIP，再上傳到 GitHub Releases。
