# 階段5執行紀錄

前置：階段4.9實測81.79%、13/14、版本3/3、授權0，336 passed／1 skip；36/55。沿用openspec-apply-change與executing-plans，沒有Git，原地TDD。

介面檢查：Answer沒有來源metadata欄位，因此來源詳細資訊由citations受權端點依ID取得，主張加伺服器可信的官方／虛構公司標示；不把角色／帳號送往模型。引用只接受本次ContextBundle.units ID，生成前後重驗。未支持／衝突語意由模型及人工評估核對，不將ID驗證冒充語意驗證。

使用者既有授權：沿用.env，累計硬上限US$1，不展示或記錄金鑰；不讀保留題正文，只用20開發題及既有6案例。人工語意核對產生待核對檔，不能代簽使用者。

5.1–5.3離線實作：先出現缺少answering模組collection error，再17 passed；個人餘額與未受控例外新增2 failed後修正，含注入／政策／provider回歸99 passed。繁簡字表opencc-python-reimplemented 0.1.7，wheel SHA256已核對並鎖入requirements.lock，STCharacters字表SHA256 9207708da9f2e2a248f39c457b2fccad26ec42e7efaf47a860e6900464f4cac5；保留本來也合法的后／里／干等歧義字，不自動轉換。全新.runtime/stage5-lock-venv --require-hashes完整安裝與pip check通過，Torch單一hash不變。

第五階段獨立審查review_stage5：0 Critical、3 Important。預設生成器漏傳OpenAISettings先1 failed後修正；個人餘額常見改寫、reason無引用事實通道新增5 failed後修正。模型reason仍做簡體檢查，但展示只用伺服器固定說明，所有事實須走有引用claims；不是把ID驗證當語意正確。語意評估保持human_review_pending，不代簽使用者。

評估入口只接受development／stability，固定26與18次分母；6案例hash對應完整Question排序精簡JSON，並驗證角色／日期／預期相同。初次啟動失敗在API前，費用仍0.0332040；修正後開始development-run1，詳細輸出限目前Windows使用者與SYSTEM，未讀保留題正文。

真實API診斷：run1共26次，13 answered／13 error；run2共26次，17 answered／2 error／7 insufficient。錯誤原樣保留且計入分母。已依官方教育部簡編本確認「雇」為合法繁體（https://dict.concised.moe.edu.tw/dictView.jsp?ID=16833&la=0&powerMode=0），修正OpenCC轉換偏好誤當專用字的誤判；先1 failed後通過。提示改為同來源結論合併、恰列引用聯集、沒有支持則空清單與不足狀態，未更改模型或token預留。

第二輪D10及D15/employee仍因輸出512上限截斷；長來源hash重複多次耗用額度。加入short-id-v1：只傳本次唯一短ID，provider先驗原始模型短ID白名單再還原原來源，AnswerService再驗上下文與當前授權；未知ID及原始未送ID均拒絕。2個協定測試先2 failed，修正後provider／上下文／回答／注入99 passed。同步proposal／design／spec／tasks且strict通過；78個三模式上下文重組完全相同，81.79%及13/14不變，設定hash更新，沒有重標任何資料。獨立審查先前3項修正通過；短ID新增協定以安全回歸另驗，沒有冒稱已經過先前審查。

新增答案核對頁，先collection error後單測通過；獨立Chrome合成資料4項瀏覽器檢查通過：初始pending、null匯出、true/false與complete、匯出不含答案或證據正文。核對頁不更改eval/labels.jsonl，不代簽人工語意。

最終記錄：完整372 passed／1 skip；最終提示受影響模組103 passed，補充衝突fixture後35 passed。4輪開發104次＋穩定18次，stage5估算0.0872516，全專案0.1204556／132次／預留0。最終開發狀態25/26、穩定狀態18/18，但D09漏O04/21且誤套病假規則，D15/employee狀態不符，因此5.4／5.5不通過，未進6。人工語意仍pending，原labels SHA256完全不變；5.1–5.3勾選後39/55。


## D09／D15修正續作
- 使用者授權：只調開發題、不改既有標註及門檻、API累計≤US$1，第五階段通過才進第六。
- 根因：D09全題重排O04/21第9（0.38035），獨立不利處分子句第1（0.99488）；D15員工錯把一般補件推測成特殊覆核識別。
- Ruling: 保留既有top20候選，對明示「以及」並列的最多兩個子句補算重排並取最大值；全文保留，數字／否定不刪，生成仍收原問題。這是開發集的召回修正，不擴大候選、門檻或送出權限。
- RED: 新增3項複合查詢／授權／無效子句分數測試，全部如預期失敗。
- 使用者另行確認D09/O04/21有用，允許另存新增標註；原eval/labels.jsonl不修改。

