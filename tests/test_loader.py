from docx_extract.loader import load
from docx_extract import ns

DOCX = r"C:\Users\admin\Downloads\ĐỀ VẬT LÍ LẦN 3_VER 2 (2).docx"

def test_load_returns_body_rels_assets():
    doc = load(DOCX)
    assert doc.body.tag == ns.q("w", "body")
    # có ít nhất 1 rId trỏ tới media
    assert any(v.startswith("word/media/") for v in doc.rels.values())
    # asset bytes nạp được
    media = [k for k in doc.assets if k.startswith("word/media/")]
    assert media and isinstance(doc.assets[media[0]], bytes)
