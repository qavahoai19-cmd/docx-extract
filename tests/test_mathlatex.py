from lxml import etree
from docx_extract.mathlatex import omml_to_latex
from docx_extract import ns

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
