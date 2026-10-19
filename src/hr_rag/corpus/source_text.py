"""Extract selected full articles and complete Q&A from saved official HTML."""

import html
import re
from datetime import date


def _clean(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def extract_law(page: str, section_ids: list[str]) -> list[dict]:
    articles = {}
    for row in re.split(r'<div class="row">', page):
        match = re.search(r'<a[^>]*\bname="([0-9-]+)"[^>]*>(.*?)</a>', row, re.S)
        if not match or '<div class="law-article">' not in row:
            continue
        lines = re.findall(r'<div class="line-\d+[^"]*">(.*?)</div>', row, re.S)
        lines = [_clean(line) for line in lines]
        key = match.group(1)
        if key in articles:
            raise ValueError("duplicate_article")
        articles[key] = {
            "section_id": key,
            "title": _clean(match.group(2)),
            "text": "\n".join(line for line in lines if line),
        }
    if any(key not in articles or not articles[key]["text"] for key in section_ids):
        raise ValueError("article_missing_or_empty")
    return [articles[key] for key in section_ids]


def extract_qa(page: str) -> dict:
    try:
        question = _clean(
            re.search(r"<th[^>]*>問題</th>\s*<td>(.*?)</td", page, re.S).group(1)
        )
        answer = re.search(r"<th>答案</th>\s*<td>(.*?)</td>\s*</tr>", page, re.S).group(
            1
        )
        paragraphs = [
            _clean(p)
            for p in re.split(r"</(?:p|li|div|tr)>|<br\s*/?>", answer, flags=re.I)
        ]
        paragraphs = [p for p in paragraphs if p]
        published = re.search(r"發布日期:(\d{4}-\d{2}-\d{2})", page).group(1)
        updated = re.search(r"(?<!網站)更新日期:(\d{4}-\d{2}-\d{2})", page).group(1)
        date.fromisoformat(published)
        date.fromisoformat(updated)
        if not question or not paragraphs:
            raise ValueError
    except (AttributeError, ValueError) as exc:
        raise ValueError("qa_missing_or_empty") from exc
    return {
        "published_at": published,
        "item_updated_at": updated,
        "section": {
            "section_id": "qa",
            "title": question,
            "text": "\n".join(
                ["問：" + question, "答：" + paragraphs[0], *paragraphs[1:]]
            ),
        },
    }
