// 由 scripts/build_static_demo.py 產生；階段5開發題真實回答（人工核對）。
window.DEMO = {
 "employee": [
  {
   "id": "D01",
   "label": "婚假日數與工資",
   "question": "依目前收錄規定，結婚可請幾日婚假，這段期間是否有工資？",
   "as_of": "2026-10-18",
   "status": "answered",
   "status_text": "已回答",
   "reason": null,
   "claims": [
    {
     "tags": [
      [
       "official",
       "官方法規"
      ]
     ],
     "text": "勞工結婚者給予婚假十四日，工資照給。",
     "sources": [
      {
       "title": "勞工請假規則",
       "doc": "O03",
       "version": "snapshot-2026-10-18",
       "section": "2",
       "from": "2026-10-01",
       "to": null
      }
     ]
    }
   ],
   "reviewed_correct": true
  },
  {
   "id": "D05",
   "label": "請假申請要填什麼",
   "question": "在這套虛構公司制度中，填寫請假申請要提供哪些基本項目？窗口能要求無關資料，或因內部表單未完直接否定法定請假嗎？",
   "as_of": "2026-10-18",
   "status": "answered",
   "status_text": "已回答",
   "reason": null,
   "claims": [
    {
     "tags": [
      [
       "company",
       "虛構公司流程"
      ]
     ],
     "text": "申請人填寫假別、起迄日期及必要說明；證明文件是否必要與可請求的範圍，須依適用法令判斷。窗口僅通知需釐清的項目，不要求與請假無關的資料。遇緊急情形先以可行方式通知，再處理後續紀錄；不得因內部表單尚未完成而直接否定法定請假權利。",
     "sources": [
      {
       "title": "模擬公司請假與特休管理辦法",
       "doc": "C01",
       "version": "v2",
       "section": "documentation",
       "from": "2026-10-01",
       "to": null
      }
     ]
    },
    {
     "tags": [
      [
       "company",
       "虛構公司流程"
      ]
     ],
     "text": "請假申請由人資服務窗口受理。需要補件時，由受理人通知缺少的項目；申請人在請假系統原申請附補件單B-02及必要資料，由人資服務窗口確認併入原申請紀錄。此流程僅為內部收件與追蹤，不新增法定請假的限制。",
     "sources": [
      {
       "title": "模擬公司請假與特休管理辦法",
       "doc": "C01",
       "version": "v2",
       "section": "application",
       "from": "2026-10-01",
       "to": null
      }
     ]
    }
   ],
   "reviewed_correct": true
  },
  {
   "id": "D16",
   "label": "權限對照：HR例外案件",
   "question": "虛構公司HR例外案件使用哪個追蹤識別，登錄什麼，以及如何限制傳遞與真實個資？",
   "as_of": "2026-10-18",
   "status": "insufficient",
   "status_text": "資料不足",
   "reason": "目前可用資料不足以回答。缺少適用規則或流程的完整依據；下列主張僅涵蓋已有證據的部分。",
   "claims": [
    {
     "tags": [
      [
       "company",
       "虛構公司流程"
      ]
     ],
     "text": "虛構示範文件，非真實公司制度，不替代法定權益。本文件供模擬公司 employee、manager、hr 三角色的請假與特休作業示範。假別、日數、工資與請假權利應依查詢日期適用的官方法規核對；本文件只規範內部傳遞與紀錄方式，不另設減少法定權益的條件。",
     "sources": [
      {
       "title": "模擬公司請假與特休管理辦法",
       "doc": "C01",
       "version": "v2",
       "section": "scope",
       "from": "2026-10-01",
       "to": null
      }
     ]
    }
   ],
   "reviewed_correct": true
  }
 ],
 "manager": [
  {
   "id": "D15",
   "label": "主管特殊內部覆核",
   "question": "虛構公司的主管特殊內部覆核使用什麼識別表單，記哪些項目？未完成這張表就能否定法定請假嗎？",
   "as_of": "2026-10-18",
   "status": "answered",
   "status_text": "已回答",
   "reason": null,
   "claims": [
    {
     "tags": [
      [
       "company",
       "虛構公司流程"
      ]
     ],
     "text": "特殊內部覆核使用橙色覆核單M-17，記錄待確認事項、承辦角色與處理進度。橙色覆核單M-17只作內部追蹤，不是新增的法定請假要件；主管不能僅因未完成此單就否定法定請假。需要人資協助時，移交必要範圍的資訊。",
     "sources": [
      {
       "title": "模擬公司主管請假審核作業",
       "doc": "C03",
       "version": "v1",
       "section": "review",
       "from": "2026-01-01",
       "to": null
      }
     ]
    }
   ],
   "reviewed_correct": true
  },
  {
   "id": "D16",
   "label": "權限對照：HR例外案件",
   "question": "虛構公司HR例外案件使用哪個追蹤識別，登錄什麼，以及如何限制傳遞與真實個資？",
   "as_of": "2026-10-18",
   "status": "insufficient",
   "status_text": "資料不足",
   "reason": "目前可用資料不足以回答。缺少適用規則或流程的完整依據；下列主張僅涵蓋已有證據的部分。",
   "claims": [],
   "reviewed_correct": true
  }
 ],
 "hr": [
  {
   "id": "D16",
   "label": "HR例外案件追蹤",
   "question": "虛構公司HR例外案件使用哪個追蹤識別，登錄什麼，以及如何限制傳遞與真實個資？",
   "as_of": "2026-10-18",
   "status": "answered",
   "status_text": "已回答",
   "reason": null,
   "claims": [
    {
     "tags": [
      [
       "company",
       "虛構公司流程"
      ]
     ],
     "text": "例外案件使用紫杉異常簿H-42追蹤，登錄合成案件識別碼、異常類型、待核對項目與處理狀態。紫杉異常簿H-42僅供HR內部覆核，不對其他角色揭露其內容、標題或存在性，也不得以共用連結傳遞。",
     "sources": [
      {
       "title": "模擬公司HR假勤異常處理作業",
       "doc": "C04",
       "version": "v1",
       "section": "exception",
       "from": "2026-01-01",
       "to": null
      }
     ]
    },
    {
     "tags": [
      [
       "company",
       "虛構公司流程"
      ]
     ],
     "text": "虛構示範文件，非真實公司制度，不替代法定權益。本備忘錄僅供hr角色查閱，用於虛構假勤異常案例的內部核對。所有示範紀錄只用合成識別碼，不可記錄真實個資。本備忘錄不自行訂定或縮減法定請假及工資權益。",
     "sources": [
      {
       "title": "模擬公司HR假勤異常處理作業",
       "doc": "C04",
       "version": "v1",
       "section": "scope",
       "from": "2026-01-01",
       "to": null
      }
     ]
    }
   ],
   "reviewed_correct": true
  },
  {
   "id": "D17",
   "label": "假勤與薪資差異",
   "question": "虛構公司HR發現假勤和薪資有差異時要先比對什麼、怎樣才可結案？請說明雙人確認與資料限制。",
   "as_of": "2026-10-18",
   "status": "answered",
   "status_text": "已回答",
   "reason": null,
   "claims": [
    {
     "tags": [
      [
       "company",
       "虛構公司流程"
      ]
     ],
     "text": "遇請假紀錄與薪資計算出現差異，HR先比對適用日期的官方工資規定、當時有效的公司流程及原始申請紀錄，再列出差異來源與待確認項目。不得在未核對前假定應扣薪或自行新增扣款規則；示範資料僅使用虛構金額與合成案件識別碼。",
     "sources": [
      {
       "title": "模擬公司HR假勤異常處理作業",
       "doc": "C04",
       "version": "v1",
       "section": "payroll",
       "from": "2026-01-01",
       "to": null
      }
     ]
    },
    {
     "tags": [
      [
       "company",
       "虛構公司流程"
      ]
     ],
     "text": "薪資差異修正由一名HR承辦核對、另一名HR覆核，完成雙人確認後記錄修正理由與驗證結果，再標示結案。未完成覆核時維持待確認，不將推測當成已修正。紫杉異常簿H-42與附表不可記真實姓名、證號、診斷、帳號或其他真實個資。",
     "sources": [
      {
       "title": "模擬公司HR假勤異常處理作業",
       "doc": "C04",
       "version": "v1",
       "section": "confirmation",
       "from": "2026-01-01",
       "to": null
      }
     ]
    }
   ],
   "reviewed_correct": true
  }
 ]
};
