# 第五階段 D09／D15 開發修正

本輪只使用20題開發集。保留題僅由既有檢核器串流計算hash；未讀取題目、答案或證據正文。5.4、5.5仍需實際結果與人工核對才可勾選，第六階段尚未開始。

## 修正與限制

- D09：完整問題把O04第21條排到第9（0.38035），獨立不利處分子句則第1（0.99488）。保留原top20候選及完整問題，最多加入兩個「以及」後的並列子句重排，取最大分後仍取top5；每次計分重驗權，不使用題號、金標或標註決策。
- D15：兩輪提示診斷仍把一般補件資訊猜成特殊覆核表名稱。加入具名表單的必要證據檢查，缺直接名稱／識別依據時回資料不足並移除猜測。只處理明示名稱詢問，不攔一般附件／欄位問題。通過此檢查不代表已證明流程適用性，語意仍須人工檢核。
- 審查發現1 Important（一般表單問題誤拒與名稱格式漏認），已用5項先失敗測試重現並修正。另補中途撤權測試；不進行第二輪重複審查。

## 檢索驗證

固定原max_units=5、min_relevance=0.58、leave_scope_filter=true，80%門檻不變；完整三模式本機實跑，見retrieval-stage5-compound.json。

|模式|Top-5全組|組裝全組|人工精確度|
|---|---:|---:|---:|
|dense|12/14|12/14|77.50%|
|hybrid|11/14|11/14|66.55%|
|rerank|14/14|14/14|82.14%|

三模式版本3/3、授權與執行錯誤0、待標註0。與先前送入模型的上下文相比，只有D09新增O04第21條，其餘25個角色執行的上下文相同。D09必要證據3/3、個別精確度80%。

原eval/labels.jsonl SHA256仍為092e10881957c25bf1d80509cd742bac6bee5b15b26725c56c79e78084e13255。使用者確認D09/O04/21有用，另存eval/labels.supplemental.jsonl（SHA256 ae774bd9e47529e514d16e11f7e771ce3c58a72bddc171a8aad4589db2586ec6）。補充檔不得覆寫既有鍵；沒有修改或降低既有判斷。

## 實測紀錄

mini修正後紀錄已保存於受限目錄.runtime/stage5-private/development-compound-v2.json與stability-compound-v2.json，含實際請求、原始輸出、最終結果與凍結hash；同名HTML供人工逐題核對。前輪診斷均保留，不覆寫成最終結果。

API沿用.env，不顯示、不記錄或寫回憑證；以原累計帳本與min(.env設定,1美元)限制。成本彙總含所有失敗診斷輪次，公開報告不含限閱正文。最終費用與驗收數字以stage5-api-summary-fixes.json及下方執行結果為準。


## 完整比較與結論（2026-10-19）

D09缺證據與D15員工猜測已修正；第五階段整體仍未通過，不啟動第六階段。只用既有20開發題，沒有更改問題、答案基準、原有標註或驗收門檻。正式預設仍為mini；GPT-4.1只保存為未選用候選。

|相同開發範圍的實際結果|mini修正後|GPT-4.1候選|
|---|---:|---:|
|開發角色執行|26|26|
|回答狀態符合預期（非正確率）|26/26|25/26|
|固定6案例各3次狀態符合|18/18|18/18|
|開發26次成本估算|US$0.0179396|US$0.104266|
|穩定18次成本估算|US$0.0112660|US$0.064738|
|44次合計|US$0.0292056|US$0.169004|
|整體5.4／5.5|未通過|未通過|

兩候選提示不同（mini正式提示及GPT-4.1診斷第4版提示），因此是可用設定比較，不宣稱純模型因果實驗。GPT-4.1的完整44次約為mini成本的5.79倍；沒有足夠證據支持現在直接切換正式模型。

GPT-4.1改善了D08遞延結清計薪時點、D11系統提交方式，以及D12–D14流程不得新增法定限制的提醒。D09開發與穩定三次都涵蓋日數、事假、薪資及禁止不利處分，必要引用齊全；D15員工回資料不足，沒有送出C03/C04無權內容。

仍有以下已知問題，不能以answered或引用ID存在冒稱通過：

- D05未交代緊急情形先通知、再處理紀錄；固定三次也全部遺漏。
- D06未交代窗口保留通知與收件進度。
- D08未完整保留年度終結未休原則應發工資的說明，雖然遞延結清計薪基準已正確。
- D10缺一般事前通知／證明及窗口追蹤等既有必要項目。
- D11缺必要性有疑義時轉人資核對及不得以缺件自動否定權利的完整說明。
- D18開發輪模型輸出claims=[]但citations仍有e1，既有引用聯集檢查正確阻擋，回error；這次算失敗，沒有事後刪引用改成通過。穩定三次則正確資料不足，原開發失敗仍保留。
- 權限題另有一般流程被推廣成特殊流程的初步疑慮，詳見受限的逐題初查；沒有發現送出無權來源。

