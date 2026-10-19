# Tasks

> 本文件是「企業請假與特休 RAG Implementation Plan」。由實作者（Codex）依 OpenSpec apply 流程（.agents/skills/openspec-apply-change）逐階段執行，逐項取得證據才勾選。0.1–0.6 已於 2026-10-18 完成且勾選證據仍有效；同日規劃審查後新增真實長度實測，第一次以本機模型未達標，使用者改選 OpenAI 生成，階段 0 因此改為 0.7–0.9，完成後才可進入階段1。

## Codex 交接（2026-10-18）

- 已完成：0.1–0.6（證據見 reports/stage-0.md）；規劃審查修正；第一次真實長度實測（本機 Qwen2.5-1.5B，正確 0/5，見 reports/runtime.md 與 reports/feasibility-long-context.json）。
- 0.7離線實作已完成：98項測試、Ruff、全新venv雜湊安裝與pip check通過；後補.env自動載入達109項（證據見 reports/stage-0.md）。該次未呼叫真實API。
- 0.8已完成：使用者明確授權後，GPT-4.1 mini與GPT-4.1各5題，自動及Codex逐題內容核對皆5/5、繁體與耗時通過。10次請求累計估算US$0.0332040、預留0；本輪建議mini（US$0.0010884／題）。完整離線測試125 passed。內容核對不是使用者人工簽核；兩候選2027-01-14停用，詳見reports/runtime.md。
- 0.9已完成：使用者收到模型與成本比較後指示繼續0.9，凍結gpt-4.1-mini-2025-04-14及預算、60秒逾時／2次重試、45秒P95告警、encoder常駐；131項離線測試與Ruff通過。沒有新增API呼叫或費用，階段0完成。必要時使用者已授權評估Luna，但目前無需加測、未啟用或自動切換。
- 階段1可獨立工作已完成：6官方／4公司、11版本、20開發題草稿、6穩定案例、清單與評估檢核；205 passed／1 Windows symlink權限skip，Ruff及OpenSpec strict通過。完整證據見reports/stage-1.md及stage-1-artifacts.json。
- 階段1最新驗收：使用者已逐題核對20開發題，並明確確認11個文件版本及10題保留題內容無誤（2026-10-18）。11版本已verified，維護到期日2026-11-17；清單與開發題嚴格檢核0錯誤。保留題最終10題schema／引用／人工審核檢核全部通過，SHA256已凍結為ed30ff0f75e95deb0e349ef90a3d063f9b3f3f8e6354c1eff76b6a5ec5981989；未讀入正文或代改原檔。最新證據見reports/stage-1-resume.md。
- 最新進度（2026-10-19，Claude接續）：階段5通過（使用者人工核對），原文候選GPT-4.1正式接入；階段6完成（reports/stage-6.md）；7.1凍結、7.3、7.4完成，53/55；7.2保留題已執行但授權11/12未達（使用者決定照實記錄），7.5驗收報告完成、MVP未標記完成。以下為先前紀錄：0～4通過，5.1–5.3完成，39/55。原文候選GPT-4.1已完成0.8、4.9及26＋18次實測；Codex初查13/14可回答、3/3不足、3/3版本、18/18穩定；D11漏必要性疑義轉人資仍算失敗。5.4／5.5待使用者人工核對，未進6。正式模型仍mini；累計445次／US$0.8992952／預留0。最新reports/stage-5-verbatim-v3.md與兩份私人HTML，原題／標註／門檻未改。
- 使用者已自行提供專案根目錄.env，授權沿用既有金鑰與成本設定；本次累計硬上限1美元。OpenAI後台帳號用量限制由使用者管理，本機帳本不代表其他應用支出。
- 必須停下來請使用者決定：0.8 全部候選模型未達標；累計費用將超過上限；需要調降門檻、縮小範圍或改角色矩陣；換用未授權的更貴模型。必要時評估Luna已有使用者授權，但仍須查證快照／價格／參數並通過同一門檻，不提高原1美元累計上限。
- 不得做：建立、索取或保存金鑰到任何檔案與報告；讀取或草擬保留題（HR_RAG_HOLDOUT_PATH 內容）；刪除或覆寫第一次實測紀錄；跳過階段驗收。
- 規劃改動須同步 proposal、specs、design、tasks，並以 `openspec validate build-hr-leave-rag-mvp --strict` 驗證。

**Goal:** 以 10 份主文件完成官方引用、公司流程查詢及前置權限過濾三項能力。

**Architecture:** 文件正規化後存入 SQLite 與本機向量快照；伺服器先建立有權且有效的候選集合，在本機檢索與重排，最後只把問題與已授權的最終上下文送到 OpenAI API 生成。單輪本機網頁展示，不共用答案快取。

**Tech Stack:** Python 3.12、venv、SQLite、NumPy、sentence-transformers（本機 embedding 與重排）、jieba、rank-bm25、FastAPI、Jinja2、pytest、openai SDK 與 tiktoken（0.7 補鎖）；生成模型為 OpenAI，快照 ID 於 0.9 鎖定。

