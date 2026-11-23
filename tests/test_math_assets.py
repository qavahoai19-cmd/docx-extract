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


def test_unsupported_math_preserves_source_and_counts_failure():
    c = _ctx()
    xml = etree.fromstring(f'<m:oMath xmlns:m="{ns.M[1:-1]}"><m:futureMath><m:r><m:t>x</m:t></m:r></m:futureMath></m:oMath>')
    original = etree.tostring(xml, encoding="utf-8")
    c.omml(xml)
    c.resolve_ocr()
    assert c.manifest[0]["latex"] is None
    assert c.manifest[0]["review_required"]
    assert "futureMath" in c.manifest[0]["error"]
    assert c.written["mathml_1.xml"] == original
    assert c.ocr_stats["failures"] == c.ocr_stats["omml_failures"] == 1
    assert c.ocr_stats["total"] == c.ocr_stats["omml_total"] == 1


def test_counts_include_word_equations_and_blank_source_is_not_a_failure():
    c = _ctx()
    c.omml(etree.fromstring(f'<m:oMathPara xmlns:m="{ns.M[1:-1]}"><m:oMath><m:r><m:t>x</m:t></m:r></m:oMath><m:oMath><m:r><m:t>y</m:t></m:r></m:oMath></m:oMathPara>'))
    c.omml(etree.fromstring(f'<m:oMath xmlns:m="{ns.M[1:-1]}"><m:r><m:t> </m:t></m:r></m:oMath>'))
    c.resolve_ocr()
    c.resolve_ocr()
    assert c.ocr_stats["omml_total"] == c.ocr_stats["total"] == 2
    assert c.ocr_stats["ocr_total"] == c.ocr_stats["failures"] == 0
    assert c.manifest[1]["empty"]

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
    # ocr_fn giả lập để test không phụ thuộc torch/pythonnet thật.
    c = Context(
        rels={"rId5": "word/embeddings/oleObject1.wmf"},
        assets={"word/embeddings/oleObject1.wmf": b"WMF"},
        ocr_fn=lambda data, ext: "x^{2}",
    )
    w_obj = _w_object("Equation.DSMT4")
    assert c.ole(w_obj) == "[!m:$mathtype_1$]"
    assert c.counter == 1
    assert c.written["mathtype_1.wmf"] == b"WMF"
    assert not c.warnings
    assert c.latex["mathtype_1"] == "x^{2}"
    assert c.manifest[-1]["latex"] == "x^{2}"


def test_ole_equation_ocr_failure_warns_but_keeps_placeholder():
    # ocr_fn trả None (OCR thất bại) -> cảnh báo, KHÔNG crash, placeholder ảnh
    # vẫn xuất ra, không có entry trong ctx.latex.
    c = Context(
        rels={"rId5": "word/embeddings/oleObject1.wmf"},
        assets={"word/embeddings/oleObject1.wmf": b"WMF"},
        ocr_fn=lambda data, ext: None,
    )
    w_obj = _w_object("Equation.DSMT4")
    assert c.ole(w_obj) == "[!m:$mathtype_1$]"
    assert "mathtype_1" not in c.latex
    assert c.warnings
    assert c.manifest[-1]["latex"] is None


def test_ole_equation_ocr_exception_warns_but_keeps_placeholder():
    # ocr_fn raise exception -> vẫn bắt lại, cảnh báo, không crash.
    def boom(data, ext):
        raise RuntimeError("model crashed")

    c = Context(
        rels={"rId5": "word/embeddings/oleObject1.wmf"},
        assets={"word/embeddings/oleObject1.wmf": b"WMF"},
        ocr_fn=boom,
    )
    w_obj = _w_object("Equation.DSMT4")
    assert c.ole(w_obj) == "[!m:$mathtype_1$]"
    assert "mathtype_1" not in c.latex
    assert c.warnings


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


def test_omml_populates_latex_map():
    from docx_extract.context import Context
    from docx_extract import ns
    from lxml import etree
    c = Context(rels={}, assets={})
    frac = (f'<m:oMath xmlns:m="{ns.M[1:-1]}"><m:f>'
            f'<m:num><m:r><m:t>a</m:t></m:r></m:num>'
            f'<m:den><m:r><m:t>b</m:t></m:r></m:den></m:f></m:oMath>')
    m = etree.fromstring(frac)
    assert c.omml(m) == "[!m:$mathml_1$]"
    assert c.latex["mathml_1"] == r"\frac{a}{b}"
    assert c.manifest[-1]["latex"] == r"\frac{a}{b}"


def test_deferred_ocr_preserves_ids_and_updates_existing_manifest_entries():
    c = Context(rels={"rId5": "word/media/formula.wmf"},
                assets={"word/media/formula.wmf": b"WMF"}, defer_ocr=True)
    assert c.ole(_w_object("Equation.DSMT4")) == "[!m:$mathtype_1$]"
    c.counter += 1  # an unrelated image owns id 2
    assert c.ole(_w_object("Equation.3")) == "[!m:$mathtype_3$]"
    entries = list(c.manifest)
    assert not c.latex
    class Client:
        stats = {"total": 2}
        def recognize(self, jobs):
            assert [item[0] for item in jobs] == ["mathtype_1", "mathtype_3"]
            return {oid: {"latex": oid, "error": ""} for oid, _, _ in reversed(jobs)}
    c.resolve_ocr(Client())
    assert [entry["latex"] for entry in entries] == ["mathtype_1", "mathtype_3"]
    assert c.counter == 3 and not c.pending_ocr and not c.warnings


def test_deferred_ocr_unexpected_error_keeps_asset_and_warns():
    c=Context(rels={"rId5":"word/media/a.wmf"},assets={"word/media/a.wmf":b"WMF"},defer_ocr=True)
    c.ole(_w_object("Equation.DSMT4"))
    class BrokenClient:
        def recognize(self, jobs):
            raise RuntimeError("unexpected failure")
    c.resolve_ocr(BrokenClient())
    assert c.written["mathtype_1.wmf"]==b"WMF"
    assert c.manifest[0]["latex"] is None
    assert "unexpected failure" in c.warnings[0]
