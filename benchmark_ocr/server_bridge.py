"""Benchmark-only adapter: historical preprocessing, one shared warmed model.

The old model loader is deliberately replaced with the current pinned loader
so both paths use the same weights, attention and GPU-compatible dtype.
No production module imports this adapter.
"""
import importlib.util
import os
from pathlib import Path
import sys
from time import perf_counter

from fastapi import File, Form, UploadFile
from starlette.concurrency import run_in_threadpool


ROOT = Path(os.environ["DOCX_BENCH_ROOT"]).resolve()
sys.path.insert(0, str(ROOT / "optimized/colab_ocr_server"))
import ocr_server as current


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


saved_logic = sys.modules["ocr_logic"]
try:
    load_file("ocr_logic", ROOT / "baseline/colab_ocr_server/ocr_logic.py")
    previous = load_file("benchmark_previous_server", ROOT / "baseline/colab_ocr_server/ocr_server.py")
finally:
    sys.modules["ocr_logic"] = saved_logic
previous._get_model = current._get_model
previous._gpu_lock = current._gpu_lock
app = current.app


def recognize_previous(data, ext):
    started = perf_counter()
    prepare_s = 0.0
    infer_s = 0.0
    try:
        begin = perf_counter()
        try:
            png = previous.convert_to_png(data, ext) if previous.needs_conversion(ext) else data
        finally:
            prepare_s = perf_counter() - begin
        begin = perf_counter()
        try:
            latex = previous.run_ocr(png)
        finally:
            infer_s = perf_counter() - begin
        result = {"latex": latex}
    except Exception as exc:
        result = {"latex": "", "error": str(exc)}
    result["timings"] = {"prepare_s": prepare_s, "infer_s": infer_s,
                         "total_s": perf_counter() - started}
    return result


@app.post("/benchmark/baseline")
async def baseline(file: UploadFile = File(...)):
    return await run_in_threadpool(recognize_previous, await file.read(), previous.ext_of(file.filename or ""))


@app.post("/benchmark/after")
async def after(file: UploadFile = File(...)):
    result = await run_in_threadpool(current.recognize_items,
        [("formula", await file.read(), previous.ext_of(file.filename or ""))], False)
    return {**result["results"][0], "timings": result["timings"]}


@app.post("/benchmark/after/batch")
async def after_batch(files: list[UploadFile] = File(...), ids: str = Form(...)):
    return await current.ocr_batch(files=files, ids=ids, x_ocr_cache="off")


@app.on_event("startup")
def warm_previous():
    import io
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (240, 90), "white")
    ImageDraw.Draw(image).text((20, 25), "x + 1", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    result = recognize_previous(buffer.getvalue(), "png")
    if not result.get("latex"):
        raise RuntimeError("Baseline warm-up failed: " + str(result))


@app.get("/benchmark/health")
def benchmark_health():
    import torch
    return {**current.health(), "baseline_adapter": "historical preprocessing + shared pinned model loader",
            "gpu": torch.cuda.get_device_name(0), "torch": torch.__version__, "cuda": torch.version.cuda}