- GREEN: 複合重排／新增標註隔離／評估33項通過；三模式實測rerank14/14、82.142857%、版本3/3、無權0、待標註0。
- D15兩輪提示診斷各5次（員工3、主管1、人資1），員工皆仍猜表單；不將提示修正誤標成功。第二輪只在隔離診斷程序調提示，未變正式提示。
- Ruling: 以具名表單缺少直接證據的必要條件做保守拒答；不把文件代碼當表單身份。不以題號／角色／金標硬指定結果，不提供未知欄位內容；具名證據存在仍須模型與人工語意檢查。
- RED: 3個合成不同流程問題＋具名/一般流程區分4項如預期失敗。


### 2026-10-19 獨立審查修正
- 審查0 Critical／1 Important：原表單名稱檢查將附件／欄位等一般提問誤拒，也不認得「表單名稱：…」與空白代碼格式。5項補充測試RED確認後，縮小到明示名稱詢問、支援兩種明確表示；不放寬原驗收門檻。
- Minor中途撤權新增回歸測試，第二子句不送入撤回內容；測試通過。
- v1開發實測26/26完成，18 answered／8 insufficient，狀態全符且D09引用補齊、D15員工受控資料不足；保存原輪，不當作最終程式驗收。
- v1完整離線381 passed／1 Windows skip；v2需另跑含新增審查案例的完整回歸。


### GPT-4.1候選比較（使用者明確同意）
- mini修正後狀態全對，但內容仍有D08遞延計薪時點錯誤，以及直接適用程序/例外省略；未以狀態冒稱答案通過。
- 使用者2026-10-19明確同意測gpt-4.1-2025-04-14，累計仍限1美元。官方模型頁查證單價input2/output8美元每百萬tokens、快照、Responses與Structured Outputs支援；停用日仍2027-01-14。
- 第一輪新0.8內容5/5、自動內容檢查5/5、耗時全過，但與其他API診斷並行使舊成本彙總以全域預留差值計算而出現負值。此輪不得宣稱成本門檻通過；原帳本仍正確且未重設，需在無其他API程序時以最終提示重跑0.8。
- GPT-4.1隔離提示比較只使用D05/D07/D08/D09/D15既有授權上下文。提示要求保留直接適用的程序、例外與計算時點，不注入題號/金標/保留題，不改原模型預算。

- GPT-4.1五輪各5次提示診斷仍有程序/例外省略，未選為正式模型。候選採第4輪提示，獨立保存config/generation.gpt41-candidate.json，重跑固定F1–F5、三模式4.9、26次開發與18次穩定性。正式mini設定不變，不把候選hash誤稱正式凍結。
- Luna可用性查證：官方模型頁僅列gpt-6-luna，未提供日期快照；本機已鎖tiktoken 0.14.0無gpt-6映射，不能擅自假設tokenizer。此輪未呼叫Luna、未增加其費用。來源：https://developers.openai.com/api/docs/models/gpt-6-luna 。
- 最終D09/D15修正離線全套387 passed／1 Windows symlink skip（243.79秒），reports/stage5-fixes-final-tests.xml；Ruff --no-cache及OpenSpec strict通過。

- GPT-4.1順序重驗0.8：固定5題自動5/5、繁體全過、全部低於60秒；P50 11.0992秒、P95 18.684秒，估算US$0.034908、預留0。Codex依原證據核對F1–F5未發現所問核心錯誤（非使用者人工簽核）。候選續跑4.9與完整5.4/5.5。

- GPT-4.1三模式重新實跑4.9：78個上下文的有序ID與mini修正後完全相同；rerank14/14、82.142857%、版本3/3、授權/執行錯誤0。
- 候選答案批次輔助腳本缺Windows spawn入口守衛，子程序重入導致API前失敗；原development/stability-gpt41-candidate.json保留（0 API費用，不排除失敗紀錄）。補__main__守衛後另跑candidate-v2，未變正式實作、題目或候選設定。

- 完整GPT-4.1候選26＋18次完成：開發25/26狀態（D18空claims但附e1受控錯誤），穩定18/18狀態但D05三次漏緊急通知，未通過。全專案291次／US$0.5415252／預留0，全部失敗費用與原帳本核對一致。正式mini未切換，39/55不變，未進6；詳細與初查／核對頁見stage-5-fixes.md。
