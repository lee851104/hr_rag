# 階段5驗收：人工核對與原文候選採用

2026-10-19。**5.4、5.5依使用者人工核對通過；階段5通過，41/55。** 原題、標註與門檻未改；未讀保留題正文；本步驟沒有新增API呼叫。

## 人工核對匯入

| 項目 | 結果 |
|---|---|
| 開發核對JSON | 使用者 2026-10-19T01:49:42Z；source_sha256 `06b51dc6…f49ae015` 與 development-verbatim-gpt41-v3.json 相符；review SHA256 `04bd5b1f…14daac4` |
| 穩定核對JSON | 使用者 2026-10-19T02:55:55Z（第二次匯出）；source_sha256 `35e559b1…4ba69b` 相符；review SHA256 `89cabc9b…40fef9acd` |
| 第一次穩定匯出 | 02:26:13Z，D05第2、3次及D13第1次各1筆引用標「不支持」→15/18。使用者確認為誤選，自行於核對頁更正並重新匯出；第一次匯出與計算保留於 `stability-verbatim-gpt41-v3.review-export1.json`、`reports/stage5-human-review-stability-v3-export1.json`。Claude曾嘗試以對話內容代為套用更正，被安全審查拒絕並移除，未產生任何代填檔。 |

匯入工具 `python -m hr_rag.answer_review --source … --review … --output …`：驗 schema、source hash、kind、complete、核對者、時間、每列 question_id／role／repeat、主張－引用對與答案一致、所有判定為布林值；依原門檻計算，不改寫判定。模型狀態與預期不符的列即使人工勾正確也不計通過。測試 `tests/test_answer_review.py` 16 passed（先觀察 import 失敗再實作）。

## 依原門檻計算

| 5.4 開發 | 結果 | 門檻 |
|---|---|---|
| 可回答（direct／paraphrase_cross／version） | 14/14 | ≥13/14 |
| 資料不足 | 3/3 | 3/3 |
| 版本 | 3/3 | 3/3 |
| 權限角色執行 | 9/9 | （記錄） |
| 引用支持（主張－引用對） | 36/36＝100% | ≥95% |
| 關鍵主張覆蓋 | 26/26 | 100% |

| 5.5 穩定（6案例×3次） | 結果 |
|---|---|
| 必要內容／狀態／覆蓋／引用全符合的執行 | 18/18 |
| 引用支持 | 37/37 |
| 模型故障或狀態不符 | 0 |

三次結果皆依同一預期答案判正確，未見矛盾。D05三次選段長度不同但必要答案完整，未要求字句相同。

**與Codex初查的差異：** D11使用者判定正確且覆蓋完整；Codex初查曾認為漏「必要性有疑義時轉人資」。以使用者人工判定為準；即使D11不計，可回答仍為13/14，結論不變。

## 原文候選正式接入

- `config/generation.selected.json`（SHA256 `96489f26…aac1b4f26`）：由 candidate-v3（SHA256記於 candidate_sha256）複製 mode／settings／system／schema／implementation_sha256，status=selected，附兩份人工核對檔hash。
- `config/models.lock.json` 新增 `selected_generation`（設定hash、人工評估檔hash與passed、歷史鎖定位置）；`openai_generator` mini摘要設定保留為歷史。原檔另存 `config/history/models.lock.2026-10-18.json`（SHA256 `77ab0f39…40e577e58a8`，與交接時一致）。新lock SHA256 `9b6f938d75081160cea6e15b5c4dbd6891c17f459fae3477f1b59e4c1e7f8200`。
- `src/hr_rag/generation.py`：`selected_generator()` 只在設定檔hash、status、mode、SYSTEM、SourceSelection schema、verbatim.py實作hash皆與驗收一致時建立 `VerbatimGenerator`；否則 `generation_selection_changed`，不退回摘要。
- `AnswerService` 預設生成器、`answer_evaluation`（開發真實評估）與 `evaluation` 的組裝預算改用正式選定設定與 `build_verbatim_payload`，確保正式路徑與已測payload／預算一致（4096／2048／512／128、60秒、2次重試）。
- `OpenAISettings()` 類別預設仍為mini（歷史凍結測試依此），正式路徑不直接用它。

測試：`tests/test_generation_selection.py`（先觀察 import 失敗）、更新 `test_answering.py` 的預設生成器斷言（mini→已採用候選，屬本次決定的變更）。完整離線 `pytest -q` **432 passed、1 Windows symlink權限skip，177.94秒**（`.runtime/stage5-adoption-tests.log`）；Ruff及 `openspec validate --strict` 通過。

## 費用

本步驟0次API。帳本 445次、已結算US$0.8992952、預留0、剩餘US$0.1007048（累計上限US$1不變）。
