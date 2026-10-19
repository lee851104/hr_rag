> 2026-10-18依使用者新指示：保留題格式及hash凍結改為階段4前門檻；允許先完成獨立階段2。以下「不進階段2」為當時歷史狀態，最新進度見stage-2.md。

# 最新驗收狀態（2026-10-18）

使用者已逐題確認D01–D20，並確認「11個文件可以，10題保留我也看過沒問題了，你可以繼續做」。已保存於stage-1-human-reviews.json；11版本標記verified，last_reviewed_at=2026-10-18，next_review_due=2026-11-17。保留題內容核對確認與格式通過分開記錄，不代改外部檔案。

- 清單嚴格檢核：0錯誤；當日到期清單空。
- 開發題嚴格檢核：20/20已核對，分配6/5/3/3/3，14獨立可回答題、26角色案例。
- 開發檔SHA256：06b18e9c8023d515ddad485222fa0634e661c95b26fd9881f235738a07ad21a4；固定6穩定案例及hash一致。
- 命令：`.venv/Scripts/python.exe -m pytest tests/test_manifest.py tests/test_evaluation_schema.py tests/test_source_text.py tests/test_stage1_data.py -q -p no:cacheprovider`。
- 結果：74 passed, 1 skipped in 4.39s；skip是Windows symlink權限不足。
- 外部保留題可讀、10行，嚴格檢核仍為evaluation_unreadable_or_invalid_schema；錯誤彙總與下方前次紀錄一致。未把題目、答案、證據組或逐題結果讀入對話；未修改外部檔案。
- OpenSpec完成1.1、1.2、1.3、1.6，總13/55；1.4、1.5尚待有效保留題摘要。階段1未整體放行，因此尚未進入階段2。
- 本輪沒有API呼叫、沒有新增題目或來源文件。stage-1-artifacts.json及stage-1-review-content.html保留為人工核對前的歷史快照，不代表目前簽核狀態。

## 給原保留題作者Claude的修正指示

請修正原專案外holdout/holdout.jsonl，沿用既有10題，不新增題目。使用者已於2026-10-18確認內容核對通過。依hr-leave-rag/eval/evaluation.schema.json修正：類別只能direct、paraphrase_cross、version、permission、insufficient（4/3/1/1/1）；role_expectations每個角色值必須是Expectation物件，包含expected_behavior、answer_key、required_evidence_groups、forbidden_sources；刪除schema不允許的額外欄位。依使用者實際確認填review_status=verified、reviewer、reviewed_at，保留原作者。確認公司題答案與證據引用已具體完整，不能用佔位字串。

修正後使用同一檢核器，指定--split holdout、--manifest data/manifest.json及外部原檔--path，以--summary-output eval/holdout.manifest.json只輸出合格摘要。不要把題目或答案貼回Codex。若修正改變已核對的語意，僅該部分需再由使用者確認。

## 以下為前次檢查歷史紀錄

# 階段1續作檢查（2026-10-18）

使用者已提供專案外 holdout 資料夾，內有 `holdout.jsonl`。最新 proposal／design／specs／tasks 已允許不參與調參的 Claude 草擬、使用者審核定稿；Codex 不得草擬、修改或讀取題目內容。這取代前次報告「保留題尚未撰寫／只能使用者本人撰寫」的狀態與說明，人工審核及格式門檻不變。

本次只執行現有檢核器與固定欄位錯誤彙總，沒有將題目、答案、證據組或逐題結果輸出到對話或專案檔案，未修改外部檔案。未使用.env或API。

## 檢核結果

外部檔案存在，10行；嚴格檢核失敗：`evaluation_unreadable_or_invalid_schema`。安全彙總如下（是錯誤數，不是逐題內容）：

| 項目 | 數量 |
| --- | ---: |
| direct／version／permission／insufficient | 4／1／1／1 |
| 類別值不符合允許值 | 3 |
| role_expectations內預期物件型態不符 | 16 |
| 缺review_status | 10 |
| 額外且不被schema允許的欄位 | 20 |
| role_expectations內其他規則驗證錯誤 | 2 |

