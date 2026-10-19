# Spec Delta

## Purpose

將檢索到的證據轉成可人工核對的繁體中文答案，明確分開官方依據與虛構公司流程，讓使用者能從每項關鍵結論回到來源；證據不完整、相互衝突或不在權限範圍時，不以模型常識填補缺口。

## ADDED Requirements

### Requirement: Stable evidence based responses
系統 SHALL 在固定問題、角色、日期、資料與模型設定下保持關鍵主張及回答狀態一致；不要求文字逐字相同。對預先選定的 6 個開發案例各獨立執行 3 次，涵蓋官方、公司、跨文件、版本、權限與資料不足，不能出現相互矛盾的資格、日數、流程、版本或拒答行為。

#### Scenario: Three independent requests
- **WHEN** 以最終設定對固定 6 案例各發出 3 次不共用答案快取的請求
- **THEN** 18 次執行均符合各案例預期，關鍵主張無矛盾且通過引用與授權檢查；模型錯誤不能作為穩定拒答通過，報告不把重複執行算成新增獨立題

### Requirement: Grounded and labeled claims
系統 SHALL 以繁體中文回答，每項影響請假資格、日數、薪資或流程的關鍵主張附上支持它的引用；引用顯示文件名稱、來源類型、版本、條號或章節及有效日期。模擬公司內容必須標示虛構。伺服器 SHALL 以鎖定版本的繁簡字表檢查生成的主張與原因文字，含簡體專用字時不展示該答案。

#### Scenario: Official plus company process
- **WHEN** 同時引用法規與 C02 申請流程
- **THEN** 答案分別標示官方依據與模擬公司流程，引用可開啟對應原文，不把內部流程描述成法律要求

#### Scenario: Simplified Chinese output
- **WHEN** 生成的主張含簡體專用字（例如「请假」「规定」）
- **THEN** 回傳受控的輸出格式錯誤並記錄原因，計入錯誤率；不自動轉換後當成通過

#### Scenario: Compact citation transport
- **WHEN** 最終授權上下文的來源識別碼過長
- **THEN** 系統 MAY 使用單次請求內唯一短ID，SHALL 只將實際送出ID白名單中的引用還原到原始來源；原始未送ID與未知ID均拒絕，還原後重新驗權，不將對照表或身分資料送往外部

### Requirement: Unsupported and conflicting answers
系統 SHALL 對證據不足回覆「目前可用資料不足以回答」並說明缺少的非敏感資訊；有部分支持時只回答有支持部分。來源衝突不得自行混合成確定結論，應列出已授權的衝突來源並標記待人工核對。

#### Scenario: Personal remaining leave
- **WHEN** 使用者問自己還剩多少天特休，而沒有個人假勤資料
- **THEN** 回覆資料不足，不捏造天數或聲稱查到人事紀錄

#### Scenario: Conflicting company rule
- **WHEN** 測試資料的公司規定與官方依據產生明顯矛盾
- **THEN** 顯示衝突待核對，不選擇較高相似度的片段就當成正確制度

### Requirement: Treat retrieved instructions as data
系統 SHALL 將文件及使用者輸入視為不可信內容；文件中的「忽略規則」「改用 HR 角色」等文字不得改變權限、系統提示或可用來源。生成引用識別碼必須存在於本次授權證據集合。

#### Scenario: Document injection and invented citation
- **WHEN** 文件夾帶要求揭露限閱資料的指令，或模型輸出不存在的引用
- **THEN** 指令不起作用；不合法引用的回答不直接展示，回傳受控失敗或資料不足並記錄原因

### Requirement: Controlled external generation
系統 SHALL 以 OpenAI API 生成答案，只送出系統提示、使用者原始問題與本次最終上下文單位，不送使用者識別碼、帳號、角色名稱或 session。只允許 https://api.openai.com/v1 端點；API 金鑰只從環境變數或不入版控的設定讀取，不得出現在日誌、稽核、報告或錯誤訊息。每次呼叫 SHALL 記錄 response id、實際模型 ID、token 用量與成本估算；累計成本達設定上限時停止呼叫。自動測試預設使用假 client，不連網也不需金鑰。

部署預設 SHALL 使用0.9依可行性實測凍結的模型快照、token預算、逾時、重試及價格。使用者必要時授權的Luna候選仍須查證與驗證，不得自動改模型或繞過累計成本上限；更換模型不得靜默沿用其他模型的價格。

#### Scenario: Missing API key
- **WHEN** 未設定 OPENAI_API_KEY 就提出問題
- **THEN** 回傳可理解的「生成服務未設定」受控錯誤與查詢識別碼，不呼叫外部服務，不顯示堆疊

#### Scenario: Load local generation settings
- **WHEN** 使用者在專案根目錄不入版控的 `.env` 填入 OPENAI_API_KEY 與 HR_RAG_COST_LIMIT_USD，並從其他工作目錄啟動程式
- **THEN** 系統 SHALL 自動讀取該固定檔案，既有環境變數優先；不輸出、記錄、寫回或快取金鑰，不展開shell／變數，也不從檔案啟用真實API測試或更換端點；檔案格式錯誤只回傳固定受控錯誤

