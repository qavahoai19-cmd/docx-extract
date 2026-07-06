from lxml import etree
from docx_extract.context import Context
from docx_extract import ns

def _ctx(rels=None, assets=None):
    return Context(rels=rels or {}, assets=assets or {})

def test_global_counter_shared_across_types():
    c = _ctx()
    m = etree.fromstring(f'<m:oMath xmlns:m="{ns.M[1:-1]}"><m:r/></m:oMath>')
    assert c.omml(m) == "[!m:$mathml_1$]"
    # ảnh kế tiếp lấy số 2 (chung bộ đếm)
    draw = etree.fromstring(
        f'<w:drawing xmlns:w="{ns.W[1:-1]}" xmlns:a="{ns.A[1:-1]}" xmlns:r="{ns.R[1:-1]}">'
        f'<a:blip r:embed="rId9"/></w:drawing>')
    c2 = Context(rels={"rId9": "word/media/image14.png"}, assets={"word/media/image14.png": b"PNG"})
    c2.counter = 1
    assert c2.image(draw) == "[img:$img_2$]"
    assert c2.written["img_2.png"] == b"PNG"

def test_omml_fragment_saved():
    c = _ctx()
    m = etree.fromstring(f'<m:oMath xmlns:m="{ns.M[1:-1]}"><m:r/></m:oMath>')
    c.omml(m)
    assert "mathml_1.xml" in c.written
    assert b"oMath" in c.written["mathml_1.xml"]

def test_missing_rid_warns_but_emits():
    c = _ctx()
    draw = etree.fromstring(
        f'<w:drawing xmlns:w="{ns.W[1:-1]}" xmlns:a="{ns.A[1:-1]}" xmlns:r="{ns.R[1:-1]}">'
        f'<a:blip r:embed="rNope"/></w:drawing>')
    assert c.image(draw) == "[img:$img_1$]"
    assert c.warnings


def _w_object(progid, rid="rId5"):
    ole_attrs = f'ProgID="{progid}"' if progid is not None else ""
    return etree.fromstring(
        f'<w:object xmlns:w="{ns.W[1:-1]}" xmlns:v="{ns.V[1:-1]}" '
        f'xmlns:o="{ns.O[1:-1]}" xmlns:r="{ns.R[1:-1]}">'
        f'<v:shape><v:imagedata r:id="{rid}"/></v:shape>'
        f'<o:OLEObject Type="Embed" {ole_attrs}/>'
        '</w:object>'
    )


def test_ole_equation_object_emits_mathtype():
    # ProgID chứa "Equation" (Equation.DSMT4 / Equation.3) -> hành vi cũ,
    # không đổi: placeholder mathtype_N, bộ đếm tăng, asset ghi ra.
    c = Context(
        rels={"rId5": "word/embeddings/oleObject1.wmf"},
        assets={"word/embeddings/oleObject1.wmf": b"WMF"},
    )
    w_obj = _w_object("Equation.DSMT4")
    assert c.ole(w_obj) == "[!m:$mathtype_1$]"
    assert c.counter == 1
    assert c.written["mathtype_1.wmf"] == b"WMF"
    assert not c.warnings


def test_ole_non_equation_object_skipped_with_warning():
    # w:object không phải OLE Equation (vd Excel.Sheet.12) -> không sinh
    # placeholder mathtype, không tiêu số bộ đếm, có cảnh báo ghi lại.
    c = Context(
        rels={"rId5": "word/embeddings/oleObject1.xlsx"},
        assets={"word/embeddings/oleObject1.xlsx": b"XLSX"},
    )
    w_obj = _w_object("Excel.Sheet.12")
    assert c.ole(w_obj) is None
    assert c.counter == 0
    assert not c.written
    assert c.warnings
    assert "Excel.Sheet.12" in c.warnings[0]


def test_ole_missing_progid_skipped_with_warning():
    c = _ctx()
    w_obj = _w_object(None)
    assert c.ole(w_obj) is None
    assert c.counter == 0
    assert c.warnings
