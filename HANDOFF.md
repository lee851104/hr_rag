# 新 Session 交接：企業請假與特休 RAG

更新日期：2026-10-19（Asia/Taipei，Claude接續完成階段5驗收與階段6）。本檔整理已完成的事實與後續限制；新 session 應先核對檔案現況。以下「費用」「最新候選」等較早段落保留作背景，現況以上方段落為準。

## 先讀與目前停止點（2026-10-19 Claude 接續後）

**2026-10-19 最終狀態：53/55。7.1凍結、7.3、7.4完成；7.2保留題已執行，授權11/12未達（H09 employee預期insufficient、實際answered但只引用C01公開內容；使用者決定照實記錄、不改判、不修改系統）；7.5 reports/acceptance.md完成，MVP依Release veto未標記完成。README已改寫（舊版docs/README-history.md）。剩餘API預算約US$0.061（461次／US$0.9392692）。若日後要修H09守衛，原保留題須標記曝光並重建新保留集。**

**介面補充（同日）：** 每角色兩題示範問題＋日期預設當天；之後依使用者確認的草稿改版介面（側欄＋底部提問列、本人查詢紀錄頁）；公開前移除本機使用者目錄（保留題位置改由 `HR_RAG_HOLDOUT_PATH` 或 `%LOCALAPPDATA%`）；目前凍結 `eval/final.freeze.json`（`561676be…`），v1–v3在 `eval/history/`。GitHub：https://github.com/lee851104/hr_rag ，靜態展示 docs/（GitHub Pages）。正式網頁啟動用workspace `.claude/launch.json` 的 `hr-rag-web`（使用者已用 `hr_rag.auth init` 設好自己的密碼）。

1. 本檔。
2. `openspec/changes/build-hr-leave-rag-mvp/tasks.md`：「最新進度」、5.4／5.5與階段6驗收段落、階段7。
3. `reports/stage-5-acceptance.md`：人工核對匯入、門檻計算與原文候選正式接入。
4. `reports/stage-6.md`：網頁、追溯、回饋、告警、三角色瀏覽器實測與修正。

### 階段5（人工驗收通過）

- 使用者核對JSON：`.runtime/stage5-private/{development,stability}-verbatim-gpt41-v3.review.json`（穩定性為第二次匯出；第一次匯出有3筆誤選，保留於 `-review-export1.json` 及 `reports/stage5-human-review-stability-v3-export1.json`）。Claude曾想以對話內容代套更正，被安全審查擋下並移除；更正由使用者本人在核對頁完成。
- `python -m hr_rag.answer_review` 驗hash／身份／引用對後依原門檻計算：開發可回答14/14、不足3/3、版本3/3、引用36/36、覆蓋26/26；穩定18/18、引用37/37。D11使用者判正確（與Codex初查不同，已揭露）。
- 正式生成改為原文選段 `verbatim-reference-closure-v3`（gpt-4.1-2025-04-14）：`config/generation.selected.json` 由 `config/models.lock.json` 的 `selected_generation` 以SHA256鎖定；`hr_rag.generation.selected_generator()` 驗設定／提示／schema／verbatim.py實作，不符即拒絕。舊mini摘要鎖定保存於 `config/history/models.lock.2026-10-18.json`；`OpenAISettings()` 類別預設仍為mini（歷史測試依此），正式路徑不用它。

### 階段6（完成）

- 新增 `audit.TraceStore／traced_answer／replay`、`feedback.py`、`monitoring.py`、`web.py` 模板與CSS；`AnswerService` 回報階段資訊並對防線攔截記 `guard/illegal_evidence`。
- 瀏覽器實測用 `.runtime/run_stage6_demo.py`（workspace根目錄 `.claude/launch.json` 的 `hr-rag-stage6-demo`）：隔離帳號 `.runtime/stage6-demo/`（測試密碼檔在此，非使用者帳號）、追溯／回饋在 `.runtime/audit-private/stage6-demo-*.sqlite3`。使用者原本 `.runtime/auth.sqlite3` 三帳號仍未設定密碼、未啟用。
- 實測發現並修正：no-referrer使表單Origin為null而無法登入（階段3既有）；錯誤狀態標籤誤示「暫時無法生成」（以回饋閉環修正，feedback `bb50b50c` fixed）。
- 完整離線 481 passed、1 skip；Ruff、OpenSpec strict通過。

### 階段7注意