#### Scenario: Cost limit reached
- **WHEN** 累計估算成本已達 HR_RAG_COST_LIMIT_USD
- **THEN** 不再發出生成請求，回傳受控錯誤 cost_limit 並記錄於事件日誌；評估執行停止並保留已完成結果，不把未執行題當通過

#### Scenario: Rate limit or server error
- **WHEN** OpenAI API 回傳 429 或 5xx
- **THEN** 依凍結設定有限次重試並退避；仍失敗時回傳受控錯誤並計入錯誤率，不回傳捏造答案

### Requirement: Minimal demonstrable interface
系統 SHALL 提供登入、單輪提問、選填查詢日期、答案與原文引用檢視；顯示目前角色與資料快照資訊，預設僅綁定本機位址。介面 SHALL 標示答案由外部模型依引用證據生成，並提醒使用者不要輸入個人資料。模型逾時、空結果與無效輸入有可理解的回應，不顯示堆疊或金鑰。

#### Scenario: Model unavailable
- **WHEN** 生成服務逾時或失效
- **THEN** 顯示暫時無法生成及查詢識別碼，不回傳捏造答案，其他請求仍可處理

#### Scenario: Role sample questions
- **WHEN** 已登入使用者開啟提問頁
- **THEN** 只列出目前角色的兩題示範問題（取自開發集、不含保留題或明確日期），點選只填入問題而不送出；查詢日期預設為當天（Asia/Taipei），使用者可自行調整；猜測其他角色的示範題ID不會顯示其內容


### Requirement: Specific process identity support
系統 SHALL 要求特定流程、表單名稱與識別碼有直接證據對應；不得把一般申請或補件資訊推測成不同特殊流程。

#### Scenario: General evidence cannot identify a special form
- **WHEN** 問題詢問特定表單與欄位，但可用證據僅含一般流程
- **THEN** 回覆insufficient，只列有直接支持的一般原則，不猜測表單名稱或代碼

具名表單安全補充：查詢明示詢問表單名稱／識別時，已授權上下文若沒有直接的表單代碼或具名使用敘述，伺服器回資料不足並移除模型猜測。此為必要條件，不聲稱通過即語意正確；仍須人工支持率與完整覆蓋驗收，不讀題號、角色金標或無權來源。

### Requirement: Server derived citation union
系統 SHALL 從模型逐項主張的citation_ids建立對外引用清單，且只接受本次送出來源；不讓模型另外維護頂層引用聯集。

#### Scenario: Empty supported claims
- **WHEN** 模型回覆insufficient並提供空claims及原因
- **THEN** 對外Answer.citations為空，不產生無所屬引用

#### Scenario: Unknown claim or obsolete duplicate summary
- **WHEN** 逐項主張包含未送出來源，或模型輸出舊頂層citations欄位
- **THEN** 嚴格拒絕輸出，保留已使用費用與原始受限紀錄，不靜默修補錯誤

### Requirement: Verbatim evidence selection candidate
系統的原文候選模式 SHALL 只從本次已授權證據選取完整段落並附來源，不以模型文字取代原文，也不以輸出全部上下文替代必要答案驗收。

#### Scenario: Selected paragraph preserves limitations
- **WHEN** 原文模式選中含程序、例外或計算時點的段落
- **THEN** 伺服器保留該段全部文字及正確引用，仍檢查是否真正回答問題與當前來源權限

原文候選v2：為解析正文對其他文件／版本／條文的參照，只為本次已授權上下文另送document_id、version_id、section_id三欄來源標示；不送角色、user_id、帳號、session、路徑或未入上下文的文件資訊。三欄一併計入evidence_budget及完整payload預算。摘要模式仍維持id與正文。允許明確被所問規則準用的其他規定，但不得將不同假別的規則直接混用。

原文候選v2的參照補充由程式執行：模型選段後，只在同一已授權上下文中，補上明示參照文件及具名假別規定的現有完整段落；來源去重、有限閉包、不查上下文外文件。補入段落標記「參照補充」，引用仍經原白名單及當前權限檢核。否定參照不展開，文件代號邊界精確匹配；僅作保守字面依賴補充，不宣稱能完整解析所有法律準用關係。未降低語意／引用支持／完整性驗收。


原文候選v3補充：來源標示以source=[document_id, version_id, section_id]及緊湊JSON傳送，全部計入原2048證據／4096上下文預算，不提高限制。每次請求schema的source_ids採實際送出引用別名的enum，避免文件代號被當成引用ID；本機仍拒絕重複及未知ID。組裝與請求共用build_verbatim_payload計數。明示參照不得跨逗號或否定詞補入排除來源，新增否定範圍回歸；完整原文不等於語意完整，仍須原5.4／5.5人工門檻。
