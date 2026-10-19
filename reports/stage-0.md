# 階段 0 驗收報告

目前狀態（2026-10-18更新）：**0.1–0.9已完成，階段0通過**。使用者收到0.8模型比較與每題成本後指示繼續0.9，依該指示凍結已達標的mini；Luna僅為必要時已授權的候選，未啟用。下方保留各次原始歷史紀錄，現行0.9驗收見文末。本次未進入階段1。

日期：2026-10-18（Asia/Taipei）。範圍：OpenSpec build-hr-leave-rag-mvp 的0.1–0.6。結論：通過本階段驗收；依使用者要求停止，未進入階段1。

## 逐項證據

| 任務 | 結果 | 證據 |
|---|---|---|
| 0.1 環境與依賴 | 通過 | Python3.12.10；.venv與全新.venv-verify均成功安裝54個hash鎖定套件；兩者pip check皆No broken requirements found；README含重建命令 |
| 0.2 共用型別 | 通過 | Principal、QueryRequest、DocumentVersion、Chunk、Evidence、ContextBundle、Claim、Answer；未知角色、空問題、無效日期及反向區間測試；修復文件日期接受時間戳問題 |
| 0.3 providers | 通過 | embed/rerank/generate真實介面；維度、NaN、錯誤JSON、HTTP timeout、token超限、生成截斷與子程序終止測試通過；保留實際模型交換掛點 |
| 0.4 真實模型可行性 | 通過 | 第二輪embedding10/10、reranker10/10、generator10/10；runtime-smoke.json all_passed=true，命令exit0；第一輪9/10生成失敗完整保留 |
| 0.5 最小稽核 | 通過 | record_event回傳UUID；一般日誌僅白名單固定代碼及耗時，密碼／key／任意正文不寫入；成本未知為null；寫入失敗不吞錯 |
| 0.6 上下文預算 | 通過 | 模型上限及本機4096上限記錄；2048證據／512輸出／128餘量；負值、無剩餘空間、超限先阻止生成；runtime.md記token計算法、暫定P95門檻及限制 |

## 驗證命令與結果

在專案根目錄執行：

```powershell
uv pip sync requirements.lock --require-hashes --python .venv/Scripts/python.exe
.venv/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e .
.venv/Scripts/python.exe -m pip check
py -3.12 -m venv .venv-verify
uv pip sync requirements.lock --require-hashes --python .venv-verify/Scripts/python.exe
.venv-verify/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src tests scripts --no-cache
.venv/Scripts/python.exe -m ruff format --check src tests scripts --no-cache
.venv/Scripts/python.exe scripts/smoke_models.py
openspec validate build-hr-leave-rag-mvp --strict
```

已觀察結果：pip check兩環境成功；pytest 55 passed；Ruff All checks passed／12 files already formatted；第二輪真實模型30次介面驗證全過（10筆樣本×3模型），不能稱為30題獨立RAG評估。OpenSpec格式檢核於最後交付時再次執行，不能替代上述程式驗收。

固定依賴SHA256：90578e25f5941f8f406a1e5c1321634cb3a6285ea7b0f394400f6346c8fa1023。模型清單SHA256：3a2872a3bb6830211a68fc155de2efc4dc459698b1ac336306e275a968395ed1。其餘實際模型檔與exe hash在runtime-smoke.json；最終程式與測試hash清單在stage-0-artifacts.json。

## 審查、修正與限制

- 使用獨立審查者檢查本階段程式與計畫，未把後續功能誤列為本階段缺漏。
- 重要問題1：日期欄位會把數字解成1970時間戳；先觀察15項回歸失敗，再共用嚴格CalendarDate驗證，完整套件55/55通過。
- 重要問題2：生成第4筆有證據卻拒答；保存失敗輪次，修正基礎提示後同10題全過，沒有放寬判定或丟棄失敗題。
- 次要待辦：ContextBundle.token_count的描述值目前仍接受bool轉int；生成前會用真實tokenizer重算，不影響預算防線。嚴格整數檢核留待階段4組裝。
- 未建立Git，故沒有commit或工作樹；只在使用者選定的獨立專案目錄實作，保留progress-stage-0.md紀錄。未複製參考專案。
- 本機硬體有限，三模型依序載入，沒有同時常駐或完整鏈路的效能保證。第一輪背景卡住的舊沙箱pytest已核對PID後停止；最終生成服務及encoder亦已結束。
- 乾淨安裝與模型實測由主執行者完成，獨立審查者未另外重做大型下載與安裝。