- 7.2需要使用者設定 `HR_RAG_HOLDOUT_PATH` 並執行保留題評估；**Claude／Codex 都不可讀保留題正文**，只核對hash。保留題上下文人工標註須由使用者完成。
- 剩餘API預算約 **US$0.0921**（帳本449次／US$0.9078732）。gpt-4.1每題約US$0.002～0.0025，10保留題×角色執行大致可負擔，但重跑空間很小；開始前先估算。
- 7.1凍結須記錄新lock（`9b6f938d…f8200`）、`generation.selected.json`（`96489f26…aac1b4f26`）與 `config/monitoring.json`（`d7fc38fc…11157`）。

## 工作環境

- Workspace：`D:/@spin/5.DL/RAG/企業RAG知識點`
- 專案根目錄：`D:/@spin/5.DL/RAG/企業RAG知識點/hr-leave-rag`
- PowerShell、Python 3.12；使用專案 `.venv/Scripts/python.exe`。
- 此專案目前沒有Git repository；直接在現有專案工作，不自動初始化Git或建立另一份語料／帳本。
- 使用者指定 `openspec-apply-change`；skill在專案 `.agents/skills/openspec-apply-change/SKILL.md`，change是 `build-hr-leave-rag-mvp`。
- 私人實測檔在 `.runtime/stage5-private`，ACL受限；沙箱下存取可能需要正常的工具升權。不要放寬ACL或搬到公開報告目錄。

## 不可遺失的使用者限制

- 回應使用繁體中文，重點即可；不要開場白、讚美或反覆詢問下一步。
- 只用開發題調整；**不改原題、不改既有人工標註、不降低門檻**。D09已核准的新增標註另存在補充檔。
- `.env` 位於專案根目錄，已完成自動載入，環境變數優先。使用者已授權沿用，不需重新詢問金鑰來源。
- **不要顯示、記錄、複製或寫回API金鑰；不要輸出 `.env` 內容。**
- **API全專案累計硬上限US$1，包含失敗、小測、重試及先前session。不可重置、另建帳本或只計算本輪費用。**
- 禁止讀取、草擬、修改或以保留題正文調參。只可核對manifest、彙總與檔案hash。`verify_baseline()`的hash驗證可用。
- 使用者已同意「原文為主」：模型選段，程式呈現完整原文與引用；仍依原題目、標註和門檻驗收。
- 使用者已授權GPT-4.1實驗。Luna只有必要時可評估的授權，尚未查證並凍結可用快照／價格，未實測、未啟用；不能直接切換。
- 各階段完成驗收才進後續。不可代填使用者人工審核欄位。

## 費用：優先保護剩餘預算

最後實際帳本對帳：**445次；已結算估算US$0.8992952；預留US$0；剩餘US$0.1007048**。

- 原帳本：`.runtime/openai-cost.sqlite3`，不可刪除／重置／改路徑。
- 最新對帳：`reports/stage5-api-summary-verbatim-v3.json`，回連 `stage5-api-summary-verbatim.json`、`stage5-api-summary-wire.json`及更早歷史。
- 成功及失敗實驗均已包含；交換明細費用總和與帳本一致。
- 最終開發26次US$0.065852，穩定18次US$0.041900；合計US$0.107752。v3固定5題可行性另US$0.027220。
- 新session開始如需費用資訊，讀帳本彙總即可，無需再次呼叫API。人工核對及第六階段離線工作應優先進行。
- **不要直接重跑下面列出的live runner**：原始檔已存在，runner會拒絕覆寫；重跑也會耗剩餘預算。保留所有失敗紀錄，不為取得滿分持續抽樣。

## 最新候選與驗收結果

正式預設仍為 `config/models.lock.json` 的 `gpt-4.1-mini-2025-04-14` 摘要模式。原文候選 **尚未採用**，不能把runner內的替換視為正式應用已接好。

候選：`config/generation.verbatim-candidate-v3.json`；模型 `gpt-4.1-2025-04-14`；當輪記錄單價輸入US$2／百萬tokens、輸出US$8／百萬tokens。固定預算：4096上下文、2048證據、512輸出保留、128安全餘量、60秒逾時／2次重試。

