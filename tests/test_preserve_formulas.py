import json
from pathlib import Path
import sys

from lxml import etree

from docx_extract import clean_docx
from docx_extract import assemble, mathlatex, mathnative, mathocr, ns
from docx_extract.context import Context


def forbidden(*args, **kwargs):
    raise AssertionError("Preserve mode must not convert formulas or contact OCR")


def test_preserve_word_equation_retains_original_xml_without_conversion(monkeypatch):
    monkeypatch.setattr(mathlatex, "omml_to_latex", forbidden)
    context = Context(rels={}, assets={}, preserve_formulas=True)
    equation = etree.fromstring(f'<m:oMath xmlns:m="{ns.M[1:-1]}"><m:r><m:t>α+β</m:t></m:r></m:oMath>')
    original = etree.tostring(equation, encoding="utf-8")
    assert context.omml(equation) == "[!m:$mathml_1$]"
    assert context.written["mathml_1.xml"] == original
    assert not context.latex and not context.warnings
    assert context.manifest[0]["preserved"] and context.manifest[0]["latex"] is None


def test_real_mathtype_document_preserves_images_and_never_uses_any_converter(monkeypatch):
    sample = Path(__file__).parent / "fixtures/sample.docx"
    # Compare the same numbering-preserving mode before enabling any converter.
    baseline_markup, baseline = assemble.extract_docx(str(sample), native_math=False, preserve_formulas=True)
    monkeypatch.setenv("DOCX_EXTRACT_NATIVE_MATH", "1")
    monkeypatch.setenv("DOCX_EXTRACT_OCR_ENDPOINT", "http://must-not-be-called/ocr")
    monkeypatch.setattr(mathnative, "ole_to_latex", forbidden)
    monkeypatch.setattr(mathlatex, "omml_to_latex", forbidden)
    monkeypatch.setattr(mathocr, "OCRClient", forbidden)
    markup, context = clean_docx(str(sample), ocr_client=object(), preserve_formulas=True)
    assert markup == baseline_markup and context.written == baseline.written
    equations = [item for item in context.manifest if item["type"] == "mathtype"]
    assert len(equations) == 16
    assert all(item["preserved"] and item["latex"] is None for item in equations)
    assert not context.pending_ocr and not context.latex
    assert context.ocr_stats["failures"] == context.ocr_stats["http_requests"] == 0
    assert context.ocr_stats["ocr_total"] == context.ocr_stats["native_attempted"] == 0
    assert context.ocr_stats["mode"] == "preserve_formulas"


def test_keep_formulas_cli_works_without_creating_ocr_client(tmp_path, monkeypatch, capsys):
    from docx_extract.__main__ import main
    sample = Path(__file__).parent / "fixtures/sample.docx"
    monkeypatch.setattr("docx_extract.__main__.OCRClient", forbidden)
    monkeypatch.setattr(sys, "argv", ["docx_extract", str(sample), "--keep-formulas", "-o", str(tmp_path)])
    main()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ocr"]["mode"] == "preserve_formulas"
    assert len(list((tmp_path / "sidecar").iterdir())) == len(manifest["assets"])
    assert "không chuyển LaTeX" in capsys.readouterr().out