現有11個文件版本仍為pending，嚴格清單回報11個待人工核對。尚未收到使用者確認的核對範圍與日期；不代填reviewer、reviewed_at或標為verified。OpenSpec strict通過，實作進度仍為9/55，沒有進入階段2。

## 提供給獨立保留題作者的格式修正依據

`eval/evaluation.schema.json` 是從現有 Question 模型匯出的機器格式，沒有任何題目。請獨立作者在專案外依此修正原檔，實作agent不代改內容：

- 類別限定direct、paraphrase_cross、version、permission、insufficient；保留題分配4/3/1/1/1。
- role_expectations是角色到Expectation物件的映射。每個物件必須有expected_behavior、answer_key、required_evidence_groups、forbidden_sources，不能放字串佔位。
- direct／paraphrase_cross／version須answered，有非空答案及證據組；insufficient的答案與證據組須為空陣列；permission三角色齊全。
- 每行Question只允許匯出schema列出的欄位，不接受額外註記欄位。review_status為pending或verified；只有使用者已實際核對才填verified與真實reviewer／reviewed_at。
- 依最新tasks要求，由獨立作者／使用者核對公司題答案與證據定位；Codex不讀保留題來修正或調參。

修正及人工審核後，由使用者在專案外驗證，僅將摘要輸入專案（操作命令見stage-1-review-guide.md）。本次沒有把未通過的檔案凍結為正式保留集，也未覆寫holdout.manifest.json為已通過。


## 2026-10-18 階段4前重新驗證（Claude修正後）

依使用者授權執行現有檢核器，僅回傳彙總，不將保留題題目、答案或證據內容輸入對話。正式holdout.jsonl共10筆，7筆schema合格；仍有3筆缺review_status、6處不允許額外欄位、1處category不符、6處證據定位不是Reference物件、1處employee預期不符合約束。正式檔嚴格驗證失敗。

另檢查同資料夾holdout.candidate-H07-H09.jsonl：全10筆schema、類別分配及manifest引用有效性均通過，但7筆verified、3筆pending，嚴格檢核回human_review_pending。候選尚不能直接凍結，未修改外部任何檔案。

使用者先前已確認10題內容；若Claude僅做格式轉換且內容與已核對版本一致，應沿用該既有審核紀錄並完成正式檔合併；若候選改變答案或證據語意，需由使用者核對變更。Codex不讀正文、不代改保留題、不自行將pending改為verified。

本次不產生正式保留集hash，不勾選1.4／1.5，不開始階段4；進度仍25/55。安全診斷見reports/holdout-format-check.json，沒有API呼叫或費用。


## 最終凍結與搬移（2026-10-18）

使用者確認H07–H09依C01–C03原文修正且已核准，其他7題不變。現有檢核器嚴格檢查正式檔成功：10題、可回答8、角色執行12、verified10、分配4/3/1/1/1，引用及生效日期／角色均通過。只查看摘要，未將題目、答案或證據正文輸入對話。

SHA256：ed30ff0f75e95deb0e349ef90a3d063f9b3f3f8e6354c1eff76b6a5ec5981989。

正式檔與兩備份已移至 %LOCALAPPDATA%/hr-leave-rag-private/holdout；逐檔驗hash後才移除原暫存副本。資料夾關閉ACL繼承，只授權目前使用者及SYSTEM。Windows使用者環境變數HR_RAG_HOLDOUT_PATH已指向新正式檔，現有終端需重新載入此變數，新終端可取得新值。未讀取或修改.env。

C01–C04原始快照內「LLM草稿，待人工核對」是歷史文字；目前data/manifest.json的11版本已依使用者前次確認標為verified。此次不改來源內容或hash，以manifest及使用者審核紀錄為現行狀態。未來公司文件修改須重驗H07–H09的引用及答案；語意核對由使用者／獨立作者進行，重新產生驗證與凍結紀錄。

baseline.freeze.json綁定文件manifest、11版本原文／normalized hash及開發題hash；專案資料／評估／報告／設定區檢查未含保留題正文。第一階段1.1–1.6驗收通過，總進度27/55，放行第四階段。以前未通過的描述保留為歷史紀錄，以本節為準。
