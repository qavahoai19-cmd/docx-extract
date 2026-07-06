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
