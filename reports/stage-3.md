# 階段3：身分、權限與有效候選集合

2026-10-18。**第三階段3.1～3.6驗收通過。** 最終回歸281 passed／1 Windows symlink權限skip（140.69s）；本階段49項全部通過，獨立審查的重要問題已修正。第二階段S01～S20已由使用者確認通過；簽核及對應索引hash保存於stage-2-artifacts.json。

| 角色 | O01～O06、C01、C02 | C03 | C04 |
| --- | --- | --- | --- |
| employee | 可讀 | 拒絕 | 拒絕 |
| manager | 可讀 | 可讀 | 拒絕 |
| hr | 可讀 | 可讀 | 可讀 |

角色矩陣仍須同時符合片段有效期、現行ACL及未撤回條件；更新只能縮限初始文件ACL。未知日期／缺ACL預設拒絕。歷史版本含起日、不含迄日，parent引用同樣驗權。

## 實作

- auth.py：三個伺服器示範帳號、scrypt隨機salt密碼雜湊、隨機session／CSRF只存hash、8小時期限、登入輪替／登出失效／改密碼撤銷、每次驗證取得現行角色。初始帳號未啟用；使用者在本機終端設定密碼後才可登入，沒有公開預設密碼。
- policy.py：每次查SQLite active世代與撤回表，過濾後才回傳Chunk；無共享候選或上下文快取。明確西元／民國日、月、年和as_of不符時回傳含兩者的釐清訊息；相對日期不視為衝突，無效日期要求釐清。
- citations.py：子／父片段引用均重新驗ACL、日期、withdrawals；缺片段、無權、撤回皆相同錯誤。
- web.py：GET/POST /login、GET /session、POST /logout、GET /citations/{id}?as_of=YYYY-MM-DD。HttpOnly／SameSite=strict cookie、登入一次性CSRF與登出CSRF、Origin／Host檢查、no-store、禁止外框及腳本。只綁定127.0.0.1:8000，關閉proxy headers及access log。HTTP本機cookie不設Secure，不能當作遠端HTTPS部署配置。
- 沒有註冊、角色切換或查詢／模型端點。一般HTTP請求無法傳入Principal；問答、檢索、重排器及生成防線依原計畫於後續階段接入，不能把本階段測試稱為完整RAG端到端驗收。

## 錯誤回應

| 情境 | 結果 |
| --- | --- |
| 未登入／失效session | 401 authentication_required |
| 帳密錯誤 | 401 invalid_credentials，不回傳輸入 |
| role等額外登入欄位 | 400 invalid_login_form；不能升權 |
| CSRF缺漏、錯誤、重播／跨來源 | 403 csrf_failed |
| 不存在／無權／撤回／日期失效的引用 | 404 citation_not_found，無標題或正文 |
| 已登入但引用日期不合法／未填 | 400 invalid_date |

## 測試證據

測試只用合成帳密與隔離資料庫；metadata更新測試沿用階段2的隔離corpus fixture，不使用保留題。

- 首輪29 passed；補充邊界案例與最終結果見下方驗收紀錄。
- 角色矩陣、日期交界、缺ACL、未知日期、hr→employee、並行HTTP帳號、伺服器角色降權、引用猜測與撤回已涵蓋。
- metadata測試：同一employee session先可讀C02，發布ACL縮為hr後舊ID立即不可讀；hr仍可讀。再發布未來生效日後hr也不可讀，生效日當天可讀。兩次發布均0次embedding，原citation ID保持穩定。
- 原有API provider／環境變數測試持續使用假設定，沒有讀取真實.env，沒有新增API呼叫或費用。

## 鎖檔與乾淨環境

從[uvicorn官方PyPI](https://pypi.org/project/uvicorn/)及[python-multipart官方PyPI](https://pypi.org/project/python-multipart/)查證版本（2026-10-18），鎖定0.53.0／0.0.32，新間接依賴click8.5.0。重新解析時以原鎖檔約束，原有61套件版本未升級。

```powershell
uv pip compile pyproject.toml --extra dev --python .venv/Scripts/python.exe --python-platform windows --constraint .runtime/requirements-before-stage3.lock --output-file requirements.lock --generate-hashes
# 檢查Torch只保留下列官方Windows wheel雜湊後：
.venv/Scripts/python.exe -m venv .venv-stage3-verify
uv pip sync requirements.lock --require-hashes --python .venv-stage3-verify/Scripts/python.exe
.venv-stage3-verify/Scripts/python.exe -m pip check
```

實際全新venv安裝64套件成功，pip check：No broken requirements found。Torch SHA256：2be20b2c05a0cce10430cc25f32b689259640d273232b2de357c35729132256d。開發venv同步後恢復editable安裝，pip check也通過。

## 本機使用

```powershell
.venv/Scripts/python.exe -m hr_rag.auth init
.venv/Scripts/python.exe -m hr_rag.web
```

第一個命令依序以隱藏輸入設定employee／manager／hr密碼（12～256字元），只保存雜湊；不輸入API金鑰。之後開啟http://127.0.0.1:8000/login。重設單一帳號使用`python -m hr_rag.auth set-password --user employee`，會撤銷該帳號舊session。初始化不讀.env，不自動啟動模型。

## 下一階段門檻

1.4／1.5保留題格式與有效摘要／SHA256尚未完成；第四階段開始前仍須驗證與凍結。不得因第三階段通過而跳過，也不讀取保留題正文來修正格式。


## 審查與最終驗證紀錄

獨立審查發現兩項Important（年資誤當民國年、空格日期漏判），均已補RED回歸後修正。另補期間排除不能遮蔽四位西元年與完整年月日的2個RED回歸，完成相同修正批次。沒有未處理的Critical／Important；未進行第二輪審查。

- `python -m pytest tests/test_auth.py tests/test_policy.py tests/test_citation_access.py -q -p no:cacheprovider`：**49 passed，23.54s**。
- 乾淨venv先驗35 passed／1 metadata測試deselected（54.54s），該metadata測試已在上述49項中通過；日期最後修正後再驗`test_policy.py`：**33 passed，0.55s**。
- Ruff check與format check：通過，37檔格式一致。
- OpenSpec strict：通過。正式manifest嚴格驗證0錯誤，20開發題仍verified且hash未變。
- 實際`python -m hr_rag.web`啟動：GET /login 200、登入表單及no-store正確。測試後已停止本次啟動的程序；目前沒有持續執行網頁服務。
- requirements.lock SHA256：a996806af195323348e5d3f30d3df210d1d03eab87b5147463c5899d582d2e94。
- 第三方Starlette TestClient產生1則anyio別名棄用警告，不是測試失敗；保留原套件版本，沒有為消除警告升級無關依賴。
- 全專案最終回歸：**281 passed、1 skipped、1第三方棄用warning，140.69s**。skip僅因Windows無symlink建立權限（test_evaluation_schema.py:187）；其餘測試全通過。

驗收結論：3.1～3.6完成，整體OpenSpec進度25/55；階段4未開始。此次API呼叫0、費用0，未顯示或記錄金鑰。帳號密碼設定仍由使用者於本機互動終端完成，與程式驗收分開。