**Spec:** 同目錄 proposal.md、design.md、specs/*/spec.md。所有下列路徑相對 hr-leave-rag 專案根目錄；命令均為後續實作完成後才可執行，不代表已執行成功。

## Global Constraints

- 2026-10-18 使用者核准依賴調整：1.1、1.2、1.3、1.6與20開發題人工核對通過後，可先執行不讀取保留題的階段2；1.4／1.5保留題格式驗證、合格摘要及SHA256凍結延後至階段4開始前完成。階段1整體仍不可提前標記通過，階段2片段人工核對與其他階段門檻不變。

- 2026-10-18 使用者補充0.7設定入口：自動讀取專案根目錄 `.env` 的 OPENAI_API_KEY 與 HR_RAG_COST_LIMIT_USD，環境變數優先；檔案不入版控，不顯示／記錄／寫回憑證。以暫存假設定驗證路徑、優先序、格式錯誤與隔離；不從檔案啟用HR_RAG_LIVE_API。此補充取代下文「只讀環境變數」的入口限制，不變更其他階段驗收。

- 10 個主文件、11 個初始版本；6 官方＋4 模擬公司；角色 employee/manager/hr。
- 日期分開記錄；有效區間含起日不含迄日；未知日期不假填。
- 30 題分為 20 開發／10 保留；保留題由不參與調參的 Claude 草擬、使用者審核定稿，存於專案外（HR_RAG_HOLDOUT_PATH），專案內只留題數、分配與hash，Codex 不得讀取或用於調參。
- 子片段不超過400、查詢表示不超過96個encoder tokens，均以實際tokenizer計數。
- 生成改用 OpenAI API（2026-10-18 使用者決定），embedding 與重排留在本機；只送問題與已授權的最終上下文，不送身分資訊。金鑰由使用者以環境變數提供；累計成本達 HR_RAG_COST_LIMIT_USD 即停止。換模型或降低門檻由使用者決定。
- 預設 pytest 不連網、不需金鑰；真實 API 呼叫只在明確設定 HR_RAG_LIVE_API=1 或執行實測命令時發生，並記錄成本。
- 同義詞表、工程fixture、回饋與稽核都不是新增主文件，不匯入知識索引；穩定性18次執行不增加獨立題數。
- 所有檢索模式、父片段、引用與紀錄存取都驗權；無權片段必須為零。
- 一次一個階段；除上述使用者核准的階段2例外外，每階段驗收通過才進入下一階段。新增功能或變更門檻先更新規格。
- 自動測試採先失敗、再最小實作、再通過；人工驗收附實際證據。若已建立 Git，階段通過後做範圍明確的 commit，不自動推送。

## Review Focus

- 新舊版交界、未知日期、各條文不同生效日 → 階段 2/3 日期測試。
- 原文端點、跨帳號、提示文字冒充 HR → 階段 3/6 授權測試。
- 切片割裂例外或混淆法規與公司流程 → 階段 2/5 人工與跨文件測試。
- 更新失敗、撤回後殘留向量／BM25 → 階段 2/4 快照與雙路徑測試。
- FAQ 原句洩漏、保留題被調參看到、模型故障被排除分母 → 階段 1/5/7 評估與故障測試。
- 父段重複、超出模型上限、預算移除例外、引用未送入模型的候選 → 階段 4/5 上下文與引用測試。
- 檢索命中卻充滿雜訊、同題三次矛盾 → 階段 4/5/7 精確度與穩定性驗收。
- 查詢紀錄殘留已撤回內容、重播混用新版、回饋無回歸證據、告警漏報 → 階段 6 安全與治理測試。
- OpenAI 模型在真實長度上下文的正確率、繁體輸出、延遲與成本 → 0.8 實測，階段5再驗。
- 送往 OpenAI 的請求夾帶無權內容、身分資訊或金鑰外洩到日誌 → 0.7／3／5 測試。
- 子片段或查詢超過encoder上限、民國日期誤轉、問答頁誤用網站更新日 → 階段 1/2/4 測試。
- 保留題內容出現在專案目錄或實作對話中 → 階段 1/7 檢查。

## 0. 環境與執行契約

Files: pyproject.toml、requirements.lock、src/hr_rag/{contracts,settings,providers,audit}.py、tests/test_contracts.py、tests/test_providers.py、README.md、reports/runtime.md；0.7–0.9另有src/hr_rag/providers.py的OpenAI生成、tests/test_openai_provider.py、.env.example、scripts/feasibility_long_context.py、reports/feasibility-long-context-openai.json、config/models.lock.json。

Interfaces: contracts 定義 Principal(user_id, role)、DocumentVersion（design 日期／來源／維護欄位）、Chunk(id, document_id, version_id, section_id, parent_id, text, allowed_roles, effective_from, effective_to)、Evidence(chunk, score)、ContextBundle(units, citation_map, token_count, dropped_reasons, config_hash)、Claim(text, citation_ids)、Answer(status, claims, citations, reason)、QueryRequest(question, as_of)。ContextBundle 的 units 是最終有序完整證據單位，citation_map 保存單位與來源定位；狀態固定 answered/insufficient/conflict/error，證據欄位禁止使用前端傳入內容。

- [x] 0.1 建立 Python 3.12 venv 與套件設定，鎖定依賴並驗證 `.venv/Scripts/python.exe -m pip check` 成功；README 記錄可重現安裝命令。
- [x] 0.2 定義上述型別及設定驗證；先寫 tests/test_contracts.py，斷言未知角色、空問題、無效日期、反向有效區間均被拒絕，執行 `python -m pytest tests/test_contracts.py -q` 通過。
- [x] 0.3 實作 providers 介面 `embed(texts: list[str]) -> ndarray`、`rerank(query: str, texts: list[str]) -> list[float]`、`generate(question: str, context: ContextBundle) -> Answer`；提供取得實際模型請求及原始輸出的稽核掛點。測試替身與故障注入驗證輸出長度、NaN、逾時及無效 JSON 被受控處理。
- [x] 0.4 檢查可用硬體，選擇並鎖定實際 embedding／reranker／generator 與 revision，以 10 個無敏感資料樣本執行三種介面；reports/runtime.md 記錄模型、硬體、耗時及限制；不能以替身代替此項。
- [x] 0.5 建立 `record_event(event: dict) -> str` 最小稽核介面，回傳 trace_id；測試金鑰與密碼欄位不被寫出；將本階段命令與結果寫入 reports/stage-0.md。
- [x] 0.6 定義 ContextBundle、模型上下文上限、token計算法、evidence_budget、output_reserve、safety_margin；測試負值、無剩餘預算及輸入加輸出保留量超限的設定被拒絕。reports/runtime.md 記錄實測模型設定與本機P95告警門檻及理由，不把門檻當實測成績。
- [x] 0.7 實作 OpenAI 生成 provider（離線部分不需金鑰）：補鎖官方 openai SDK 與 tiktoken，重新產生 requirements.lock 時保留 Torch 官方 Windows wheel 的單一 SHA256，在全新 venv 以 --require-hashes 安裝並 pip check。新增 OpenAI 生成類別，符合既有 `generate(question, context) -> Answer` 介面與稽核掛點；以 Structured Outputs 嚴格 JSON schema 取得 Answer，API 支援時不在 OpenAI 端保存回應。settings 新增生成 provider 設定，只允許 https://api.openai.com/v1，金鑰只讀 OPENAI_API_KEY（新增只含空白欄位的 .env.example），並支援 HR_RAG_COST_LIMIT_USD 累計成本上限；呼叫前以 tiktoken 檢查預算，呼叫後記錄 response id、實際模型 ID、usage（含推理 tokens）與成本估算；audit 錯誤碼新增 rate_limited、cost_limit、not_configured。先寫 tests/test_openai_provider.py（假 client、不連網）並觀察失敗，再實作到通過：缺金鑰受控錯誤且不發請求、非允許端點被拒、請求只含系統提示／問題／上下文且不含 user_id 與角色、金鑰不出現在例外與稽核、429／5xx 有限重試後受控失敗、逾時、無效 JSON 與不符 schema、達成本上限停止呼叫。真實 API 測試僅在 HR_RAG_LIVE_API=1 時執行。完整 pytest 與 ruff 通過；本機 LlamaGenerator 保留供 0.4 紀錄重現，不刪除。
- [x] 0.8 真實長度可行性實測（OpenAI，須使用者已設定 OPENAI_API_KEY 與 HR_RAG_COST_LIMIT_USD）：沿用 scripts/feasibility_long_context.py 的20個證據單位、固定5段上下文與F1–F5（F2檢核已收緊），新增 `--provider openai --model <ID>` 執行，結果另存 reports/feasibility-long-context-openai.json，不覆寫第一次本機結果。從 OpenAI 當時官方模型清單選至少一個小型低價模型與一個較大的模型（皆支援 Structured Outputs），官方價格與查證日期寫入 reports/runtime.md。量測關鍵主張與引用正確性（自動檢核加人工判定）、繁體輸出、本機檢索與 API 往返耗時、本機 encoder 記憶體、每題 tokens 與成本。門檻：5題至少4題正確、全部繁體、單題總耗時皆低於單次逾時；在達標模型中選每題成本較低者。全部未達標時停止並請使用者決定。（2026-10-18 第一次實測用本機 Qwen2.5-1.5B：正確0/5、繁體未通過、耗時通過，見 reports/runtime.md；使用者因此改選 OpenAI。）
- [x] 0.9 依0.8結果凍結 OpenAI 模型快照 ID、context_limit、evidence_budget、output_reserve（含推理 tokens）、safety_margin、逾時與重試次數、HR_RAG_COST_LIMIT_USD 建議值、encoder 常駐策略，以及低於單次逾時的暫定P95告警門檻；更新 config/models.lock.json（含價格查證日期）、settings 預設值與 reports/runtime.md，重跑0.6預算測試與完整 pytest，並將證據補入 reports/stage-0.md。使用者確認選定模型與每題成本後，階段0才算通過。

## 1. 資料與評估基準

Depends on: 0。Files: data/manifest.json、data/raw/、data/normalized/、eval/development.jsonl、eval/holdout.manifest.json（保留題正文在專案外）、src/hr_rag/corpus/manifest.py、tests/test_manifest.py、reports/stage-1.md。

進度（2026-10-18）：11文件版本與20開發題已由使用者核對，嚴格驗證0錯誤；74項階段1測試通過、1項Windows symlink權限skip。1.1–1.6全部完成；10保留題格式、引用及審核通過，已凍結hash並移至專案外私人資料夾。人工核對及驗證證據見reports/stage-1-resume.md。

- [x] 1.1 依 design 的 O01–O06 下載並保存官方原始快照、網址與擷取時間；逐份核對條文範圍與日期證據，清單中官方數量斷言 `official_count == 6`。民國日期轉為西元並保存原始字串；納入索引的條文逐條依施行條款（如勞基法第86條）及沿革頁記錄施行日；O05、O06採問答發布日期為effective_from並註明非法規生效日，項目更新日期經人工比對才記為revised_at，不使用網站頁尾更新日。
- [x] 1.2 自編 C01–C04，C01 含兩版且只改申請窗口／流程；逐份核對虛構標示、角色矩陣與法規衝突；斷言 `document_count == 10`、`version_count == 11`。
- [x] 1.3 實作 `validate_manifest(path: Path) -> list[str]` 與民國日期轉換，先測重複 ID、缺來源、無權限、日期未知、版本重疊、hash 不符，以及「民國 113 年 07 月 31 日」→2024-07-31、「一百零六年一月一日」→2017-01-01、不合法民國日期進待核對；`python -m pytest tests/test_manifest.py -q` 全過，真實清單沒有未處理錯誤。
- [x] 1.4 草擬並由人工核對20題開發題、逐角色預期（role_expectations）、必要證據組及答案，分配依 design 6. 節；權限題三角色預期齊全。10題保留題已於2026-10-18由不參與調參的Claude草擬、交使用者審核，存於HR_RAG_HOLDOUT_PATH指定的專案外位置；Codex不得草擬、修改或讀取。其中H07–H09依賴公司文件，C01–C04定稿後由使用者（可再請Claude協助，不得交給Codex）依原文補齊答案與證據定位，審核後才凍結hash。專案內只建立eval/holdout.manifest.json（題數、分配、SHA256、草擬者、審核者），內容由使用者提供。報告記錄各類題數、hash、撰寫者及核對者；不得宣稱尚未人工核對的題目已驗收。
- [x] 1.5 新增評估格式檢核，斷言開發20題、各類加總與 question_id 不重複、role_expectations 欄位完整且權限題含三角色；保留題由使用者在專案外以同一檢核器驗證10題與分配，專案只記輸出摘要與hash；檢查專案目錄內沒有保留題正文。只以白名單匯入 data，不可匯入 eval；將來源清單與評估分割證據寫入 reports/stage-1.md。
- [x] 1.6 為10主文件補 source_publisher、maintenance_owner、last_reviewed_at、next_review_due；測試缺負責角色及不合理核對日期被拒絕，到期清單正確指出文件與責任。從20題開發集固定選出官方、公司、跨文件、版本、權限、資料不足各一題作穩定性案例，記錄角色、日期、預期結果及hash；不新增主文件或獨立評估題。

## 2. 匯入、切片與版本

進度（2026-10-18）：2.1–2.4及2.6已完成；232 passed／1 Windows symlink skip、Ruff與真實本機embedding通過，獨立審查問題已修正。44父段／46子片段，embedding最大388／reranker最大311 tokens。2.5的S01～S20已由使用者全部簽核，第二階段整體通過。證據見reports/stage-2.md。

Depends on: 1.1、1.2、1.3、1.6及20開發題人工核對；保留題1.4／1.5延後至階段4前。Files: src/hr_rag/corpus/{ingest,chunking}.py、src/hr_rag/storage.py、tests/test_ingestion.py、tests/test_versions.py、reports/stage-2.md。

Interfaces: `chunk_document(document: DocumentVersion, text: str) -> list[Chunk]`；`ingest(manifest_path: Path) -> str` 回傳發布的 generation_id；`withdraw(document_id: str, version_id: str) -> None`。

- [x] 2.1 先以條文、項款、完整問答和例外建立切片測試，再實作 chunk_document；斷言每個片段有原文定位、版本與 ACL，例外與所屬規則可一併回溯；以實際encoder tokenizer斷言全部子片段不超過400 tokens，超長條文依項款拆分且共用父片段，單句超限標記待人工處理而不截斷。
- [x] 2.2 實作 SQLite 表、原文 hash 與向量快照；`test_ingest_twice_is_idempotent` 斷言重匯入前後 ID 集合與數量相同，`python -m pytest tests/test_ingestion.py -q` 通過。
- [x] 2.3 實作 staging 驗證後原子發布；故意令 embedding 中途失敗，`test_failed_generation_preserves_active` 斷言 active generation 不變且無半成品可查。
- [x] 2.4 實作撤回與版本區間檢查；tests/test_versions.py 涵蓋 2026-09-30/v1、2026-10-01/v2、未知日期隔離、分條施行與重疊拒絕；全部通過。
- [x] 2.5 人工核對至少20片段、涵蓋全部10主文件，記錄正反例原文與定位；全數正確及前述自動測試通過才將 reports/stage-2.md 標為通過。
- [x] 2.6 實作增量向量重用；以embedding呼叫紀錄驗證相同匯入0次、只修改C02時其餘9份ID與向量不變、只改ACL／日期0次、刪除片段從索引退出；模型或切片設定改變有全量重建原因。更新失敗仍保留舊generation，將呼叫數及hash證據補入reports/stage-2.md，所有本階段任務通過才放行。

## 3. 身分、權限與有效候選集合

Depends on: 2。Files: src/hr_rag/{auth,policy,citations,web}.py、tests/test_auth.py、tests/test_policy.py、tests/test_citation_access.py、reports/stage-3.md。

Interfaces: `authenticate(session_id: str) -> Principal`；`eligible_chunks(principal: Principal, as_of: date) -> list[Chunk]`；`read_citation(principal: Principal, citation_id: str, as_of: date) -> Chunk`。web 建立登入／登出及引用端點，查詢端點留到階段6。

- [x] 3.1 先補鎖網頁執行依賴（uvicorn、python-multipart），重新產生 requirements.lock 時保留 Torch 官方 Windows wheel 的單一 SHA256，在全新 venv 以 --require-hashes 安裝並 pip check 通過；再建立三個伺服器示範帳號、密碼雜湊及伺服器 session；tests/test_auth.py 斷言未登入401、任意 role 欄位無法升權、登出後舊session失效。
- [x] 3.2 實作 eligible_chunks；以獨立合成測試而非保留題驗證 C03/C04 三角色矩陣、缺 ACL 預設拒絕、條文有效區間；`python -m pytest tests/test_policy.py -q` 全過。
- [x] 3.3 實作 read_citation 與 `GET /citations/{citation_id}`，tests/test_citation_access.py 斷言不存在與未授權均404且不帶標題，撤回後原引用也404；用測試替身建立 citation，不依賴尚未完成的生成。
- [x] 3.4 測試 hr→employee、兩帳號並行與角色變更後重查：各請求 eligible IDs 只含自己的授權集合，不共享上下文；問題中明確的西元或民國日期（含只到年或年月）與查詢日期不同時回傳釐清訊息並顯示兩者，「今年」「明年」等相對說法不判為衝突。
- [x] 3.5 執行 `python -m pytest tests/test_auth.py tests/test_policy.py tests/test_citation_access.py -q`，將角色矩陣、錯誤回應與全部結果寫入 reports/stage-3.md；任何洩漏都阻止下一階段。
- [x] 3.6 接續2.6的metadata更新fixture，驗證發布後新ACL／日期立即作用於eligible IDs及原引用，舊session不能保留舊權限；將新增結果納入reports/stage-3.md。

## 4. 檢索基線與改善

Depends on: 3及完整階段1（包含1.4／1.5保留題格式驗證、合格摘要與SHA256凍結）；開始前必須重新確認，不可先跑檢索實驗或調參。Files: src/hr_rag/{retrieval,evaluation,query,context}.py、config/query-synonyms.json、tests/test_retrieval.py、tests/test_evaluation.py、tests/test_query.py、tests/test_context.py、reports/retrieval-comparison.json、reports/stage-4.md。

Interfaces: `retrieve(query: str, principal: Principal, as_of: date, mode: str, k: int = 5) -> list[Evidence]`，mode 為 dense/hybrid/rerank；`evaluate(cases_path: Path, mode: str, corpus: str) -> dict`。

補充介面：`normalize_query(question: str) -> str` 保留原問題另存稽核；`assemble_context(evidence: list[Evidence], principal: Principal, as_of: date, question: str) -> ContextBundle`。預算依最終模型提示序列化計算，不只對證據文字計數；完成前處理、組裝與評分後才比較模式，4.9為本階段最終放行。

2026-10-18開發調整：使用者要求不改人工標註、不降門檻；4.9比較可關閉的leave_scope_filter。僅排除問題與後續給假條文明確假別不符的完整單位；第一名、一般規則、否定／比較、多假別與法規交互引用保守保留，不用題號／來源ID／gold／labels決定排除。必須以新合成反例、實際三模式與完整安全回歸驗證，完整設定含此開關及規則版本後才凍結。

- [x] 4.1 先寫假向量可預期排名測試，再實作 dense；在評分前呼叫 eligible_chunks，tests/test_retrieval.py 斷言無權及過期高相似片段仍不會進候選。
- [x] 4.2 加入保留條號的中文 BM25、RRF常數60與最多20候選規則；測試同分排序、空集合、候選不足及父片段展開後重新驗權。
- [x] 4.3 加入 rerank，測試替身記錄輸入以斷言未授權文本從未送入重排器；撤回來源後 dense/BM25/rerank 均無殘留命中。
- [x] 4.4 實作 evaluate 與 `python -m hr_rag.evaluation --split development --mode all --corpus full` CLI；人工小例測試證據組計分、零分母、錯誤不刪分母與候選/展開的計分差異。
- [x] 4.5 實作版本化中文同義詞前處理；tests/test_query.py 驗證特休／特別休假配對命中相同必要證據組，補休不混同特休，否定、條號、日數與日期保留；處理後查詢表示超過96個encoder tokens回傳受控「問題過長」錯誤且不呼叫encoder。三模式使用共同查詢表示；用開發題記錄前處理開／關差異，凍結詞表hash。
- [x] 4.6 實作assemble_context：同父段去重、跨來源合併限制、來源映射、穩定排序、重新驗權、相關度篩選（context_max_units與min_relevance，C用重排分數、A／B用相對第一名比例，至少保留第一名）及完整單位token預算；tests/test_context.py 涵蓋同父段多次命中、跨來源相同正文、官方／公司衝突、低於門檻的單位被篩掉並記原因、小預算排除完整條文、提示本身超限、已篩掉或移除的片段不在引用白名單。`python -m pytest tests/test_query.py tests/test_context.py -q` 全過。
- [x] 4.7 擴充evaluate，分列Top-5（篩選前）與組裝後（篩選後）必要證據組覆蓋率／全組命中，及人工標註最終上下文精確度；有用性標註存於eval/labels.jsonl，以question_id、role與單位內容SHA256為鍵跨模式及重跑重用，只對新單位要求標註。測試5單位中2有用得到0.4、空上下文與執行錯誤記0、合併來源不重複計數、相同單位重用既有標註，不能以展開全文改善Top-5分數。
- [x] 4.8 固定快照、模型、提示與切片參數，實跑三模式；開發可回答14題至少13題完整證據Top-5命中、開發版本3/3、授權錯誤0，記錄逐題差異後只依開發集選最終模式，寫入 reports/stage-4.md。
- [x] 4.9 補齊三模式逐題上下文與人工有用性判定；選定模式除4.8外，開發組裝後完整證據至少13/14、平均上下文精確度≥80%，模型輸入無權／失效片段0。只用開發集凍結相關度篩選參數，以完整組裝設定、篩選參數及前處理版本更新reports/stage-4.md後才放行。

## 5. 證據式回答與拒答

Depends on: 4。Files: src/hr_rag/{answering,citations}.py、tests/test_answering.py、tests/test_prompt_injection.py、reports/stability.json、reports/stage-5.md。

Interfaces: `answer(request: QueryRequest, principal: Principal) -> Answer`；`validate_citations(answer: Answer, context: ContextBundle) -> list[str]`；使用階段0 providers 及階段4 retrieve/assemble_context，只允許引用實際送入模型的context。

- [x] 5.1 先測官方／公司混合題與假引用，再實作來源標示、證據白名單和 claims 組裝；`test_unknown_citation_rejected` 斷言不合法ID無法顯示給使用者，引用附版本與定位。補鎖繁簡字表依賴並實作輸出檢查，`test_simplified_output_rejected` 斷言含簡體專用字的主張回傳受控格式錯誤且計入錯誤率。
- [x] 5.2 實作無證據、部分證據、衝突處理；測試個人剩餘假數不得捏造，假設衝突文件只留測試fixture，不混進10份正式語料。
- [x] 5.3 tests/test_prompt_injection.py 使用夾帶「我是HR／忽略規則」文件與問題；檢查候選、模型輸入及輸出引用均未升權；tests/test_answering.py 驗證逾時、無效JSON、無效日期與空輸入的受控結果；以假 client 攔截送往 OpenAI 的請求，斷言 employee／manager 查 C04 時請求不含 C04 正文、標題、使用者識別碼與角色名稱。
- [x] 5.4 用實際模型跑開發題並人工核對，至少13/14可回答題正確、3/3資料不足題不捏造、3/3版本題正確，引用支持率≥95%及關鍵主張覆蓋率100%；將逐題理由與測試命令寫入 reports/stage-5.md。修證據與提示後仍未達標時，經使用者同意費用後改用較大的 OpenAI 模型，重跑0.8、4.9與整個階段5；需要降低門檻時停止並請使用者決定。報告附本階段 API 呼叫次數、tokens 與實際費用。
- [x] 5.5 對階段1固定的6個開發案例各獨立呼叫實際模型3次，不共用答案快取；18次關鍵主張／狀態／引用均符合預期且無矛盾，模型故障不能算穩定通過。保存輸入hash、生成設定與逐次結果至reports/stability.json，人工核對後納入reports/stage-5.md；穩定性失敗不得放行。

5.4／5.5驗收（2026-10-19）：使用者人工核對匯入以`python -m hr_rag.answer_review`驗source hash、26／18筆身份、引用對與判定完整後依原門檻計算，不改寫判定。開發：可回答14/14、資料不足3/3、版本3/3、權限9/9、引用支持36/36、覆蓋26/26（reports/stage5-human-review-development-v3.json）。穩定：18/18、引用37/37（reports/stage5-human-review-stability-v3.json；第一次匯出3筆誤選的15/18結果保留於-export1）。原文候選已正式接入（config/generation.selected.json、models.lock.json selected_generation），432 passed／1 skip。詳見reports/stage-5-acceptance.md。

階段5實作補記：長引用ID採short-id-v1傳輸，本機一對一白名單還原與再驗權；輸出預留512不變。reason不提供無引用事實的顯示通道。完整上下文與80%精確度重驗維持不變後才執行最終實測。

## 6. 展示頁與可觀測性

Depends on: 5。Files: src/hr_rag/web.py、src/hr_rag/templates/、src/hr_rag/{audit,feedback,monitoring}.py、tests/test_web.py、tests/test_audit.py、tests/test_feedback.py、tests/test_monitoring.py、reports/stage-6.md。

補充介面：本機開發者使用 `python -m hr_rag.audit replay --trace-id ID`、`python -m hr_rag.audit purge --before DATE` 與 `python -m hr_rag.monitoring check`。`POST /queries/{id}/feedback` 只接受本人查詢的rating/reason enum，session與CSRF照原規則；回饋處置只用本機CLI，無新增角色、外部通知或自動知識更新。

- [x] 6.1 建立本機HTML登入、問題、日期、答案與引用視圖；`POST /query` 僅接受 question/as_of，角色來自session；`GET /queries/{id}` 只可查本人紀錄，tests/test_web.py 覆蓋未登入及越權存取。畫面標示答案由外部模型依引用證據生成，並提醒不要輸入個人資料；生成服務未設定或達成本上限時顯示可理解的訊息。
- [x] 6.2 加上HTML轉義、CSRF檢查與登出清空畫面，測試文件含script不執行、缺CSRF的變更請求被拒、登入後cookie設定及伺服器綁定127.0.0.1。
- [x] 6.3 擴充階段0稽核為 spec 要求欄位；tests/test_audit.py 斷言模型／提示／快照hash、OpenAI response id、實際模型 ID、usage 與成本估算、階段耗時、錯誤原因可追蹤，密碼／金鑰／Authorization header／限閱正文不進一般日誌，未知成本為null。
- [x] 6.4 三角色各完成一次瀏覽器端提問與引用檢視、測試錯誤提示；執行 `python -m pytest tests/test_web.py tests/test_audit.py -q`，記錄畫面與P50/P95實測資料至 reports/stage-6.md，不捏造效能承諾。
- [x] 6.5 實作受限稽核保存與重播：原始／處理後問題、實際有序模型提示及證據、生成設定、原始輸出、最終答案與主張引用映射；來源更新後重播仍與當時輸入hash相同且不呼叫模型。測試憑證不保存、正文不進一般日誌、預設30天保存／清除、稽核寫入失敗不回傳無追溯的成功答案。
- [x] 6.6 擴充本人查詢與回饋存取測試：角色降權或來源撤回後原答案及引用不再揭露已禁內容；他人trace／feedback與全域重播不可讀，不能從回饋側路取得限閱內容。
- [x] 6.7 實作有用／無用回饋、原因分類與本機處置狀態；tests/test_feedback.py 驗證缺回歸證據不得標記已修正。用既有開發案例或隔離fixture展示一次回報→分析→修正→回歸通過，保留處理人及原因，不新增主文件、不修改保留題。
- [x] 6.8 實作本機告警：tests/test_monitoring.py 注入20次含2次錯誤、P95超門檻、連續3次模型失敗、非法證據被防線阻擋，以及恢復正常的資料；各自觸發／恢復紀錄正確。不足20次或缺指標標資料不足；正常401/404不當成洩漏，告警不含正文。延遲門檻依完整鏈路實測設定且低於單次請求逾時，於測試前凍結，與正式評估分開保存。
- [x] 6.9 執行 `python -m pytest tests/test_web.py tests/test_audit.py tests/test_feedback.py tests/test_monitoring.py -q`，以受限重播、回饋閉環、告警觸發／恢復及三角色介面證據更新reports/stage-6.md，所有本階段任務通過才放行。

階段6驗收（2026-10-19）：網頁、CSRF／轉義、白名單事件、受限追溯重播與30天清除、本人紀錄降權／撤回重驗、回饋閉環（feedback bb50b50c→回歸JUnit→fixed）、本機告警全部有測試；三角色瀏覽器實測4次API（US$0.0085782）。瀏覽器實測另發現並修正階段3既有的no-referrer使表單Origin為null而無法登入。481 passed／1 skip。帳本449次／US$0.9078732。詳見reports/stage-6.md。

## 7. 凍結驗收與求職交付

Depends on: 6。Files: reports/acceptance.md、reports/corpus-comparison.json、README.md；使用既有 tests 與 evaluation，不延後補寫早期階段應有的測試。

- [x] 7.1 凍結最終設定、OpenAI 模型快照 ID、提示、語料、同義詞、上下文預算、告警門檻、成本上限與評估hash；執行 `python -m pytest -q` 並保存完整結果，確認所有安全及日期測試通過，固定6案例的18次穩定性執行對應最終設定且全過。
7.1凍結（2026-10-19）：eval/final.freeze.json（SHA256 ea94e4727666ad2a0374af82144d5f8f2bd83ef14dea67ab1900324f9d4ad4dc）記錄64檔hash、設定摘要與語料指紋；完整pytest 494 passed／1 skip（reports/stage7-freeze-tests.xml）。固定18次穩定性與最終設定的生成設定、提示、verbatim／providers／context／retrieval／query及評估資料hash相同；answering.py僅階段6加入紀錄掛點、models.lock.json僅新增採用條目，詳見reports/stage-7-freeze.md。7.2入口改為 `python -m hr_rag.holdout`（見design）。

- [ ] 7.2 由使用者設定 HR_RAG_HOLDOUT_PATH 後使用 `python -m hr_rag.evaluation --split holdout --mode selected --corpus full` 跑10題保留題並人工標註保留題上下文，先自行檢視逐題結果；檔案hash須與eval/holdout.manifest.json相符。再彙總固定設定下全30題；Top-5證據、組裝後證據與答案各≥20/22且保留各≥7/8，開發與保留上下文精確度各≥80%；版本4/4、不足4/4、權限12/12、引用門檻全過。分列必要證據組覆蓋率，失敗不刪題，依曝光規則處理。
7.2執行結果（2026-10-19，未勾選）：使用者執行檢索／標註38項／12次API（US$0.0313960）／答案核對12/12正確。Top-5、組裝後21/22（保留7/8）、答案22/22（8/8）、精確度82.14%／100%、版本4/4、不足4/4、引用53/53、覆蓋38/38通過；**權限11/12未通過**：H09 employee預期insufficient、實際answered（只引用C01公開內容，無C03外洩，使用者判正確），依凍結規則狀態不符即不計通過。使用者決定維持判定、照實記錄，不為此修改系統或改判。詳見reports/stage-7-holdout.md。

- [x] 7.3 執行 `python -m hr_rag.evaluation --split development --mode all --corpus official`，與full比較共同官方題；公司流程題在official應資料不足，不能直接比較不同可回答分母。保存三模式與6/10文件比較。
- [x] 7.4 整理 README：問題、10份資料與維護者、角色矩陣、架構、日期規則、安裝／增量更新／重建／啟動／評估／受限重播／清除／回饋處理／告警檢查命令、OpenAI 金鑰與成本上限設定方式、送往 OpenAI 的資料範圍與 OpenAI API 資料政策連結（附查證日期）、全專案 API 呼叫次數與實際費用、模型硬體、真實量測、已知限制、公司文件／開發題／保留題各由誰撰寫，以及程式參考來源；從乾淨環境依README重做一次並記錄。
7.3／7.4（2026-10-19）：官方6份 vs 完整10份，共同官方題7題三模式結果相同（rerank 7/7），公司題在official必要證據0／公司單位0；完整語料三模式即時重現4.9（reports/stage-7-official.md，0次API）。README改寫為完整專案說明（舊內容存docs/README-history.md），並依README在全新venv重建：pip check通過、494 passed／1 skip（reports/stage7-clean-env-tests.xml）。

7.5（未勾選）：reports/acceptance.md已逐項對照五份規格；因7.2授權11/12（Release veto），MVP不標記完成。

7.5後介面補充（2026-10-19，使用者要求）：提問頁每角色兩題開發集示範問題（點選只填入）、查詢日期預設當天。只改web.py、home.html、app.css與規格Scenario「Role sample questions」，檢索／生成／評估不變。原凍結移至eval/history/final.freeze.2026-10-19-v1.json，新凍結記錄supersedes與變更原因；保留題與各評估結果沿用，不重跑。

介面改版（2026-10-19，使用者確認草稿後）：側欄＋底部提問列、來源標籤、本人查詢紀錄頁；凍結v2移至eval/history，新凍結記錄supersedes。完整測試501 passed／1 skip（reports/stage7-ui-redesign-tests.xml）。

公開準備（2026-10-19）：README依使用者指定8段改寫、docs/靜態展示（階段5開發題真實回答）、MIT授權；移除本機使用者目錄並以凍結v4記錄；502 passed／1 skip。

- [ ] 7.5 完成 reports/acceptance.md，逐項對照五份spec全部Requirement與Scenario、各階段報告及三項能力演示；沒有任何未通過硬門檻才標記MVP完成，且規劃完成不得誤標為此項完成。

## Workflow follow-up

- 以上實作及驗收完成後，使用 OpenSpec 的檢查流程對照實際程式與規格；CLI格式驗證不能替代此步。
- 使用者要求歸檔時再同步正式規格並archive；本次變更維持進行中，MVP尚未全部完成。
- 後續需求改動須同步proposal、specs、design、tasks與相關測試，不以聊天口頭覆蓋檔案。


第五階段修正追蹤：D09以compound-clause-max-v1補足複合問題子句證據；D15以特定流程識別直接支持規則修正。使用者已另行核准D09/O04/21有用，存於labels.supplemental.jsonl；原標註檔不變。完整重驗前5.4/5.5不勾選，未放行第六階段。

具名表單安全補充：查詢明示詢問表單名稱／識別時，已授權上下文若沒有直接的表單代碼或具名使用敘述，伺服器回資料不足並移除模型猜測。此為必要條件，不聲稱通過即語意正確；仍須人工支持率與完整覆蓋驗收，不讀題號、角色金標或無權來源。

### 5.4修正執行紀錄（2026-10-19，未驗收）

先以離線RED→GREEN修正引用wire，對外Answer不變；再以原開發題檢核。8題二次審稿診斷仍漏必要內容，未採用，不算正式驗收。原題／標註／門檻保持不變，5.4及5.5通過前不得進6。費用包括失敗及診斷，累計硬上限US$1。詳見reports/stage-5-wire-fixes.md。

使用者後續同意：先測原文選取＋引用模式；需保留原必要答案與人工門檻，小測有效才完整重驗。此同意不等於第五階段驗收。

原文候選v2：為解析正文對其他文件／版本／條文的參照，只為本次已授權上下文另送document_id、version_id、section_id三欄來源標示；不送角色、user_id、帳號、session、路徑或未入上下文的文件資訊。三欄一併計入evidence_budget及完整payload預算。摘要模式仍維持id與正文。允許明確被所問規則準用的其他規定，但不得將不同假別的規則直接混用。

原文候選v2的參照補充由程式執行：模型選段後，只在同一已授權上下文中，補上明示參照文件及具名假別規定的現有完整段落；來源去重、有限閉包、不查上下文外文件。補入段落標記「參照補充」，引用仍經原白名單及當前權限檢核。否定參照不展開，文件代號邊界精確匹配；僅作保守字面依賴補充，不宣稱能完整解析所有法律準用關係。未降低語意／引用支持／完整性驗收。


原文候選v3補充：來源標示以source=[document_id, version_id, section_id]及緊湊JSON傳送，全部計入原2048證據／4096上下文預算，不提高限制。每次請求schema的source_ids採實際送出引用別名的enum，避免文件代號被當成引用ID；本機仍拒絕重複及未知ID。組裝與請求共用build_verbatim_payload計數。明示參照不得跨逗號或否定詞補入排除來源，新增否定範圍回歸；完整原文不等於語意完整，仍須原5.4／5.5人工門檻。
