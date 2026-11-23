import requests as requests_module  # để raise đúng loại exception mathocr bắt
import pytest
from docx_extract import mathocr


class _FakeResponse:
    def __init__(self, json_data, status_ok=True):
        self._json = json_data
        self._status_ok = status_ok
        self.status_code = 200 if status_ok else 500

    def raise_for_status(self):
        if not self._status_ok:
            raise requests_module.HTTPError("boom")

    def json(self):
        return self._json


@pytest.fixture(autouse=True)
def isolated_transport(monkeypatch):
    class Session:
        def get(self, *args, **kwargs):
            return _FakeResponse({}, False)

        def post(self, url, **kwargs):
            return mathocr.requests.post(url, **kwargs)

        def close(self):
            pass

    monkeypatch.setattr(mathocr.requests, "Session", Session)
    monkeypatch.setenv("DOCX_EXTRACT_OCR_CACHE", "off")
    monkeypatch.setenv("DOCX_EXTRACT_OCR_PREPARE_IMAGES", "0")


def test_image_to_latex_returns_none_when_endpoint_not_configured(monkeypatch):
    monkeypatch.delenv("DOCX_EXTRACT_OCR_ENDPOINT", raising=False)
    assert mathocr.image_to_latex(b"WMFDATA", "wmf") is None


@pytest.mark.parametrize("payload", [
    {"latex": r"\[\sqrt{2}\frac{x-4}{}\]"},
    {"latex": "x", "error": "token limit reached"},
])
def test_invalid_nonempty_output_is_rejected_and_never_cached(tmp_path, payload):
    session = BatchSession()
    session.post = lambda *args, **kwargs: _FakeResponse(payload)
    with mathocr.OCRClient(endpoint="http://test/ocr", session=session,
                           cache_path=tmp_path / "cache.sqlite3") as client:
        for _ in range(2):
            result = client.recognize([("formula", b"image", "png")])["formula"]
            assert result["latex"] is None and result["error"]
        assert client.stats["http_requests"] == 2
        assert client.stats["cache_hits"] == 0
        assert client.db.execute("SELECT COUNT(*) FROM ocr").fetchone()[0] == 0


def test_cache_bypass_also_disables_server_cache(tmp_path):
    session = BatchSession()
    with mathocr.OCRClient(endpoint="http://test/ocr", session=session, use_cache=False,
                           cache_path=tmp_path / "cache.sqlite3") as client:
        for _ in range(2):
            assert client.recognize([("formula", b"image", "png")])["formula"]["latex"]
        assert client.db is None and len(session.posts) == 2
        assert all(kwargs["headers"]["X-OCR-Cache"] == "off" for _, kwargs in session.posts)


def test_invalid_existing_cache_entry_is_not_reused(tmp_path):
    session = BatchSession()
    with mathocr.OCRClient(endpoint="http://test/ocr", session=session,
                           cache_path=tmp_path / "cache.sqlite3") as client:
        client._discover()
        client._save_cached([(client._key(b"image", "png"), r"\frac{x}{}")])
        result = client.recognize([("formula", b"image", "png")])
        assert result["formula"]["latex"] == "x^2"
        assert len(session.posts) == 1 and client.stats["cache_hits"] == 0


class BatchSession:
    def __init__(self, *, namespace="model-1", failed=False, legacy=False):
        self.namespace, self.failed, self.legacy = namespace, failed, legacy
        self.posts = []

    def get(self, *args, **kwargs):
        return _FakeResponse({"cache_namespace": self.namespace})

    def post(self, url, **kwargs):
        import json
        self.posts.append((url, kwargs))
        if url.endswith("/batch"):
            if self.legacy:
                response = _FakeResponse({}, False)
                response.status_code = 404
                return response
            ids = json.loads(kwargs["data"]["ids"])
            # Deliberately reverse results: positional matching corrupts math.
            return _FakeResponse({"results": [{"id": oid, "latex": "" if self.failed else f"latex:{oid}"} for oid in reversed(ids)]})
        return _FakeResponse({"latex": "" if self.failed else "x^2"})

    def close(self):
        pass


def test_batch_deduplicates_and_maps_out_of_order_results():
    session = BatchSession()
    with mathocr.OCRClient(endpoint="http://test/ocr", session=session, prepare=False) as client:
        result = client.recognize([("m1", b"one", "wmf"), ("m2", b"two", "wmf"), ("m3", b"one", "wmf")])
    assert result["m1"]["latex"] == result["m3"]["latex"] == "latex:m1"
    assert result["m2"]["latex"] == "latex:m2"
    assert len(session.posts) == 1
    assert len(session.posts[0][1]["files"]) == 2
    assert client.stats["deduplicated"] == 1


