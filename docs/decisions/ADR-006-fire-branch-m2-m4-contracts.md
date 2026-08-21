# ADR-006：消防支管 M2–M4 計畫與編輯契約

日期：2026-08-20  
狀態：M2–M4 拓樸／計畫契約及 topology-only 沙盒通過；灑水頭 Connector 尚未在本輪驗證；不重新部署

## 背景

消防支管的 CAD 候選、SVG 顯示與 Revit 建模若各自重新判斷，會造成畫面看似正確、建模卻引用另一條管線。SVG 也需要讓使用者只做小幅、可追蹤的修正，而不是拖曳圖形直接改模型。

## 決策

1. M2 使用 `fire_branch_route_candidate_decision.v1`。候選先按是否到達目標灑水頭排序，再比較 CAD 連續覆蓋、管徑／拓樸證據、非路徑交點、轉折、長度與穩定識別碼。每個候選都保留指標、選取原因及淘汰原因。Revit 回傳的 `cad_route_assignments` 以權威結果為主轉入每顆灑水頭的候選決策；若離線排序與 Revit 選擇不一致，計畫標為待核對，不偷偷改路徑。
2. M3 對每一個支管、主管段、接頭及異徑建立穩定 `plan_entity_id`。計畫建立時檢查缺漏與重複；SVG 以 `data-plan-entity-id` 輸出，單顆試點不例外；Revit 建模前要求 `fire_branch_topology_plan.v5` 的 plan ID、hash 與項目 ID，執行與回報沿用同一識別碼及拓樸計畫 identity。
3. M4 只接受版本化結構命令：`change_segment_diameter`、`change_junction_type`、`change_reducer_sizes`、`choose_main_continuation`、`choose_route_candidate`、`mark_reviewed`。命令必須帶 `plan_id`、`expected_revision`、`expected_hash`、`target_id` 與原因。SVG 有多顆灑水頭候選時，按灑水頭列出候選並寫回同一份計畫；舊 `set_*` 命令僅為相容性保留。
4. 修改會產生新 revision，不覆寫父計畫；純拓樸驗證通過後才可進入 Revit 預檢／沙盒。這一輪不修改既有灑水頭垂管建立流程，也不自行重開或部署 Revit。

## 驗證

- `python -m unittest discover -p 'test_*.py' -q`
- 結果：263 項通過；活動模型預覽 CAD matched、覆蓋率 100%、12 顆灑水頭路徑候選均已解析，`fire_branch_topology_plan.v5` 為 valid。
- 可回復沙盒批次 `20260820-170852`：主管／支管證據元素曾建立，之後 `model_restored=true`、`restoration_verified=true`、無殘留元素；兩顆試點在既有 `CreateFireDropWithTransition` 的 DN25 灑水頭垂管建立失敗。此結果不否定 M2–M4 拓樸契約，但也不足以批准正式建模或 DLL 部署。
- 為了把兩個驗證邊界分開，`test_fire_branch_pipes` 新增僅限沙盒的 `sandbox_scope=topology_only`；它只驗證計畫指定的主管／支管／接頭，回報 `sprinkler_connectivity_assessed=false`，不進入既有灑水頭垂管流程，也不允許正式建立使用。
- 活動 Revit topology-only 沙盒批次 `20260820-180056` 通過：2 段 DN25 計畫管段、1 條 feeder、2 條 branch，`failed=[]`；`verification_status=verified`；`model_restored=true`、`restoration_verified=true`、`rollback_status=verified`、無殘留元素。此結果只證明 M2–M4 的計畫驅動幾何可建立並回復，`sprinkler_connectivity_assessed=false`。
- 已覆蓋候選比較、Revit 候選回傳轉接、計畫識別碼、版本／雜湊防呆、結構化編輯命令與 SVG 一對一標記。
- 本輪不重新開啟或部署 Revit；正式建模與灑水頭 Connector 連通仍需後續獨立驗證。

## 後續門檻

下一個門檻是獨立處理既有灑水頭垂管／Connector 路徑；不得把該路徑的失敗混入已通過的 M2–M4 拓樸契約。正式建立前仍須以同一份 plan hash 與 `plan_entity_id` 重新預檢。
