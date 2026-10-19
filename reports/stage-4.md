# 階段4：檢索比較與上下文組裝

日期：2026-10-18。狀態：自動實作與本機三模式比較完成；4.9人工上下文有用性尚未驗收，第四階段整體未通過，不進入第五階段。

## 前置與資料隔離

階段1、2、3均已通過。保留題已由獨立作者Claude修正並經使用者核准，現有strict檢核exit0；正式檔及兩備份移至專案外私人資料夾，Windows使用者環境變數已設定。最終SHA256為ed30ff0f75e95deb0e349ef90a3d063f9b3f3f8e6354c1eff76b6a5ec5981989。第四階段只串流驗證該檔hash，不解析題目／答案／證據；所有選參均只使用20題開發集。

`baseline.freeze.json`綁定清單、來源版本及開發集。C01–C04原始快照保留舊「待人工核對」標示，manifest已依使用者確認verified；此次未改正文。未來來源或題庫改變須重驗及凍結，公司題語意由使用者／獨立作者核對。

## 實作

- 三模式：dense cosine；中文BM25與dense以RRF60融合；融合最多20候選再以本機BGE reranker重排。條號、數字、日期保留，同分按ID穩定排序。
- 各路徑計分前篩選角色、日期及撤回；重排前再驗，無權文字不送入模型。回傳前檢查generation及候選權限。非法metadata隔離，不因缺ACL使整批授權查詢崩潰。
- 共用版本化同義詞「特休→特別休假」，補休不合併；雙encoder tokenizer均須不超過96tokens，超限不呼叫encoder。
- 同父段去重，依排名保留完整父段與來源映射；缺少可證明共同適用範圍的metadata時不跨來源合併，避免法規／公司、不同角色規則被誤合。重驗父段後才納入模型上下文。
- 相關度篩選先於預算：最多1～5單位，rerank採絕對分數，dense／hybrid相對第一名；至少保留第一名，但授權及完整單位預算優先。超額整段移除，引用白名單只含實際送出的單位。
- 使用生成provider共用的純payload建構器計算系統提示、原問題、schema與證據預算；不建立API client、不讀取金鑰。原生成provider改為呼叫同一純函數，行為由既有離線測試守住。
- 評估分列篩選前Top-5與組裝後必要證據組覆蓋／全組命中；空上下文及錯誤精確度0，未標註為null。保留失敗列與分母，組裝失敗保留已完成的Top-5及授權檢查。禁用來源支援文件及文件／版本兩種格式。
- 標註依題號、角色及內容SHA256跨模式重用；保存核對者、理由與標註檔hash。未以gold reference命中或LLM判斷冒充人工有用性。

## 固定輸入

| 項目 | 值／SHA256 |
|---|---|
| generation | dd483ec3be394e49b004ec58b87c292f |
| 執行指紋（含撤回、ACL及日期） | 704b2558e591b0c5722a88e0731cf4d3bc6a711008fd3ae8d4e67a827d72869d |
| manifest | fd19b3730eb61c23ab650fa5d9a86768c35e46913eaebf38ba7f5289c4f4b04d |
| 開發題 | 06b18e9c8023d515ddad485222fa0634e661c95b26fd9881f235738a07ad21a4 |
| models.lock | 77ab0f395e54a4c18c0786abcc5a052f16c91bf09232956b6a90e540577e58a8 |
| 系統提示 | 8e1cb3220cb3d789062a2efd9e3b7ab48eba806b72de1b646b7b67845da3ae06 |
| 同義詞 zh-leave-v1 | 4c3ec2ff4bba79a270f618e23b9b5beba5a7d0e56858354725b5e269b7fd19da |
| 人工標註檔（目前空） | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |

三模式每模式20題、26角色執行；獨立可回答14題、版本3題。44父段／46子片段，固定512維embedding，模型revision及切片設定保存在models.lock及active generation metadata。評估開始／結束的執行指紋須相同，跨模式的指紋及模型／提示／詞表／標註hash也須相同，否則不產生合格比較。

## 實測與候選選擇

命令（專案根目錄、只用本機模型）：

```powershell
.venv/Scripts/python.exe -m hr_rag.evaluation --split development --mode all --corpus full --context-max-units 5 --min-relevance 0.58 --output reports/retrieval-candidate.json
```

| 模式 | Top-5完整命中 | 組裝完整命中 | 版本 | 授權錯誤 | 執行錯誤 | 人工平均精確度 |
|---|---:|---:|---:|---:|---:|---|
| dense | 12/14 | 12/14 | 3/3 | 0 | 0 | 未標註 |
| hybrid | 11/14 | 11/14 | 3/3 | 0 | 0 | 未標註 |
| rerank | 13/14 | 13/14 | 3/3 | 0 | 0 | 未標註 |

依Top-5門檻選rerank：只有此模式達13/14。dense漏D08、D09；hybrid漏D08、D09、D10；rerank只漏D09。逐題角色、分數、必要組、正文、實際上下文、引用映射及排除理由見retrieval-candidate.json。D09缺少必要組，未刪題或修改答案。

