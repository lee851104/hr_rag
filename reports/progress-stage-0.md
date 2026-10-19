# SDD ledger — plan: openspec/changes/build-hr-leave-rag-mvp/tasks.md

本次僅執行 0.1–0.6，階段 1–7 不在授權範圍。

## Pre-flight

- 0.2 → 0.3/0.6：共用 ContextBundle，provider 只接收組裝後證據；此階段不實作檢索與上下文組裝。
- 0.3 → 0.4：模型可行性必須呼叫實際 provider，不能用替身結果代替。
- 0.4 → 0.6：實際模型的上下文上限、token計算及耗時作為設定依據。
- 0.5 → 階段6：目前只建立不含正文的事件稽核介面，完整重播留待階段6。
- Ruling: 專案沒有 Git，直接在使用者已指定的獨立 hr-leave-rag 目錄實作，使用本檔保存紀錄，不執行依賴 Git 的工作樹與提交腳本。成本：目前沒有 Git 歷史回復能力。
- Ruling: 本機僅約2.2 GiB可用RAM、940MX僅2GB；三種模型依序載入，以CPU推論及GGUF量化生成器驗證，避免同時常駐。成本：正式互動延遲仍待後續階段量測。
- 本機模型不使用 OpenAI API，不讀取或建立 API 金鑰，不呼叫付費服務。

## Tasks

- 0.1：Python 3.12.10；.venv與全新.venv-verify皆以54套件鎖檔安裝並通過pip check；README已記重建命令。
- 0.2：初次測試因contracts模組不存在而失敗；實作後契約與settings測試通過。
- 0.3：初次測試因providers、local_models模組不存在而失敗；實作後全套40測試通過（3.51秒），包含真實子程序逾時終止。
- 0.4 complete：第二輪三模型各10/10，runtime-smoke.json all_passed=true，生成P50=10.9794秒/P95=13.6256秒。
- 0.5 complete：先有缺模組失敗，再完成白名單事件紀錄；防洩漏測試通過，stage-0.md已記命令、結果與限制。
- 0.6 complete：預算設定、負值、零輸出、超限與本機端點限制測試通過；runtime.md記錄實測數據與暫定180秒P95觀察門檻及其限制。
- 0.7 not passed（2026-10-18，規劃審查後新增）：公開法條與勞動部問答組成5個完整父段（證據1,715 tokens），手寫5題；常駐與依序兩種模式輸出相同，正確0/5，F2／F4／F5的reason含簡體，F3達512輸出上限；單題最長106秒（常駐）／135秒（依序），皆低於180秒；RSS峰值3.18 GiB（常駐）／1.80 GiB（依序）。未改提示或設定，停在此處待使用者選擇備案。
- Ruling（2026-10-18，使用者決定）：生成改用 OpenAI API，embedding 與重排留在本機；tasks 重新編號為 0.7 實作 OpenAI 生成、0.8 以 OpenAI 重跑真實長度實測、0.9 定案，上一行的第一次實測即舊 0.7。後續交由 Codex 執行。成本：生成需 API 費用且資料會送到 OpenAI。

## 安裝診斷

- uv從CPU索引解析torch==2.8.0+cpu失敗，改用官方索引確認的Windows wheel URL。
- uv生成的直接URL項目混入其他平台hash，觸發雜湊衝突。獨立下載後SHA256與官方索引均為2be20b2c05a0cce10430cc25f32b689259640d273232b2de357c35729132256d；鎖檔只保留此檔正確hash，再以--require-hashes在全新環境成功安裝。
- 一般沙箱拒絕建立venv、啟動uv或網路下載；限於此專案目錄的安裝與模型下載經工具審核放行，未變更系統Python或全域套件。

## Final review

- 獨立審查：review_stage0（gpt-6-astra），只讀階段0程式與規格，不要求階段1–7功能。
- Final: fixed 文件／片段日期將整數或午夜日期時間自動轉成日期 — 新增15項真實回歸測試，觀察15 failed後共用CalendarDate檢核，完整套件55/55通過（3.85秒）。
- Final: fixed 生成器對已提供的每週二證據錯誤拒答 — 第一輪9/10生成結果保存在runtime-smoke-attempt-1.json及runtime-exchanges-attempt-1.json；一般提示補上使用已明示證據的指示，原10題不改動，第二輪10/10通過，整體all_passed=true。
- Final: minor (deferred): ContextBundle.token_count仍接受bool轉int；此欄位目前只是描述值，生成前使用模型tokenizer重算，沒有使用它放行預算。嚴格整數輸入檢核留待上下文組裝階段。
- Final: Ruling: 審查未判定階段1–7的權限、日期隔離、引用白名單、檢索品質與正式追溯 — 遵守使用者只執行階段0的範圍，這些仍未實作；成本：目前介面不能當完整RAG產品使用。
- Final: Ruling: 審查未重跑大型下載／乾淨安裝及未完成報告 — 由主執行者以真實下載、第二個venv的pip check、最終模型輸出及報告核對負責；成本：這部分沒有第二次獨立重跑。
