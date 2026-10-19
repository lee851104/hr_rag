# SDD ledger — plan: openspec/changes/build-hr-leave-rag-mvp/tasks.md 階段2

使用openspec-apply-change、writing-plans及executing-plans；由本對話實作，完成後依executing-plans進行一次獨立整體審查。使用者已核准階段2與保留題格式修正解耦，不重複詢問。既有專用資料夾未建Git，不另初始化或commit，保留本紀錄。

## 介面與測試步驟

- 2.1：tests/test_chunking.py先驗完整父段、條款例外、真實tokenizer、400上限、單句超限拒絕、穩定ID；RED後建立corpus/chunking.py。型別沿用contracts，詳細介面見design第12節。
- 2.2／2.3：tests/test_ingestion.py先驗相同匯入ID/數量、SQLite原文hash與向量對應、embedding中途失敗及寫檔失敗保留active；RED後建立storage.py、corpus/ingest.py。
- 2.4：tests/test_versions.py先驗9/30與10/1、逐節日期、未知日期、重疊拒絕、撤回後重匯入仍拒；RED後加入撤回與資料驗證。
- 2.6：新增相同匯入零embedding、僅改C02保留其餘9份ID與向量、ACL／日期更新零embedding、刪除退出、模型／切片設定全重建及原因、失敗快取不發布。
- 2.5：本機真實embedding及tokenizer產生正式索引、比對全部原文定位；輸出至少20片段覆蓋10文件供使用者核對，不代簽。
- 每步pytest對應檔案通過後，最後完整pytest與ruff及OpenSpec strict。命令均用.venv/Scripts/python.exe，pytest禁cacheprovider避免Windows ACL問題。

## Pre-flight

- 1.3→2.1：ManifestRecord含逐節日期，normalized JSON不含日期；切片同時使用兩者，不能把文件起日套給全部條文。
- 2.1→2.2：Chunk契約不含offset，另存parent／offset／token_count以追溯，避免破壞既有型別。
- 2.3→2.4：撤回與匯入共用SQLite寫交易；只透過active快照讀取，避免復活舊版。
- 2.6→3.6：metadata更新保留ID、重算候選；stage2只提供儲存候選過濾，登入授權屬stage3。
- Ruling: 初始ACL嚴格檢核保持原樣，增量只允許縮限；若允許擴權會超出已批准角色矩陣。
- Ruling: 原始來源保留，任一未知日期或超長單句阻止整次發布並記安全待處理原因；不跳過壞節留下不完整來源。

實作驗證：切片5項RED→GREEN；匯入／版本19項RED，metadata-only發現角色數檢查錯誤後修正GREEN；含manifest共60 passed。全suite229 passed、1 symlink權限skip(55.19s)，Ruff check/format通過。真實embedding完成46×512向量、43唯一文字6批，最大388tokens，重匯入0次；已產20片段待人工核對。獨立review_stage2依executing-plans進行一次整體審查，等待結果。

Final review: review_stage2獨立整體審查完成。兩個Important已用3個RED案例重現後修正：雙tokenizer超限、同程序詞表變更與實際設定cache失效。反例定位缺漏提升為需修正項（2.5有明文要求），已補20項實際對照。Ruling: 保持2.5待人工核對，不因原文程式比對成功而勾選。舊的較慢targeted測試程序在修正優化後被最終全suite取代並停止，避免同時重載多份大型詞表；以最後完整suite結果為驗證。最終本機重建77.976s，46×512、embedding388/reranker311，重匯入0次，前次run保存。

Task 2.1/2.2/2.3/2.4/2.6: complete — 最終全suite232 passed,1 symlink skip(159.09s)，兩個Important與具體反例缺漏已修正；3個RED回歸均GREEN。最終模型重建／20正反例原文定位檢查通過。2.5維持pending，總進度18/55。不進stage3，不讀保留題，無新增API費用。


2026-10-18使用者後續明確確認「S01～S20全部通過」。比對20個S編號、10文件覆蓋、active generation、manifest hash及向量快照hash無變；已更新artifact逐項verified與HTML簽核狀態，完成2.5及整體階段2驗收，接續階段3。先前pending描述是歷史紀錄。