首輪max_units=3時三模式組裝完整命中10／10／11，原始紀錄retrieval-comparison.json保留。開發題D10所需第五名重排分數約0.589，D11需要第四名，因此候選改為max_units=5、min_relevance=0.58；這不是人工精確度結論。完整候選設定存於config/retrieval.candidate.json，status為pending_human_precision，尚未凍結為已通過的最終設定。

組裝版本whole-parent-v1，生成快照gpt-4.1-mini-2025-04-14；4096 context／2048 evidence／512 output reserve／128 safety margin。三模式最大完整輸入2370tokens，保留輸出與安全餘量仍在上限內。模型未被呼叫生成。候選實測逐列耗時加總dense 17.25秒、hybrid 3.74秒、rerank 274.58秒；包含冷啟動且當時並行離線回歸，僅為該次觀察，不作公平速度排名或正式延遲承諾。

## 驗證與審查

先失敗後實作的詳細紀錄見stage-4-worklog.md。一次獨立整體審查發現2項Important、0項Critical；3個新增回歸先失敗後通過。修正評估無法偵測撤回、跨模式快照不一致，以及組裝失敗抹除檢索成績／授權錯誤。新增合成凍結測試確認保留題位元組、manifest、開發題及來源變更都要求重驗；沒有使用真實保留題正文。

```powershell
.venv/Scripts/python.exe -m pytest -q --tb=line -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check src tests scripts --no-cache
openspec validate build-hr-leave-rag-mvp --strict
```

結果：完整回歸313 passed、1 skipped（Windows symlink privilege unavailable），241.90秒；之後僅補3個同義詞配對驗收測試，未改產品程式，四個階段4測試模組35 passed（5.46秒）。Ruff及OpenSpec strict通過。兩項第三方棄用警告來自starlette／jieba，不影響通過結果。

## 同義詞開關比較

```powershell
.venv/Scripts/python.exe -m hr_rag.evaluation --split development --mode all --corpus full --no-normalize --context-max-units 5 --min-relevance 0.58 --output reports/retrieval-no-normalize.json
```

六個模式／開關組合全部以真實本機模型跑完整26角色執行，沒有快取答案或重用檢索排名；共用執行指紋及模型、提示、資料、標註hash驗證通過。兩組唯一預定差異為normalize開關，相關度及預算相同。

| 模式 | Top-5關→開 | 組裝完整命中關→開 |
|---|---:|---:|
| dense | 12→12 | 12→12 |
| hybrid | 10→11 | 10→11 |
| rerank | 13→13 | 12→13 |

分母均14。只有D03、D07、D08的查詢表示改變；D07在hybrid的必要組由1/2提升2/2，在rerank的組裝必要組也由1/2提升2/2。三模式開／關版本均3/3、授權及執行錯誤均0。保留同義詞開啟；詞表hash已綁定候選設定，人工精確度仍待核對，不能用這個改善推論其已通過。完整逐題差異與兩來源報告hash見normalization-comparison.json。

## 4.9待人工驗收

目前三模式去重後167個待標註上下文單位，呈現在retrieval-candidate-review.html及同名JSON。這是既有開發題的模型上下文，不是新增題庫。每項含題號、角色、日期、來源版本／段落、問題及單位全文；核對整個單位有用／無用，部分有用但主要無關應記無用，保存判定理由與核對者。

平均精確度目前為null，不能宣稱≥80%。使用者標註後寫入eval/labels.jsonl，再使用相同設定重算；若不足80%，只能依開發集分析調整並補核對新單位，不可降低門檻或查看保留題。4.9通過前不進入階段5；其餘階段4實作不需API金鑰。

本階段API呼叫0、費用0；既有累計估算US$0.0332040、上限US$1不變。未讀取、顯示或記錄.env或金鑰。

## 使用者補充：互動核對與JSON匯出（2026-10-18）

依使用者要求，retrieval-candidate-review.html已改為離線互動核對頁：每項可選尚未核對／有用／無用，填選用補充理由，顯示進度並以清單hash隔離瀏覽器暫存。點「匯出JSON」下載目前結果；未完成也可匯出，useful為null、reviewer及reviewed_at為null，不會冒充已審核。完成項目的reason採補充文字，未填則採畫面明示的有助回答／無助回答或主要無關。

匯出包含schema_version、原始核對清單SHA256、時間、核對者、complete、counts及逐項labels；每項綁定review_id、question_id、role、content_sha256。匯出不含問題或證據正文，不會自動寫入正式eval/labels.jsonl或放行4.9。原167項資料、順序、同名JSON及candidate設定綁定hash全部不變，沒有重跑模型或呼叫API。

驗證：新增測試先1 failed／1 passed，實作後相關15項測試通過；Ruff與格式檢查通過。以獨立暫存Chrome設定檔及3項合成資料完成9項瀏覽器操作檢查：初始待核對、空核對者阻擋、true／false／null三態匯出、理由、來源識別、不匯出正文、重載恢復、改回待核對、全部完成匯出。沒有以測試選擇修改正式人工標註。

## 人工標註收到與重算（2026-10-18）

