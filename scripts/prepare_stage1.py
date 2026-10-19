"""Reproduce pending-review corpus from fixed local snapshots; never reads secrets."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from hr_rag.corpus.manifest import roc_to_iso
from hr_rag.corpus.source_text import extract_law, extract_qa

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/official-2026-10-18"
VERSION = "snapshot-2026-10-18"
TITLES = {
    "O01": "勞動基準法",
    "O02": "勞動基準法施行細則",
    "O03": "勞工請假規則",
    "O04": "性別平等工作法",
    "O05": "特休申請、預排與事病假轉換問答（單則問答）",
    "O06": "曆年制、遞延與離職結算問答（單則問答）",
}
# Original promulgation/revision strings, not site footer dates.
DATES = {
    "O01": ("中華民國七十三年七月三十日", "民國 113 年 07 月 31 日", "86"),
    "O02": ("中華民國七十四年二月二十七日", "民國 113 年 03 月 27 日", "51"),
    "O03": ("中華民國七十四年三月二十日", "民國 115 年 09 月 30 日", "12"),
    "O04": ("中華民國九十一年一月十六日", "民國 112 年 08 月 16 日", "40"),
}
# Current text's most recent amendment, history entry and effective-date ruling.
SECTIONS = {
    "O01": {
        "38": (
            "2018-03-01",
            "沿革19：一百零七年一月三十一日；第86條明定一百零七年三月一日施行",
        ),
        "39": (
            "2016-12-23",
            "沿革17：一百零五年十二月二十一日；自公布日施行，依中央法規標準法13加2日",
        ),
        "43": (
            "1984-08-01",
            "沿革1：七十三年七月三十日制定，後續未改本條；第86條自公布日施行，加2日",
        ),
    },
    "O02": {
        "5": ("1997-06-14", "沿革2：八十六年六月十二日；第51條自發布日施行，加2日"),
        "7": ("2017-06-18", "沿革14：一百零六年六月十六日；第51條自發布日施行，加2日"),
        "24": ("2017-06-18", "沿革14：一百零六年六月十六日；第51條自發布日施行，加2日"),
        "24-1": (
            "2018-03-01",
            "沿革15：一百零七年二月二十七日；第51條自發布日施行，加2日",
        ),
    },
    "O03": {
        "2": (
            "2026-10-01",
            "沿革9：一百十五年九月三十日；第12條明定一百十五年十月一日施行",
        ),
        "3": ("2011-10-16", "沿革5：一百年十月十四日；第12條自發布日施行，加2日"),
        "4": ("2010-05-06", "沿革4：九十九年五月四日；第12條自發布日施行，加2日"),
        "5": (
            "1985-03-22",
            "沿革1：七十四年三月二十日制定，後續未改本條；第12條自發布日施行，加2日",
        ),
        "6": ("2019-01-17", "沿革6：一百零八年一月十五日；第12條自發布日施行，加2日"),
        "7": (
            "2026-01-01",
            "沿革8：一百十四年十二月九日；第12條明定一百十五年一月一日施行",
        ),
        "8": (
            "1985-03-22",
            "沿革1：七十四年三月二十日制定，後續未改本條；第12條自發布日施行，加2日",
        ),
        "9": (
            "2026-01-01",
            "沿革8：一百十四年十二月九日；第12條明定一百十五年一月一日施行",
        ),
        "9-1": (
            "2026-01-01",
            "沿革8：一百十四年十二月九日增訂；第12條明定一百十五年一月一日施行",
        ),
        "10": (
            "1985-03-22",
            "沿革1：七十四年三月二十日制定，後續未改本條；第12條自發布日施行，加2日",
        ),
    },
    "O04": {
        "14": (
            "2014-12-13",
            "沿革7：一百零三年十二月十一日；第40條本次修正自公布日施行，加2日",
        ),
        "15": (
            "2022-01-18",
            "沿革9：一百十一年一月十二日；一百十一年一月十七日行政院院臺勞字第1110001084號令定一百十一年一月十八日施行",
        ),
        "16": (
            "2014-12-13",
            "沿革7：一百零三年十二月十一日；第40條本次修正自公布日施行，加2日；非97年版第16條",
        ),
        "20": (
            "2011-01-07",
            "沿革4：一百年一月五日；第40條本次修正自公布日施行，加2日",
        ),
        "21": (
            "2008-01-18",
            "沿革2：九十七年一月十六日；第40條本次修正自公布日施行，加2日；另定施行日的第16條不在此列",
        ),
    },
}
DATE_RULE = "https://law.moj.gov.tw/LawClass/LawSingle.aspx?flno=13&pcode=A0030133"


def save_json(path, data):
    content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists() and path.read_bytes() != content:
        raise ValueError("existing_artifact_differs_requires_review")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def base_record(document_id, version, title, raw_path, sections):
    normalized_path = ROOT / f"data/normalized/{document_id}-{version}.json"
    digest = save_json(
        normalized_path,
        {
            "document_id": document_id,
            "version_id": version,
            "title": title,
            "sections": sections,
        },
    )
    return {
        "document_id": document_id,
        "version_id": version,
        "title": title,
        "source_type": "official" if document_id.startswith("O") else "company",
        "source_url": None,
        "is_synthetic": document_id.startswith("C"),
        "published_at": None,
        "revised_at": None,
        "effective_from": None,
        "effective_to": None,
        "allowed_roles": ["employee", "manager", "hr"],
        "content_sha256": digest,
        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "review_status": "pending",
        "reviewer": None,
        "raw_path": raw_path.relative_to(ROOT).as_posix(),
        "normalized_path": normalized_path.relative_to(ROOT).as_posix(),
        "last_reviewed_at": None,
        "next_review_due": None,
    }


def main():
    metadata = json.loads((RAW / "sources.json").read_text(encoding="utf-8"))
    documents = []
    for key, title in TITLES.items():
        source = metadata[key]
        raw_path = ROOT / source["path"]
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("source_hash_mismatch")
        page = raw_path.read_text(encoding="utf-8")
        qa = extract_qa(page) if key not in SECTIONS else None
        sections = [qa["section"]] if qa else extract_law(page, list(SECTIONS[key]))
        record = base_record(key, VERSION, title, raw_path, sections)
        record.update(
            {
                "source_url": source["source_url"],
                "fetched_at": source["fetched_at"],
                "source_publisher": "全國法規資料庫（法務部）" if not qa else "勞動部",
                "maintenance_owner": "專案資料維護者",
                "author": "官方原文；Codex擷取整理（待人工核對）",
            }
        )
        if qa:
            evidence = (
                f"依問答發布日期，非法規生效日：發布日期:{qa['published_at']}；"
                f"項目更新日期:{qa['item_updated_at']}，尚無內容變更比對證據，revised_at留空；不使用網站頁尾更新日。"
                f"原文 {source['path']}；{source['source_url']}"
            )
            record.update(
                published_at=qa["published_at"],
                effective_from=qa["published_at"],
                date_evidence=evidence,
                indexed_sections=[
                    dict(
                        section_id="qa",
                        effective_from=qa["published_at"],
                        effective_to=None,
                        date_evidence=evidence,
                    )
                ],
            )
        else:
            published, revised, commencement = DATES[key]
            history = metadata[key + "-history"]
            if (
                hashlib.sha256((ROOT / history["path"]).read_bytes()).hexdigest()
                != history["sha256"]
            ):
                raise ValueError("history_hash_mismatch")
            basis = (
                f"全文 {source['path']} 第{commencement}條；沿革 {history['path']}；"
                f"{history['source_url']}；自公布／發布日施行之第三日規則 {DATE_RULE}。"
            )
            record.update(
                published_at=roc_to_iso(published),
                revised_at=roc_to_iso(revised),
                effective_from=min(v[0] for v in SECTIONS[key].values()),
                date_evidence=f"制定／發布：{published}；最後修正日期：{revised}。{basis}文件起日取索引條文最早起日，逐條日期才是有效性依據；不代表完整歷史版本庫。",
                indexed_sections=[
                    dict(
                        section_id=s,
                        effective_from=v[0],
                        effective_to=None,
                        date_evidence=v[1] + "。" + basis,
                    )
                    for s, v in SECTIONS[key].items()
                ],
            )
        documents.append(record)
    for draft in json.loads(
        (ROOT / "scripts/company_drafts.json").read_text(encoding="utf-8")
    ):
        key, version = draft["document_id"], draft["version_id"]
        raw_path = ROOT / f"data/raw/company/{key}-{version}.md"
        record = base_record(key, version, draft["title"], raw_path, draft["sections"])
        start, end = draft["effective_from"], draft["effective_to"]
        evidence = (
            "虛構示範公司設定，非真實公布或法規日期；"
            f"區間[{start}, {end or '無迄日'})。"
            "Codex於2026-10-18草擬，待使用者核對；有效日起日僅為版本測試。"
        )
        record.update(
            published_at=start,
            revised_at=start if version == "v2" else None,
            effective_from=start,
            effective_to=end,
            date_evidence=evidence,
            fetched_at=datetime.fromtimestamp(
                raw_path.stat().st_mtime, timezone.utc
            ).isoformat(),
            source_publisher="專案自編（虛構示範）",
            maintenance_owner="專案制度維護者",
            author="Codex (LLM draft)",
            indexed_sections=[
                dict(
                    section_id=s["section_id"],
                    effective_from=start,
                    effective_to=end,
                    date_evidence=evidence,
                )
                for s in draft["sections"]
            ],
        )
        if key == "C03":
            record["allowed_roles"] = ["manager", "hr"]
        elif key == "C04":
            record["allowed_roles"] = ["hr"]
        documents.append(record)
    save_json(
        ROOT / "data/manifest.json", {"schema_version": 1, "documents": documents}
    )
    print("Prepared 10 documents / 11 versions, all pending human review.")


if __name__ == "__main__":
    main()
