from docx_extract import mathocr


def test_image_to_latex_skips_conversion_for_png(monkeypatch):
    monkeypatch.setattr(mathocr, "wmf_to_png", lambda data, ext: (_ for _ in ()).throw(
        AssertionError("wmf_to_png không nên được gọi cho ext=png")))

    class FakeModel:
        def infer(self, tokenizer, prompt, image_file, **kw):
            assert prompt == "<image>\nFree OCR."
            return "x^{2}+1"

    monkeypatch.setattr(mathocr, "_get_model", lambda: (object(), FakeModel()))
    assert mathocr.image_to_latex(b"PNGDATA", "png") == "x^{2}+1"


def test_image_to_latex_converts_wmf_then_ocr(monkeypatch):
    monkeypatch.setattr(mathocr, "wmf_to_png", lambda data, ext: b"PNGBYTES")

    class FakeModel:
        def infer(self, tokenizer, prompt, image_file, **kw):
            with open(image_file, "rb") as f:
                assert f.read() == b"PNGBYTES"
            return "\\frac{a}{b}"

    monkeypatch.setattr(mathocr, "_get_model", lambda: (object(), FakeModel()))
    assert mathocr.image_to_latex(b"WMFDATA", "wmf") == r"\frac{a}{b}"


def test_image_to_latex_returns_none_when_conversion_fails(monkeypatch):
    monkeypatch.setattr(mathocr, "wmf_to_png", lambda data, ext: None)
    assert mathocr.image_to_latex(b"WMFDATA", "wmf") is None


def test_image_to_latex_returns_none_on_model_exception(monkeypatch):
    monkeypatch.setattr(mathocr, "wmf_to_png", lambda data, ext: b"PNGBYTES")

    def boom():
        raise RuntimeError("model load failed")

    monkeypatch.setattr(mathocr, "_get_model", boom)
    assert mathocr.image_to_latex(b"WMFDATA", "wmf") is None


def test_wmf_to_png_returns_none_without_pythonnet(monkeypatch):
    # Môi trường test không cài pythonnet -> import lỗi -> None (không crash)
    assert mathocr.wmf_to_png(b"not a real wmf", "wmf") is None
