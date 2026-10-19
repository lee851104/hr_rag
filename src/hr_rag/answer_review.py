"""開發答案人工核對頁；只匯出判定，不代簽或自動通過。"""

import argparse
import hashlib
import html
import json
from datetime import datetime
from pathlib import Path

# tasks.md 5.4／5.5原門檻；不得在此調降。
ANSWERABLE = {"direct", "paraphrase_cross", "version"}
# 開發可回答14題至少13；保留可回答8題至少7（7.2）。
MIN_ANSWERABLE = {"development": 13, "holdout": 7}
MIN_CITATION_SUPPORT = 0.95


def render(report, source_hash):
    def escape(value):
        return html.escape(str(value))
    cards, identifiers = [], []

    def select(row, kind, index=0):
        return (
            f'<select data-row="{row}" data-kind="{kind}" data-index="{index}">'
            '<option value="">尚未核對</option><option value="true">通過</option>'
            '<option value="false">不通過</option></select>'
        )

    for index, row in enumerate(report["rows"]):
        answer = row["answer"]
        units = {u["id"]: u for u in (row.get("context") or {}).get("units", [])}
        pair_ids, claims = [], []
        for claim_index, claim in enumerate(answer["claims"]):
            cites = []
            for cid in claim["citation_ids"]:
                unit = units.get(cid, {})
                pair_index = len(pair_ids)
                pair_ids.append({"claim_index": claim_index, "citation_id": cid})
                location = "/".join(
                    str(unit.get(k, ""))
                    for k in ("document_id", "version_id", "section_id")
                )
                cites.append(
                    f"<details><summary>{escape(location)}：此引用支持該主張？ "
                    f"{select(index, 'citation', pair_index)}</summary>"
                    f"<pre>{escape(unit.get('text', '引用不在上下文'))}</pre></details>"
                )
            claims.append(f"<li>{escape(claim['text'])}{''.join(cites)}</li>")
        identifiers.append(
            {
                "question_id": row["question_id"],
                "role": row["role"],
                "repeat": row["repeat"],
                "claim_citation_pairs": pair_ids,
            }
        )
        expected = "<br>".join(escape(x) for x in row["expected"]["answer_key"])
        if not expected:
            expected = escape(row["expected"].get("expected_behavior", "insufficient"))
        cards.append(
            f"<article><h2>{escape(row['question_id'])}／{escape(row['role'])}"
            f"／第{row['repeat']}次</h2><p>{escape(row['question'])}</p>"
            f"<details><summary>既有預期答案</summary><p>{expected}</p></details>"
            f"<p>實際狀態：{escape(answer['status'])}</p><ol>{''.join(claims)}</ol>"
            f"<p>{escape(answer.get('reason') or '')}</p>"
            "<p>所有必要答案、限制與狀態均正確？ "
            f"{select(index, 'correct')}</p>"
            "<p>全部關鍵主張都有引用（不能只看ID存在）？ "
            f"{select(index, 'covered')}</p>"
            f'<label>核對理由 <textarea data-note="{index}"></textarea>'
            '</label></article>'
        )
    meta = json.dumps(
        {"source_sha256": source_hash, "kind": report["kind"], "rows": identifiers},
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    return (
        """<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<title>第五階段答案核對</title><style>
body{font:17px/1.65 system-ui;max-width:1050px;margin:30px auto;padding:0 20px;
background:#f3f5f7;color:#182534}
header{position:sticky;top:0;background:#eef3ff;padding:12px;border:1px solid #ccd7eb}
article{background:white;padding:20px;margin:20px 0;border:1px solid #cbd3df;
border-radius:10px}
h2{font-size:20px}pre{white-space:pre-wrap;background:#f3f5f7;padding:12px}
select,button,input,textarea{font:inherit}
textarea{display:block;width:95%;min-height:50px}details{margin:8px 0}
button{padding:8px 16px}small{display:block}
</style><h1>第五階段答案核對</h1>
<p>這裡核對新生成答案，不會修改原本的上下文有用性標註。錯誤或遺漏也要保留並標不通過。
每項引用需實際支持旁邊主張；資料不足題應拒絕捏造。穩定性案例另比較三次是否矛盾。</p>
<header>核對者 <input id="reviewer" value="使用者">
<button id="export">匯出核對JSON</button><span id="progress"></span>
<small>判定暫存在此瀏覽器；匯出可包含未完成項目，不會自動放行驗收。</small></header>
"""
        + "".join(cards)
        + '<script type="application/json" id="meta">'
        + meta
        + """</script>
<script>
const meta=JSON.parse(document.getElementById('meta').textContent);
const fields=[...document.querySelectorAll('select')];
const notes=[...document.querySelectorAll('textarea')];
const reviewer=document.getElementById('reviewer');
const key='answer-review:'+meta.source_sha256;
function state(){return {values:fields.map(x=>x.value),notes:notes.map(x=>x.value),
reviewer:reviewer.value};}
function update(){document.getElementById('progress').textContent=
  ' 已核對 '+fields.filter(x=>x.value!=='').length+'/'+fields.length;
  try{localStorage.setItem(key,JSON.stringify(state()));}catch(e){}}
try{const old=JSON.parse(localStorage.getItem(key)||'null');if(old){
fields.forEach((x,i)=>x.value=old.values[i]||'');
notes.forEach((x,i)=>x.value=old.notes[i]||'');reviewer.value=old.reviewer||'使用者';}}catch(e){}
document.addEventListener('change',update);document.addEventListener('input',update);update();
document.getElementById('export').addEventListener('click',()=>{
 const who=reviewer.value.trim();if(!who){alert('請填核對者');return;}
 const decision=(row,kind,index=0)=>{const e=fields.find(x=>+x.dataset.row===row
 &&x.dataset.kind===kind&&+x.dataset.index===index);
 return e.value===''?null:e.value==='true';};
 const rows=meta.rows.map((r,i)=>({...r,correct:decision(i,'correct'),
 key_claims_covered:decision(i,'covered'),
 citation_reviews:r.claim_citation_pairs.map((p,j)=>({
 ...p,supported:decision(i,'citation',j)})),reason:notes[i].value.trim()}));
 const complete=fields.every(x=>x.value!=='');
 const output={schema_version:1,source_sha256:meta.source_sha256,
 kind:meta.kind,reviewer:who,
 reviewed_at:new Date().toISOString(),complete,rows};
 const url=URL.createObjectURL(new Blob([JSON.stringify(output,null,2)+'\\n'],
 {type:'application/json'}));
 const a=document.createElement('a');a.href=url;
 a.download='hr-rag-answer-review-'+meta.kind+'.json';a.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
});
</script></html>"""
    )


def write(source):
    source = Path(source)
    raw = source.read_bytes()
    output = source.with_suffix(".html")
    output.write_text(
        render(json.loads(raw), hashlib.sha256(raw).hexdigest()), encoding="utf-8"
    )
    return output


def _pairs(row):
    return [
        {"claim_index": i, "citation_id": cid}
        for i, claim in enumerate(row["answer"]["claims"])
        for cid in claim["citation_ids"]
    ]


def _validate(report, raw, review):
    if review.get("schema_version") != 1:
        raise ValueError("schema_version_unsupported")
    if review.get("source_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("source_sha256_mismatch")
    if review.get("kind") != report["kind"]:
        raise ValueError("kind_mismatch")
    if review.get("complete") is not True:
        raise ValueError("review_incomplete")
    if not str(review.get("reviewer") or "").strip():
        raise ValueError("reviewer_missing")
    try:
        datetime.fromisoformat(str(review.get("reviewed_at")).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("reviewed_at_invalid") from None
    identity = ("question_id", "role", "repeat")
    if [tuple(r.get(k) for k in identity) for r in review["rows"]] != [
        tuple(r[k] for k in identity) for r in report["rows"]
    ]:
        raise ValueError("row_identity_mismatch")
    for row, decided in zip(report["rows"], review["rows"]):
        pairs = _pairs(row)
        reviewed = [
            {k: c.get(k) for k in ("claim_index", "citation_id")}
            for c in decided["citation_reviews"]
        ]
        if decided["claim_citation_pairs"] != pairs or reviewed != pairs:
            raise ValueError("citation_pairs_mismatch")
        decisions = [decided.get("correct"), decided.get("key_claims_covered")]
        decisions += [c.get("supported") for c in decided["citation_reviews"]]
        if not all(isinstance(value, bool) for value in decisions):
            raise ValueError("decision_missing")


def assess(report, raw, review):
    """以使用者匯出的判定計算原門檻；判定本身不由程式改寫。"""
    _validate(report, raw, review)
    joined = list(zip(report["rows"], review["rows"]))

    def key(row):
        return {k: row[k] for k in ("question_id", "role", "repeat")}

    def expected(row):
        # 日期釐清以資料不足狀態回覆，不另設答案狀態。
        value = row["expected"]["expected_behavior"]
        return "insufficient" if value == "clarify" else value

    def ok(row, decided):
        return row["answer"]["status"] == expected(row) and decided["correct"]

    def count(rows):
        return {"passed": sum(ok(r, d) for r, d in rows), "total": len(rows)}

    unsupported = [
        key(row) | {k: c[k] for k in ("claim_index", "citation_id")}
        for row, decided in joined
        for c in decided["citation_reviews"]
        if not c["supported"]
    ]
    total_pairs = sum(len(d["citation_reviews"]) for _, d in joined)
    support = {"supported": total_pairs - len(unsupported), "total": total_pairs}
    support["rate"] = support["supported"] / total_pairs if total_pairs else None
    result = {
        "kind": report["kind"],
        "reviewer": review["reviewer"],
        "reviewed_at": review["reviewed_at"],
        "source_sha256": review["source_sha256"],
        "citation_support": support,
        "unsupported_citations": unsupported,
        "key_claims_covered": {
            "passed": sum(d["key_claims_covered"] for _, d in joined),
            "total": len(joined),
        },
        "status_mismatches": [
            key(r) | {"status": r["answer"]["status"]}
            for r, _ in joined
            if r["answer"]["status"] != expected(r)
        ],
        "marked_incorrect": [key(r) for r, d in joined if not d["correct"]],
        "reasons": [key(r) | {"reason": d["reason"]} for r, d in joined
                    if d.get("reason")],
    }
    covered = result["key_claims_covered"]
    if report["kind"] in MIN_ANSWERABLE:
        for name, rows in (
            ("answerable", [x for x in joined if x[0]["category"] in ANSWERABLE]),
            ("insufficient", [x for x in joined if x[0]["category"] == "insufficient"]),
            ("version", [x for x in joined if x[0]["category"] == "version"]),
            ("permission", [x for x in joined if x[0]["category"] == "permission"]),
        ):
            result[name] = count(rows)
        result["passed"] = (
            result["answerable"]["passed"] >= MIN_ANSWERABLE[report["kind"]]
            and all(
                result[n]["passed"] == result[n]["total"]
                for n in (
                    ("insufficient", "version")
                    if report["kind"] == "development"
                    else ("insufficient", "version", "permission")
                )
            )
            and (support["rate"] is None or support["rate"] >= MIN_CITATION_SUPPORT)
            and covered["passed"] == covered["total"]
        )
    else:
        runs = [
            ok(r, d) and d["key_claims_covered"]
            and all(c["supported"] for c in d["citation_reviews"])
            for r, d in joined
        ]
        result["runs"] = {"passed": sum(runs), "total": len(runs)}
        result["passed"] = bool(runs) and all(runs)
    return result


def main():
    parser = argparse.ArgumentParser(description="匯入人工答案核對並計算原門檻")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    review_raw = args.review.read_bytes()
    result = assess(json.loads(raw), raw, json.loads(review_raw))
    result["review_sha256"] = hashlib.sha256(review_raw).hexdigest()
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: result[k] for k in result if k != "reasons"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
