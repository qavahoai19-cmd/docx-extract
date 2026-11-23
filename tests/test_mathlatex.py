from lxml import etree
from docx_extract.mathlatex import omml_to_latex
from docx_extract import ns
import pytest

def _omath(inner: str):
    return etree.fromstring(
        f'<m:oMath xmlns:m="{ns.M[1:-1]}">{inner}</m:oMath>')

def _r(t):  # m:r run
    return f'<m:r><m:t>{t}</m:t></m:r>'

def test_plain_run():
    assert omml_to_latex(_omath(_r("x") + _r("+") + _r("1"))) == "x+1"

def test_fraction():
    frac = f'<m:f><m:num>{_r("a")}</m:num><m:den>{_r("b")}</m:den></m:f>'
    assert omml_to_latex(_omath(frac)) == r"\frac{a}{b}"

def test_superscript():
    sup = f'<m:sSup><m:e>{_r("x")}</m:e><m:sup>{_r("2")}</m:sup></m:sSup>'
    assert omml_to_latex(_omath(sup)) == "x^{2}"

def test_subscript():
    sub = f'<m:sSub><m:e>{_r("a")}</m:e><m:sub>{_r("n")}</m:sub></m:sSub>'
    assert omml_to_latex(_omath(sub)) == "a_{n}"

def test_radical_default_sqrt():
    rad = f'<m:rad><m:deg/><m:e>{_r("2")}</m:e></m:rad>'
    assert omml_to_latex(_omath(rad)) == r"\sqrt{2}"

def test_delimiter_parens():
    d = f'<m:d><m:e>{_r("x")}</m:e></m:d>'
    assert omml_to_latex(_omath(d)) == r"\left(x\right)"


@pytest.mark.parametrize("glyph,command", [("⃗", r"\vec"), ("→", r"\overrightarrow"),
    ("ˆ", r"\hat"), ("¯", r"\bar")])
def test_accents_use_original_symbol(glyph, command):
    xml = f'<m:acc><m:accPr><m:chr m:val="{glyph}"/></m:accPr><m:e>{_r("n")}</m:e></m:acc>'
    assert omml_to_latex(_omath(xml)) == command + "{n}"


def test_default_accent_stays_hat():
    assert omml_to_latex(_omath(f'<m:acc><m:e>{_r("x")}</m:e></m:acc>')) == r"\hat{x}"


def test_overline_and_chemical_arrow_are_not_dropped():
    assert omml_to_latex(_omath(f'<m:bar><m:e>{_r("B")}</m:e></m:bar>')) == r"\overline{B}"
    arrow = '<m:groupChr><m:groupChrPr><m:chr m:val="⇄"/><m:vertJc m:val="bot"/></m:groupChrPr><m:e>' + _r("\u2003\u2003") + '</m:e></m:groupChr>'
    assert omml_to_latex(_omath(arrow)) == r"\rightleftarrows"


def test_invisible_delimiter_and_equation_array():
    xml = f'<m:d><m:dPr><m:begChr m:val=""/><m:endChr m:val=")"/></m:dPr><m:e>{_r("x")}</m:e></m:d>'
    assert omml_to_latex(_omath(xml)) == r"\left.x\right)"
    array = f'<m:eqArr><m:e>{_r("x=1")}</m:e><m:e>{_r("y=2")}</m:e></m:eqArr>'
    assert omml_to_latex(_omath(array)) == r"\begin{aligned}x=1\\y=2\end{aligned}"


@pytest.mark.parametrize("xml", ['<m:futureMath><m:r><m:t>x</m:t></m:r></m:futureMath>',
    '<m:acc><m:accPr><m:chr m:val="?"/></m:accPr><m:e><m:r><m:t>x</m:t></m:r></m:e></m:acc>'])
def test_unknown_structures_are_rejected_without_partial_latex(xml):
    assert omml_to_latex(_omath(xml)) is None


def test_arc_and_repeated_arrow_keep_their_shape():
    arc = f'<m:groupChr><m:groupChrPr><m:chr m:val="⏜"/><m:pos m:val="top"/></m:groupChrPr><m:e>{_r("MN")}</m:e></m:groupChr>'
    assert omml_to_latex(_omath(arc)) == r"\overset{\frown}{MN}"
    arrow = '<m:groupChr><m:groupChrPr><m:chr m:val="⇇"/></m:groupChrPr><m:e/></m:groupChr>'
    assert omml_to_latex(_omath(arrow)) == r"\leftleftarrows"


def test_word_line_break_inside_equation_does_not_discard_content():
    xml = etree.fromstring(f'<m:oMath xmlns:m="{ns.M[1:-1]}" xmlns:w="{ns.W[1:-1]}"><m:r><m:t>x</m:t><w:br/><m:t>y</m:t><w:lastRenderedPageBreak/></m:r></m:oMath>')
    assert omml_to_latex(xml) == r"x\allowbreak y"


def test_integral_command_does_not_merge_with_its_variable():
    expression = f'<m:nary><m:naryPr><m:chr m:val="∫"/></m:naryPr><m:e>{_r("f")}</m:e></m:nary>'
    assert omml_to_latex(_omath(expression)) == r"\int f"
