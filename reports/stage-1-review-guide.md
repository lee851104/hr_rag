# 階段1人工核對清單

2026-10-18：11個文件版本及20題開發題已由使用者核對通過；10題保留題內容亦已確認，唯原檔格式仍須由獨立作者修正。已完成的人工核對不需重做，最新狀態見stage-1-resume.md。這份清單不包含保留題題目。

## 來源與公司制度

依 `data/manifest.json` 的 `raw_path`、`normalized_path`、`indexed_sections` 逐份核對：

1. 6 份官方原文與索引條文一致，沒有漏掉項款或例外。日期原始字串、沿革項次及施行條款見各條 `date_evidence`。文件最早起日不是所有條文共同起日。
2. O05/O06 各一則完整問答，以發布日 2025-07-07 為解釋資料起日。項目更新日 2026-04-23 沒有前後內容比對證據，`revised_at` 保持 null。
3. C01–C04 都是虛構示範；C01 v1/v2 只有申請窗口與補件流程不同。核對內部規則不縮減法定權利。C01/C02 三角色可讀；C03 僅 manager/hr；C04 僅 hr。
4. 確認維護責任：官方為「專案資料維護者」、公司文件為「專案制度維護者」。人工完成後才填真實核對者、`last_reviewed_at`，`next_review_due` 預設該日加30天，並將 `review_status` 改成 verified。不要以擷取日代填核對日。C01 的兩個版本分別核對。

官方全文及沿革保留在 `data/raw/official-2026-10-18/`；`sources.json` 記錄各快照網址、擷取時間、SHA256。`data/normalized/` 只含明列索引範圍。來源輔助頁與評估檔不在匯入白名單。

## 開發題

逐題核對 `eval/development.jsonl` 的問題、日期、逐角色答案及必要證據組。組內為可替代證據；不同組必須全部命中。權限題須核對三角色，不可用 HR 的答案替 employee 計分。

全部20題由 Codex 草擬，已由使用者逐題核對通過（2026-10-18）。完成各題後填 `reviewer`、`reviewed_at`、`review_status=verified`，保留原作者。若答案或標註改動，重新核對 `eval/stability-cases.json` 的相同六個題號、角色、日期、預期結果和 hash；不能悄悄換題。

目前固定六案：D01 官方、D05 公司、D09 跨文件、D13 版本、D16 權限、D18 資料不足，皆 employee。這是預選，不是18次模型執行結果。

## 使用者自行準備保留題

依2026-10-18更新計畫，10題可由不參與調參的Claude草擬、使用者審核定稿，存於專案外；不要將正文交給本實作對話或Codex。使用者已提供外部草稿，但格式尚未通過，詳見stage-1-resume.md。`eval/holdout.manifest.json` 目前記錄格式未通過與使用者內容確認，不是有效凍結摘要。機器格式見 `eval/evaluation.schema.json`。

格式沿用 `src/hr_rag/evaluation_schema.py` 的 Question/Expectation/Reference：每行一個 JSON，`split=holdout`；類別分配 direct 4、paraphrase_cross 3、version 1、permission 1、insufficient 1。除權限題外每題一角色，權限題三角色；可回答題要有答案與必要證據組，資料不足時兩者為空陣列。`forbidden_sources` 應列該角色不可讀文件。日期 YYYY-MM-DD；引用使用清單既有的 document_id/version_id/section_id。作者、核對者填實際人員，完成核對才標 verified。

使用者自行在 PowerShell 執行（不需 API；不要把正文或逐題輸出貼回此對話）：

```powershell
# 在這個終端先設定 HR_RAG_HOLDOUT_PATH 為專案外檔案位置。
.venv/Scripts/python.exe -m hr_rag.evaluation_schema --split holdout --path "$env:HR_RAG_HOLDOUT_PATH" --manifest data/manifest.json --summary-output eval/holdout.manifest.json
```

命令只輸出類別計數、作者／核對者、hash 等摘要。通過格式不代表答案已經過人工判定；人工與格式兩者都完成才可放行階段1。開發工具不自動讀取該環境變數或保留題正文。

## 驗證命令

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m hr_rag.evaluation_schema --split development --path eval/development.jsonl --manifest data/manifest.json --allow-pending-review
.venv/Scripts/python.exe -c "from pathlib import Path; from hr_rag.corpus.manifest import validate_manifest; print(validate_manifest(Path('data/manifest.json')))"
```

第二個命令允許草稿，只驗結構、數量及證據適用性。最後一個命令是嚴格驗證，人工核對未完成時會列 pending human review。完成核對後，開發題命令也應移除 `--allow-pending-review` 再驗。實際匯入前必須使用嚴格清單驗證；白名單函式只限定可讀檔案，不能取代發布門檻。
