# 企業請假與特休 RAG

目前狀態：**階段0～6通過（50/55），下一步階段7**；本機網頁 `python -m hr_rag.web`（127.0.0.1:8000），稽核重播／清除、回饋與告警指令見[階段6報告](reports/stage-6.md)；正式生成為人工驗收後採用的原文選段模式（gpt-4.1-2025-04-14），見[階段5驗收](reports/stage-5-acceptance.md)。以下為較早紀錄：原文候選GPT-4.1完整實測後，Codex初查可回答13/14、資料不足3/3、版本3/3、穩定18/18；D11仍漏必要性疑義轉人資，保留失敗。原題／標註／門檻不變，未進第六階段。累計API估算US$0.8992952／1美元，預留0。最新見[原文候選實測與人工核對](reports/stage-5-verbatim-v3.md)。

0.8兩個OpenAI候選各5題通過自動檢核與Codex內容核對，0.9正式預設為 `gpt-4.1-mini-2025-04-14`，平均估算US$0.0010884／題。本機首次失敗紀錄保留，embedding與reranker留在本機；證據見[階段0報告](reports/stage-0.md)與[runtime.md](reports/runtime.md)。階段1沒有API呼叫或新增費用。

驗收證據：[階段0報告](reports/stage-0.md)、[硬體／模型／耗時](reports/runtime.md)、[逐筆模型結果](reports/runtime-smoke.json)。

專案位置：`D:/@spin/5.DL/RAG/企業RAG知識點/hr-leave-rag`。

階段1離線嚴格檢核：

```powershell
.venv/Scripts/python.exe -m hr_rag.evaluation_schema --split development --path eval/development.jsonl --manifest data/manifest.json
.venv/Scripts/python.exe -c "from pathlib import Path; from datetime import date; from hr_rag.corpus.manifest import validate_manifest, due_reviews; p=Path('data/manifest.json'); print(validate_manifest(p)); print(due_reviews(p, as_of=date.today()))"
```

`--allow-pending-review`只允許驗證草稿結構，不能據此發布索引或驗收。嚴格清單驗證目前0錯誤，11版本均已人工核對。`scripts/collect_sources.py`明確執行才連網下載官方公開頁，不使用API金鑰；`scripts/prepare_stage1.py`只讀已保存的快照重建同一份待核對草稿，遇既有不同內容拒絕覆寫。正式匯入入口見下方階段2命令；20片段人工驗收已完成。

## 規劃入口

- [開發設計與各階段驗收](openspec/changes/build-hr-leave-rag-mvp/design.md)
- [依序執行的任務清單](openspec/changes/build-hr-leave-rag-mvp/tasks.md)
- [需求與範圍](openspec/changes/build-hr-leave-rag-mvp/proposal.md)
- [文件、日期與版本規格](openspec/changes/build-hr-leave-rag-mvp/specs/knowledge-corpus/spec.md)
- [角色與權限規格](openspec/changes/build-hr-leave-rag-mvp/specs/access-control/spec.md)
- [檢索與比較規格](openspec/changes/build-hr-leave-rag-mvp/specs/evidence-retrieval/spec.md)
- [回答與引用規格](openspec/changes/build-hr-leave-rag-mvp/specs/grounded-answering/spec.md)
- [評估與追蹤規格](openspec/changes/build-hr-leave-rag-mvp/specs/evaluation-observability/spec.md)

## 固定邊界

10 份主文件：6 官方＋4 虛構公司文件，另保存公司辦法1份舊版。共10個文件ID、11個初始版本。

三項能力：官方依據與引用、公司流程與來源區分、檢索前角色權限過濾。

兩項資料設計重點：發布／修正／生效／失效／擷取日期分開；評估包含改寫與跨文件題，不只照抄FAQ。

實作順序：0環境與模型可行性 → 1語料與評估基準 → 2匯入切片與版本 → 3身分權限 → 4檢索比較 → 5證據回答 → 6網頁與日誌 → 7最終驗收。

