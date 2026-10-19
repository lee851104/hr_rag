# 階段7.3：官方6份 vs 完整10份語料比較

2026-10-19。開發集、三模式、凍結設定（rerank min_relevance 0.58、dense／hybrid 0.75、5單位、leave_scope_filter）。本機 embedding／reranker 即時推論，**0次API**。執行前通過 `freeze verify`。原始彙總：`reports/stage7-official-comparison.json`；腳本 `.runtime/stage7_official_compare.py`。

## 共同官方題（必要證據全為O01–O06：D01、D02、D03、D04、D07、D08、D09）

| 模式 | 語料 | Top-5完整 | 組裝後完整 | 已標註精確度 |
|---|---|---|---|---|
| dense | full | 5/7 | 5/7 | 77.86% |
| dense | official | 5/7 | 5/7 | 77.86% |
| hybrid | full | 5/7 | 5/7 | 58.81% |
| hybrid | official | 5/7 | 5/7 | 63.10% |
| rerank | full | 7/7 | 7/7 | 85.71% |
| rerank | official | 7/7 | 7/7 | 85.71% |

共同官方題的單位都已有人工標註（待標0）。加入4份公司文件沒有降低官方題的檢索品質；hybrid 在 official 下精確度略高（少了公司文件雜訊）。選定的 rerank 在兩種語料都完整命中。

## 公司流程題（D05、D06、D10–D14）在 official 語料

三模式皆：必要證據命中 0/7、上下文中公司文件單位 0。必要依據不在語料內，依回答層守衛應為資料不足；本步驟沒有呼叫生成API，不另驗證生成層的回覆文字。這些題目不與 full 共用可回答分母。

## 完整語料三模式（全開發集，即時推論）

| 模式 | Top-5完整 | 組裝後完整 | 精確度 | 授權錯誤 |
|---|---|---|---|---|
| dense | 12/14 | 12/14 | 77.50% | 0 |
| hybrid | 11/14 | 11/14 | 66.55% | 0 |
| rerank | 14/14 | 14/14 | 82.14% | 0 |

與4.9結果一致。4.9當時是以先前真實排名重播驗證；本次以即時模型推論重現了相同結果。official 語料全開發集另有待標上下文（dense 81、hybrid 80、rerank 16 項，皆屬公司題／權限題換成官方段落後的新單位），因此不報全開發集 official 精確度，也不據此比較。
