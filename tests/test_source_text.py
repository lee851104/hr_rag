import pytest

from hr_rag.corpus.source_text import extract_law, extract_qa


def test_law_preserves_all_paragraphs_and_ignores_navigation():
    page = """<div class="row"><div class="col-no"><a name="24-1">第 24-1 條</a>
    </div><div class="col-data"><div class="law-article">
    <div class="line-0000">原則<strong>完整</strong>。</div>
    <div class="line-0004">但有例外 &amp; 條件。</div></div></div></div>
    <footer>網站更新日期2026-10-18</footer>"""
    assert extract_law(page, ["24-1"]) == [
        {
            "section_id": "24-1",
            "title": "第 24-1 條",
            "text": "原則完整。\n但有例外 & 條件。",
        }
    ]


@pytest.mark.parametrize("page", ["", '<a name="2">第 2 條</a>'])
def test_missing_article_is_not_silently_omitted(page):
    with pytest.raises(ValueError, match="article_missing_or_empty"):
        extract_law(page, ["2"])


def test_qa_publication_is_not_footer_update():
    page = """<th>問題</th><td>如何辦理？</td><tr><th>答案</th>
    <td><p>規則一。</p><p>但書二。</p></td></tr>
    發布日期:2025-07-07 更新日期:2026-04-23
    <footer>網站更新日期:2026-10-18</footer>"""
    result = extract_qa(page)
    assert result["published_at"] == "2025-07-07"
    assert result["item_updated_at"] == "2026-04-23"
    assert result["section"]["text"] == "問：如何辦理？\n答：規則一。\n但書二。"


def test_qa_missing_answer_fails_closed():
    with pytest.raises(ValueError, match="qa_missing_or_empty"):
        extract_qa("發布日期:2025-07-07")


def test_qa_preserves_exception_in_list_and_trailing_text():
    page = """<th>問題</th><td>如何辦理？</td><tr><th>答案</th>
    <td><p>一般規則。</p><ul><li>必要例外。</li></ul>補充限制。</td></tr>
    發布日期:2025-07-07 更新日期:2026-04-23"""
    assert extract_qa(page)["section"]["text"] == (
        "問：如何辦理？\n答：一般規則。\n必要例外。\n補充限制。"
    )