## 停止邊界

未建立data或eval資料、未收集官方文件、未寫公司制度、未實作檢索／權限／網頁。10份主文件、11個初始版本、30題正式評估仍是後續規格，沒有擴張範圍。

階段1–7任務維持未勾選。不執行OpenSpec sync或archive，不啟動下一階段。

## 0.7 OpenAI 生成 provider 離線驗收（2026-10-18）

範圍：依 tasks.md「Codex交接」、design Decision 1 與使用者指示實作0.7。未取得、建立、索取或保存真實API金鑰；沒有生成API請求，沒有實際API費用。未讀取保留題。未更動本機首次真實長度實測檔或本機模型鎖定檔。

| 項目 | 實作及實際證據 |
|---|---|
| SDK與依賴 | openai 3.33.0、tiktoken 0.14.0；61個依賴固定版本與hash。Torch維持官方Windows CPU wheel唯一SHA256 `2be20b2c05a0cce10430cc25f32b689259640d273232b2de357c35729132256d` |
| 全新安裝 | 新建 `.venv-openai-verify`，`uv pip sync ... --require-hashes` 成功安裝61個套件；實際重新下載590.7MiB Torch wheel並通過雜湊檢查；兩個venv的pip check均成功 |
| 生成契約 | 新增OpenAISettings、OpenAIGenerator.generate -> Answer及既有CheckedProviders相容入口；Responses API嚴格schema、store=false、伺服器再次Pydantic驗證；LlamaGenerator保留 |
| 資料範圍 | 真SDK＋MockTransport攔截：僅問題、系統提示及最終證據id/text；無帳號、角色、ACL、丟棄候選或引用定位等額外資料。尚未實作階段3的ACL判斷，呼叫者須傳入已授權ContextBundle |
| 設定與錯誤 | 僅官方端點、缺金鑰／成本設定／模型價格為not_configured；429、5xx最多重試2次，1／2秒退避；SDK重試與redirect關閉；逾時不重送；無效JSON、schema、截斷與缺失usage受控失敗 |
| Token | 完整序列化請求含schema計數；不信任ContextBundle.token_count；記錄API輸入差異並在低估超過5%時提高當前生成器餘量。另以預熱o200k_base詞表、封鎖socket驗證完整輸入482 tokens／證據26 tokens，見openai-tokenizer-smoke.json；非0.8實測 |
| 成本 | Decimal計價；output含reasoning、不重複加總；SQLite原子預留／結算跨實例與重啟生效；剩餘額不足不送出；未知費用null且保守保留預算；錯誤輸出仍計費；並行預留與重試中途額度耗盡案例通過 |
| 稽核 | response id、實際模型、usage含推理、成本與token差異；完整交換僅傳給受信任hook並遮蔽金鑰。一般事件白名單不保存正文。SDK／HTTP日誌在呼叫範圍內遮蔽（含lazy logger）；稽核失敗不展示成功答案 |
| 測試先行 | 先寫32項測試，確認缺少OpenAIGenerator/OpenAISettings而32 failed（stage-0-7-red.log）；最終新增43項、既有55項，合計98項。單元測試使用合成金鑰與禁止socket的fixture |
| 獨立審查 | 一項Important：lazy import的傳輸logger未套遮蔽；一項原列Minor：token差異沒有hook時未落盤，按design明確紀錄要求列為必修。兩者皆先重現失敗，再修正並通過全套測試；無保留的審查缺陷 |

