# 階段3執行紀錄

2026-10-18。使用者確認S01～S20全部通過後，核對generation及manifest hash，已記錄階段2人工簽核並完成2.5。使用openspec-apply-change與executing-plans原地執行既有計畫；此資料夾沒有Git，不建立額外repo或提交。

Ruling: 首次建立employee／manager／hr三帳號時停用登入，以未知隨機值的scrypt雜湊佔位；本機`python -m hr_rag.auth init`以getpass設定後啟用。不提供公開預設密碼、不寫明文密碼、不將API金鑰當登入密碼。這是部署設定，不降低三角色驗證門檻；測試以獨立合成密碼驗證全部帳號。

Ruling: session只存token／CSRF的SHA256，八小時到期；登入輪替，登出或改密碼撤銷。角色每次JOIN伺服器users表，不複製到session。CLI管理可信，不提供網頁角色管理API。

Ruling: 引用與eligible_chunks直接讀active SQLite世代及撤回表，先驗ACL／日期再輸出正文；不載入整份向量快照。Principal為伺服器內部信任邊界，HTTP不能傳入或建立Principal。呼叫端每個新請求必須重新authenticate，不能跨請求沿用Principal或候選。

Ruling: 日期衝突檢查為純函數，查詢端點依原計畫留待階段6；函數不改寫as_of。相對日期不推算，缺或無效ACL與未知生效日期預設拒絕。

3.1 dependencies: 新增uvicorn0.53.0、python-multipart0.0.32，解析新增click8.5.0；原有版本完全保留。Torch只保留官方cp312 Windows CPU wheel SHA256。新.venv-stage3-verify以--require-hashes安裝64套件並pip check通過；開發venv同樣pip check通過，恢復editable安裝。

3.1–3.6 RED: 首次新增三個測試檔，因auth／policy／citations模組不存在出現3個collection error。實作後29 passed。追加兩個邊界RED：Unicode CSRF字串引發TypeError、未登入且缺日期被FastAPI提前回422；修正為403／401，已加入回歸。另驗session輪替、CSRF跨session／重播、預設帳號停用、loopback綁定、HTTP雙帳號並行。

待最終全suite、Ruff、OpenSpec strict與獨立整體審查後完成3.5驗收；第四階段仍以1.4／1.5保留題格式、摘要及hash凍結為前置門檻。未讀保留題正文或.env，沒有呼叫生成API。


獨立審查：review_stage3_final完成一次整體審查，無Critical；兩項Important為年資誤判及空格日期漏判。新增11案例，先重現10 failed／1 passed，再以期間語意辨識與日期組件空白支援修正，policy全31 passed；同樣31項在全新venv通過。沒有再派第二輪審查。原先全suite268 passed／1 skip（203.15s）記錄保留，修正後全suite執行中，不以舊結果代替。

Ruling: 期間語意（任職／工作／年資／滿等，以及年資後綴）不是曆年；明示民國或ISO格式仍視為絕對日期。支援日期數字與年月日之間空白，避免只匹配年份而忽略月日。

3.1／3.2／3.3／3.4／3.6已完成；3.5待最終全suite及本階段測試回報後勾選。乾淨venv新增35 passed／1昂貴匯入案例deselected（54.54s），該匯入案例在開發venv完整36項測試中通過。真正uvicorn CLI啟動GET /login 200，含登入表單與no-store，測完已停止本次process，未影響其他服務。正式.runtime/auth.sqlite3已建立三帳號，尚未由使用者設定密碼，均停用。


最後日期邊界：期間辨識不能遮蔽四位西元年／完整年月日。兩例先2 failed後修正；完整stage3命令49 passed(23.54s)，乾淨venv policy33 passed(0.55s)。Ruff及OpenSpec strict通過。前一版全suite279 passed／1 skip(164.19s)保存為歷史，最後兩例修正後全suite重新執行；以最新結果作最終驗收。

Final acceptance: 最新全suite281 passed,1 symlink skip,1第三方棄用warning(140.69s)，stage3 49 passed(23.54s)，Ruff、全新venv及OpenSpec strict通過。完成3.5，階段3驗收通過，進度25/55；未執行階段4，保留1.4／1.5完整門檻。無新增API呼叫或費用。
