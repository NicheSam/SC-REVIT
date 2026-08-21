# 消防支管 M2–M4 topology-only 活動模型驗證

日期：2026-08-20  
活動文件：`大甲分局_MEP_sc168jobim`  
驗證批次：`20260820-180056`  
模式：`test_fire_branch_pipes`／`execution_mode=sandbox`／`sandbox_scope=topology_only`

## 測試範圍

- 主管：ElementId `13740034`，DN100。
- 試點灑水頭：ElementId `13599867`、`13599868`。
- 拓樸計畫：`fire_branch_topology_plan.v5`。
- Plan ID：`sandbox-topology-20260820-m2m4`。
- 計畫管段：2 段，均為 DN25；兩段具有連續端點與穩定 `plan_entity_id`。
- 接頭計畫：1 個 `reducing_tee`，主管 DN100、支管 DN25。

## 結果

- 計畫管段套用數：2。
- 建立證據元素：1 條 feeder、2 條 branch。
- 建立失敗：0。
- `verification_status`：`verified`。
- `model_restored`：`true`。
- `restoration_verified`：`true`。
- `rollback_status`：`verified`。
- `residual_created_element_ids`：空集合。
- `topology_plan_identity`：schema、plan ID、plan hash 均回傳。

## 邊界

本測試只證明 M2–M4 的計畫驅動主管／支管／接頭幾何可建立並完整回復。`sprinkler_connectivity_assessed=false` 是刻意設定：測試跳過既有灑水頭垂管與灑水頭 Connector 路徑，不能解讀成灑水頭已完成連通，也不允許直接作為正式建立證據。

本輪沒有重開 Revit，也沒有重新部署 DLL。下一個獨立工作項目是既有灑水頭垂管／Connector 路徑的診斷與回歸，不能與已通過的 M2–M4 拓樸契約混在一起。