驗證命令（專案根目錄）：

```powershell
$env:UV_CACHE_DIR = "$PWD/.cache/uv"
uv pip compile pyproject.toml --extra dev --python .venv/Scripts/python.exe --python-platform windows --output-file requirements.lock --generate-hashes --quiet
uv pip sync requirements.lock --require-hashes --python .venv/Scripts/python.exe
.venv/Scripts/python.exe -m venv .venv-openai-verify
uv pip sync requirements.lock --require-hashes --python .venv-openai-verify/Scripts/python.exe
.venv/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e .
.venv-openai-verify/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e .
.venv/Scripts/python.exe -m pip check
.venv-openai-verify/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -m pytest -q
.venv-openai-verify/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src tests scripts --no-cache
.venv/Scripts/python.exe -m ruff format --check src tests scripts --no-cache
openspec validate build-hr-leave-rag-mvp --strict
```

環境限制：最初沙箱中的pytest無法存取既有Temp及.runtime目錄，屬環境錯誤，未算作RED證據；經核准在沙箱外執行仍帶有socket禁網防護的測試，才取得32項預期功能失敗與後續通過證據。未因環境問題降低驗收。

新requirements.lock SHA256：`c9ca039b55b86128bc01be53b1a8505c8a8e522aec4ecb9cb663c4e65c12d437`。本機config/models.lock.json仍為 `3a2872a3bb6830211a68fc155de2efc4dc459698b1ac336306e275a968395ed1`。首次實測feasibility-long-context.json SHA256：`a2ad09983692980dd99d8807cb7f696753894b93689679d72e5637e022376e5e`。本次變動檔案另存stage-0-7-artifacts.json，保留原stage-0-artifacts.json。

停止條件：使用者已授權完成所有不需API的後續工作，但下一項0.8需要真實API與成本上限，0.9需要實測結果與使用者確認；階段1明確依賴整個階段0。故0.7完成後停止，沒有跳過前置驗收，也沒有啟動0.8或階段1–7。正式模型／價格／效能與繁體回答品質尚未驗收。專案未建立Git，無commit或push。

## .env 自動載入補充（2026-10-18）

使用者已自行將金鑰填入專案根目錄 `.env`，並要求接上自動載入。新增 `load_generation_environment`，由OpenAIGenerator在設定檢核前呼叫；固定使用與pyproject.toml同層的檔案，環境變數優先（含空值），只讀金鑰及成本上限，不修改檔案或全域環境、不快取憑證、不執行shell／變數展開。檔案格式錯誤轉為固定not_configured，不帶原始內容。未新增套件，既有鎖檔不變。

新增tests/test_environment.py共11項隔離測試，先觀察7 failed／4 passed，再實作通過；涵蓋工作目錄獨立、環境優先、缺檔、BOM、引號、註解、格式錯誤、禁止展開與修改後重新讀取。測試只讀暫存假設定，未讀取使用者的真實金鑰。另以不輸出值的本機檢查確認：檔案存在、有效來源具有非空金鑰、成本上限格式有效；這不代表金鑰已經過API驗證。

驗收：完整pytest **109 passed**（13.76秒）；Ruff check通過、15 files already formatted；OpenSpec strict通過。獨立唯讀審查未發現重要問題。README、proposal、design、spec及tasks同步載入規則；前述98項與artifact hash屬原0.7歷史驗收快照。本次沒有顯示、記錄或改寫使用者金鑰，也沒有呼叫真實API或執行0.8。

## 0.8 真實API可行性實測（2026-10-18）

使用者明確授權使用.env的設定、累計不超過1美元。新增 `hr_rag.feasibility_openai`，既有腳本增加 `--provider openai --model <ID>`，可重複指定兩個已查價候選；固定20個證據單位、5段上下文與F1–F5未變，不執行保留題。原本本機入口仍可重現。

