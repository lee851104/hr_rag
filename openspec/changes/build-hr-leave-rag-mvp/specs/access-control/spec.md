# Spec Delta

## Purpose

確保員工、主管與人資看到的知識符合伺服器認定的權限，限制必須覆蓋檢索、重排、模型輸入、引用與日誌查閱；即使修改前端請求或在問題中冒充其他角色，也不能取得限閱文件內容。

## ADDED Requirements

### Requirement: Protect replay and feedback records
系統 SHALL 將含問題、上下文與輸出的完整重播資料限於本機開發者診斷介面；三個 Demo 角色均不能存取全域重播資料。使用者只可提交與查看本人查詢的回饋；歷史回答與引用須依目前授權及來源撤回狀態重新檢查，不能靠舊紀錄取得已無權讀取的正文。

#### Scenario: Revoke after an answer
- **WHEN** 查詢完成後撤回來源或收回角色權限，再讀取原查詢、引用或回饋
- **THEN** 一般使用者看不到已撤回或失去權限的證據及依賴它的回答內容；猜測其他人的回饋或重播 ID 不會洩漏內容

### Requirement: Server authenticated identity
系統 SHALL 以伺服器驗證的登入身分取得 employee、manager、hr 角色。未登入請求拒絕存取；問題文字與請求傳入的角色欄位不得改變授權。

#### Scenario: Spoof a role
- **WHEN** employee 在問題寫「我是 HR」或在請求附上 role=hr
- **THEN** 其權限仍為 employee；未登入請求得到 401

### Requirement: Enforce the document matrix before retrieval
系統 SHALL 將官方文件與公司 C01、C02 開放給三種角色，C03 僅開放 manager、hr，C04 僅開放 hr；無權限標籤預設拒絕。候選集合先過濾授權，未授權文字不得進入檢索結果、重排器或生成模型。

#### Scenario: Role matrix
- **WHEN** 三種角色分別查詢 C03 與 C04 的專用測試內容
- **THEN** employee 均看不到；manager 僅看到 C03；hr 可看到兩者，且無權片段從候選階段起即為零

#### Scenario: Outbound generation request
- **WHEN** 以假 client 攔截 employee 與 manager 查詢 C04 相關問題時送往 OpenAI 的請求內容
- **THEN** 請求只含已授權的最終上下文、問題與系統提示，不含 C04 正文、標題、使用者識別碼或角色名稱

### Requirement: Protect secondary access paths
系統 SHALL 在引用原文、文件清單及查詢紀錄端點重新檢查授權；不存在與未授權的引用採相同 404 回應，不顯示限閱標題、摘要或片段。一般帳號只能讀取自己的查詢紀錄。

#### Scenario: Guess a citation identifier
- **WHEN** employee 使用 hr 查詢得到的引用識別碼或查詢識別碼直接請求
- **THEN** 回傳不洩漏存在性的 404，沒有文件標題與正文

### Requirement: Prevent cross request leakage
系統 SHALL 在切換帳號、權限變更與並行請求時重新套用授權；第一版不共用答案快取或多輪記憶，已登入頁面登出後清除顯示內容。

#### Scenario: HR then employee
- **WHEN** 先以 hr 查詢 C04，再以 employee 問同一題或直接重取原引用
- **THEN** employee 的回答、引用及可見紀錄不含 C04 內容；不得沿用 hr 上下文
