"""產生 GitHub Pages 靜態展示資料：取階段5開發題的真實回答（使用者人工核對通過）。

只讀本機私人結果（.runtime/stage5-private，不入版控），
輸出 docs/demo-data.js。只收開發題，不含保留題；不含金鑰、帳號或模型原始交換。
"""

import json
from pathlib import Path

from hr_rag.web import STATUS_TEXT, split_claim

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".runtime/stage5-private/development-verbatim-gpt41-v3.json"
REVIEW = ROOT / "reports/stage5-human-review-development-v3.json"
OUTPUT = ROOT / "docs/demo-data.js"
# 每個角色可點的題目；D16 用來對照同一題在不同角色的權限差異。
PICKS = {
    "employee": [
        ("D01", "婚假日數與工資"),
        ("D05", "請假申請要填什麼"),
        ("D16", "權限對照：HR例外案件"),
    ],
    "manager": [("D15", "主管特殊內部覆核"), ("D16", "權限對照：HR例外案件")],
    "hr": [("D16", "HR例外案件追蹤"), ("D17", "假勤與薪資差異")],
}


def main():
    run = json.loads(SOURCE.read_text("utf-8"))
    review = json.loads(REVIEW.read_text("utf-8"))
    incorrect = {(r["question_id"], r["role"]) for r in review["marked_incorrect"]}
    titles = {
        (d["document_id"], d["version_id"]): d["title"]
        for d in json.loads((ROOT / "data/manifest.json").read_text("utf-8-sig"))[
            "documents"
        ]
    }
    rows = {(r["question_id"], r["role"]): r for r in run["rows"]}
    data = {}
    for role, picks in PICKS.items():
        items = []
        for question_id, label in picks:
            row = rows[(question_id, role)]
            units = {u["id"]: u for u in row["context"]["units"]}
            claims = []
            for claim in row["answer"]["claims"]:
                tags, text = split_claim(claim["text"])
                claims.append(
                    {
                        "tags": tags,
                        "text": text,
                        "sources": [
                            {
                                "title": titles[
                                    (units[c]["document_id"], units[c]["version_id"])
                                ],
                                "doc": units[c]["document_id"],
                                "version": units[c]["version_id"],
                                "section": units[c]["section_id"],
                                "from": units[c]["effective_from"],
                                "to": units[c]["effective_to"],
                            }
                            for c in claim["citation_ids"]
                        ],
                    }
                )
            items.append(
                {
                    "id": question_id,
                    "label": label,
                    "question": row["question"],
                    "as_of": row["as_of"],
                    "status": row["answer"]["status"],
                    "status_text": STATUS_TEXT[row["answer"]["status"]],
                    "reason": row["answer"]["reason"],
                    "claims": claims,
                    "reviewed_correct": (question_id, role) not in incorrect,
                }
            )
        data[role] = items
    OUTPUT.write_text(
        "// 由 scripts/build_static_demo.py 產生；階段5開發題真實回答（人工核對）。\n"
        "window.DEMO = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n",
        encoding="utf-8",
    )
    print(json.dumps({r: len(v) for r, v in data.items()}))


if __name__ == "__main__":
    main()
