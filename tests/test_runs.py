from lxml import etree
from docx_extract.runs import render_paragraph
from docx_extract import ns

def _p(xml_inner: str):
    xml = f'<w:p xmlns:w="{ns.W[1:-1]}">{xml_inner}</w:p>'
    return etree.fromstring(xml)

def _run(text, b=False, i=False, vert=None, u=False):
    rpr = "<w:rPr>"
    if b: rpr += "<w:b/>"
    if i: rpr += "<w:i/>"
    if vert: rpr += f'<w:vertAlign w:val="{vert}"/>'
    if u: rpr += '<w:u w:val="single"/>'
    rpr += "</w:rPr>"
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'

def test_plain_text():
    assert render_paragraph(_p(_run("Nội năng")), None) == "Nội năng"

def test_bold():
    assert render_paragraph(_p(_run("không", b=True)), None) == "[!b:$không$]"

def test_bold_italic():
    assert render_paragraph(_p(_run("a", b=True, i=True)), None) == "[!b!i:$a$]"

def test_superscript():
    assert render_paragraph(_p(_run("2", vert="superscript")), None) == "[!sup:$2$]"

def test_subscript():
    assert render_paragraph(_p(_run("0", vert="subscript")), None) == "[!sub:$0$]"

def test_merge_adjacent_same_format():
    inner = _run("ab", b=True) + _run("cd", b=True)
    assert render_paragraph(_p(inner), None) == "[!b:$abcd$]"

def test_no_merge_different_format():
    inner = _run("a", b=True) + _run("b")
    assert render_paragraph(_p(inner), None) == "[!b:$a$]b"

def test_option_letters_are_stripped_and_correct_starred():
    inner = (_run("A.", b=True) + _run(" nóng chảy.")
             + _run("D.", b=True, u=True) + _run(" ngưng tụ."))
    got = render_paragraph(_p(inner), None)
    assert "A. nóng chảy." in got
    assert "*D. ngưng tụ." in got
    assert "[!b:$A.$]" not in got


def test_simple_field_keeps_result_text_but_not_instruction():
    inner = (_run("Trước ") + '<w:fldSimple w:instr=" MERGEFIELD question ">'
             + _run("nội dung câu hỏi", b=True) + '</w:fldSimple>' + _run(" sau"))
    assert render_paragraph(_p(inner), None) == "Trước [!b:$nội dung câu hỏi$] sau"


def test_special_run_characters_preserve_word_boundaries():
    inner = ('<w:r><w:t>một</w:t><w:cr/><w:t>hai</w:t><w:tab/>'
             '<w:t>ba</w:t><w:noBreakHyphen/><w:t>bốn</w:t>'
             '<w:softHyphen/><w:t>năm</w:t></w:r>')
    assert render_paragraph(_p(inner), None) == "một\nhai    ba\u2011bốn\u00adnăm"


def test_symbol_font_math_characters_are_decoded_in_source_order():
    from docx_extract.context import Context

    inner = '<w:r><w:t>x</w:t>' + ''.join(
        f'<w:sym w:font="Symbol" w:char="{code}"/>'
        for code in ("F0AE", "F057", "F044", "F02D", "F077", "F06A", "F070", "F0D6", "F0B4")
    ) + '<w:t>y</w:t></w:r>'
    ctx = Context({}, {})
    assert render_paragraph(_p(inner), ctx) == "x→ΩΔ−ωϕπ√×y"
    assert not ctx.warnings


def test_unknown_symbol_is_preserved_with_a_warning():
    from docx_extract.context import Context

    ctx = Context({}, {})
    markup = render_paragraph(_p('<w:r><w:sym w:font="Custom" w:char="F099"/></w:r>'), ctx)
    assert markup == "\uf099"
    assert any("Custom" in warning and "F099" in warning for warning in ctx.warnings)


def test_unknown_inline_wrapper_keeps_visible_text_but_skips_deleted_text():
    inner = ('<w:unknown>' + _run("còn lại") + '</w:unknown>'
             '<w:del>' + _run("đã xóa") + '</w:del>'
             '<w:moveFrom>' + _run("đã chuyển") + '</w:moveFrom>'
             '<w:ins>' + _run(" mới") + '</w:ins>')
    assert render_paragraph(_p(inner), None) == "còn lại mới"


def test_correct_option_letter_and_period_in_separate_runs():
    # Physics exam: only the letter is underlined; the period has another rPr.
    inner = (_run("A.", b=True) + _run(" Nhôm.    ")
             + _run("D", b=True, u=True) + _run(".", b=True) + _run(" Sắt non."))
    assert render_paragraph(_p(inner), None) == "A. Nhôm.    *D. Sắt non."


