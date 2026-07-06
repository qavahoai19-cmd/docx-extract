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