| 檢查 | 最新結果與限制 |
|---|---|
| 0.8固定5題重驗 | 自動4/5、全繁體、全未逾時，P95 13.4248秒；Codex內容初查未見必要答案錯誤 |
| F2自動失敗 | 正確原文不符合既有regex的12字間距；維持原4/5，不改評分器 |
| 4.9 rerank | Top5及組裝後完整證據14/14，原人工標註精確度82.142857%，版本3/3，授權／執行錯誤／待標註0 |
| 4.9 dense／hybrid | 完整證據12/14、11/14；精確度77.5%、66.55% |
| 開發26角色執行 | 狀態26/26符合預期；Codex初查獨立可回答13/14、資料不足3/3、版本3/3、權限角色9/9 |
| 開發引用 | 36/36主張－引用對初查支持，已生成主張引用覆蓋100%；無主張列分母為零，標不適用 |
| 固定六案例×3 | 18/18初查符合必要內容、狀態及引用，未見矛盾；37/37主張－引用對支持 |
| 完整離線測試 | 410 passed、1 Windows symlink權限skip，180.48秒 |
| Ruff／OpenSpec strict | 通過 |

**D11仍失敗**：只選C01申請窗口與B-02流程，漏C02 FAQ中的必要項目核對及「必要性有疑義時轉人資」。整題判錯，不得把引用存在當成內容完整。原答案門檻是至少13/14，因此保留此失敗並不自動表示整個候選不達標，仍須人工確認其他項目。

已改善：D05／D06／D08／D10等摘要漏項由完整原文保留；D09補上明示準用的事假不給工資條文及不利處分保護，三次均完整；D12～D14保留有效版本的實際窗口／表單。D15員工缺少具名表單直接依據時，既有服務守衛回資料不足且移除猜測，hr／manager正常回答。

限制：原文較長；D03／D04附帶整條背景，D13參照補充包含同文件背景。D16員工及D20可能選公開示範說明，幫助有限但未捏造受限或真實公司答案。D05三次長度不同但必要答案均完整；穩定性要求無矛盾，沒有要求字句完全相同。

4.9最近重驗是**先前真實三模式top5及分數的驗證重播**，逐次驗索引／ACL／日期／撤回／全文，再重算實際組裝與原標註；不宣稱重新跑檢索模型推論。最終26＋18次生成皆為獨立真實API，無答案快取。

## 人工核對頁與新 Session 接續順序

兩頁已生成，預設全部「尚未核對」，匯出JSON綁定原始結果SHA256：

- `D:/@spin/5.DL/RAG/企業RAG知識點/hr-leave-rag/.runtime/stage5-private/development-verbatim-gpt41-v3.html`：26筆。
- `D:/@spin/5.DL/RAG/企業RAG知識點/hr-leave-rag/.runtime/stage5-private/stability-verbatim-gpt41-v3.html`：18筆。

1. 先處理使用者提供的新答案核對結果；尚無結果時，不重跑API，也不提前進6。核對的是新生成答案，既有上下文有用性標註不用重做。
2. 收到JSON時，驗證source_sha256對應原始結果、26／18筆身份與repeat、每項引用判定完整、核對者及日期。匯入／驗收自動化尚不能假設已有，需先查現有程式。
3. 依原門檻計算：5.4可回答至少13/14、不足3/3、版本3/3、引用支持≥95%、關鍵主張引用覆蓋100%；5.5固定18次必要內容／狀態／引用皆符合且無矛盾。不得預填全部通過，D11仍應按實際內容判錯。
4. 人工通過後，將已測原文候選正式接入生成器選擇與設定，保存候選及歷史鎖定紀錄，確保正式路徑和已測payload／預算一致；不能只改模型ID卻仍走摘要生成器。以適當離線測試驗證，不因單純接線重跑整套API。
5. 更新5.4／5.5證據與勾選，接著依使用者既有授權繼續階段6：本機網頁及日誌等，以tasks.md為準。後續live測試仍沿用剩餘累計預算。

## 本輪主要實作位置

