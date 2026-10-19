# 階段2：匯入、切片與版本

**最終驗收：通過（2026-10-18）。** S01～S20 人工核對全部通過，覆蓋10主文件；確認對應現行 generation、manifest hash。自動驗證232 passed／1 Windows權限skip及嚴格檢核證據如下。歷史待簽核描述保留為執行紀錄，以本段與 artifacts 簽核為準。

2026-10-18。使用者核准先完成階段2獨立工作；保留題格式、合格摘要與hash凍結延後至階段4前，1.4／1.5仍待完成。此變更已同步proposal、design、tasks、evaluation-observability spec。沒有讀取保留題或.env，沒有生成API呼叫與新增費用。

## 已實作與驗證

| 任務 | 行為與證據 |
| --- | --- |
| 2.1 | 真實embedding／reranker兩個tokenizer（含特殊tokens），各400硬上限；完整條文／問答父段、項款／句界切分、節內字元定位；單句超限受控拒絕發布；逐節有效日期、ACL繼承 |
| 2.2 | SQLite保存版本、原始內容/hash、normalized內容、父子段與列號；NumPy不可變向量快照；相同重匯入generation、ID、數量與向量完全相同 |
| 2.3 | BEGIN IMMEDIATE序列化寫入；先完成staging快照再交易切換active；embedding中途及寫檔失敗保持舊版；快取跟隨交易rollback；快照hash/shape/有限值檢查 |
| 2.4 | C01於2026-09-30選v1、2026-10-01選v2；O01逐條日期；問答發布日前不取用；未知日期、未核對、重疊拒絕整次發布並記安全原因；版本撤回持續有效，重匯入不復活 |
| 2.6 | 相同匯入0呼叫；隔離fixture只改C02一節只算1筆；其餘9文件ID／向量逐一相同；ACL／日期metadata更新0呼叫；刪節同步退出active片段／父段／向量；模型與切片設定改變記錄全重建原因 |
| 2.5 | 全46片段程式逐一比對原文及token，已選20項涵蓋10主文件供人工核對；**2026-10-18 使用者確認 S01～S20 全部通過** |

本階段的CorpusStore.snapshot是受信任的本機資料介面，不是登入或公開HTTP端點。它依目前active及撤回紀錄讀取，並可按角色／日期篩選；階段3由Principal銜接授權，階段4再驗證BM25等路徑。舊快照物件不能作為未來請求的授權憑據。

## 真實本機實測

命令：`.venv/Scripts/python.exe scripts/verify_stage2.py`。

- 最終generation：dd483ec3be394e49b004ec58b87c292f。
- 10主文件、11版本、44完整父段、46子片段；向量矩陣46×512，全部有限值。
- embedding最大388、reranker最大311 tokens；兩者各≤400，所有片段原文位置逐一吻合。
- 43筆不同文字實算（6批：8／8／8／8／8／3），相同文字共用向量快取，沒有跨來源合併證據ID。
- 相同資料第二次匯入：embedding 0呼叫，generation不變。
- 最終重建與兩次匯入及定位檢核合計77.976秒；前次146.670秒紀錄保存在stage-2-artifacts.json.previous_runs，這些不是查詢延遲。
- 設定、資料hash與20筆原文證據見stage-2-artifacts.json；人工核對頁stage-2-review.html，全部pending。

## 測試紀錄

先寫測試：切片5項因缺chunking模組失敗；匯入／版本19項因缺ingest模組失敗。加入實作後，metadata-only案例發現ACL縮限仍套用原角色數量判定；以同一失敗案例修正為檢查重複角色，原始矩陣仍維持預設嚴格驗證。相關60項回歸通過。

全專案：`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` → 229 passed, 1 skipped in 55.19s。skip為Windows symlink privilege unavailable，不計為通過。

Ruff check通過；format check共33檔已格式化。OpenSpec strict已通過；獨立程式審查及修正見下方。

## 核對與後續門檻

人工核對至少20片段涵蓋全部10文件尚未完成，因此階段2整體未驗收，不進階段3。保留題依使用者核准可由Claude平行修正，在階段4開始前必須完成格式驗證、合格摘要及hash凍結，不能以本階段測試取代。

裁定：原始資料保留、任何未知日期或單句超限拒絕整次發布，避免部分來源悄悄消失；增量ACL只允許縮限既有角色矩陣。若未來需要擴權或部分匯入，須明確修訂規格。本專案未建立Git，沒有commit或推送。


## 獨立審查與修正

review_stage2獨立整體審查發現兩項Important：embedding對特殊文字可能輸出UNK短序列，但reranker仍超限；同程序tokenizer檔更新後快取實例與記錄hash不一致。新增三個回歸測試先全數失敗（未拒絕600個emoji、更新後仍舊計數1而非3、實際tokenizer改變未重建），再修正為雙tokenizer上限及實際計數實例指紋。無參數tokenizer快取已移除，匯入內共用一次載入的實例以避免逐文件重載。計數實例停用截斷／padding，不受注入物件後續修改影響。

反例只有通用文字的審查項原列Minor；依2.5明確要求「正反例原文與定位」提升為需修正項，已補另一真實來源節的全文、文件／版本／節／父段ID、原始路徑及hash，20項逐一驗證。不把這次程式修正或代理審查冒充人工核對。

沒有未處理的審查發現；最終全套驗證結果見下方。兩個向量世代與前次實測紀錄保留，沒有覆寫前次失敗或測量資料。


## 最終驗證與任務狀態

`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` → **232 passed, 1 skipped in 159.09s**。全部新增回歸通過；skip為Windows symlink權限。Ruff check、33檔format check通過。2.1–2.4、2.6已勾選，OpenSpec進度18/55；2.5仍待使用者核對20片段，階段2整體未通過，不進入階段3。

增量呼叫證據：重匯入0次；隔離fixture只改C02一節=1筆、其餘9文件ID與向量逐一相等；ACL／日期0次、刪節0次，模型／切片設定變更皆記錄原因。正式快照SHA256與10文件各自的「ID＋向量」SHA256已補入stage-2-artifacts.json，可連同manifest/config指紋追溯；不把fixture當成實際法規改版。

最終向量快照SHA256：`d872e7ea170b28c5919de71737b20b29dfef3e7237207eaea0836ff8875a1dca`。
