import struct
import zipfile
from pathlib import Path

from lxml import etree
import pytest

from docx_extract import clean_docx, ns
from docx_extract.context import Context
from docx_extract.mathnative import UnsupportedMath, mtef_to_latex, ole_to_latex


def char(text, embell=None, face=3):
    value = b"\x02"+bytes([1 if embell else 0,face+128])+struct.pack("<H",ord(text))
    return value + (b"\x06\x00"+bytes([embell])+b"\0" if embell else b"")


def line(*children):
    return b"\x01\x00"+b"".join(children)+b"\0"


def template(selector, *slots, variation=0):
    return b"\x03\0"+bytes([selector,variation,0])+b"".join(slots)+b"\0"


def equation(*children):
    return b"\x05\x01\x00\x07\x00DSMT7\0\x01"+line(*children)+b"\0"


def test_fraction_scripts_vectors_and_prescripts_keep_structure():
    fraction = template(11,line(char("a")),line(char("b")))
    assert mtef_to_latex(equation(fraction)) == r"\frac{a}{b}"
    scripts = template(29,line(char("i")),line(char("2")))
    assert mtef_to_latex(equation(char("x"),scripts)) == r"{x}_{i}^{2}"
    assert mtef_to_latex(equation(char("B",11))) == r"\vec{B}"
    pre = template(29,line(char("1")),line(char("2")),variation=1)
    assert mtef_to_latex(equation(pre,char("H"))) == r"{}_{1}^{2}H"


def test_truncated_unknown_or_unsupported_content_is_rejected():
    valid = equation(char("x"))
    for data in [valid[:-2],valid+b"\x02",equation(b"\x63"),equation(char(chr(0xF123))),
                 equation(char("x",37)),equation(template(36,line(char("x"))))]:
        with pytest.raises(UnsupportedMath):
            mtef_to_latex(data)


def test_custom_typeface_requires_known_font_and_preserves_bold():
    header = b"\x05\x01\x00\x07\x00DSMT7\0\x01"
    definitions = b"\x11\x05Times New Roman\0\x08\x01\x03"
    assert mtef_to_latex(header+definitions+line(char("x",face=-1))+b"\0") == r"\boldsymbol{x}"
    unknown = definitions.replace(b"Times New Roman",b"Unknown Symbol Font")
    with pytest.raises(UnsupportedMath,match="custom typeface"):
        mtef_to_latex(header+unknown+line(char("x",face=-1))+b"\0")


def test_real_sample_is_complete_without_ocr_and_keeps_sidecars(monkeypatch):
    monkeypatch.delenv("DOCX_EXTRACT_OCR_ENDPOINT",raising=False)
    monkeypatch.setenv("DOCX_EXTRACT_NATIVE_MATH","1")
    path=Path(__file__).parent/"fixtures/sample.docx"
    markup, context = clean_docx(path)
    assert context.ocr_stats["native_success"] == 16
    assert context.ocr_stats["http_requests"] == context.ocr_stats["failures"] == 0
    assert all(a.get("latex") for a in context.manifest if a["type"] == "mathtype")
    with zipfile.ZipFile(path) as z:
        assert ole_to_latex(z.read("word/embeddings/oleObject7.bin")) == r"\vec{B}"
    monkeypatch.setenv("DOCX_EXTRACT_NATIVE_MATH","0")
    old_markup,old_context=clean_docx(path)
    assert markup==old_markup and context.written==old_context.written and context.counter==old_context.counter


def test_invalid_native_formula_falls_back_to_ocr(monkeypatch):
    monkeypatch.setenv("DOCX_EXTRACT_NATIVE_MATH","1")
    obj=etree.fromstring(f'<w:object xmlns:w="{ns.W[1:-1]}" xmlns:v="{ns.V[1:-1]}" xmlns:o="{ns.O[1:-1]}" xmlns:r="{ns.R[1:-1]}"><v:imagedata r:id="image"/><o:OLEObject ProgID="Equation.DSMT4" r:id="ole"/></w:object>')
    context=Context(rels={"image":"render.wmf","ole":"equation.bin"},assets={"render.wmf":b"original","equation.bin":b"invalid"},defer_ocr=True)
    assert context.ole(obj)=="[!m:$mathtype_1$]"
    class Client:
        stats={"total":1,"failures":0,"http_requests":1}
        def recognize(self, jobs):
            assert jobs==[("mathtype_1",b"original","wmf")]
            return {"mathtype_1":{"latex":"x","error":""}}
    context.resolve_ocr(Client())
    assert context.manifest[0]["latex"]=="x" and context.manifest[0]["native_error"]
    assert context.ocr_stats["native_success"]==0 and context.ocr_stats["native_fallback"]==1
    assert context.ocr_stats["failures"]==0 and context.written["mathtype_1.wmf"]==b"original"
