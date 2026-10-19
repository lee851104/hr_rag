# 第五階段原文候選 v3：實測完成，待人工驗收

2026-10-19。依使用者核准改採「模型選相關段落、程式保留完整原文與引用」。只用開發題；未改題目、標註、門檻或正式模型鎖定，未讀保留題正文。第五階段5.4／5.5仍未勾選，第六階段未開始。

## 結果

以下為自動檢查及Codex逐題內容初查，不能代替使用者人工核對。逐題理由保存在stage5-verbatim-v3-preliminary-review.json；原始人工欄位全部仍為待核對。

| 檢查 | 結果 |
|---|---|
| 0.8固定5題 | 自動4/5、全繁體、全未逾時，P95 13.4248秒 |
| 4.9 rerank | Top5及組裝後完整證據14/14，原人工標註精確度82.142857%，版本3/3，授權／執行錯誤／待標註0 |
| 5.4獨立可回答題 | Codex初查13/14（92.86%）；D11維持失敗 |
| 資料不足／版本 | 3/3、3/3 |
| 三角色權限題 | 9/9符合預期，未見受限內容外洩 |
| 開發引用 | 36/36主張－引用對由原文支持；已生成關鍵主張引用覆蓋100% |
| 5.5六案例各三次 | 18/18初查符合預期；37/37主張－引用對支持，未見矛盾 |
| 完整離線測試 | 410 passed、1 Windows symlink權限skip，180.48秒 |

D11仍只選到申請窗口與B-02段落，漏掉FAQ中「必要項目核對、必要性有疑義時轉人資」；整題判錯，沒有降低標準或移除分母。引用覆蓋是已生成主張是否有支持引用，不是缺漏答案的豁免；D11缺漏反映在答案正確率。無主張的拒答列之引用分母為零，標示不適用，不算滿分。

D09的家庭照顧假規定會明示準用事假工資，程式只從已送出且已授權上下文補上原事假條文，保留各自適用範圍。三次均有日數、薪資與不利處分保護。D15員工角色仍由既有具名表單守衛拒答；hr／manager完整保留特殊表單及限制。

原文輸出較長：D03／D04有整條背景；D13補入同文件的範圍與說明；D16員工及D20只有公開示範背景，幫助有限但未編造受限／真實公司答案。D05三次選段長度不同，必要答案皆完整，未見矛盾；不把選段完全一致當穩定性定義。仍請人工確認可讀性及適用性。

0.8的F2完整原文保留禁止擅改事病假，但未符合既有regex的12字間距；自動分數仍4/5，不修改評分器。Codex內容核對F1–F5未見必要內容錯誤。4.9採先前真實三模式top5及分數的驗證重播，逐次核對索引、權限、日期、撤回及全文，重新計算實際組裝預算與原標註；不是重新執行檢索模型推論。44次生成均為獨立真實API，沒有答案快取。

## 實作與失敗保留

- 摘要生成wire只由模型輸出逐主張引用，程式建立引用聯集，避免D18全域空引用衝突；外部Answer介面不變。
- 候選以source_ids選段，程式從實際送出的payload還原原文；本機嚴格檢查未知／重複引用及目前權限。
- 只送出最小source=[document_id, version_id, section_id]供明示參照判斷。使用緊湊JSON，固定可行性證據2035tokens，仍在原2048預算內；完整schema、enum及提示均計入4096限制。
- 參照補充只在本次上下文做有限閉包，不讀外部文件，不使用題號或金標。獨立審查指出否定語句可被前面肯定動詞跨逗號誤讀；新增3個反例確認失敗，再阻止跨逗號及否定詞匹配。此保守字面規則不宣稱完整理解法律依賴。
- v2固定5題出現文件代號被當引用ID，3/5不通過，原始紀錄保留。v3 schema將source_ids限制為本次實際引用別名enum，同時保留本機驗證；新回歸先失敗後通過。
- 二次審稿、原文文字欄位、只增加依賴提示等不合格實驗均保留且計費。正式models.lock.json仍是mini摘要；候選設定為config/generation.verbatim-candidate-v3.json，尚未採用。

## 成本與驗證

最終44次：開發26次US$0.065852（輸入29338／輸出897tokens）；穩定18次US$0.041900（輸入18210／輸出685tokens），合計US$0.107752。v3的0.8另5次US$0.027220。

全專案帳本445次，累計估算US$0.8992952，預留0，剩餘US$0.1007048。包括所有失敗與診斷，未重置帳本。對帳鏈見stage5-api-summary-verbatim-v3.json，回連verbatim、wire與fixes歷史摘要；所有交換成本合計與帳本相等。這是既定單價估算，不代表帳號其他應用費用。

執行命令：

```powershell
.venv/Scripts/python.exe .runtime/evaluate_verbatim_v3.py retrieval
.venv/Scripts/python.exe .runtime/evaluate_verbatim_v3.py feasibility
.venv/Scripts/python.exe .runtime/evaluate_verbatim_v3.py answers
.venv/Scripts/python.exe .runtime/summarize_verbatim_v3.py
.venv/Scripts/python.exe -m pytest -q --junitxml=reports/stage5-verbatim-v3-tests.xml
.venv/Scripts/python.exe -m ruff check src tests
openspec validate build-hr-leave-rag-mvp --strict
```

Ruff及OpenSpec strict通過。verify_baseline只驗保留題hash、不解析正文；開發題、原標註、補充標註、語料清單及模型鎖定hash維持原值。未輸出或記錄API金鑰。

## 人工核對與放行

依tasks.md 5.4「用實際模型跑開發題並人工核對」及5.5「人工核對後納入reports/stage-5.md」，目前只能標為待人工驗收，不能進階段6。

- `.runtime/stage5-private/development-verbatim-gpt41-v3.html`：26筆角色執行。
- `.runtime/stage5-private/stability-verbatim-gpt41-v3.html`：6案例×3次，共18筆。

兩頁保留原預期答案、實際原文與引用，每項預設「尚未核對」，可匯出JSON；未預填Codex判定。核對的是新生成答案，不重做原上下文有用性標註。允許記錄D11不通過，門檻本來就是13/14；其餘項目按實際內容判定，不要求全部勾通過。完成有效人工審核、計算原門檻並採用候選設定後，才可更新5.4／5.5並進入第六階段。
