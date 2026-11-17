from lxml import etree

from docx_extract import ns
from docx_extract.assemble import clean_docx
from docx_extract.context import Context
from docx_extract.loader import Document
from docx_extract.runs import render_paragraph


MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
WPG = "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"


def element(tag, content):
    return etree.fromstring(
        f'<w:{tag} xmlns:w="{ns.W[1:-1]}" xmlns:a="{ns.A[1:-1]}" '
        f'xmlns:v="{ns.V[1:-1]}" xmlns:o="{ns.O[1:-1]}" '
        f'xmlns:r="{ns.R[1:-1]}" xmlns:mc="{MC}" xmlns:wpg="{WPG}">'
        f'{content}</w:{tag}>'
    )


def equation(rid):
    return (f'<w:r><w:object><v:shape><v:imagedata r:id="{rid}"/></v:shape>'
            '<o:OLEObject ProgID="Equation.DSMT4"/></w:object></w:r>')


def context():
    return Context(rels={rid: f"word/media/{rid}.wmf" for rid in ("one", "two", "fallback")},
                   assets={f"word/media/{rid}.wmf": rid.encode() for rid in ("one", "two", "fallback")},
                   defer_ocr=True)


def test_vml_group_preserves_each_image_in_source_order():
    paragraph = element("p", '<w:r><w:t>before</w:t><w:pict><v:group>'
                        '<v:shape><v:imagedata r:id="one"/></v:shape>'
                        '<v:shape><v:imagedata r:id="two"/></v:shape>'
                        '</v:group></w:pict><w:t>after</w:t></w:r>')
    ctx = context()
    assert render_paragraph(paragraph, ctx) == "before[img:$img_1$][img:$img_2$]after"
    assert ctx.written == {"img_1.wmf": b"one", "img_2.wmf": b"two"}


def test_alternate_graphics_extract_choice_without_duplicate_fallback():
    paragraph = element("p", '<w:r><mc:AlternateContent><mc:Choice Requires="wpg">'
                        '<w:drawing><a:blip r:embed="one"/><a:blip r:embed="two"/></w:drawing>'
                        '</mc:Choice><mc:Fallback><w:pict><v:shape>'
                        '<v:imagedata r:id="fallback"/></v:shape></w:pict>'
                        '</mc:Fallback></mc:AlternateContent></w:r>')
    ctx = context()
    assert render_paragraph(paragraph, ctx) == "[img:$img_1$][img:$img_2$]"
    assert [entry["source"] for entry in ctx.manifest] == ["word/media/one.wmf", "word/media/two.wmf"]


def test_unknown_alternate_requirement_uses_fallback():
    paragraph = element("p", '<w:r><mc:AlternateContent>'
                        '<mc:Choice xmlns:future="urn:unsupported" Requires="future">'
                        '<w:drawing><a:blip r:embed="one"/></w:drawing></mc:Choice>'
                        '<mc:Fallback><w:pict><v:shape><v:imagedata r:id="fallback"/>'
                        '</v:shape></w:pict></mc:Fallback></mc:AlternateContent></w:r>')
    ctx = context()
    assert render_paragraph(paragraph, ctx) == "[img:$img_1$]"
    assert ctx.written == {"img_1.wmf": b"fallback"}


def test_textbox_nested_table_equation_is_added_to_ocr_queue():
    paragraph = element("p", '<w:r><w:drawing><w:txbxContent>'
                        '<w:p><w:r><w:t>inside</w:t></w:r></w:p>'
                        '<w:tbl><w:tr><w:tc><w:p>' + equation("one") +
                        '</w:p></w:tc></w:tr></w:tbl>'
                        '</w:txbxContent></w:drawing></w:r>')
    ctx = context()
    markup = render_paragraph(paragraph, ctx)
    assert "inside" in markup and "[!m:$mathtype_1$]" in markup
    assert [(oid, data, ext) for oid, data, ext, _ in ctx.pending_ocr] == [("mathtype_1", b"one", "wmf")]


def test_content_controls_and_nested_tables_reach_ocr_once(monkeypatch):
    monkeypatch.setenv("DOCX_EXTRACT_NATIVE_MATH", "0")
    body = element("body", '<w:sdt><w:sdtContent><w:p><w:r><w:t>Question</w:t></w:r></w:p>'
                   '<w:tbl><w:tr><w:tc><w:p>' + equation("one") + '</w:p>'
                   '<w:tbl><w:tr><w:tc><w:p>' + equation("two") + '</w:p>'
                   '</w:tc></w:tr></w:tbl></w:tc></w:tr></w:tbl>'
                   '</w:sdtContent></w:sdt>')
    ctx = context()
    document = Document(body=body, rels=ctx.rels, assets=ctx.assets)
    monkeypatch.setattr("docx_extract.assemble.load", lambda _: document)

    class OCR:
        stats = {"total": 2, "failures": 0}

        def recognize(self, jobs):
            assert jobs == [("mathtype_1", b"one", "wmf"), ("mathtype_2", b"two", "wmf")]
            return {oid: {"latex": data.decode(), "error": ""} for oid, data, _ in jobs}

    markup, result = clean_docx("unused.docx", ocr_client=OCR())
    assert "Question" in markup
    assert markup.index("mathtype_1") < markup.index("mathtype_2")
    assert result.latex == {"mathtype_1": "one", "mathtype_2": "two"}
