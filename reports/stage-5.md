# 階段5：證據式回答與拒答

目前狀態（2026-10-19更新）：**階段5通過，41/55**。使用者人工核對：開發可回答14/14、不足3/3、版本3/3、引用36/36、覆蓋26/26；穩定18/18、引用37/37。原文候選GPT-4.1已正式接入，見[階段5驗收](stage-5-acceptance.md)。以下為驗收前紀錄：原文候選GPT-4.1完整實測後，Codex初查可回答13/14、資料不足3/3、版本3/3、穩定18/18；D11仍漏必要性疑義轉人資，保留失敗。原題／標註／門檻不變，未進第六階段。累計API估算US$0.8992952／1美元，預留0。最新見[原文候選實測與人工核對](stage-5-verbatim-v3.md)。 以下保留初次歷史紀錄，不能取代本輪狀態。

## 實作與安全邊界

answering.AnswerService串接已凍結rerank／完整上下文／OpenAI。只允許本次實際送出單位的引用，模型生成前後都重驗有效日期與權限。引用詳細資料包含來源名稱、官方／虛構公司分類、版本、章節與有效日期。主張由伺服器標示來源類型；引用ID驗證不等於語意支持，後者仍需人工。

長引用ID透過short-id-v1映射成單次請求內唯一短ID，模型輸出先驗短ID白名單，再還原原始來源、再驗上下文。對照表只存在本機受限交換資料，不送帳號、角色、使用者識別碼、session或C04無權內容。未送入的原始ID與猜測ID都不能還原。

