"""Physical print sizes, self-contained pages, and honest source/OCR labels."""
import importlib.util
import json
from pathlib import Path
import re
import zipfile

from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "kaggle_ocr" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


printing = load("hybrid_exam_export_test", "hybrid_exam_export.py")
images = load("hybrid_formula_images_print_test", "hybrid_formula_images.py")
fixture_spec = importlib.util.spec_from_file_location("hybrid_image_fixtures", ROOT / "tests/test_hybrid_formula_images.py")
fixtures = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixtures)


def test_word_geometry_keeps_distinct_sizes_for_same_image(tmp_path):
    body = '''<w:p><w:r><w:pict><v:shape style="width:72pt;height:18pt"><v:imagedata r:id="rId1"/></v:shape></w:pict></w:r>
        <w:r><w:pict><v:shape style="width:144pt;height:36pt"><v:imagedata r:id="rId1"/></v:shape></w:pict></w:r></w:p>'''
    source = fixtures.make_docx(tmp_path / "input.docx", [("media/formula.png", fixtures.png_formula(), "image")], body)
    extraction = images.mark_docx_images(source, tmp_path)
    first, second = extraction["images"][0]["occurrences"]
    assert first["width_mm"] == pytest.approx(25.4)
    assert first["height_mm"] == pytest.approx(6.35)
    assert second["width_mm"] == pytest.approx(50.8)
    assert second["height_mm"] == pytest.approx(12.7)


def test_drawingml_emu_dimensions_and_crop(tmp_path):
    body = '''<w:p><w:r><w:drawing><a:graphic><a:graphicData>
        <a:ext cx="1440000" cy="360000"/><a:srcRect l="10000" r="5000"/>
        <a:blip r:embed="rId1"/></a:graphicData></a:graphic></w:drawing></w:r></w:p>'''
    source = fixtures.make_docx(tmp_path / "input.docx", [("media/formula.png", fixtures.png_formula(), "image")], body)
    extraction = images.mark_docx_images(source, tmp_path)
    occurrence = extraction["images"][0]["occurrences"][0]
    assert occurrence["width_mm"] == 40
    assert occurrence["height_mm"] == 10
    assert occurrence["crop"]["l"] == 0.1
    assert occurrence["crop"]["r"] == 0.05


def test_print_raster_is_not_cropped_or_upscaled_for_ocr(tmp_path):
    source = fixtures.make_docx(tmp_path / "input.docx", [("media/formula.png", fixtures.png_formula(), "image")],
                                 '<w:p>' + fixtures.vml_image() + '</w:p>')
    extraction = images.mark_docx_images(source, tmp_path)
    record = extraction["images"][0]
    plan = images.prepare_image_plan(record["markers"][0], extraction, tmp_path, allow_install=False)
    record = plan["records"][0]
    with Image.open(record["display_path"]) as image:
        assert image.size == (140, 35)
    with Image.open(record["raster_path"]) as image:
        assert max(image.size) >= 384
    tag = printing.source_image_html(record, dict(width_mm=25.4, height_mm=6.35))
    assert 'data-width-mm="25.40000"' in tag
    assert 'data-height-mm="6.35000"' in tag
    assert "data:image/png;base64," in tag
    assert "formula_png" not in tag


def test_print_setup_reads_word_paper_and_margins():
    setup = printing.read_print_setup(ROOT / "tests/fixtures/sample.docx")
    assert setup["width_mm"] == pytest.approx(210, abs=0.1)
    assert setup["height_mm"] == pytest.approx(297, abs=0.1)
    assert setup["left_mm"] == pytest.approx(20, abs=0.1)
    assert setup["right_mm"] == pytest.approx(15, abs=0.1)


def test_real_pandoc_print_html_preserves_inline_sizes_and_mathml(tmp_path):
    pypandoc = pytest.importorskip("pypandoc")
    body = '''<w:p><w:r><w:t>BEFORE</w:t></w:r><w:r><w:pict><v:shape style="width:72pt;height:18pt"><v:imagedata r:id="rId1"/></v:shape></w:pict></w:r><w:r><w:t>AFTER</w:t></w:r></w:p>
        <w:p><m:oMath><m:r><m:t>x+1</m:t></m:r></m:oMath></w:p>'''
    source = fixtures.make_docx(tmp_path / "input.docx", [("media/formula.png", fixtures.png_formula(), "image")], body)
    extraction = images.mark_docx_images(source, tmp_path)
    record = extraction["images"][0]
    plan = images.prepare_image_plan("BEFORE " + record["markers"][0] + " AFTER", extraction, tmp_path, allow_install=False)
    images.record_ocr_result(plan, plan["tasks"][0][2], "$x+1$", "$x+1$")
    report = printing.export_exam_pages(source, extraction, plan, tmp_path, title="Exam <test>",
                                        pandoc=pypandoc.get_pandoc_path(), make_pdf=False)
    page = (tmp_path / "de-thi.html").read_text(encoding="utf-8")
    assert 'Exam &lt;test&gt;' in page and "In / lưu PDF" in page
    assert 'data-width-mm="25.40000"' in page and 'data-height-mm="6.35000"' in page
    # Word may stretch a source bitmap non-uniformly: print its DOCX display box,
    # not an object-fit:contain letterbox at the bitmap's original aspect ratio.
    assert "max-width:none;object-fit:fill" in page
    assert "HYBRIDIMAGE" not in page
    assert page.index("BEFORE") < page.index('class="source-image"') < page.index("AFTER")
    assert "<math" in page
    # OCR annotation blocks are outside the source paragraph and hidden in print.
    assert ".ocr-notes{display:none!important}" in page
    assert '<section class="ocr-notes">' in page
    assert not report["recovered_unplaced_images"]
    assert report["print_content"] == "source_docx_images_and_native_math"
    assert report["ocr_annotations"] == "screen_only"
    assert (tmp_path / "print-report.json").is_file()
    comparison = (tmp_path / "doi-chieu-ocr.html").read_text(encoding="utf-8")
    assert '<body class="show-ocr">' in comparison
    assert not re.search(r'<img[^>]+src="(?!data:)', page)


def test_missing_image_is_visible_not_stretched_placeholder():
    tag = printing.source_image_html(dict(id="bad-image", status="conversion_error"))
    assert "missing-image" in tag and "cần kiểm tra" in tag


def test_pdf_conversion_is_labelled_original_not_ocr(tmp_path, monkeypatch):
    source = tmp_path / "exam.docx"
    source.write_bytes(b"DOCX test fixture, only subprocess contract is tested")
    output = tmp_path / "result"
    output.mkdir()
    monkeypatch.setattr(printing.shutil, "which", lambda name: "soffice-test")
    def fake_soffice(command, **kwargs):
        (output / "exam.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * 150)
        return type("Process", (), dict(stdout="converted", stderr="", returncode=0))()
    monkeypatch.setattr(printing.subprocess, "run", fake_soffice)
    result = printing.original_layout_pdf(source, output, allow_install=False)
    assert result["ok"] and result["kind"] == "original_docx_layout_not_ocr"
    assert Path(result["path"]).name == "de-thi-goc.pdf"
