from pathlib import Path
from lxml import etree
from docx_extract import clean_docx, ns

DOCX = Path(__file__).parent / "fixtures" / "sample.docx"

def test_clean_docx_runs_endtoend():
    markup, ctx = clean_docx(DOCX)
    assert "Câu 1" in markup
    assert "PHẦN I" in markup
    assert "[!m:$mathtype_" in markup       # có placeholder MathType
    assert "[img:$img_" in markup            # có ảnh
    assert ctx.written                        # có asset trích ra
    # không có định dạng rác lọt vào
    assert "w:color" not in markup


def test_clean_docx_no_anchor_emits_full_body_with_warning(monkeypatch):
    # Critical fix: một docx KHÔNG có bất kì đoạn nào bắt đầu bằng
    # "PHẦN"/"Nhóm"/"Câu" (đề khác cấu trúc, heading khác wording, hoặc
    # không có heading) không được phép âm thầm trả về markup rỗng.
    from docx_extract import assemble
    from docx_extract.loader import Document

    body_xml = (
        f'<w:body xmlns:w="{ns.W[1:-1]}">'
        '<w:p><w:r><w:t>Đề không có heading chuẩn</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Một số nội dung khác cần được giữ lại</w:t></w:r></w:p>'
        '</w:body>'
    )
    body = etree.fromstring(body_xml)
    doc = Document(body=body, rels={}, assets={})

    monkeypatch.setattr(assemble, "load", lambda path, **kwargs: doc)

    markup, ctx = assemble.clean_docx("dummy.docx")
    assert markup.strip() != ""
    assert "Đề không có heading chuẩn" in markup
    assert "Một số nội dung khác cần được giữ lại" in markup
    assert any("no PHẦN/Nhóm/Câu anchor found" in w for w in ctx.warnings)


def test_reading_passage_and_data_table_before_first_question_are_preserved(monkeypatch):
    from docx_extract import assemble
    from docx_extract.loader import Document

    body = etree.fromstring(
        f'<w:body xmlns:w="{ns.W[1:-1]}">'
        '<w:p><w:r><w:t>Đọc ngữ liệu sau và trả lời câu hỏi:</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Đây là đoạn văn bắt buộc để làm bài.</w:t></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cho biết: H = 1</w:t></w:r>'
        '</w:p></w:tc></w:tr></w:tbl>'
        '<w:p><w:r><w:t>Câu 1: Dựa vào ngữ liệu trên.</w:t></w:r></w:p>'
        '</w:body>'
    )
    monkeypatch.setattr(assemble, "load", lambda _, **kwargs: Document(body, {}, {}))
    markup, _ = assemble.extract_docx("unused.docx")
    assert markup.splitlines() == [
        "Đọc ngữ liệu sau và trả lời câu hỏi:",
        "Đây là đoạn văn bắt buộc để làm bài.",
        "[* Cho biết: H = 1 *]",
        "Câu 1: Dựa vào ngữ liệu trên.",
    ]
