from docx_extract.answer import is_option_marker, render_marker

def test_detect_marker():
    assert is_option_marker("A.")
    assert is_option_marker(" B) ")
    assert not is_option_marker("Chọn D.")
    assert not is_option_marker("Nhóm I.")

def test_marker_plain_when_not_underlined():
    # fmt = (bold, italic, vert, underline)
    assert render_marker("B.", (True, False, None, False)) == "B."

def test_marker_star_when_underlined():
    assert render_marker("D.", (True, False, None, True)) == "*D."
