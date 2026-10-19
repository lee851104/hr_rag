# 階段6：展示頁與可觀測性

2026-10-19（Claude接續）。**6.1～6.9完成，階段6通過，50/55。** 未讀保留題正文；未改題目、標註或門檻；正式生成為階段5人工驗收後採用的原文選段模式（gpt-4.1-2025-04-14）。

## 實作

| 項目 | 位置 | 內容 |
|---|---|---|
| 6.1 網頁 | `src/hr_rag/web.py`、`templates/`、`static/app.css` | 登入→首頁（角色、資料快照、外部模型與勿輸入個資提示）→`POST /query`（只收question／as_of＋CSRF）→`GET /queries/{id}`（本人限定，含原文引用展開）。生成未設定／達費用上限／逾時顯示可理解訊息與查詢識別碼。 |
| 6.2 安全 | 同上 | Jinja2自動轉義；CSP `default-src 'none'; style-src 'self'`（無任何腳本）；表單CSRF；同源檢查；登出頁回 `Clear-Site-Data` 並使session失效；只綁127.0.0.1。 |
| 6.3 稽核 | `src/hr_rag/audit.py` | `query`／`guard` 事件白名單：去識別user_ref（本機HMAC）、角色、日期、模式、快照（generation id＋manifest hash）、候選與最終證據ID、模型、提示／設定SHA256、response id、usage、成本、各階段耗時、錯誤／拒答代碼。無資料為null。 |
| 6.5 受限追溯 | `audit.TraceStore`、`traced_answer`、`replay`、CLI | 存原始／處理後問題、實際有序請求（系統提示＋問題＋最終上下文）、生成設定、原始輸出、最終答案、主張－引用對照、驗證結果；內容SHA256防竄改、input SHA256核對；預設30天、`purge`清除；寫入失敗回錯誤、不回無追溯答案；憑證欄位剔除、含金鑰樣式即拒存。 |
| 6.6 側路授權 | `web.py` | 本人紀錄每次以目前角色、撤回狀態與原查詢日期重驗；不可驗證的主張整段隱藏並提示；他人／不存在／格式錯誤ID同一404；無任何HTTP重播入口。 |
| 6.7 回饋 | `src/hr_rag/feedback.py`、CLI | 有用／無用＋4類原因enum，本人限定；處置 pending→analyzed→fixed／wont_fix；fixed須附通過且含修正測試的JUnit回歸證據（存SHA256），wont_fix須理由；使用者端只見分類與狀態。 |
| 6.8 告警 | `src/hr_rag/monitoring.py`、`config/monitoring.json` | 最近20次查詢錯誤率≥10%、P95>45秒、連續3次模型失敗、下游防線攔截非法證據；不足20次標資料不足；觸發／恢復歷史只含指標與數值。 |

`AnswerService` 另回報各階段資訊與拒答代碼；`assemble_context` 的重新驗權若攔到無權／失效證據，或生成後重驗失敗，即記 `guard/illegal_evidence`（證據不送模型）。生成器已記錄的錯誤不再重複記一次，避免連續失敗被重複計數。

告警門檻凍結：`config/monitoring.json`（SHA256 `d7fc38fc…11157`）沿用0.9的45秒（低於60秒逾時），於故障注入測試前凍結。階段5的44次真實API回答P50 1.26秒／P95 2.43秒，但採檢索排名重播、未含encoder推論，**不代表完整鏈路**。

## 瀏覽器三角色實測（6.4）

`.runtime/run_stage6_demo.py` 以隔離示範帳號（隨機測試密碼存 `.runtime/stage6-demo/demo-credentials.json`，非使用者帳號）、隔離事件／追溯／回饋檔啟動本機伺服器；費用上限取 `.env` 與US$1較低者。內建瀏覽器實際操作：

| 角色 | 問題 | 結果 | 總耗時（檢索／生成） | 費用 |
|---|---|---|---|---|
| employee | D01 婚假 | 已回答：婚假十四日、工資照給，引用O03 §2，展開原文正確 | 86.80秒（82.89冷啟動／3.41） | US$0.001806 |
| employee | 超長問題 | 「無法處理此問題／問題過長」＋查詢識別碼；未呼叫模型 | <0.1秒 | 0 |
| employee | D16（C04主題） | 資料不足；只見公開C01範圍說明，無C04內容 | 20.75秒（18.34／2.39） | US$0.001950 |
| manager | D15 | 已回答：C03橙色覆核單M-17＋C01不得因表單否定法定請假 | 11.24秒（9.56／1.63） | US$0.002432 |
| hr | D16 | 已回答：C04紫杉異常簿H-42及C04範圍限制 | 22.70秒（19.77／2.91） | US$0.002390 |

