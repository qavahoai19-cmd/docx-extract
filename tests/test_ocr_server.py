import io
import json
from pathlib import Path
import sys

import pytest

Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "colab_ocr_server"))
import ocr_server as server
from ocr_logic import crop_whitespace


def png(mark=0):
    image = Image.new("RGB", (1000, 800), "white")
    ImageDraw.Draw(image).rectangle((450,350,549+mark,399), fill="black")
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


@pytest.fixture
def client(monkeypatch):
    server._result_cache.clear()
    monkeypatch.setattr(server, "_backend", "transformers")
    monkeypatch.setattr(server, "_inference_batch_size", 1)
    monkeypatch.setattr(server, "_get_model", lambda: (None, None))
    monkeypatch.setattr(server, "_infer_transformers", lambda data: "x^2")
    with TestClient(server.app) as client:
        yield client


def test_crop_uses_ink_not_white_canvas():
    with Image.open(io.BytesIO(crop_whitespace(png()))) as image:
        assert image.size == (140,90)


def test_invalid_nonempty_model_output_is_not_cached(client, monkeypatch):
    calls = []
    def infer(data):
        calls.append(data)
        return r"\[\sqrt{2}\frac{x-4}{}\]"
    monkeypatch.setattr(server, "_infer_transformers", infer)
    for _ in range(2):
        result = client.post("/ocr", files={"file": ("one.png", png())}).json()
        assert not result["latex"] and "empty" in result["error"]
    assert len(calls) == 2 and not server._result_cache


def test_invalid_existing_server_cache_is_discarded(client, monkeypatch):
    import hashlib
    image = png()
    key = ("source", "png", hashlib.sha256(image).digest())
    server._result_cache[key] = r"\frac{x}{}"
    result = client.post("/ocr", files={"file": ("one.png", image)}).json()
    assert result["latex"] == "x^2"
    assert server._result_cache[key] == "x^2"


def test_transparent_background_is_flattened_to_white():
    image = Image.new("RGBA", (100,100), (0,0,0,0))
    ImageDraw.Draw(image).rectangle((45,45,54,54), fill="black")
    output=io.BytesIO();image.save(output,"PNG")
    with Image.open(io.BytesIO(crop_whitespace(output.getvalue()))) as crop:
        assert crop.size == (50,50)
        assert crop.getpixel((0,0)) == (255,255,255)


def test_batch_isolates_corrupt_image_and_preserves_ids(client):
    response = client.post("/ocr/batch", data={"ids": json.dumps(["good", "bad"])},
                           files=[("files",("one.png",png())),("files",("two.png",b"broken"))])
    assert response.status_code == 200
    good, bad = response.json()["results"]
    assert good["id"] == "good" and good["latex"] == "x^2"
    assert bad["id"] == "bad" and not bad["latex"] and bad["error"]


def test_batch_rejects_duplicate_ids(client):
    response = client.post("/ocr/batch", data={"ids": '["same","same"]'},
                           files=[("files",("one.png",png())),("files",("two.png",png()))])
    assert response.status_code == 400


def test_vectors_use_one_libreoffice_process_per_batch(client, monkeypatch):
    calls=[]
    def convert(command, **kwargs):
        calls.append(command)
        for source in command[command.index("--outdir")+2:]:
            Path(source).with_suffix(".png").write_bytes(png())
    monkeypatch.setattr(server.subprocess,"run",convert)
    response=client.post("/ocr/batch",data={"ids":'["a","b"]'},files=[("files",("one.wmf",b"wmf")),("files",("two.emf",b"emf"))])
    assert len(calls)==1
    assert all(item["latex"] for item in response.json()["results"])
    assert any(arg.startswith("-env:UserInstallation=") for arg in calls[0])


def test_server_cache_reuses_identical_images(client, monkeypatch):
    calls=[]
    monkeypatch.setattr(server,"_infer_transformers",lambda image: calls.append(image) or "x^2")
    for _ in range(2):
        assert client.post("/ocr",files={"file":("one.png",png())}).json()["latex"]=="x^2"
    assert len(calls)==1


def test_source_dedup_and_cache_happen_before_vector_conversion(client, monkeypatch):
    converted, inferred = [], []

    def prepare(items):
        converted.append([oid for oid, _, _ in items])
        return {oid: png() for oid, _, _ in items}, {}

    monkeypatch.setattr(server, "_prepare_images", prepare)
    monkeypatch.setattr(server, "_infer_transformers", lambda image: inferred.append(image) or "x")
    first = client.post("/ocr/batch", data={"ids": '["a","b"]'},
                        files=[("files", ("a.wmf", b"same")), ("files", ("b.wmf", b"same"))]).json()
    second = client.post("/ocr", files={"file": ("again.wmf", b"same")}).json()
    assert converted == [["a"]] and len(inferred) == 1
    assert [row["latex"] for row in first["results"]] == ["x", "x"] and second["latex"] == "x"


def test_source_cache_bypass_still_runs_conversion_and_model(client, monkeypatch):
    converted, inferred = [], []

    def prepare(items):
        converted.append(len(items))
        return {oid: png() for oid, _, _ in items}, {}

    monkeypatch.setattr(server, "_prepare_images", prepare)
    monkeypatch.setattr(server, "_infer_transformers", lambda image: inferred.append(image) or "x")
    for _ in range(2):
        response = client.post("/ocr", headers={"X-OCR-Cache": "off"}, files={"file": ("a.wmf", b"same")})
        assert response.json()["latex"] == "x"
    assert converted == [1, 1] and len(inferred) == 2


