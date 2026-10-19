# 階段7：7.1最終凍結與保留題執行器

2026-10-19（Claude）。**7.1完成，51/55。** 7.2保留題尚未執行；本步驟沒有讀取保留題正文（只核對檔案位置與SHA256 `ed30ff0f…1989`），沒有API呼叫。

## 7.1 凍結

`eval/final.freeze.json`（SHA256 `ea94e4727666ad2a0374af82144d5f8f2bd83ef14dea67ab1900324f9d4ad4dc`），`python -m hr_rag.freeze write` 產生、`verify` 通過：

- 64個檔案hash：`pyproject.toml`、`requirements.lock`、`config/*.json`（含 models.lock、generation.selected、retrieval.selected、query-synonyms、monitoring）、`config/history/*.json`、`data/manifest.json`、`eval/*.jsonl|*.json`（開發題、原／補充標註、穩定案例、保留題manifest、baseline）、`src/hr_rag/**`（程式、模板、CSS），以及合併30題時使用的開發證據 `reports/stage5-human-review-*.json`、`reports/retrieval-stage5-verbatim-v3.json`。
- 設定摘要：原文選段 verbatim-reference-closure-v3、gpt-4.1-2025-04-14、提示SHA256 `73863f97…3d5e`、預算4096／2048／512／128、60秒逾時／2次重試；encoder bge-small-zh-v1.5 `7999e1d3…`、bge-reranker-base `2cfc18c9…`；檢索 rerank、5單位、min_relevance 0.58、leave_scope_filter；同義詞 `4c3ec2ff…`；告警20次／10%／3次連續失敗／P95 45秒；累計成本上限US$1。
- 語料：active generation `dd483ec3be394e49b004ec58b87c292f`、manifest `fd19b373…`、執行指紋 `704b2558…`。
- 保留題每一步都先 `verify` 並比對語料指紋，任何不符即拒絕執行。重新凍結須另存舊檔，`write` 不覆寫。

**完整測試：** `pytest -q` 494 passed、1 Windows symlink權限skip（206.98秒，`reports/stage7-freeze-tests.xml`）。安全、日期、授權、注入、引用、追溯測試皆在其中。

**固定6案例×3次與最終設定的對應：** 穩定性結果的候選設定hash與 `generation.selected.json` 來源相同；提示SHA256相同；`verbatim.py`、`providers.py`、`context.py`、`retrieval.py`、`query.py`、`retrieval.selected.json`、開發題、標註、穩定案例hash皆相同，人工核對18/18。不同處：`answering.py`（階段6只加入階段紀錄、拒答代碼與防線事件，回答邏輯不變，既有回答測試期望值未改仍通過）、`models.lock.json`（只新增 selected_generation 條目）。當時檢索為已驗證的真實排名重播，非重新推論；保留題則以即時檢索執行。

## 保留題執行器（7.2用）

`python -m hr_rag.holdout`，必須先在同一個終端機設定 `HR_RAG_HOLDOUT_PATH`：

| 步驟 | 動作 | API |
|---|---|---|
| `retrieve` | 檔案須在專案外且hash相符；以凍結的rerank設定檢索與組裝12次角色執行；產生私人上下文標註頁 | 否 |
| `import-labels --export 檔` | 核對標註頁hash與完整性後寫入私人標註檔；不覆寫、不重複 | 否 |
| `answer` | 每個角色執行1次真實生成（不重跑；輸出已存在即拒絕）；產生私人答案核對頁 | 約12次 |
| `score --review 檔` | 依使用者答案核對與標註計算保留集及30題門檻 | 否 |

所有結果、核對頁與標註只存在 `%LOCALAPPDATA%/hr-leave-rag-private/holdout/stage7/`。主控台與 `reports/stage7-holdout-summary.json` 只有數字、題號與hash，不含題目、答案、理由或證據正文。測試 `tests/test_holdout.py`（9項，合成fixture，含不外洩正文的檢查）與 `tests/test_freeze.py`（4項）先觀察失敗再實作；`evaluate()` 的保留題分支是先實作再補測試，照實記錄。

門檻（不變）：Top-5、組裝後與答案各全體≥20/22且保留≥7/8；開發與保留精確度各≥80%；版本4/4、不足4/4、權限12/12；引用支持≥95%、關鍵主張覆蓋100%；授權錯誤0。失敗不刪題；看過保留題結果後不得據以修改系統，若修改須依曝光規則將其轉為回歸集。

**揭露：** 保留題由Claude於2026-10-18草擬、使用者審核；階段5驗收接線、階段6與本凍結也由Claude（同一模型）完成。期間沒有以保留題調整檢索、提示或門檻，所有調參依據都是開發集，但「草擬者與後期實作者為同一模型」需在最終報告揭露。

## 費用

本步驟0次API。帳本449次、US$0.9078732、剩餘約US$0.0921。`answer` 每次呼叫先預留約US$0.0123再按實際結算，12次預估實際約US$0.03。
