# 第五階段引用與完整性修正（2026-10-19）

計畫：openspec/changes/build-hr-leave-rag-mvp/tasks.md。延續既有非Git工作目錄，未建立新分支或覆寫舊結果。

Ruling: 引用wire改成claims-only-v2、保留外部Answer契約 — 根因是模型重複維護引用聯集 — 若錯則provider輸出會失敗，須以白名單、空主張及舊欄位拒絕測試阻擋。

Pre-flight: provider產生Answer，AnswerService仍驗聯集／支持／權限；prompt/schema變短可能影響上下文預算，實測前必須核對實際組裝內容。

引用RED：新增4個測例，3 failed／1 passed；GREEN：tests/test_openai_provider.py 49 passed。

二次審稿診斷8題、8次API，從US$0.5415252增至US$0.5490068（本輪US$0.0074816），預留0。使用快取開發草稿與原授權證據，沒有讀保留題。D05有改善，但D06仍漏窗口紀錄、D08仍錯計薪時點、D10/D11仍漏程序，D15生成仍混用流程（正式服務另有拒答守衛）。不是新鮮端到端評估，不宣稱通過。原始紀錄位於受限.runtime/stage5-private/review-pass-pilot-v1.json。

Ruling: 不採用二次審稿 — 小測未解決完整性，避免增加每題費用及延遲 — 若錯可能錯過可調整的審稿方法，但保留原始紀錄供後續研究。

5.4/5.5未通過，第六階段未開始；不得用程式或Codex初查代替使用者人工核對。


引用真實小測：D18原開發問題＋原授權上下文，mini連續3次均insufficient、空claims／citations、無provider錯誤。僅驗證引用格式回歸，不是26＋18次正式驗收；受限紀錄wire-citations-pilot-v1.json。本次3次US$0.0015852。

API費用已逐交換與帳本對帳：全部302次、US$0.5505920、預留0；本輪11次共US$0.0090668（包含失敗語意方法小測8次）。先前完整彙總保持原樣，新彙總見stage5-api-summary-wire.json。重現彙總命令：`.venv/Scripts/python.exe .runtime/summarize_stage5_wire.py`。

安全測試完整首輪389 passed／2 failed／1 skip；兩失敗為test_prompt_injection仍送出舊頂層citations假回應。修正fixture為新wire、保留所有原安全斷言並新增正常引用聯集斷言後，4項安全測試全部通過。首次失敗紀錄stage5-wire-tests.xml保留。

Final review: 新的獨立review_wire_citations唯讀審查未發現Critical/Important問題；檢查白名單、別名還原、空主張、舊欄位拒絕、成本結算與錯誤記錄。沒有代理讀取金鑰或保留題，沒有新增API呼叫；後續僅修正上述測試fixture。

必要內容修正尚未完成。摘要式生成仍漏條件；使用者後續同意先測選出相關完整原文再附引用；候選未驗收，尚未切換正式模式。即使採用摘錄式回答，也必須按原必要內容／引用支持／權限／穩定門檻重驗，不可單靠複製所有上下文宣稱通過。


引用修正完整離線：391 passed／1 Windows symlink權限skip（stage5-wire-final-tests.xml，233.45秒）；Ruff及OpenSpec strict通過。三模式重驗dense 12/14／77.5%、hybrid 11/14／66.55%、rerank 14/14／82.14%，版本皆3/3、授權／執行錯誤／待標註皆0（retrieval-stage5-wire.json）。

使用者同意原文模式後新增候選：src/hr_rag/verbatim.py。Ruling: 以只含source_ids的嚴格schema選段，由程式還原完整原文 — 原文小測v1保留文字欄位時模型仍改寫，6/8輸出拒絕，失敗未事後修補 — 代價是回答較長，且選錯段落仍可能不能回答問題，須逐題核對。

原文候選RED：新模組不存在、assemble_context未接受實際payload_builder，測試如預期失敗。實作後provider／context／answering／注入等120項通過。候選使用實際生成器schema與提示計算組裝預算，並保留原已授權全文作為輸出唯一來源。正式預設仍摘要mini。

原文小測v2（mini）補齊D05/D06/D08/D10/D11，但D18仍選了無關特休條文，未判為整體通過。GPT-4.1同格式小測保留這5題必要項目，D10移除不必要協調背景，D18正確空引用；D15員工仍須既有服務守衛拒絕，D17選入背景來源需核對。兩者均僅候選，不將來源ID命中或逐字相同當成完整語意驗收。

後續完整評估採先前已授權GPT-4.1快照與原單價，先重跑0.8、4.9，再執行26開發＋18穩定；設定記錄config/generation.verbatim-candidate.json，未覆寫models.lock.json或人工標註。

原文候選完整離線398 passed／1 skip（172.99秒，stage5-verbatim-tests.xml）；Ruff通過。候選0.8為4/5自動命中，達原門檻；F2原文正確包含「亦不得將勞工已請的事(病)假擅自更改為特別休假」，未符合原regex最多12字間距限制，原自動分數仍保持4/5，未改評分器；Codex語意初查不代替人工簽核。成本US$0.024794、P95 12.8437秒、預留0。


原文候選4.9重驗：dense 12/14、77.5%；hybrid 11/14、66.55%；rerank 14/14、82.142857%；三模式版本3/3、授權／執行錯誤／待標註0。78份有序上下文與引用wire重驗完全相同。

重驗原始metadata中的prompt_sha256曾繼承摘要生成器指紋；實際組裝明確使用原文提示與SourceSelection schema。未覆寫原始結果；另以verbatim-payload-recheck.json逐份重建78個payload，所有input_tokens都精確相等，記錄實際提示SHA256 24c1037b6f64f787bc745dfb2817aa82826cddda83087c860c21f442e79eefa4。後續評估腳本已綁定正確候選類別，正式開發／穩定結果另記錄4個實作檔hash。

原文候選Final review: 獨立review_verbatim_candidate未發現重要具體缺陷，核對來源還原、ID驗證、日期／撤回、文字限制、預算及既有錯誤／成本路徑；未執行API或讀禁讀資料。本次審查不代表人工內容驗收。


原文v1正式開發26次狀態26/26符合，但D09漏被指向的事假工資規則、D12～D14只選版本查閱指引而漏實際窗口及表單，4題必要引用群不足；初查可回答題最多10/14、版本0/3，不通過。D15員工由既有具名表單守衛正確拒答。不得把「逐字引用」自動等同於內容完整。

下一個診斷只增加通用跨來源依賴指示：已選段落若把所問答案指向另一規定或文件，須同選本次證據裡的具體內容，不能以查閱指引代替答案。評估病例包含D09獨立3次、D08、D12～D14、D18；不把題號、金標、來源ID寫入生成規則。先小測後決定是否採用。

若僅修改選段提示，4.9使用上一輪真實三模式top5與分數精確重播組裝及評估：逐次核對索引／ACL／日期／撤回指紋與每個來源全文，重新依原人工標註算精確度及覆蓋。正式應用檢索不變；後續開發26＋穩定18仍各自獨立真實API，不共用答案快取，報告明列檢索重播，避免將重播稱為新檢索模型推論。


本輪最終原文v3實測與完整成本已另存stage-5-verbatim-v3.md及stage5-api-summary-verbatim-v3.json。累計445次／US$0.8992952／預留0，Codex初查13/14及穩定18/18，D11仍失敗；未替使用者人工簽核，未進6。