def test_benchmark_can_bypass_server_cache(client, monkeypatch):
    calls=[]
    monkeypatch.setattr(server,"_infer_transformers",lambda image: calls.append(image) or "x^2")
    for _ in range(2):
        assert client.post("/ocr",headers={"X-OCR-Cache":"off"},files={"file":("one.png",png())}).json()["latex"]=="x^2"
    assert len(calls)==2 and not server._result_cache


def test_optional_api_key_protects_ocr_but_allows_health(client,monkeypatch):
    monkeypatch.setenv("DOCX_OCR_API_KEY","test-key")
    assert client.get("/health").status_code==200
    assert client.post("/ocr",files={"file":("one.png",png())}).status_code==401
    assert client.post("/ocr",headers={"Authorization":"Bearer test-key"},files={"file":("one.png",png())}).status_code==200


def test_warmup_runs_inference_and_sets_readiness(client,monkeypatch):
    monkeypatch.setattr(server,"_warmed_up",False)
    server.warmup_model()
    assert client.get("/health").json()["warmed_up"]


def test_inference_does_not_block_health(client, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    entered, release = threading.Event(), threading.Event()
    def infer(image):
        entered.set()
        release.wait(timeout=3)
        return "x^2"
    monkeypatch.setattr(server,"_infer_transformers",infer)
    with ThreadPoolExecutor(max_workers=2) as pool:
        recognition=pool.submit(client.post,"/ocr",files={"file":("one.png",png())})
        assert entered.wait(timeout=2)
        health=pool.submit(client.get,"/health")
        try:
            assert health.result(timeout=1).status_code==200
        finally:
            release.set()
        assert recognition.result(timeout=2).json()["latex"]=="x^2"


def test_vllm_receives_a_real_image_batch(client, monkeypatch):
    batches=[]
    monkeypatch.setattr(server,"_backend","vllm")
    def infer(images):
        batches.append(len(images))
        return [{"latex": f"x_{index}"} for index in range(len(images))]
    monkeypatch.setattr(server,"_infer_vllm",infer)
    response=client.post("/ocr/batch",data={"ids":'["a","b"]'},files=[("files",("one.png",png())),("files",("two.png",png(10)))])
    assert batches==[2]
    assert [r["latex"] for r in response.json()["results"]]==["x_0","x_1"]


def test_transformers_batch_is_bounded_and_keeps_per_image_errors(client, monkeypatch):
    batches = []
    monkeypatch.setattr(server, "_inference_batch_size", 2)

    def infer(images):
        batches.append(len(images))
        return [{"latex": "x"}, {"latex": "", "error": "token limit reached"}][:len(images)]

    monkeypatch.setattr(server, "_infer_transformers_batch", infer)
    response = client.post("/ocr/batch", data={"ids": '["a","b","c"]'},
                           files=[("files", ("a.png", png())), ("files", ("b.png", png(5))),
                                  ("files", ("c.png", png(10)))]).json()
    assert batches == [2, 1]
    assert [row["id"] for row in response["results"]] == ["a", "b", "c"]
    assert [row["latex"] for row in response["results"]] == ["x", "", "x"]
    assert response["results"][1]["error"] == "token limit reached"


def test_cuda_oom_splits_batch_without_losing_image_results(client, monkeypatch):
    class OutOfMemoryError(RuntimeError):
        pass

    sizes, releases = [], []

    def infer(images):
        sizes.append(len(images))
        if len(images) > 1:
            raise OutOfMemoryError("not enough GPU memory")
        return [{"latex": "recovered"}]

    monkeypatch.setattr(server, "_inference_batch_size", 2)
    monkeypatch.setattr(server, "_infer_transformers_batch", infer)
    monkeypatch.setattr(server, "_clear_cuda_cache", lambda: releases.append(True))
    response = client.post("/ocr/batch", data={"ids": '["a","b"]'},
                           files=[("files", ("a.png", png())), ("files", ("b.png", png(5)))]).json()
    assert sizes == [2, 1, 1] and len(releases) == 1
    assert [row["latex"] for row in response["results"]] == ["recovered", "recovered"]


@pytest.mark.parametrize("matches,faster", [(True, True), (False, True), (True, False)])
def test_batch_startup_validation_falls_back_when_outputs_differ(client, monkeypatch, matches, faster):
    monkeypatch.setattr(server, "_inference_batch_size", 2)
    monkeypatch.setattr(server, "_batch_verified", False)
    monkeypatch.setattr(server, "_batch_validation_error", "")
    ticks = iter([0.0, 2.0, 2.0, 3.0 if faster else 5.0])
    monkeypatch.setattr(server, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(server, "_infer_transformers", lambda _: "x")
    monkeypatch.setattr(server, "_infer_transformers_batch", lambda images:
                        [{"latex": "x" if matches else "different"} for _ in images])
    server.validate_transformers_batch()
    verified = matches and faster
    assert server._inference_batch_size == (2 if verified else 1)
    assert server._batch_verified is verified
    assert bool(server._batch_validation_error) is not verified


def test_vllm_truncated_output_is_not_accepted_or_cached(client,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(server,"_backend","vllm")
    monkeypatch.setitem(sys.modules,"vllm",SimpleNamespace(SamplingParams=lambda **kwargs:kwargs))
    class Model:
        def generate(self,inputs,params):
            assert len(inputs)==1 and params["temperature"]==0
            return [SimpleNamespace(outputs=[SimpleNamespace(text="incomplete",finish_reason="length")])]
    monkeypatch.setattr(server,"_get_model",lambda:(None,Model()))
    result=client.post("/ocr",files={"file":("one.png",png())}).json()
    assert not result["latex"] and result["error"]=="token limit reached"
    assert not server._result_cache