使用者提供hr-rag-context-labels-2026-10-18.json，並明示判斷可能有誤、應視為可參考及複核的人工判定，不能當作絕對正確。原始檔逐位元組保存於context-labels-user-2026-10-18.json，SHA256為5b6711f197539f783fc3643dad1e7ee66fb6b4d91d05b11152d723037d9e34da。

核對清單hash、167個review_id／題號／角色／內容hash、bool型別、日期、核對者、理由及彙總均吻合；167完成、0漏項，75有用／92無用。原判定完整匯入eval/labels.jsonl，另附來源hash及human_judgment_revisable註記；以LabelStore逐項回讀核對一致，沒有自行更改任何選擇。

只替原retrieval-candidate.json的固定上下文補上人工分數，沒有重新執行檢索或生成。14個可回答題逐題精確度取算術平均：dense 71.79%、hybrid 61.79%、rerank 72.02%；權限題與D18–D20資料不足題仍保留標註，但不加入此14題平均分母。完整逐題分數、來源與標註hash見context-labels-assessment.json。這是依本次人工標註計算的估計，並非對判斷百分之百正確的保證。

另列兩項值得複核的差異，尚未判定一定是使用者錯誤：L035／D06被標無用，但內容明列以原申請紀錄查補件與處理狀態，以及不需揭露診斷、身分證號；L071／D11被標無用，但內容明列保留原申請、不另重提，依有效C01方式補件。這兩項也是既有必要證據組的命中來源，因此標為待複核，不由Codex改標有用。

4.9仍未通過：當前rerank人工精確度72.02%低於80%；不降低門檻、不利用保留題、不為達標改標註、不進階段5。前文「尚未標註／null」是收到此檔以前的歷史狀態，以本節為準。本次API呼叫與費用均0。

### 使用者複核更正：L035、L071

使用者明確指示兩項都改為有用。已在eval/labels.jsonl追加兩筆更正，保留原167筆及原始匯出；最新有效判定仍為167項，77有用／90無用。更正記錄含使用者、日期、來源對話、原判定及更正前標註檔hash；LabelStore回讀確認兩項均為true，其他165項不變。

固定原上下文重算：dense 74.64%、hybrid 64.64%、rerank 77.02%。分母仍為14個可回答題，Top-5與組裝命中不變；前述兩項必要證據組差異已解除。最新結果見context-labels-assessment.json，更正前結果另存context-labels-assessment-before-correction.json；可攜更正版匯出為context-labels-user-corrected-2026-10-18.json。

目前仍未達80%，4.9維持未通過；不進階段5。以上更正只依使用者明確指示，不代表人工判定絕對正確，仍保留可修正註記。本次沒有模型或API呼叫。


## 最終驗收：開發集改善達標（2026-10-18）

未變更eval/labels.jsonl、題目、金標、語料或門檻，未讀取保留題正文。590組分界搜尋不能單靠max_units與min_relevance同時達標，因此加入可關閉的假別範圍篩選。只排除單一假別問題中、非第一名且明確只規定不同假別的完整給假段；否定、混合程序、一般限制、跨法規引用與不確定句保留。這是開發集選出的規則，尚未用保留集驗證泛化。

| 模式 | Top-5完整命中 | 組裝完整命中 | 人工上下文精確度 |
|---|---|---|---|
| dense | 12/14 | 12/14 | 77.50% |
| hybrid | 11/14 | 11/14 | 66.55% |
| rerank | 13/14 | 13/14 | 81.79% |

三模式均版本3/3、授權錯誤0、執行錯誤0、待標註0。最終選rerank：77.02%→81.79%，完整證據仍13/14，4.9通過。主要提升是D04產檢假問題排除生理假及家庭照顧假規則；沒有把同主題段落重新標成有用。

凍結設定config/retrieval.selected.json：rerank、同義詞開啟、max_units=5、min_relevance=0.58、leave_scope_filter=true、whole-parent-v2／explicit-grant-v1；同檔包含完整OpenAI預算、設定及輸入／程式／實測報告hash。保留原candidate與歷史實測，不覆寫人工標註。

命令：`.venv/Scripts/python.exe -m hr_rag.evaluation --split development --mode all --corpus full --context-max-units 5 --min-relevance 0.58 --leave-scope-filter --output reports/retrieval-final-stage4.json`。本次三模式各26角色執行，全部使用真實本機embedding／reranker；不是回放分數。生成API呼叫0、費用0。

獨立審查2 Important已以7個先失敗後通過的反例修正；最終完整離線回歸336 passed／1 Windows symlink權限skip（244.66秒），Ruff及OpenSpec strict通過。人工標註沿用使用者已核對結果，不聲稱人工標註絕對正確；只是不能以總分未達標推論使用者太嚴格。第四階段完整通過，放行第五階段。


階段5補充重驗：生成提示與引用短ID傳輸只改序列化，78組實際排名重組後單位逐ID完全相同，rerank81.7857%與13/14保持不變；config/retrieval.selected.json已更新提示／組裝hash，詳見retrieval-stage5-final-prompt-recheck.json。原實測與人工標註檔保留。階段5已知失敗不回寫第四階段分數。
