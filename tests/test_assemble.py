from docx_extract import clean_docx

DOCX = r"C:\Users\admin\Downloads\ĐỀ VẬT LÍ LẦN 3_VER 2 (2).docx"

def test_clean_docx_runs_endtoend():
    markup, ctx = clean_docx(DOCX)
    assert "Câu 1" in markup
    assert "PHẦN I" in markup
    assert "[!m:$mathtype_" in markup       # có placeholder MathType
    assert "[img:$img_" in markup            # có ảnh
    assert ctx.written                        # có asset trích ra
    # không có định dạng rác lọt vào
    assert "w:color" not in markup
