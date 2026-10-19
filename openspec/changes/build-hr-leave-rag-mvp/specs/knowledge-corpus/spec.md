# Spec Delta

## Purpose

提供有來源、可追溯且可依時間判斷有效性的繁體中文請假知識，讓後續檢索與引用建立在人工核對的文件上；同時區分主文件與歷史版本，避免文件數量、法規日期及虛構公司規定被混為一談。

## ADDED Requirements

### Requirement: Assigned document maintenance
系統 SHALL 為每份主文件保存來源發布單位、專案維護負責角色、最後核對日與下次核對日；官方發布單位不等於專案維護者。到期項目列入本機待核對清單，只有內容或有效性完成核對才更新紀錄，不假稱已自動同步來源。

#### Scenario: Review becomes due
- **WHEN** 以指定檢查日期執行清單檢核，某文件已到下次核對日
- **THEN** 列出文件 ID、負責角色及核對原因；10 份文件均有負責角色，缺漏者不得通過資料驗收

### Requirement: Incremental embedding reuse
系統 SHALL 在相同模型與切片設定下重用未變更片段的向量。完全相同資料重匯入不呼叫 embedding；僅 ACL 或有效期改變時更新中繼資料而不重算向量。模型或切片設定改變須明確記錄全量重建原因，增量發布仍遵循原子切換與失敗回復。

#### Scenario: Change one existing document
- **WHEN** 在隔離測試快照只修改 C02 正文並重匯入
- **THEN** 只對新增或文字改變的片段呼叫 embedding，其餘 9 份主文件的片段 ID 與向量不變；刪除片段不得殘留在任何檢索路徑

#### Scenario: Metadata only update
- **WHEN** 測試快照只修改一個文件的 ACL 或有效日期
- **THEN** embedding 呼叫數為零，發布後所有檢索、父片段展開及引用查閱立即遵循新限制

### Requirement: Fixed and attributable corpus
系統 SHALL 收錄清單中 6 份官方與 4 份模擬公司主文件，使用 10 個穩定文件識別碼；公司辦法另存 1 個歷史版本。官方文件保留網址，模擬文件顯示虛構標示；相同內容的 HTML 與 PDF 不得重複計為主文件。

#### Scenario: Count and provenance
- **WHEN** 完成第一版資料驗收
- **THEN** 清單含 10 個主文件、11 個初始版本，每個版本均有原始檔、來源類型、內容雜湊及人工核對紀錄

### Requirement: Separate dates and effective intervals
系統 SHALL 分別保存發布日、修正日、生效日、失效日與擷取時間；未知日期為空並附原因，不得以擷取日推定生效日。版本有效區間為含起日、不含迄日；同一文件不得有重疊的有效版本。法規不同條文施行日不一致時 SHALL 在條文層記錄，依據施行條款與法規沿革人工核對。來源的民國紀年日期 SHALL 轉為 ISO 8601 西元日期並保存原始字串；主管機關問答沒有生效日時，以問答發布日期作為生效起日並註明不是法規生效日，網站頁尾更新日不得當成文件日期。

#### Scenario: Transition boundary
- **WHEN** 模擬辦法 v1 的失效日與 v2 的生效日同為 2026-10-01
- **THEN** 2026-09-30 查詢只使用 v1，2026-10-01 查詢只使用 v2

#### Scenario: Unknown effective date
- **WHEN** 待匯入資料無法確認適用時間
- **THEN** 內容保留於待核對區，不進入可回答的有效索引，並列出待核對原因

#### Scenario: ROC calendar dates
- **WHEN** 法規頁顯示「修正日期：民國 113 年 07 月 31 日」，或條文寫「自一百零六年一月一日施行」
- **THEN** 分別記為 2024-07-31 與 2017-01-01，date_evidence 保存原始字串；不合法或無法解析的民國日期進入待核對，不猜測

#### Scenario: Interpretive Q&A without effective date
- **WHEN** 勞動部問答頁只有發布日期 2025-07-07 與項目更新日期 2026-04-23
- **THEN** effective_from 為 2025-07-07 並註明依發布日期；更新日期經人工確認內容變動才記為 revised_at；查詢日期早於 2025-07-07 時該問答不提供證據

### Requirement: Preserve evidence structure
系統 SHALL 保留法規條號、項款、章節、問答配對與引用定位；切片繼承來源、版本、有效區間與權限，不得切斷必要例外而改變原意。每個子片段 SHALL 分別以實際 embedding 與 reranker tokenizer 計數，兩者均不超過 400 tokens，讓 embedding 與重排（查詢加片段共用 512 tokens）都不需截斷；超過時依項、款、段落拆分，由父片段保證條件完整。

#### Scenario: Trace a chunk
- **WHEN** 取得任一可檢索片段
- **THEN** 能回到唯一原始版本及證據位置，查看完整條文或問答；人工檢查至少 20 個片段且涵蓋全部 10 份主文件，定位與文字均一致

#### Scenario: Article longer than the encoder limit
- **WHEN** 一條含多項與例外的條文或一則問答超過 400 個 encoder tokens
- **THEN** 依項、款或段落拆成多個子片段，全部共用同一父片段；任何子片段都不被截斷，單一句子仍超限時標記待人工處理而不進入有效索引

### Requirement: Repeatable and recoverable ingestion
系統 SHALL 對相同版本重複匯入保持片段數與識別碼不變；新版未完成解析、檢核及索引前不得取代可用版本。更新與撤回必須同步作用於所有檢索路徑。

#### Scenario: Failed update
- **WHEN** 新版索引建立失敗
- **THEN** 現有可用版本保持完整，錯誤有紀錄，重試不產生重複片段

#### Scenario: Withdrawn source
- **WHEN** 管理者撤回一個來源版本
- **THEN** 該版本不再出現在一般查詢結果或可開啟的引用中，其他文件仍可使用