- `src/hr_rag/providers.py`：摘要wire改為 `GeneratedAnswer(status, claims, reason)`；引用聯集由程式建立。新增可替換payload／decode掛點，對外Answer契約不變。
- `src/hr_rag/verbatim.py`：`SourceSelection`、`VerbatimGenerator`、`build_verbatim_payload`、`expand_source_references`。模型只傳source_ids；程式從實際送出的payload還原全文。
- `source_ids`的每次請求schema enum只允許已送出的引用別名；本機仍拒絕未知及重複ID，避免文件代號被誤當引用。
- 來源標示只送 `source=[document_id, version_id, section_id]`；緊湊JSON，固定可行性證據2035tokens，原2048上限未提高。
- 明示參照只在本次已授權上下文做有限閉包、去重，不查外部；新增原文標記「參照補充」。否定參照與跨逗號誤補已加反例修正。此為保守字面規則，不是完整法律依賴解析器。
- `src/hr_rag/context.py`：組裝接受實際payload_builder；預算與實際送出schema／提示一致。
- `src/hr_rag/answering.py`：提供生成器payload建構器，保留權限／日期／撤回／表單直接依據等守衛。
- `src/hr_rag/answer_review.py`：新答案HTML核對與匯出；不能把Codex初查自動轉成使用者簽核。
- 相關測試：`tests/test_verbatim.py`、`test_openai_provider.py`、`test_prompt_injection.py`、context／answering測試。
- 本輪獨立審查發現的否定參照缺陷，已先觀察3個反例失敗後修正；引用enum也先失敗再通過。歷史測試及失敗實驗不刪除。

## 結果、工具與重現證據

最新正式結果檔（私人，不覆寫）：

- `.runtime/stage5-private/feasibility-verbatim-gpt41-v3.json`
- `.runtime/stage5-private/retrieval-verbatim-gpt41-v3.json`
- `.runtime/stage5-private/development-verbatim-gpt41-v3.json`
- `.runtime/stage5-private/stability-verbatim-gpt41-v3.json`

工具（已在磁碟，勿當成可清除的臨時資料）：

- `.runtime/evaluate_verbatim_v3.py`：retrieval／feasibility／answers；後兩者會呼叫真實API，現在不要重跑。
- `.runtime/replay_frozen_retrieval.py`：評估用驗證重播，不替換正式檢索器。
- `.runtime/summarize_verbatim_v3.py`：對帳、統計及生成核對頁；原始結果不應被修改。
- `reports/stage5-verbatim-v3-tests.xml`、`.runtime/stage5-verbatim-v3-tests.log`：最後完整測試。
- `reports/retrieval-stage5-verbatim-v3.json`：三模式彙總。
- `reports/stability.json`：最新候選索引及過往失敗索引，accepted仍false。
- `reports/stage-5-wire-fixes.md`、`reports/stage-5-fixes.md`：先前實驗背景；最新狀態以v3報告為準。

離線檢查命令（專案根目錄）：

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src tests
openspec validate build-hr-leave-rag-mvp --strict
```

上述已通過；只在新改動或新疑慮需要時重跑，不需為交接重複整套測試。

## 凍結資料與保留題

已完成使用者審核：11個文件版本、20開發題、S01～S20片段與10保留題。保留題由Claude撰寫／修格式，使用者核准，Codex未讀正文。

保留題私人位置：`%LOCALAPPDATA%/hr-leave-rag-private/holdout/holdout.jsonl`，由 `HR_RAG_HOLDOUT_PATH` 指向。**禁止讀內容**，不再使用Claude暫存資料夾的舊路徑。

| 檔案 | SHA256 |
|---|---|
| 保留題（只可hash） | `ed30ff0f75e95deb0e349ef90a3d063f9b3f3f8e6354c1eff76b6a5ec5981989` |
| eval/development.jsonl | `06b18e9c8023d515ddad485222fa0634e661c95b26fd9881f235738a07ad21a4` |
| eval/labels.jsonl | `092e10881957c25bf1d80509cd742bac6bee5b15b26725c56c79e78084e13255` |
| eval/labels.supplemental.jsonl | `ae774bd9e47529e514d16e11f7e771ce3c58a72bddc171a8aad4589db2586ec6` |
| data/manifest.json | `fd19b3730eb61c23ab650fa5d9a86768c35e46913eaebf38ba7f5289c4f4b04d` |
| config/models.lock.json（2026-10-19採用原文候選後） | `9b6f938d75081160cea6e15b5c4dbd6891c17f459fae3477f1b59e4c1e7f8200` |
| config/history/models.lock.2026-10-18.json（原mini鎖定） | `77ab0f395e54a4c18c0786abcc5a052f16c91bf09232956b6a90e540577e58a8` |
| config/generation.selected.json | `96489f26502db0ba7294e221ff0e8bac818b17a3affc1f50d47a789aac1b4f26` |

目前核對頁、結果及實作hash已互相比對通過。以上hash是本次交接時狀態，日後正式採用候選造成的設定更新須另留證據，不應偽稱原鎖定未變。