def test_correct_marker_is_preserved_when_entire_answer_is_one_underlined_run():
    inner = _run("B. cường độ biến thiên điều hòa theo thời gian.", b=True, u=True)
    assert render_paragraph(_p(inner), None) == "*B.[!b!u:$ cường độ biến thiên điều hòa theo thời gian.$]"


def test_marker_can_span_three_formats_without_changing_answer_content():
    inner = (_run("A") + _run(".", b=True) + _run(" Một    ")
             + _run("B", b=True, u=True) + _run(".", i=True) + _run(" Hai"))
    assert render_paragraph(_p(inner), None) == "A. Một    *B. Hai"


def test_disabled_word_formatting_does_not_create_a_correct_answer():
    inner = ('<w:r><w:rPr><w:b w:val="0"/><w:i w:val="false"/>'
             '<w:u w:val="none"/></w:rPr><w:t>A.</w:t></w:r>' + _run(" Một"))
    assert render_paragraph(_p(inner), None) == "A. Một"


def test_underlined_option_reference_inside_a_sentence_is_not_an_answer_marker():
    inner = _run("Hãy giải thích vì sao chọn ") + _run("B.", u=True)
    assert render_paragraph(_p(inner), None) == "Hãy giải thích vì sao chọn [!u:$B.$]"


def test_highlighted_answer_content_marks_its_option_with_plain_letter():
    inner = (_run('A. concern    B. ') + '<w:r><w:rPr><w:highlight w:val="yellow"/>'
             '</w:rPr><w:t>affordable</w:t></w:r>' + _run('    C. convenience    D. colonial'))
    assert '*B. affordable' in render_paragraph(_p(inner), None)


def test_pronunciation_underlines_do_not_mark_other_answers_correct():
    inner = (_run('A. c') + _run('o', u=True) + _run('ncern    B. ')
             + '<w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr><w:t>aff</w:t></w:r>'
             '<w:r><w:rPr><w:highlight w:val="yellow"/><w:u w:val="single"/></w:rPr><w:t>o</w:t></w:r>'
             '<w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr><w:t>rdable</w:t></w:r>'
             + _run('    C. c') + _run('o', u=True) + _run('nvenience'))
    got = render_paragraph(_p(inner), None)
    assert '*B.' in got and '*A.' not in got and '*C.' not in got
    assert 'c[!u:$o$]ncern' in got


def test_highlighted_first_option_after_english_question_number():
    inner = (_run('Question 3. A. ', b=True)
             + '<w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr><w:t>afford</w:t></w:r>')
    assert '*A. afford' in render_paragraph(_p(inner), None)


def test_background_shading_on_answer_text_is_detected():
    inner = (_run('C. ') + '<w:r><w:rPr><w:shd w:val="clear" w:fill="FFFF00"/>'
             '</w:rPr><w:t>infrastructure</w:t></w:r>')
    assert render_paragraph(_p(inner), None) == '*C. infrastructure'


def test_color_bold_and_highlighted_whitespace_are_not_answer_signals():
    inner = ('<w:r><w:rPr><w:b/><w:color w:val="0000FF"/></w:rPr><w:t>A. </w:t></w:r>'
             '<w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr><w:t> </w:t></w:r>'
             + _run('concern    B. affordable'))
    assert '*' not in render_paragraph(_p(inner), None)


def test_highlighted_instruction_does_not_mark_plain_options():
    inner = ('<w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr><w:t>Choose one:</w:t></w:r>'
             '<w:r><w:br/></w:r>' + _run('A. one    B. two    C. three    D. four'))
    assert '*' not in render_paragraph(_p(inner), None)


def test_highlights_in_several_questions_in_one_paragraph_are_detected():
    marked = '<w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr><w:t>{}</w:t></w:r>'
    inner = (_run('Question 17. A. a B. b C. ') + marked.format('c')
             + _run(' D. d Question 18. A. e B. f C. g D. ') + marked.format('h'))
    result = render_paragraph(_p(inner), None)
    assert '*C. c' in result and '*D. h' in result


def test_underlined_tab_is_preserved_as_a_fill_in_blank():
    inner = (_run('The city’s') + '<w:r><w:rPr><w:u w:val="single"/></w:rPr><w:tab/></w:r>'
             + _run('needs upgrading.'))
    assert render_paragraph(_p(inner), None) == 'The city’s[!u:$    $]needs upgrading.'


def test_symbol_private_use_text_decodes_omega_only_for_symbol_fonts():
    template = '<w:r><w:rPr><w:rFonts w:ascii="{}"/></w:rPr><w:t>\uf077</w:t></w:r>'
    assert render_paragraph(_p(template.format('Symbol')), None) == '\u03c9'
    assert render_paragraph(_p(template.format('Euclid Symbol')), None) == '\u03c9'
    assert render_paragraph(_p(template.format('Arial')), None) == '\uf077'