繁簡檢查使用[opencc-python-reimplemented 0.1.7](https://pypi.org/project/opencc-python-reimplemented/0.1.7/)，wheel SHA256 41b3b92943c7bed291f448e9c7fad4b577c8c2eae30fcfe5a74edf8818493aa6，STCharacters字表SHA256 9207708da9f2e2a248f39c457b2fccad26ec42e7efaf47a860e6900464f4cac5。只拒簡體專用字，不把歧義字自動轉換後算通過；[教育部簡編本收錄的「雇」](https://dict.concised.moe.edu.tw/dictView.jsp?ID=16833&la=0&powerMode=0)為合法繁體，不受OpenCC偏好轉換誤擋。查證2026-10-18。

無證據直接資料不足，不呼叫生成；部分證據只展示有引用主張；衝突標記待人工核對。個人剩餘／餘額／結餘查詢不能由一般規範推算。模型reason雖先做繁體檢查，但不直接顯示無引用事實；展示固定缺口或衝突說明，缺點是一般拒答說明較概括，避免自由reason繞過引用防線。生成器錯誤、輸出格式不符及來源失效均受控回應。

## 診斷與參數維持

初次初始化錯誤在呼叫前，未花API費用。開發run1的26次結果為13 answered／13 error；run2為17 answered／2 error／7 insufficient。兩輪全數保留，不從分母移除；不能把answered當成答案語意正確。修正字表誤判、提示的多餘引用及長ID造成的512 tokens截斷。模型仍為gpt-4.1-mini-2025-04-14，temperature=0，output_reserve=512，所有預算及1美元累計上限不變，沒有改用較貴模型。

新提示及短ID的78組（三模式×26）完整重組與原實測上下文逐ID相同。這是沿用真實排名的預算重驗，不宣稱重新跑embedding／reranker。第四階段rerank精確度仍81.7857%，完整證據13/14，既有人工標註不變；詳見retrieval-stage5-transport-recheck.json，最終設定hash已更新config/retrieval.selected.json。

## 離線驗證

先失敗後通過的證據：新回答模組collection error→17 passed；個人餘額／例外2 failed→回歸99 passed；獨立審查0 Critical／3 Important，初始化1 failed、改寫餘額及reason通道5 failed後修正；雇字誤判1 failed後修正；短ID協定2 failed→provider／context／answering／注入99 passed。核對頁1項測試及Chrome4項合成瀏覽器檢查通過。

全新.runtime/stage5-lock-venv以requirements.lock --require-hashes安裝及pip check通過；既有Torch官方Windows wheel單一hash原樣保留。沒有初始化Git。

## 真實執行與人工門檻

執行命令：

```powershell
.venv/Scripts/python.exe -m hr_rag.answer_evaluation --kind development --output .runtime/stage5-private/development-final.json
.venv/Scripts/python.exe -m hr_rag.answer_evaluation --kind stability --output .runtime/stage5-private/stability-final.json
```

命令內部沿用.env，將本輪有效成本上限限制為min(原設定,1美元)，不輸出或寫回金鑰。詳細請求、輸出、角色預期及答案只存在目前Windows使用者與SYSTEM可讀的.runtime/stage5-private；一般報告不保存限閱正文。

開發固定20獨立題／26角色執行；穩定性為既有6開發案例各3次／18次實際獨立請求，未使用答案快取，不能算新增18題。所有輸入hash、設定、tokens、response id及費用保存在受限紀錄；保留題沒有此CLI入口。

5.4與5.5只有收到人工核對才可放行：答案至少13/14、資料不足3/3、版本3/3、引用支持率≥95%、關鍵主張引用覆蓋100%，18次穩定性均正確且無矛盾。網頁提供待核對／通過／不通過並匯出JSON，不會更改第四階段有用性標註，也不自動代簽。

## 最終實測結果（2026-10-18）

- 最終開發26/26執行完成，19 answered／7 insufficient／0 provider或格式錯誤；僅25/26回答狀態符合既有角色預期。這不是25/26答案正確率。
- D15/employee預期資料不足，模型仍回答通用流程；沒有把C03／C04無權內容送出，但回答狀態不符合基準，須修正。
- D09 Top-5及組裝只命中2/3必要證據組，缺O04第21條。模型在開發及三次穩定性輸出誤把家庭照顧假納入普通傷病假，引用無法支持該主張。第四階段13/14允許此缺口，固定穩定性18/18卻不能接受，因此5.5已知未通過，不得只看三次說法一致就判穩定成功。
- 最終穩定性18/18實際獨立API執行，12 answered／6 insufficient，狀態18/18符合；D09三次皆缺必要引用與存在上述語意錯誤，所以整體未通過。其他答案語意、引用支持率及關鍵主張覆蓋率仍須人工核對，未以LLM判定代簽。
- O04第21條對D09尚無既有人工有用性標註；後續若改善檢索納入此新單位，需要補這一項人工判定，原167項判定不改動。本輪沒有自行加標有用，也沒有利用保留題調整。

最終提示改為按來源及假別分開陳述，完整保留原則、條件、例外、限制、程序與計算基準，不再強制最多兩項主張。重驗78組上下文仍完全相同；證據見retrieval-stage5-final-prompt-recheck.json。第三輪診斷另存development-run3.json，不覆寫成最終成績。

本階段共122次API呼叫（4輪開發各26＋18穩定性），輸入123,049 tokens、輸出23,770 tokens；依API usage與凍結單價估算US$0.0872516。全專案累計132次、US$0.1204556，預留0，低於使用者1美元上限。所有失敗輪次費用均包含在內；詳見stage5-api-summary.json。

最終完整回歸372 passed／1 Windows symlink權限skip（248.76秒）；最後只調整語意提示，受影響生成／預算／回答／注入／評估／核對頁103 passed，補充隔離官方／公司矛盾文件後第五階段35 passed。Ruff及OpenSpec strict通過。5.1–5.3可完成，總進度39/55；5.4與5.5保持未勾選，未進階段6。

受限人工核對頁：`.runtime/stage5-private/development-final.html`（20題／26角色結果）與`stability-final.html`（既有6題各3次）。可選尚未核對／通過／不通過並匯出JSON，所有初始判定均為null。這些頁面保留供核對，不代表已知錯誤可以驗收通過；匯出不修改eval/labels.jsonl。
