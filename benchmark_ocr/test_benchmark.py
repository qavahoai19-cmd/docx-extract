import ast
import base64
from contextlib import contextmanager
import hashlib
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import threading
import zipfile

import pytest

from benchmark_ocr.build_notebook import BASELINE, ROOT, build, make_bundle
from benchmark_ocr.runner import compare, run_benchmark


@contextmanager
def fake_server():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, result):
            payload = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            self.respond({"model_loaded": True, "warmed_up": True, "batch": True,
                          "cache_namespace": "test-must-not-cache", "inference_batch_size": 1})

        def do_POST(self):
            from email.parser import BytesParser
            from email.policy import default
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            parsed = BytesParser(policy=default).parsebytes(
                ("Content-Type: " + self.headers["Content-Type"] + "\r\n\r\n").encode() + raw)
            ids = next((json.loads(part.get_payload(decode=True)) for part in parsed.iter_parts()
                        if part.get_param("name", header="content-disposition") == "ids"), None)
            calls.append({"path": self.path, "bypass": self.headers.get("X-OCR-Cache")})
            timings = {"prepare_s": 0.001, "infer_s": 0.002}
            if ids is not None:
                self.respond({"results": [{"id": oid, "latex": "x+1"} for oid in ids], "timings": timings})
            else:
                self.respond({"latex": "x+1", "timings": timings})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/ocr", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_notebook_bundle_freezes_both_versions_and_has_no_outputs():
    target = build()
    notebook = json.loads(target.read_text(encoding="utf-8"))
    assert target.stat().st_size < 1_000_000
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            ast.parse("".join(cell["source"]))
            assert cell["outputs"] == [] and cell["execution_count"] is None
    unpack = next(cell for cell in notebook["cells"] if cell["id"] == "unpack")
    assignment = next(node for node in ast.parse("".join(unpack["source"])).body
                      if isinstance(node, ast.Assign) and node.targets[0].id == "PAYLOAD")
    with zipfile.ZipFile(io.BytesIO(base64.b85decode(ast.literal_eval(assignment.value)))) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read("bundle.json"))
        assert manifest["baseline_revision"] == BASELINE
        assert "baseline/src/docx_extract/runs.py" in archive.namelist()
        assert "baseline/colab_ocr_server/ocr_server.py" in archive.namelist()
        for path, digest in manifest["files_sha256"].items():
            assert hashlib.sha256(archive.read(path)).hexdigest() == digest
        for name in ("runner.py", "ui.py", "worker.py", "server_bridge.py"):
            assert archive.read("benchmark/" + name) == (ROOT / "benchmark_ocr" / name).read_bytes()
        assert not any(path.endswith((".docx", ".sqlite3", ".env")) for path in archive.namelist())


def test_both_versions_repeat_real_http_without_cache_and_compare_outputs(tmp_path, monkeypatch):
    with zipfile.ZipFile(io.BytesIO(make_bundle())) as archive:
        archive.extractall(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path / "optimized/kaggle_ocr"))
    monkeypatch.setenv("DOCX_EXTRACT_OCR_CACHE", "off")
    sample = (ROOT / "tests/fixtures/sample.docx").read_bytes()
    with fake_server() as (endpoint, calls):
        report, download = run_benchmark([("a.docx", sample), ("b.docx", sample)], tmp_path, endpoint,
            repetitions=3, progress=lambda message: None)
    assert len(report["runs"]) == 6
    assert [row["mode"] for row in report["runs"]] == ["before", "after", "after", "before", "before", "after"]
    assert all(call["bypass"] == "off" for call in calls)
    assert all(row["metrics"]["cache_hits"] == 0 for row in report["runs"])
    assert all(row["formulas"] == 32 and row["failures"] == 0 for row in report["runs"])
    assert report["summary"]["before"]["http_requests"] == 32
    assert report["summary"]["after"]["http_requests"] == 1
    assert report["summary"]["after"]["remote_images"] == 16
    assert report["summary"]["after"]["server_infer_s"] > 0
    assert report["comparison_without_detected_differences"]
    with zipfile.ZipFile(download) as archive:
        assert "report.json" in archive.namelist()
        assert len([name for name in archive.namelist() if name.endswith("-results.zip")]) == 6
        assert not any(name.endswith(".docx") for name in archive.namelist())


def test_differences_are_matched_by_asset_not_placeholder_number():
    original = {"id": "mathtype_1", "type": "mathtype", "source": "media/a.wmf", "sha256": "raw", "latex": "x"}
    before = {"documents": [{"file": "a", "sha256": "word", "error": "",
                             "snapshot": {"markup": "same", "assets": [original]}}]}
    changed = {**original, "id": "mathtype_8", "latex": "y"}
    after = {"documents": [{"file": "a", "sha256": "word", "error": "",
                            "snapshot": {"markup": "same", "assets": [changed]}}]}
    differences = compare(before, after)
    assert not differences[0]["assets_changed"]
    assert differences[0]["changed_latex"] == [{"before_id": "mathtype_1", "after_id": "mathtype_8", "before": "x", "after": "y"}]
    after["documents"][0]["snapshot"]["assets"] = []
    assert compare(before, after)[0]["assets_changed"]


def test_server_adapter_keeps_historical_conversion_and_bypasses_current_cache(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from PIL import Image, ImageDraw
    from types import SimpleNamespace

    with zipfile.ZipFile(io.BytesIO(make_bundle())) as archive:
        archive.extractall(tmp_path)
    monkeypatch.setenv("DOCX_BENCH_ROOT", str(tmp_path))
    monkeypatch.setenv("DOCX_OCR_WARMUP", "0")
    monkeypatch.setenv("DOCX_OCR_INFERENCE_BATCH_SIZE", "1")
    monkeypatch.setenv("DOCX_OCR_API_KEY", "")
    monkeypatch.syspath_prepend(str(tmp_path / "optimized/colab_ocr_server"))
    # Import independent modules so other server tests retain their own globals.
    for name in ("ocr_server", "ocr_logic", "benchmark_previous_server"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    spec = importlib.util.spec_from_file_location("test_server_bridge", tmp_path / "benchmark/server_bridge.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    current, previous = bridge.current, bridge.previous
    calls = []
    monkeypatch.setattr(current, "_get_model", lambda: (None, None))
    monkeypatch.setattr(previous, "run_ocr", lambda data: "old")
    monkeypatch.setattr(previous, "convert_to_png", lambda data, ext: calls.append((data, ext)) or b"converted")
    monkeypatch.setattr(current, "_infer_transformers", lambda data: calls.append("new-infer") or "new")
    image = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(image).text((20, 30), "x", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    with TestClient(bridge.app) as client:
        result = client.post("/benchmark/baseline", files={"file": ("a.wmf", b"vector")})
        assert result.json()["latex"] == "old"
        assert calls == [(b"vector", "wmf")]
        # Prepopulate production cache; benchmark paths must still infer each time.
        current.recognize_items([("formula", buffer.getvalue(), "png")], True)
        calls.clear()
        for _ in range(2):
            result = client.post("/benchmark/after", files={"file": ("a.png", buffer.getvalue())})
            assert result.json()["latex"] == "new" and "timings" in result.json()
        result = client.post("/benchmark/after/batch", data={"ids": '["a","b"]'},
            files=[("files", ("a.png", buffer.getvalue())), ("files", ("b.png", buffer.getvalue()))])
        assert [row["id"] for row in result.json()["results"]] == ["a", "b"]
        assert calls == ["new-infer"] * 3
    for name in ("ocr_server", "ocr_logic", "benchmark_previous_server"):
        sys.modules.pop(name, None)
