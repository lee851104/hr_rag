# Spec Delta

## Purpose

讓查詢在有權且適用於指定日期的知識中找到完整證據，提供可比較的語意、關鍵詞混合與重排序結果；以人工標定的答案依據驗證效果，避免用文件數或看似流暢的生成文字代替檢索品質。

## ADDED Requirements

### Requirement: Versioned Chinese query normalization
系統 SHALL 保存原始問題，使用版本化的小型詞彙表處理已人工確認的同義詞，包含「特休／特別休假」；不得合併不同假別，並保留條號、數值、日期及否定條件。三種檢索模式共用同一前處理版本與查詢表示，不用保留題擴充詞表。處理後的查詢表示 SHALL 不超過 96 個 encoder tokens，讓重排時查詢與子片段合計不超過 512 tokens。

#### Scenario: Equivalent and distinct leave terms
- **WHEN** 使用只有「特休／特別休假」措辭不同的控制題，以及含「補休」「不是特休」的反例
- **THEN** 同義措辭取得相同的必要證據組，補休不被改寫成特休，否定條件不被刪除；報告記錄原始與處理後問題

#### Scenario: Query too long for the encoder
- **WHEN** 同義詞擴展後的查詢表示超過 96 個 encoder tokens
- **THEN** 回傳可理解的「問題過長」受控錯誤，不截斷查詢、不呼叫 embedding 或重排器

### Requirement: Bounded and traceable context assembly
系統 SHALL 在 Top-5 檢索後展開已授權父片段，依穩定規則去重及排序，保留各段來源對照，再以凍結的相關度篩選參數（最多單位數與相關度門檻，至少保留第一名）決定送入模型的單位，被篩掉的單位記錄原因。Top-5 命中在篩選前計分，組裝後命中與上下文精確度在篩選後計分。模型輸入加輸出保留額度及安全餘量不得超出模型上下文上限；不得截斷法律條件或例外來塞入預算。引用白名單僅包含實際送入模型的證據，不能引用因預算被移除的候選。

#### Scenario: Repeated parent and conflicting sources
- **WHEN** 多個子片段命中同一父段，另有不同來源或相互衝突的段落
- **THEN** 同一父段只出現一次；跨來源相同正文僅在來源類型、有效性與適用範圍一致時合併並保留來源對照，官方與公司規定及衝突內容不互相覆蓋

#### Scenario: Budget cannot retain a complete rule
- **WHEN** 測試以小預算使一段完整條文及其例外無法容納
- **THEN** 整個證據單位移除並記錄原因；無足夠證據時回覆資料不足，不輸入殘缺規則或超限請求；另計組裝後證據完整性，不以父段展開改算 Top-5 成績

#### Scenario: Relevance filter removes noise
- **WHEN** Top-5 去重後有 4 個父段，其中 2 個低於凍結的相關度門檻
- **THEN** 只送入其餘 2 個單位，被篩掉的單位與原因記入 dropped_reasons 且不在引用白名單；Top-5 命中仍以篩選前結果計分，若篩掉必要證據則組裝後命中記為失敗

#### Scenario: Explicit different leave category
- **WHEN** 開啟凍結的假別範圍篩選，問題明確詢問單一假別，而後續候選正文明確給予另一假別且與問題假別沒有交集
- **THEN** 可排除該完整單位並記錄leave_scope_mismatch；第一名仍依既有規則保留，授權與預算優先。無明確假別、否定／比較、多假別、一般限制或法規交互引用等不確定情況保守保留。篩選不得使用題號、文件ID、金標證據組或人工標註，也不得回填答案；開發集完整證據與80%精確度門檻不變

### Requirement: Date scoped retrieval
系統 SHALL 依明確查詢日期選取有效版本，未指定時使用 Asia/Taipei 當日並顯示日期。官方資料未覆蓋所問日期時不得假設目前版本在當時有效；無效日期拒絕，問題日期與欄位日期衝突時要求釐清。第一版只辨識問題中明確的西元或民國絕對日期；「今年」「明年」等相對說法依查詢日期解讀，不判為衝突也不推算成另一個查詢日期。

#### Scenario: Missing historical evidence
- **WHEN** 詢問某法規歷史時點，而索引只有現在的快照且無適用證據
- **THEN** 回覆缺少該日期的資料，不用目前版本替代

#### Scenario: Explicit ROC date in the question
- **WHEN** 查詢日期為 2026-10-18，問題寫「民國115年9月30日當天適用哪個申請窗口」
- **THEN** 系統辨識為 2026-09-30，與查詢日期不同，要求使用者釐清並同時顯示兩個日期，不自行擇一檢索

### Requirement: Comparable retrieval modes
系統 SHALL 提供純向量、BM25 與向量混合、混合加重排三種評估模式。三者使用相同文件版本、切片、角色與查詢日期；只有檢索方法改變。排名相同時採固定次序，以利重現。

#### Scenario: Controlled comparison
- **WHEN** 使用同一評估集執行三個模式
- **THEN** 報告包含各模式 Top-5 證據命中、耗時與逐題差異，不宣稱混合或重排必然比較好

### Requirement: Preserve complete supporting evidence
系統 SHALL 保留回答必需的例外、條件與跨文件證據；父段落展開也要套用權限與時間規則。評估以原始版本的段落定位標定，不以易變的切片 ID 當唯一標準答案。

#### Scenario: Cross document question
- **WHEN** 問題同時需要官方規定與公司申請流程
- **THEN** 檢索結果提供兩組有效且已授權的證據；缺任何必要證據時不得宣稱完整回答

### Requirement: Retrieval acceptance gate
系統 SHALL 在 22 道可回答題中至少 20 題於前 5 個檢索片段涵蓋全部必要證據組，且保留集中 8 道可回答題至少 7 題命中；每題同組可接受的替代段落任一命中即可。4 道版本題必須全部使用正確版本，未授權片段與錯誤有效區間片段均為零。開發集與保留集分開報告。

#### Scenario: Averages cannot hide leakage
- **WHEN** 總命中達標但其中一題出現無權或失效片段
- **THEN** 驗收不通過，必須修正後重跑受影響測試及完整安全回歸


### Requirement: Compound clause reranking
模式C SHALL 保留完整查詢，並對「以及」後最多兩個至少6字的子句重排同一批至多20候選，取最大分排序後仍只取top5。每次送入重排器前重驗權，不用題號或金標決定分數，生成問題不改寫。

#### Scenario: Secondary clause evidence
- **WHEN** 完整問題包含另一個明示並列要點
- **THEN** 可由該子句提高直接證據排序；原日期與否定保留，無效分數受控失敗，仍通過原完整證據及80%人工精確度門檻