先新增測試觀察因模組尚未實作而ImportError，再完成12項離線保護測試。完整命令整合測試找到RSS字典的整數鍵不相容遞迴遮蔽，修正後通過。獨立審查指出未知重試費用可能被摘要漏算，新增每題帳本差額、已知／預留分開列示，未知時平均費用null，補timeout及保留預留後成功測試。最後新增測試16項、完整pytest **125 passed（17.09秒）**，Ruff check／format通過；覆核無Important／Critical問題。所有測試均用假設定／假API，不讀使用者.env。

真實執行命令：

```powershell
$env:TIKTOKEN_CACHE_DIR = "$PWD/.cache/tiktoken"
.venv/Scripts/python.exe -I scripts/feasibility_long_context.py run --strategy resident --provider openai --model gpt-4.1-mini-2025-04-14 --model gpt-4.1-2025-04-14
```

exit 0，run `f0ce5d60-bf60-416d-a39b-c599ed4aec69`。兩模型均自動5/5、Codex實作者及獨立agent逐題核對5/5、全部繁體、全部單題小於60秒，0.8通過。內容覆核非使用者人工簽核；使用者確認仍留在0.9。逐題回答、引用與理由、usage、費用、檢索／API耗時、記憶體及官方查價來源詳見 `reports/feasibility-long-context-openai.json` 與 `reports/runtime.md`。

mini平均US$0.0010884／題，4.1平均US$0.0055524／題；本輪建議較低價mini。10次請求合計估算US$0.0332040，帳本結算同額、預留0，不超過1美元，沒有重試或擅自增加模型。兩候選已公告2027-01-14停用，後續正式選型須考慮此期限。冷啟動遇系統記憶體壓力，embedding172.5秒、reranker65.0秒；常駐後單題最長36.3031秒，冷載入另列而非隱藏。

安全檢查只輸出布林結果：26個既有reports檔案未包含真實金鑰；未顯示／記錄／改寫.env，沒有讀取保留題。原本本機報告、config/models.lock.json、requirements.lock的SHA256均與前次相同。前述「未呼叫API」為歷史紀錄，本次才首次執行API。停止於0.8；0.9、階段1以後未執行，整個階段0仍待0.9使用者確認，無Git commit或push。

## 0.9 凍結與階段0放行（2026-10-18）

使用者在收到0.8建議mini及US$0.0010884／題後指示「大權重的模型如果需要可以用luna，做完之後繼續0.9」。依此續行授權凍結成本較低且達標的mini；本輪無需增加候選或重跑API。這是對選型及繼續工作的授權，沒有把Codex的逐題內容核對改稱使用者親自評分。

config/models.lock.json新增 `default_generation_provider=openai` 與 `openai_generator`，記錄模型快照、官方價格查證日、預算、逾時、重試、P95告警、encoder常駐策略、成本建議及停用日期；原本generator／runtime仍供第一次本機實測重現。OpenAISettings的預設值與鎖檔一致，預設帳本固定於專案根目錄，避免不同工作目錄分開累計。新增檢核禁止P95告警大於等於逾時，以及更換模型卻沿用mini價格。

凍結明細與理由見runtime.md的0.9節。推薦成本上限US$1.00不取代使用者.env，實際仍讀既有上限、不清帳。Luna必要時可作候選，實際採用仍須查證精確快照、價格與參數並通過相同可行性門檻，原累計1美元限制不變；沒有自動fallback。

驗收：tests/test_frozen_settings.py先5 failed／1 passed，再與0.6的tests/test_contracts.py合跑 **44 passed**；完整pytest **131 passed（14.26秒）**，Ruff check通過、16 files already formatted。獨立唯讀審查未發現Important／Critical缺陷。新增6項測試不讀.env、不呼叫API，既有離線測試仍用假憑證及傳輸。沒有新增API費用；累計仍為US$0.0332040、10次請求、預留0。

0.8的兩份原始實測JSON及requirements.lock均保留；只有正式models.lock按0.9要求更新。README與規劃同步現況，0.9勾選後階段0完成；本次停止於0.9，階段1以後未執行，專案無Git故無commit或push。
