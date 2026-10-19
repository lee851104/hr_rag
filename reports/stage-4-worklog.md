# 階段4執行紀錄

前置：2026-10-18保留題正式檔strict exit0、10題verified、SHA256 ed30ff0f75e95deb0e349ef90a3d063f9b3f3f8e6354c1eff76b6a5ec5981989。baseline.freeze.json綁定manifest與開發題，1.4／1.5已勾選，階段1及3通過；進度27/55。僅使用開發題實作與選參，不讀保留題正文、不呼叫生成API。

執行方式：沿用openspec-apply-change與executing-plans，原地TDD，沒有Git。完成後一次獨立整體審查。

Ruling: 所有模式共用96 tokens雙tokenizer檢查與同義詞表示；BM25保留條號、數字、日期；dense cosine，RRF60，rerank最多20。授權及日期在計分前、重排前與回傳前重驗。

Ruling: 上下文共用OpenAI provider的純payload/token預算函數，不能另造與實際送出不同的提示。去重先按父段；跨來源只有明確共同適用範圍可證時才合併，沒有適用範圍metadata時保守保留，不把官方／公司互相覆蓋。

Ruling: 人工有用性標註不由LLM代簽。產生去重後待標註清單與本機頁面；同(question_id,role,內容SHA256)跨模式重用。未標註不偽造精確度，4.9保留未完成直到人工標註及門檻通過。

Ruling: forbidden_sources同時支援document_id與document_id/version_id；版本層級禁用不擴大成整文件，獨立測試驗證。

TDD：四個新模組先出現4個collection error，再完成實作及60項定向回歸。後續missing ACL測試先重現Pydantic錯誤，再修為授權路徑隔離非法metadata。擴充候選20筆上限、重排前撤回、雙tokenizer、跨來源正文相同與偽造Evidence測試後，68 passed。

獨立整體審查：review_stage4只讀檢查與合成重現，2 Important／0 Critical。第一項是withdraw不改generation、評估可能混用候選集合；第二項是組裝失敗抹除Top-5並漏計授權錯誤。新增3個回歸均先失敗（3 failed／6 passed），修正後9 passed。現在執行指紋含active metadata、所有unit ACL／日期、document metadata與撤回表；評估開始／結束及模式間均一致才接受比較。先保存及驗權Top-5，後組裝，組裝錯誤只歸零上下文，保留固定錯誤碼。

首輪實測保存在retrieval-comparison.json：相同46子片段，dense／hybrid／rerank的Top-5完整命中12／11／13（分母14）；context_max_units=3時組裝完整命中10／10／11。三模式版本均3/3、授權及執行錯誤0，人工精確度均null。此早期報告不含後補execution_fingerprint，以修正後候選重跑為正式比較證據。

開發集診斷：重排D10的必要證據包含第5名、D11包含第4名，因此max_units從3改5；D10必要第五名分數約0.589，候選min_relevance選0.58。這只是根據開發證據覆蓋選候選，不是用gold reference代替人工有用性。不修改問題、答案、語料或保留集。

最終自動證據：候選max5/min0.58的dense／hybrid／rerank Top-5及組裝各12／11／13（分母14），版本均3/3、安全及執行錯誤0；只有rerank達門檻，選為候選。關閉同義詞後Top-5為12／10／13，組裝為12／10／12；六組全部真實執行26角色，執行指紋及模型／提示／資料／標註hash一致。保留同義詞開啟，無API呼叫。未採用先前考慮的子集重跑或排名重用方案。

完整回歸313 passed／1 Windows symlink權限skip，241.90秒。之後只補三模式同義詞配對命中必要組測試，四個階段4模組35 passed（5.46秒），產品程式未再修改；Ruff及OpenSpec strict通過。

4.1～4.8完成，逐項讀取OpenSpec sourcePath／line確認後勾選，35/55。4.9維持待人工有用性，167個去重單位已提供核對頁；精確度null，candidate設定明確pending_human_precision。沒有放行階段5，沒有變更門檻或代簽。


2026-10-18 使用者要求不改標註、不降80%門檻，只用開發題改善；達標後進階段5。固定labels SHA256為092e10881957c25bf1d80509cd742bac6bee5b15b26725c56c79e78084e13255。590組完整分數分界×max_units搜尋，保住13/14且全部已有標註的最佳結果仍77.02%，見context-parameter-grid.json。新增只看問題與正文的可關閉假別範圍篩選；規格四份同步，沒有題號或來源ID特判。

獨立審查review_stage4_scope指出兩項Important：一般程序／跨法規混合段與否定問句可能誤刪。新增7個合成反例先7 failed／17 passed；改為否定不篩、程序及法規指涉不篩、每個句子必須明列假別才可判定不同範圍。修正後上下文／檢索／評估50 passed，Ruff通過；修正後真實三模式及完整回歸執行中。第一名仍保留，授權與預算優先，不變更人工標註與證據覆蓋門檻。

最終：修正後真實三模式77.50%／66.55%／81.79%；rerank完整命中13/14，版本3/3、安全及錯誤0、待標註0。完整336 passed／1 skip，4.9完成，selected設定凍結，進度36/55，放行階段5。
