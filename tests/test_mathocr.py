import requests as requests_module  # để raise đúng loại exception mathocr bắt
from docx_extract import mathocr


class _FakeResponse:
    def __init__(self, json_data, status_ok=True):
        self._json = json_data
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise requests_module.HTTPError("boom")

    def json(self):
        return self._json


def test_image_to_latex_returns_none_when_endpoint_not_configured(monkeypatch):
    monkeypatch.delenv("DOCX_EXTRACT_OCR_ENDPOINT", raising=False)
    assert mathocr.image_to_latex(b"WMFDATA", "wmf") is None


def test_image_to_latex_posts_file_and_returns_latex(monkeypatch):
    monkeypatch.setenv("DOCX_EXTRACT_OCR_ENDPOINT", "http://localhost:9000/ocr")
    monkeypatch.delenv("DOCX_EXTRACT_OCR_API_KEY", raising=False)
    captured = {}

    def fake_post(url, files, headers, timeout):
        captured["url"] = url
        captured["files"] = files
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _FakeResponse({"latex": "x^{2}+1"})

    monkeypatch.setattr(mathocr.requests, "post", fake_post)
    assert mathocr.image_to_latex(b"WMFDATA", "wmf") == "x^{2}+1"
    assert captured["url"] == "http://localhost:9000/ocr"
    assert captured["files"]["file"][0] == "formula.wmf"
    assert captured["files"]["file"][1] == b"WMFDATA"
    assert "Authorization" not in captured["headers"]


def test_image_to_latex_includes_auth_header_when_api_key_set(monkeypatch):
    monkeypatch.setenv("DOCX_EXTRACT_OCR_ENDPOINT", "http://localhost:9000/ocr")
    monkeypatch.setenv("DOCX_EXTRACT_OCR_API_KEY", "secret123")
    captured = {}

    def fake_post(url, files, headers, timeout):
        captured["headers"] = headers
        return _FakeResponse({"latex": "\\frac{a}{b}"})

    monkeypatch.setattr(mathocr.requests, "post", fake_post)
    assert mathocr.image_to_latex(b"WMFDATA", "wmf") == r"\frac{a}{b}"
    assert captured["headers"]["Authorization"] == "Bearer secret123"


def test_image_to_latex_returns_none_on_non_200(monkeypatch):
    monkeypatch.setenv("DOCX_EXTRACT_OCR_ENDPOINT", "http://localhost:9000/ocr")

    def fake_post(url, files, headers, timeout):
        return _FakeResponse({}, status_ok=False)

    monkeypatch.setattr(mathocr.requests, "post", fake_post)
    assert mathocr.image_to_latex(b"WMFDATA", "wmf") is None


def test_image_to_latex_returns_none_on_network_exception(monkeypatch):
    monkeypatch.setenv("DOCX_EXTRACT_OCR_ENDPOINT", "http://localhost:9000/ocr")

    def fake_post(url, files, headers, timeout):
        raise requests_module.ConnectionError("network down")

    monkeypatch.setattr(mathocr.requests, "post", fake_post)
    assert mathocr.image_to_latex(b"WMFDATA", "wmf") is None


def test_image_to_latex_returns_none_when_latex_missing_or_empty(monkeypatch):
    monkeypatch.setenv("DOCX_EXTRACT_OCR_ENDPOINT", "http://localhost:9000/ocr")

    def fake_post(url, files, headers, timeout):
        return _FakeResponse({"latex": ""})

    monkeypatch.setattr(mathocr.requests, "post", fake_post)
    assert mathocr.image_to_latex(b"WMFDATA", "wmf") is None
