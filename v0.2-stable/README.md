# SC REVIT v0.2-dev

這一版先把「分類規則」從資料夾架構抽出來，做成可維護的規則檔，並加入外部程式啟動時的族群庫根目錄選擇與驗證。

## 設計原則

1. 資料夾架構是唯一真實來源。
2. 規則只負責「建議分類」，不直接覆寫原始檔案。
3. 先看 Revit Category，再綜合族群名、型別名、檔名做加權判斷。
4. 沒命中、同分、或信心不足時，一律進人工確認流程。
5. 無法分類時送到：
   `03 管理區\03 無法自動分類`
6. 之後接上 Revit API 後，可再加入 Connector、系統分類、參數等更可靠訊號。

## 檔案

- `rules.json`：規則表
- `classifier.py`：分類器原型
- `library_validator.py`：族群庫根目錄驗證
- `app.py`：啟動時選擇族群庫資料夾
- `gui_app.py`：桌面工作台介面
- `gui_models.py`：GUI 任務資料模型
- `addin_installer.py`：GUI 啟動時自動檢查並安裝 Revit 外掛
- `listener_status.py`：讀取 Revit 監聽器心跳狀態
- `rfa_reader.py`：Python 端 RFA 讀取介面
- `revit_bridge/`：Revit API 橋接模組
- `revit_addin/`：真正執行 Revit API 讀檔的外掛端
- `sample_inputs.json`：測試資料
- `verify_rules.py`：檢查規則是否覆蓋所有末端資料夾

## 使用方式

```powershell
python classifier.py
```

目前輸出的是建議目標資料夾與命中的依據；不會搬移任何 RFA。

```powershell
python app.py
```

啟動後會要求選擇族群庫根目錄；若選到錯誤位置，會回報缺少哪些必要資料夾。

```powershell
python verify_rules.py
```

可檢查目前規則是否已覆蓋所有正式分類資料夾。

```powershell
python gui_app.py
```

啟動桌面工作台介面。

## RFA 讀取模組

`rfa_reader.py` 會負責驗證 `.rfa` 路徑、呼叫 `revit_bridge`，並把橋接器輸出的 JSON 轉成分類器可直接使用的資料格式。

目前已補上 `revit_addin/`，負責在 Revit 內真正開啟 RFA 並輸出 JSON。`workflow.py` 會等待這份 JSON、轉交給分類器，`app.py` 則把整段流程串成單一使用入口。

## 常駐監聽模式

Revit 外掛載入後會監聽：

```text
runtime\queue\requests
```

分類器送出請求後，Revit 會自動處理並寫回：

```text
runtime\queue\responses
```

如果讀取失敗，則寫入：

```text
runtime\queue\errors
```

Revit 外掛也會持續更新：

```text
runtime\queue\listener_heartbeat.json
```

GUI 會依這個心跳顯示 `Revit：已連線 / 未連線`。

## 未來擴充預留

目前 GUI 只做：

- 讀取
- 分類
- 人工改選
- 送待審核

資料模型已預留 `future_actions` 欄位，後續可再擴充：

- 自動更名
- 新增 / 修改 / 刪除 RFA 參數
- 發布前審核流程



## v0.3 模組化整理

本版已建立 sc_revit/ 模組邊界，後續新增功能請優先放入對應模組。詳細邊界與 Revit action 合約見：docs/v0_3_modular_architecture.md、docs/module_ownership.v0_3.json。