def test_parallel_conversion_preserves_ids_and_converts_duplicates_once(monkeypatch):
    import threading
    barrier = threading.Barrier(2)
    calls = []

    def convert(data, ext):
        calls.append(data)
        barrier.wait(timeout=2)
        return data + b"png", "png"

    monkeypatch.setattr(mathocr, "prepare_image", convert)
    with mathocr.OCRClient(endpoint="http://test/ocr", session=BatchSession(), cache_path="off",
                           prepare=True, prepare_workers=2) as client:
        results = client.recognize([("one", b"a", "wmf"), ("two", b"b", "emf"), ("repeat", b"a", "wmf")])
    assert sorted(calls) == [b"a", b"b"]
    assert results["one"] == results["repeat"]
    assert results["two"]["latex"] == "latex:two" and client.stats["rasterized"] == 2


def test_persistent_cache_reuses_success_and_invalidates_model_revision(tmp_path):
    cache = tmp_path / "cache.sqlite3"
    jobs = [("m1", b"one", "png"), ("m2", b"two", "png")]
    for namespace, expected_requests in [("v1", 1), ("v1", 0), ("v2", 1)]:
        session = BatchSession(namespace=namespace)
        with mathocr.OCRClient(endpoint="http://test/ocr", cache_path=cache, session=session) as client:
            result = client.recognize(jobs)
        assert all(item["latex"] for item in result.values())
        assert len(session.posts) == expected_requests


def test_failures_are_not_persisted(tmp_path):
    cache = tmp_path / "cache.sqlite3"
    for failed in (True, False):
        session = BatchSession(failed=failed)
        with mathocr.OCRClient(endpoint="http://test/ocr", cache_path=cache, session=session) as client:
            result = client.recognize([("m1", b"one", "png"), ("m2", b"two", "png")])
        assert len(session.posts) == 1
        assert bool(result["m1"]["latex"]) is not failed


def test_legacy_server_falls_back_once_then_reuses_session():
    session = BatchSession(legacy=True)
    with mathocr.OCRClient(endpoint="http://test/ocr", session=session, batch_size=2) as client:
        result = client.recognize([(str(i), str(i).encode(), "png") for i in range(4)])
    assert len(session.posts) == 5  # one 404, four compatible single uploads
    assert all(item["latex"] == "x^2" for item in result.values())


def test_transport_failure_stops_remaining_timeouts():
    session = BatchSession()
    def fail(*args, **kwargs):
        session.posts.append(None)
        raise requests_module.Timeout("offline")
    session.post = fail
    with mathocr.OCRClient(endpoint="http://test/ocr", session=session, batch_size=2) as client:
        result = client.recognize([(str(i), str(i).encode(), "png") for i in range(20)])
    assert len(result) == 20
    assert len(session.posts) == 1
    assert client.stats["failures"] == 20


def test_legacy_partial_success_survives_a_later_timeout():
    session=BatchSession(legacy=True)
    session.get=lambda *args,**kwargs: _FakeResponse({"batch":False})
    calls=[]
    def post(url,**kwargs):
        calls.append(url)
        if len(calls)==1:
            return _FakeResponse({"latex":"first result"})
        raise requests_module.Timeout("offline")
    session.post=post
    with mathocr.OCRClient(endpoint="http://test/ocr",session=session,batch_size=3) as client:
        result=client.recognize([(str(i),str(i).encode(),"png") for i in range(5)])
    assert len(calls)==2
    assert result["0"]["latex"]=="first result"
    assert all(not result[str(i)]["latex"] for i in range(1,5))


def test_missing_batch_id_cannot_be_assigned_another_formula():
    session=BatchSession()
    session.post=lambda *args,**kwargs:_FakeResponse({"results":[{"id":"b","latex":"only b"}]})
    with mathocr.OCRClient(endpoint="http://test/ocr",session=session) as client:
        result=client.recognize([("a",b"a","png"),("b",b"b","png")])
    assert result["a"]["latex"] is None
    assert result["b"]["latex"]=="only b"


def test_corrupt_cache_does_not_stop_ocr(tmp_path):
    cache = tmp_path / "cache.sqlite3"
    cache.write_bytes(b"broken sqlite")
    with mathocr.OCRClient(endpoint="http://test/ocr", cache_path=cache, session=BatchSession()) as client:
        result = client.recognize([("m1", b"one", "png")])
    assert result["m1"]["latex"] == "x^2"
    assert client.stats["cache_errors"] == 1


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
