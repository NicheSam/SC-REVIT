# ADR-005：依實際配件解析消防四通後異徑位置

日期：2026-08-17

狀態：採用

## 背景

消防支管拓樸已能確認 `DN100 × DN100 × DN40 × DN40` 四通，但先前在四通旁以固定 80 mm 建立短管。Revit 放入目前 Pipe Type 的四通後，四通會修剪支管；實際模型量測顯示四通連接點距原交點約 105 mm，固定 80 mm 管段因此可能縮成零長度，後續異徑與連通驗證必然失敗。

不同 Pipe Type、Routing Preferences、管件族與尺寸組合的實際佔用長度不相同，因此固定毫米數不是可通用的建模規則。

## 決策

1. 拓樸計畫只記錄 `placement_strategy = fit_to_routing_parts`，不保存固定 `offset_mm`。
2. Revit 建模先以共同支管管徑建立四通並執行 `Document.Regenerate()`。
3. 建模端從四通實際 Connector 與現有支管幾何取得可用長度。
4. 先在 `SubTransaction` 中試放異徑，量測選中 Routing Preferences 配件造成的實際修剪量，然後回復試放。
5. 以實際修剪量加上 `Application.ShortCurveTolerance` 求最近可行位置；若最近位置無法建立，以有限次二分搜尋尋找最小可行距離。
6. 正式建立後重新取得 Pipe、Connector 與管件，驗證四通端、異徑兩端、管徑方向及正長度。
7. 回應資料保存每一列實際解析出的直管長度，供完整診斷與後續比對；SVG 與建模仍共用同一拓樸計畫。

## 驗證門檻

部署前須在目標 Revit 模型完成可回復沙盒，並同時確認：

- 所有計畫四通建立成功。
- 異徑由共同大管徑朝來源小管徑配置。
- 沒有零長度或異常長管。
- 所有目標灑水頭可由主管沿 MEP Connector 路徑到達。
- 沙盒結束後沒有測試元素殘留。

## 官方依據

- Autodesk Revit 2024 API Developers Guide — Routing Preferences：管件由 Routing Preference 規則與條件選取。
  https://help.autodesk.com/cloudhelp/2024/ENU/Revit-API/files/Revit_API_Developers_Guide/Discipline_Specific_Functionality/MEP_Engineering/Revit_API_Revit_API_Developers_Guide_Discipline_Specific_Functionality_MEP_Engineering_Routing_Preferences_html.html
- Autodesk Revit 2024 API Developers Guide — Regeneration：模型修改後，讀取更新幾何前必須重新產生文件。
  https://help.autodesk.com/cloudhelp/2024/ENU/Revit-API/files/Revit_API_Developers_Guide/Basic_Interaction_with_Revit_Elements/Transactions/Revit_API_Revit_API_Developers_Guide_Basic_Interaction_with_Revit_Elements_Transactions_Getting_Element_Geometry_and_AnalyticalModel_html.html

## 影響

- 新拓樸與執行計畫版本為 `fire_branch_topology_plan.v3` 與 `fire_branch_execution_plan.v3`。
- 舊 v2 計畫仍可作歷史紀錄，但重新分析時必須產生 v3，不能再把固定 80 mm 帶入建模。
- 這項修改只處理四通後異徑，不改動已通過的灑水頭垂管連接流程。
