# SC REVIT

SC REVIT 是一套公司內部的 Revit MEP 工具集，目前聚焦在族群庫治理、CAD 點位放置、開孔定位與消防支管輔助建立。

## Versions

| Version | Folder | Status |
| --- | --- | --- |
| v0.2-stable | `v0.2-stable/` | 已封存的穩定版 |
| v0.2-dev | `v0.2-dev/` | 早期開發版備份 |

## v0.2-stable scope

- Revit family library classifier and review workflow.
- Project family recovery workflow.
- CAD block based point placement prototype.
- Opening candidate scan, 3D review, XLSX export, and plan mark prototype.
- Fire sprinkler branch pipe helper prototype.
- Revit add-in queue bridge source code.

## Repository note

這個 GitHub 版本不包含本機編譯產物、runtime 佇列、個人化的 `.addin` 絕對路徑或測試模型檔。若要部署，請在本機建置 DLL 後使用專案內的安裝腳本產生實際 `.addin`。

## Start

請先閱讀 [`v0.2-stable/README.md`](v0.2-stable/README.md) 與 [`v0.2-stable/RELEASE_NOTES_v0.2.md`](v0.2-stable/RELEASE_NOTES_v0.2.md)。
