# SC REVIT

SC REVIT 是一套 Revit 2024 MEP 輔助工具集，目前以安裝包形式提供測試使用。  
目前請使用 GitHub Releases 下載安裝包，不要使用 GitHub 的 `Code > Download ZIP`。

目前版本為 `v0.5.3`，整合點位放置、消防支管、預覽生命週期、CAD 路徑核對及部署穩定性修正。

## 快速下載

| 項目 | 連結 |
| --- | --- |
| Windows 一鍵安裝／更新包 | [下載 `SC_REVIT_v0.5.3_installer.zip`](https://github.com/NicheSam/SC-REVIT/releases/download/v0.5.3/SC_REVIT_v0.5.3_installer.zip) |
| SHA-256 校驗檔 | [下載 `SC_REVIT_v0.5.3_installer.zip.sha256`](https://github.com/NicheSam/SC-REVIT/releases/download/v0.5.3/SC_REVIT_v0.5.3_installer.zip.sha256) |
| 版本說明 | [GitHub Release：v0.5.3](https://github.com/NicheSam/SC-REVIT/releases/tag/v0.5.3) |
| 排水操作手冊 | [Markdown](docs/SC_REVIT_drainage_operation_manual.md) · [PDF](docs/SC_REVIT_drainage_operation_manual.pdf) |

> 請完整解壓縮下載的 installer ZIP，再執行裡面的 `Install_SC_REVIT.bat`。GitHub 自動提供的 `Source code (zip)` 與 `Source code (tar.gz)` 不是安裝包。

## v0.5.3 版本狀態

目前公開基準包含 Revit 2024 排水接入幹管工作流程，以及經實機驗證的消防支管建立與系統類型統一流程：

- 以開放 piping connector 作為支管來源。
- 依序選取支管與目標主管。
- 立管使用來源側雙 45°、徑向管段及平面 45° 接入。
- 支援不同管徑與專案管件設定。
- 建立後檢查管件角度、接入方向、管段長度與拓撲。

本版同時修正 CAD 點位與消防支管預覽殘留、異常座標、螢光路徑顯示及消防管網連接／系統類型問題。Agent listener 預設停用，Revit Ribbon 人工功能仍可正常使用；只在需要 Agent 功能時才手動啟用監聽。

## 排水操作手冊

目前手冊已依 `main` 的實際 Ribbon 與命令流程更新：

- [GitHub 可直接閱讀的 Markdown 完整手冊](docs/SC_REVIT_drainage_operation_manual.md)
- [下載／列印 PDF 手冊](docs/SC_REVIT_drainage_operation_manual.pdf)
- [HTML 圖文版](docs/SC_REVIT_v0.5.0_drainage_user_guide.html)（下載後以瀏覽器開啟）

目前排水面板對使用者開放三項操作：

### 排水 Ribbon 快速對照

| 圖示 | 按鈕 | 用途 |
| --- | --- | --- |
| <img src="docs/user-guide-assets/drainage_connect.png" width="44" alt=""> | 排水接入幹管 | 依提示先選來源，再選這一支要接入的主管；成功後可繼續下一支。 |
| <img src="docs/user-guide-assets/drainage_settings.png" width="44" alt=""> | 管件設定 | 依目標 Pipe Type／System Type 設定斜 T／Y、彎頭、變徑、坡度與管徑範圍。 |
| <img src="docs/user-guide-assets/align_centerline.png" width="44" alt=""> | 管中心對齊 | 先選非垂直的高程基準管，再連續對齊其他管段的局部中心線高程。 |

`45度對接`、`向下45°` 與 `垂直向下` 目前不在 Ribbon 上，不應再依舊手冊尋找這三個按鈕。

### 最短操作流程

1. 展開 `排水接入幹管`，先進入 `管件設定`。
2. 選擇目標 Pipe Type 與 System Type，新增設定列並確認管件、管徑及坡度後儲存。
3. 執行 `排水接入幹管`。
4. 依 `1/2` 提示點選設備接口或開放管端。
5. 依 `2/2` 提示明確點選本支要接入的主管。
6. 成功後直接繼續下一支；單支失敗會回復該支並顯示處理方式。
7. 按 `Esc` 結束整輪操作；成功結果合併為一次 Revit Undo。

## 下載安裝包

最新的 Revit 2024 測試安裝包：

[下載 SC_REVIT_v0.5.3_installer.zip](https://github.com/NicheSam/SC-REVIT/releases/download/v0.5.3/SC_REVIT_v0.5.3_installer.zip)

[SC REVIT v0.5.3 Release](https://github.com/NicheSam/SC-REVIT/releases/tag/v0.5.3)

請勿下載 Release 頁面自動列出的 `Source code (zip)` 或 `Source code (tar.gz)` 作為安裝包；那是給開發者使用的原始碼，不含可直接安裝的完整執行環境。

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
3. 關閉 Revit 2024 與所有 SC REVIT 視窗。
4. 執行 `Install_SC_REVIT.bat`。
5. 看到 `Installed SC REVIT successfully.` 後再開啟 Revit 2024。
6. 第一次出現未簽章外掛詢問時，確認外掛名稱為 `SC REVIT`，選擇「永遠載入」。
7. 在 Revit Ribbon 找到 `SC 族群工具`；一般 Ribbon 操作不需要開啟 Agent。

安裝腳本會自動：

- 複製 SC REVIT 到 `%LOCALAPPDATA%\SC_REVIT`
- 部署固定路徑的 Revit add-in DLL 到 `%LOCALAPPDATA%\SCRevit\Revit2024`
- 寫入 Revit 2024 addin manifest
- 設定 `SC_REVIT_HOME`

安裝時如 Revit 或 SC REVIT 正在執行，安裝程式會停止，避免覆寫正在載入的 DLL。

Agent listener 預設停用。需要 Agent 功能時，可在 SC REVIT GUI 按「啟用 Agent」，或執行安裝目錄內的 `Enable_SC_REVIT_Agent.bat`。

安裝目錄另外提供：

- `Enable_SC_REVIT_Agent.bat`／`Disable_SC_REVIT_Agent.bat`：明確啟用或停用 Agent listener。
- `Collect_SC_REVIT_Diagnostics.bat`：建立可交給開發者檢查的診斷 ZIP。
- `Uninstall_SC_REVIT.bat`：移除外掛程式與 manifest；預設保留 runtime 診斷資料。

## 更新方式

同一個 `Install_SC_REVIT.bat` 同時支援首次安裝與覆蓋更新，不需移除舊版：

1. 關閉 Revit。
2. 關閉所有 SC REVIT 視窗。
3. 到 GitHub Releases 下載新版 installer ZIP。
4. 解壓縮新版 ZIP。
5. 再次執行 `Install_SC_REVIT.bat`。
6. 重新啟動 Revit 2024。

新版安裝會覆蓋：

- `%LOCALAPPDATA%\SC_REVIT`
- `%LOCALAPPDATA%\SCRevit\Revit2024`
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

Revit 第一次載入此外掛時也會顯示未簽章警告。確認外掛名稱及下載來源後選擇「永遠載入」；固定 DLL 路徑與相同 AddIn ID 可避免每次更新都被當成不同外掛。

### Revit 卡頓、無回應或需要回報問題

1. 先執行 `Disable_SC_REVIT_Agent.bat`，確認人工 Ribbon 功能是否恢復正常。
2. 關閉 Revit 後重新測試。
3. 執行 `Collect_SC_REVIT_Diagnostics.bat`，將桌面產生的診斷 ZIP 交給開發者。

`v0.5.3` 的 Agent listener 預設停用；停用 Agent 不會移除或停用 Revit Ribbon 人工功能。

### 點工具後沒有資料

部分工具依賴目前 Revit 模型狀態。  
例如 CAD 點位需要模型中有 CAD Link / DWG，管線檢查需要先選取 pipe / duct / conduit。

## 給開發者

這個 public repo 同時保存可下載安裝版的版本說明，以及目前公開的開發原始碼。  
`v0.5.3` 已完成目前專案中的消防支管實機建立驗證；不同專案的族群 Connector、管件與系統設定仍可能不同，正式批次使用前應先做小範圍測試。

開發者打包新版 installer 時，請使用專案內的 release 打包腳本產生 installer ZIP，再上傳到 GitHub Releases。