Codex依原答案基準初查，14可回答題中至少5題有上述缺項，不能達13/14；這是未通過的初查證據，不是使用者人工簽核。引用支持率≥95%、關鍵主張覆蓋100%及18/18穩定門檻原樣保留，人工欄位全為pending。穩定輪狀態18/18，仍因D05三次內容不完整而不通過。

### 候選前置重驗與可重現資料

- GPT-4.1快照gpt-4.1-2025-04-14；[官方模型頁](https://developers.openai.com/api/docs/models/gpt-4.1)查證2026-10-19，輸入US$2／輸出US$8每百萬tokens。temperature=0，4096/2048/512/128預算、60秒逾時、2次重試均未改；[官方停用公告](https://developers.openai.com/api/docs/deprecations)仍列2027-01-14。
- 0.8順序重驗5/5自動通過，Codex核對所問核心未發現錯誤（不是使用者簽核）；P50 11.0992秒、P95 18.684秒、US$0.034908、預留0，見feasibility-stage5-gpt41-sequential.json。較早並行診斷的成本彙總失真紀錄保留，沒有將其冒稱通過。
- 4.9三模式全部重新執行。78組有序上下文與mini修正後相同，rerank仍14/14、82.142857%、版本3/3、授權與執行錯誤0、待標註0。公開摘要retrieval-stage5-gpt41-candidate.json只含彙總；完整正文移存受限目錄，原hash e9a1cf39692631cfc3ff54e4be4929728ef08058d14170f527253c03a675cbec不變。
- 候選設定config/generation.gpt41-candidate.json，SHA256 df313d82c644d8331b9b3e7c0984e8f3d386d681a94ff1ade3037dba2a555b62；提示SHA256 da78cde5ec5f7cd672b6eb000201feb6e99e7cffe9380f13c69b62f703eae64c。不是正式模型鎖檔。
- 詳細結果及可匯出JSON的HTML：.runtime/stage5-private/development-gpt41-candidate-v2.{json,html}、stability-gpt41-candidate-v2.{json,html}。既有mini的compound-v2兩份結果／HTML仍保留；HTML不預填通過、不改上下文標註。初查另存gpt41-development-precheck.json與gpt41-stability-precheck.json，不寫入人工判定欄位。
- 候選輔助腳本首次缺Windows spawn入口守衛，API前失敗，0次API／0費用；development/stability-gpt41-candidate.json保留，修正後另跑v2，沒有將失敗列刪除或覆寫為成功。
- [Luna官方頁](https://developers.openai.com/api/docs/models/gpt-6-luna)僅列gpt-6-luna，未提供本計畫要求的帶日期快照；已鎖tiktoken 0.14.0亦沒有gpt-6編碼映射。此輪未假設tokenizer、未呼叫Luna或更改既有快照規格。

本輪可重現命令（既有輸出存在時拒絕覆寫，重跑應另存新檔並先核對成本）：

```powershell
.venv/Scripts/python.exe .runtime/evaluate_gpt41_candidate.py feasibility
.venv/Scripts/python.exe .runtime/evaluate_gpt41_candidate.py retrieval
.venv/Scripts/python.exe .runtime/run_gpt41_candidate_answers.py
.venv/Scripts/python.exe .runtime/summarize_stage5_fixes.py
```

### 費用、驗證與後續邊界

全部API累計291次，依usage與已查證單價估算US$0.5415252，預留0，低於原1美元上限。從上一輪US$0.1204556起，本次新增159次／US$0.4210696。第五階段全歷史含失敗診斷及候選0.8重驗共281次，輸入345,179／輸出48,142 tokens，估算US$0.5083212；加最初0.8的US$0.0332040與原帳本逐項總額相符。沒有重設帳本、套用快取折扣或排除失敗費用。費用是API usage估算，不是帳務發票。

正式程式完整離線387 passed／1 Windows symlink權限skip，耗時243.79秒（stage5-fixes-final-tests.xml）；Ruff及OpenSpec strict通過。比較腳本後續調整沒有更動正式程式。原labels與開發題hash維持不變，保留題只驗hash，未讀正文。

不將已知錯誤交由使用者勾選來掩蓋，也不為達標繼續堆疊相似提示。下一次改進應以「生成遺漏必要條件」與「輸出引用一致性」為明確目標；若要增加多段生成／檢核流程或更動凍結預算，先調整計畫並重新驗證。5.4、5.5保持未勾選，總進度39/55，第六階段未開始。