依教學簡報補齊的規劃：中文同義詞、上下文去重／排序／長度預算、上下文精確度與同題三次穩定性、受限完整查詢追溯、文件維護責任與增量索引、回饋閉環及本機告警。混合檢索與重排序保留三模式比較；階段0只建立相關基礎契約與預算檢核，不代表這些完整功能已實作。

2026-10-18 規劃審查補正：子片段不超過400、查詢不超過96個encoder tokens；上下文加入相關度篩選；評估題改為逐角色預期；10題保留題由不參與調參的Claude草擬、使用者審核定稿，存於專案外，Codex不得讀取；民國日期轉換與勞動部問答日期規則；生成改用 OpenAI API（金鑰由使用者提供、累計成本上限、用量紀錄、只送已授權上下文）。調降門檻與階段6範圍仍待使用者決定。

每階段通過後才往下做。一次只實作當前階段，不把整份tasks視為一次要全做完；改需求先更新對應規格。

## OpenSpec 使用與目前驗證

已使用安裝在專案的 `.agents/skills/openspec-propose/SKILL.md`，CLI版本為1.14.1。遵循 [OpenSpec 官方流程](https://openspec.dev/docs/skills) 產出proposal、specs、design、tasks。

在本專案根目錄可執行：

```powershell
openspec status --change build-hr-leave-rag-mvp
openspec validate build-hr-leave-rag-mvp --strict
```

2026-10-18 規劃曾通過嚴格格式驗證，4/4規劃類型存在。格式驗證不代表程式、語料或品質驗收完成；實作勾選狀態以tasks及對應階段報告為準。

後續從階段0開始時，可要求使用 `openspec-apply-change`，指定 `build-hr-leave-rag-mvp` 並限定本次執行階段。正式規格同步與歸檔留到實作及驗收完成之後。

現有 `../rag-chatbot-main` 僅為參考，未作為本專案基礎搬入。

## 階段 0 安裝與驗證

目前鎖定 **Windows x64、Python 3.12**，套件解析工具為 uv 0.12.13。CPU版PyTorch使用官方Windows wheel及SHA256；這份鎖檔不承諾適用Linux/macOS。所有命令在本專案根目錄執行，不必啟用Activate.ps1：

```powershell
py -3.12 -m venv .venv
$env:UV_CACHE_DIR = "$PWD/.cache/uv"
uv pip sync requirements.lock --require-hashes --python .venv/Scripts/python.exe
.venv/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e .
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src tests scripts --no-cache
```

另以全新 `.venv-verify` 重做鎖檔安裝與pip check，確認不依賴全域Python套件。未來重新解析鎖檔時，必須保留Torch單一Windows檔案的官方校驗碼；本次uv曾對直接URL附加其他平台hash，已核對下載檔與官方索引後修正，不可省略雜湊檢查。

下載模型與固定版推論程式：

```powershell
.venv/Scripts/python.exe scripts/download_models.py
$lock = Get-Content -Raw config/models.lock.json | ConvertFrom-Json
New-Item -ItemType Directory -Force .runtime | Out-Null
Invoke-WebRequest $lock.runtime.url -OutFile .runtime/llama.zip
if ((Get-FileHash .runtime/llama.zip -Algorithm SHA256).Hash.ToLower() -ne $lock.runtime.sha256) { throw 'Runtime hash mismatch' }
Expand-Archive .runtime/llama.zip -DestinationPath .runtime/llama -Force
.venv/Scripts/python.exe scripts/smoke_models.py
```

以上是階段 0 的本機模型驗證，用來重現 0.4 煙霧測試與第一次真實長度實測；本機生成（Qwen2.5-1.5B、llama.cpp）已不是正式生成器，改用 OpenAI 後不必再下載。embedding 與 reranker 仍需下載。

OpenAI 生成 provider 已提供 `OpenAIGenerator(OpenAISettings(...)).generate(question, context) -> Answer`，也相容 `CheckedProviders(generation=generator)`。實際呼叫前需要使用者自行完成：建立 OpenAI API 金鑰、在 OpenAI 後台設定用量上限、設定累計成本上限 `HR_RAG_COST_LIMIT_USD`。可將 `OPENAI_API_KEY` 與 `HR_RAG_COST_LIMIT_USD` 填在專案根目錄 `.env`（與本README、pyproject.toml同層），生成器會在每次呼叫時自動讀取，與啟動時的工作目錄無關。既有程序環境變數優先，即使值為空也不被檔案覆蓋。程式不修改檔案或全域環境，不快取、顯示或記錄憑證；`.env` 已列入Git忽略清單，`.env.example` 僅列空白欄位。支援單行 `名稱=值`、單／雙引號、註解及UTF-8 BOM，不執行shell、變數插值或多行值；格式錯誤只回傳固定錯誤碼。只載入上述兩個設定，不從檔案開啟 `HR_RAG_LIVE_API` 或更改API端點。0.9已依實測凍結 `OpenAISettings()` 預設為 `gpt-4.1-mini-2025-04-14`，每百萬輸入／輸出tokens價格為US$0.40／1.60，查證日期2026-10-18。更換模型須明確提供已查證的價格及日期，不能沿用mini價格。缺少必要設定回傳 `not_configured`。

送到 OpenAI 的只有系統提示、問題與已授權最終上下文的 id／正文，以及必要生成參數和 Answer schema；不附加帳號、ACL、角色或 session。呼叫者須先完成授權與有效期過濾；provider 本身不接受 Principal，也不能代替階段3的權限檢查。請勿輸入個人資料。使用 Responses API 的嚴格 JSON schema 與 `store=false`；這個參數不是對所有服務端資料保留的保證。資料處理規則以 [OpenAI API 官方資料控制說明](https://developers.openai.com/api/docs/guides/your-data) 為準（查證日期：2026-10-18）。[Structured Outputs 官方說明](https://developers.openai.com/api/docs/guides/structured-outputs) 同日查證。

費用以 API 回傳 usage 及設定價格估算；輸出 tokens 已包含推理 tokens，不重複計費。輸入快取折扣未套用，估算採完整輸入單價。`.runtime/openai-cost.sqlite3` 保存跨實例與重啟的累計帳本（固定以專案根目錄定位，與工作目錄無關）；呼叫前原子預留完整專案輸入上限與輸出上限的費用，剩餘額不足則拒絕呼叫。429／一般4xx釋放預留；逾時、連線故障、5xx或無可靠 usage 保留預留額，未知實際成本記為 null，可能提早耗盡本機額度。不要刪除帳本來重設預算；本機估算不能代替後台用量限制。

初始執行參數為單次60秒、429／5xx最多重試2次、退避1／2秒；SDK內建重試與redirect關閉。逾時不自動重送。0.9已凍結4096／2048／512／128的專案上下文／證據／輸出／安全餘量，45秒P95告警門檻低於60秒逾時；0.8 mini五題的最大總耗時36.3031秒，45秒為暫定告警值，並非正式P95成績。encoder維持常駐，2個CPU threads；本機冷啟動仍有明顯記憶體壓力。推理模型須明確設定 `supports_temperature=False` 與最低支援的 `reasoning_effort`；不自動猜測模型能力。完整請求（含schema）用所選模型的 tiktoken 編碼估算；若實際輸入多出5%以上，增加當前生成器的安全餘量，並在交換掛點記錄差值，本次0.9依實測保留128；未來若持續增加須重新驗證設定。

tiktoken 初次使用模型詞表可能下載公開編碼檔（不需要API key，套件內含檔案SHA256檢核），可提前以 `tiktoken.encoding_for_model(model_id)` 預熱並用 `TIKTOKEN_CACHE_DIR` 指定快取；缺少或不認得編碼時受控拒絕生成。離線單元測試用真正SDK搭配MockTransport、真正tiktoken引擎搭配合成byte詞表，並封鎖socket，不依賴詞表下載或真實金鑰。0.8兩候選各5題已通過；mini平均估算US$0.0010884／題。詳見reports/runtime.md，這不是正式30題驗收結果。

一般事件日誌只記固定錯誤碼、耗時、response id、模型、用量與成本。`on_exchange` 僅供受信任的本機稽核呼叫者接收已遮蔽憑證的模型輸入／原始輸出，不可接到一般日誌或使用者端；完整受限保存由階段6完成。provider呼叫期間抑制SDK與HTTP傳輸層診斷日誌，避免服務端header或錯誤內容繞過白名單。稽核失敗不展示成功答案。

階段 0 的三個本機模型分別為[中文BGE embedding](https://huggingface.co/BAAI/bge-small-zh-v1.5)、[BGE reranker](https://huggingface.co/BAAI/bge-reranker-base)、[Qwen2.5-1.5B Q4_K_M](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF)，revision與[llama.cpp](https://github.com/ggml-org/llama.cpp/releases/tag/b11669)版本見config/models.lock.json。

煙霧測試依序啟動encoder子程序及127.0.0.1:8765生成服務，結束後釋放；該port已有服務時直接失敗，不接管其他程序。測試10筆虛構問題，結果寫入reports/runtime-smoke.json與runtime-exchanges.json；它們不屬於正式知識庫，也不能代替後續30題RAG品質驗收。

預設測試不呼叫真實API；本次未新增會自動呼叫API的測試。後續真實API測試僅能在 `HR_RAG_LIVE_API=1` 時執行，或由使用者明確啟動實測命令，並須計入成本。完整稽核、權限、檢索、網頁與資料治理仍屬後續階段。

0.8實測命令（會產生API費用；先設定.env，每次只開一個命令）：

```powershell
$env:TIKTOKEN_CACHE_DIR = "$PWD/.cache/tiktoken"
.venv/Scripts/python.exe -I scripts/feasibility_long_context.py run --strategy resident --provider openai --model gpt-4.1-mini-2025-04-14 --model gpt-4.1-2025-04-14
```

`--model`可重複指定已查價候選；每個模型都跑完整F1–F5。命令以.env與1美元的較低者限制跨次累計，不會清空帳本；模型與價格固定於0.8比較入口，0.9正式預設為mini；`config/models.lock.json` 的 `default_generation_provider`／`openai_generator` 記錄正式設定，原 `generator`／`runtime` 保留給舊本機實測重現。結果逐題保存到 `reports/feasibility-long-context-openai.json` 的獨立run，保留前次run及原本本機報告。請注意兩個比較候選已公告2027-01-14停用，價格來源、限制與比較結果見 `reports/runtime.md`。

0.9成本建議維持 `HR_RAG_COST_LIMIT_USD=1.00`，仍須使用者在.env或環境設定，不因載入預設模型而自動呼叫API。本機累計帳本目前US$0.0332040，不清零；僅建立 `OpenAISettings()` 不讀取金鑰。使用者授權必要時可用Luna作較大模型候選，但目前未測試或啟用Luna，不會自動切換；實際採用前須查證快照、價格與參數並通過相同測試及原成本上限。


## 階段2本機資料匯入

```powershell
.venv/Scripts/python.exe -m hr_rag.corpus.ingest --manifest data/manifest.json
.venv/Scripts/python.exe scripts/verify_stage2.py
```

第一個命令只讀清單白名單與已下載的本機embedding模型，輸出generation ID；第二個明確執行真實本機驗證並建立人工片段核對頁，不呼叫生成API。資料存於.runtime/corpus/corpus.sqlite3與snapshots/*.npy；不要直接編輯active指標或向量檔。相同內容不重算embedding，只改ACL／日期發布新metadata而重用向量；壞來源、未知日期或超長單句拒絕發布並保留舊active。安全錯誤碼可由CorpusStore.failures()檢視，沒有來源正文。

受信任的本機管理程式可呼叫hr_rag.corpus.ingest.withdraw(document_id, version_id)撤回版本；撤回標記持續生效，重新匯入不會自動恢復。登入與引用授權已完成；檢索模組由第四階段提供，整合查詢網頁留待第六階段。


## 階段3：登入與引用

```powershell
.venv/Scripts/python.exe -m hr_rag.auth init
.venv/Scripts/python.exe -m hr_rag.web
```

在本機終端依序設定employee、manager、hr密碼（12～256字元，輸入隱藏，只存scrypt雜湊），再開啟http://127.0.0.1:8000/login。帳號初始停用，沒有公開預設密碼；不需API金鑰。重設單一帳號：`.venv/Scripts/python.exe -m hr_rag.auth set-password --user employee`，會使舊session失效。

本階段只有登入／登出、`GET /session`與`GET /citations/{id}?as_of=YYYY-MM-DD`，查詢頁留待階段6。登出使用POST /logout，X-CSRF-Token取自已登入的/session回應。引用每次重新檢查目前角色、ACL、生效日期與撤回狀態；未授權與不存在一律404。只監聽127.0.0.1、無公開註冊／角色切換，詳細測試與限制見[階段3報告](reports/stage-3.md)。

## 保留題保存與第四階段本機比較

正式保留題及兩份備份存於 `%LOCALAPPDATA%/hr-leave-rag-private/holdout`，僅目前Windows使用者及SYSTEM有權存取。Windows使用者層級的 `HR_RAG_HOLDOUT_PATH` 已設定；新開終端會繼承，既有終端可只重新載入該變數：

```powershell
$env:HR_RAG_HOLDOUT_PATH = [Environment]::GetEnvironmentVariable('HR_RAG_HOLDOUT_PATH', 'User')
```

`.env` 仍只供生成器載入金鑰與成本設定。`eval/baseline.freeze.json` 綁定保留題SHA256、manifest、開發題與來源版本；第四階段只串流計算外部保留題的hash，不解析正文。來源、題庫或hash改變時拒絕比較，必須重新驗證與凍結。C01–C04原始快照保留歷史「待人工核對」標示，現行核對狀態以manifest的verified及使用者審核紀錄為準；修改公司文件後，H07–H09語意核對交由使用者或獨立作者。

```powershell
.venv/Scripts/python.exe -m hr_rag.evaluation --split development --mode all --corpus full --context-max-units 5 --min-relevance 0.58 --output reports/retrieval-candidate.json
.venv/Scripts/python.exe -m hr_rag.evaluation --split development --mode all --corpus full --no-normalize --context-max-units 5 --min-relevance 0.58 --output reports/retrieval-no-normalize.json
```

以上只呼叫本機embedding及reranker，沒有生成API費用。每次固定26角色執行、14可回答題，逐題保存篩選前Top-5與組裝後證據組覆蓋；錯誤不刪分母。來源撤回、索引或ACL改變會使整批比較失效。`--corpus official`目前只限制檢索來源；第七階段共同官方題的分母比較尚未實作，不可拿其全開發集彙總直接與full比較。

候選參數尚待人工精確度驗收，不是已通過的最終設定。產生的 `*-review.html` 列出開發題、角色、日期、來源定位與最終上下文；按整個單位判斷「有用／無用」，部分有用但主要無關應記無用。標註寫入 `eval/labels.jsonl`，以題號／角色／內容hash重用，保留核對者與理由；未標註的精確度為null。三模式及選定模式的上下文精確度門檻驗收見[任務4.9](openspec/changes/build-hr-leave-rag-mvp/tasks.md)。

核對操作：用瀏覽器開啟 `reports/retrieval-candidate-review.html`，展開項目選有用／無用，補充理由選填，最後點上方「匯出 JSON」。可中途匯出備份；未勾項保留待核對，全數完成時complete才為true。進度會暫存在同一瀏覽器，但仍應定期匯出；檔名為 `hr-rag-context-labels-日期.json`，包含核對清單hash供匯入時核對。匯出本身不會自動改寫正式標註或完成階段驗收。
