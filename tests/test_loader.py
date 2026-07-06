from pathlib import Path
from docx_extract.loader import load
from docx_extract import ns

DOCX = Path(__file__).parent / "fixtures" / "sample.docx"

def test_load_returns_body_rels_assets():
    doc = load(DOCX)
    assert doc.body.tag == ns.q("w", "body")
    # có ít nhất 1 rId trỏ tới media
    assert any(v.startswith("word/media/") for v in doc.rels.values())
    # asset bytes nạp được
    media = [k for k in doc.assets if k.startswith("word/media/")]
    assert media and isinstance(doc.assets[media[0]], bytes)