另驗證：登出後畫面清空且原紀錄401；hr開employee紀錄得到與不存在相同的404；回饋送出後顯示「待處理」。事件檔檢查無問題正文、文件內容、帳號名稱或金鑰樣式。

**延遲（不作效能承諾）：** 4次完成API的查詢總耗時 11.24／20.75／22.70／86.80秒，中位數21.73秒；樣本太少，P95不具意義故不計。首查包含本機encoder冷啟動（82.9秒檢索）；暖機後瓶頸是CPU重排（9.6～19.8秒），API生成1.6～3.4秒。冷啟動若落在最近20次窗口內可能觸發45秒P95告警，屬可見的營運訊號。`monitoring check` 對這5筆示範事件：錯誤率與P95「資料不足」（<20次），模型連續失敗0、非法證據0。

## 瀏覽器實測發現並修正的問題

1. **登入在真實瀏覽器一律403（階段3既有缺陷）。** `Referrer-Policy: no-referrer` 使同源表單POST的Origin被序列化為`null`，同源檢查拒絕。TestClient不送Origin所以先前測試未發現。改為`same-origin`；新增回歸 `test_browser_same_origin_form_post_is_not_null_origin`（先失敗後通過），`Origin: null` 仍被拒。
2. **回饋閉環（6.7實例）。** employee對超長問題結果回報「無用・其他」（feedback `bb50b50c`）。維護者以 `audit replay` 確認 error_code=invalid_input、未呼叫模型，但頁面把所有錯誤都標「暫時無法生成」→ 標 analyzed。新增 `test_input_error_is_not_labelled_generation_failure`，先觀察因標籤失敗，再依error_code分別顯示；以 `--junitxml=reports/stage6-feedback-regression.xml`（SHA256 `f4bb8fb1…ee11`）回歸通過後標 fixed，處理人與理由保留。重啟後瀏覽器確認顯示「無法處理此問題」與「已修正」。

## 測試

先失敗後通過：audit（新API不存在→10 errors）、feedback（collection error）、web（15 errors）、auth path、Origin回歸、錯誤標籤回歸。**monitoring測試先寫但未在實作前執行觀察失敗**，照實記錄。

```powershell
.venv/Scripts/python.exe -m pytest tests/test_web.py tests/test_audit.py tests/test_feedback.py tests/test_monitoring.py -q
.venv/Scripts/python.exe -m pytest -q --junitxml=reports/stage6-tests.xml
.venv/Scripts/python.exe -m ruff check src tests
openspec validate build-hr-leave-rag-mvp --strict
```

6.9命令50 passed；完整 **481 passed、1 Windows symlink權限skip，195.62秒**；Ruff與OpenSpec strict通過。

## 本機指令

```powershell
.venv/Scripts/python.exe -m hr_rag.web                       # 127.0.0.1:8000
.venv/Scripts/python.exe -m hr_rag.audit replay --trace-id ID
.venv/Scripts/python.exe -m hr_rag.audit purge [--before YYYY-MM-DD]   # 無日期＝清除逾30天
.venv/Scripts/python.exe -m hr_rag.feedback list|show|update ...
.venv/Scripts/python.exe -m hr_rag.monitoring check [--events PATH]
```

## 費用

本階段4次真實API（gpt-4.1），US$0.0085782。帳本 **449次、已結算US$0.9078732、預留0、剩餘US$0.0921268**（累計上限US$1，含所有歷史失敗）。

## 限制

- 隱藏策略以主張為單位；原文模式每主張單一引用，可安全拆分。
- 受限追溯保存當時正文供開發者重播，依30天保存與清除命令管理；一般使用者端看不到。
- 告警為本機CLI檢查，不做背景排程或外部通知。
- 示範帳號密碼與追溯檔只在 `.runtime/`（不入版控）；使用者原本的 `.runtime/auth.sqlite3` 帳號未變更、仍未啟用。
