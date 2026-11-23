"""FastAPI OCR server chạy trong Google Colab (T4 GPU).

Nhận ảnh công thức MathType OLE (WMF/EMF) từ docx-extract, convert sang PNG
(LibreOffice headless — Colab chạy Linux, không có GDI+ Windows), OCR sang
LaTeX bằng DeepSeek-OCR-2. Khớp đúng contract của docx_extract.mathocr.

Cách chạy trong Colab — xem README.md để có đầy đủ các cell.
"""
import io
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from time import perf_counter
from collections import OrderedDict
from contextlib import nullcontext

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from PIL import Image, ImageDraw

from ocr_logic import (adapt_infer_dtype, build_soffice_batch_cmd, crop_whitespace,
                       ext_of, needs_conversion, select_model_dtype)

app = FastAPI(title="docx-extract mathtype OCR server")

# DeepSeek-OCR-2 (transformers wrapper model.infer()) không phải batch API —
# chạy song song nhiều request trên cùng 1 GPU dễ tranh chấp bộ nhớ/crash.
# Khóa để đảm bảo tại một thời điểm chỉ có 1 lần suy luận GPU chạy.
_gpu_lock = threading.Lock()
_cache_lock = threading.Lock()

_MODEL_NAME = "deepseek-ai/DeepSeek-OCR-2"
_model = None
_tokenizer = None
_model_dtype = None
_warmed_up = False
_resolved_revision = os.getenv("DOCX_OCR_MODEL_REVISION", "main")
_backend = os.getenv("DOCX_OCR_BACKEND", "transformers")
_inference_batch_size = max(1, min(8, int(os.getenv("DOCX_OCR_INFERENCE_BATCH_SIZE", "4"))))
_batch_verified = False
_batch_validation_error = ""
_batch_validation_timings = {}
_image_size = int(os.getenv("DOCX_OCR_IMAGE_SIZE", "768"))
if _image_size not in {768, 1024}:
    raise ValueError("DOCX_OCR_IMAGE_SIZE must be 768 or 1024")
_prompt = "<image>\nOCR this formula to LaTeX."
_result_cache = OrderedDict()
_cache_limit = 2048

# Neu bien moi truong HF_HOME duoc dat truoc khi uvicorn start (vd tro vao
# Google Drive da mount), transformers se cache trong so model vao do -> lan
# sau khoi dong lai runtime Colab khong phai tai lai tu HuggingFace.
# Xem Cell 4b trong notebook de dat bien nay.


def _get_model():
    """Lazy-singleton load model — chỉ tải/khởi tạo một lần cho cả process."""
    global _model, _tokenizer, _resolved_revision, _model_dtype
    if _model is None:
        if _backend == "vllm":
            from vllm import LLM
            from vllm.model_executor.models.deepseek_ocr import NGramPerReqLogitsProcessor
            _model = LLM(model=_MODEL_NAME, revision=_resolved_revision,
                         enable_prefix_caching=False, mm_processor_cache_gb=0,
                         logits_processors=[NGramPerReqLogitsProcessor],
                         max_model_len=8192, gpu_memory_utilization=0.85)
            config = _model.llm_engine.model_config.hf_config
            _resolved_revision = getattr(config, "_commit_hash", None) or _resolved_revision
            return None, _model
        if _backend != "transformers":
            raise ValueError("DOCX_OCR_BACKEND must be transformers or vllm")
        import torch
        from transformers import AutoModel, AutoTokenizer

        _model_dtype = select_model_dtype(torch, os.getenv("DOCX_OCR_DTYPE", "auto"))
        _tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME, revision=_resolved_revision, trust_remote_code=True)
        # dtype=bfloat16 + low_cpu_mem_usage=True: nap thang trong so bf16, tranh
        # buoc trung gian nap fp32 vao RAM CPU truoc (~13-14GB, de gay OOM-kill tren
        # RAM CPU free-tier Colab ~12GB, khac voi VRAM GPU).
        # Luu y: dung torch_dtype (khong phai dtype) -- code remote cua model nay
        # (DeepseekOCR2ForCausalLM, transformers==4.46.3) chi nhan torch_dtype qua
        # __init__, dtype se bao TypeError: unexpected keyword argument 'dtype'.
        m = AutoModel.from_pretrained(
            _MODEL_NAME,
            revision=_resolved_revision,
            trust_remote_code=True,
            use_safetensors=True,
            torch_dtype=_model_dtype,
            _attn_implementation=os.getenv("DOCX_OCR_ATTENTION", "eager"),
            low_cpu_mem_usage=True,
        )
        _model = m.eval().cuda()
        adapt_infer_dtype(_model, _model_dtype, torch)
        _resolved_revision = getattr(_model.config, "_commit_hash", None) or _resolved_revision
    return _tokenizer, _model


@app.on_event("startup")
def _preload_model_on_startup() -> None:
    """Tải + khởi tạo model ngay khi server start, trước khi nhận request đầu tiên.

    Nếu không có bước này, request OCR đầu tiên sẽ tự kích hoạt _get_model() và
    bị treo rất lâu (download + load model ~3-3.4B tham số) ngay giữa lúc client
    tưởng server đã sẵn sàng.
    """
    _get_model()
    if _backend == "transformers" and _inference_batch_size > 1:
        validate_transformers_batch()
    if os.getenv("DOCX_OCR_WARMUP", "0") == "1":
        warmup_model()


def _crop_whitespace(png_bytes: bytes, padding: int = 20) -> bytes:
    """Cat bo vien trang thua quanh cong thuc, giu 1 khoang padding nho.

    LibreOffice xuat WMF/EMF sang PNG tren ca 1 "trang" mac dinh (vd 800x1131),
    trong khi noi dung cong thuc thuc te thuong chi chiem 1 vung rat nho o giua
    (vd 1 ky hieu <=50x50px giua canvas trang khong lo). Vung trang qua lon so
    voi noi dung khien DeepSeek-OCR-2 "lac" va hallucinate ra noi dung khong
    lien quan (da quan sat thuc te: tra ve ca doan van hoc thuat khong lien
    quan cho 1 anh chi co mui ten "=>"). Crop sat noi dung + padding nho giup
    model tap trung dung vao cong thuc.
    """
    return crop_whitespace(png_bytes, padding)


def convert_to_png(data: bytes, ext: str) -> bytes:
    """Convert WMF/EMF bytes -> PNG bytes qua LibreOffice headless (subprocess),
    sau do crop bot vien trang thua (xem _crop_whitespace)."""
    prepared, errors = _prepare_images([("formula", data, ext)])
    if errors:
        raise ValueError(errors["formula"])
    return prepared["formula"]


def _infer_transformers(png_bytes: bytes) -> str:
    """Chạy DeepSeek-OCR-2 trên ảnh PNG công thức (đã tightly-cropped sẵn)."""
    tokenizer, model = _get_model()
    with tempfile.TemporaryDirectory() as tmp:
        img_path = os.path.join(tmp, "formula.png")
        with open(img_path, "wb") as f:
            f.write(png_bytes)
        # The caller owns the GPU lock. Only 768/1024 are supported by this
        # encoder; eval_mode=True is needed for infer() to return the text.
        result = model.infer(tokenizer, prompt=_prompt, image_file=img_path,
                             base_size=_image_size, image_size=_image_size,
                             crop_mode=False, save_results=False,
                             eval_mode=True, output_path=tmp)
    return result.strip() if isinstance(result, str) else ""


def _namespace():
    settings = [_MODEL_NAME, _resolved_revision, _backend, _image_size, _prompt,
                "crop-v2", str(_model_dtype), os.getenv("DOCX_OCR_ATTENTION", "eager"),
                os.getenv("DOCX_OCR_MAX_TOKENS", "1024"), _inference_batch_size,
                os.getenv("DOCX_OCR_BATCH_MAX_TOKENS", "8192")]
    return hashlib.sha256(json.dumps(settings).encode()).hexdigest()


def _prepare_images(items):
    prepared, errors = {}, {}
    with tempfile.TemporaryDirectory(prefix="ocr-batch-") as tmp:
        vectors = []
        for index, (oid, data, ext) in enumerate(items):
            if needs_conversion(ext):
                source = Path(tmp) / f"formula_{index}.{ext}"
                source.write_bytes(data)
                vectors.append((oid, source))
            else:
                try:
                    prepared[oid] = _crop_whitespace(data)
                except Exception as exc:
                    errors[oid] = str(exc)
        if vectors:
            try:
                subprocess.run(build_soffice_batch_cmd([str(p) for _, p in vectors], tmp, str(Path(tmp)/"profile")),
                               check=False, capture_output=True, timeout=60)
                for oid, source in vectors:
                    try:
                        prepared[oid] = _crop_whitespace(source.with_suffix(".png").read_bytes())
                    except Exception as exc:
                        errors[oid] = str(exc)
            except Exception as exc:
                errors.update({oid: str(exc) for oid, _ in vectors})
    return prepared, errors


def _infer_vllm(pngs):
    from vllm import SamplingParams
    _, model = _get_model()
    inputs = [{"prompt": _prompt, "multi_modal_data": {"image": Image.open(io.BytesIO(png)).convert("RGB")}} for png in pngs]
    params = SamplingParams(temperature=0.0, max_tokens=int(os.getenv("DOCX_OCR_MAX_TOKENS", "1024")),
                            extra_args=dict(ngram_size=30, window_size=90,
                                            whitelist_token_ids={128821, 128822}), skip_special_tokens=True)
    outputs = model.generate(inputs, params)
    if len(outputs) != len(pngs):
        raise ValueError("Model returned a different batch length")
    return [{"latex": output.outputs[0].text.strip(),
             "error": "token limit reached" if output.outputs[0].finish_reason == "length" else ""}
            for output in outputs]


def _infer_transformers_batch(pngs):
    from transformers_batch import infer_batch
    tokenizer, model = _get_model()
    return infer_batch(model, tokenizer, pngs, prompt=_prompt, image_size=_image_size,
                       dtype=_model_dtype, max_new_tokens=int(os.getenv("DOCX_OCR_BATCH_MAX_TOKENS", "8192")))


def _clear_cuda_cache():
    import torch
    torch.cuda.empty_cache()


def _infer_bounded_batch(images):
    try:
        results = _infer_transformers_batch(images)
        if len(results) != len(images):
            raise ValueError("Model returned a different batch length")
        return results
    except Exception as exc:
        oom = type(exc).__name__ == "OutOfMemoryError"
        error = str(exc)
    # Leave the exception scope before releasing CUDA allocations and retrying.
    if oom and len(images) > 1:
        _clear_cuda_cache()
        middle = len(images) // 2
        return _infer_bounded_batch(images[:middle]) + _infer_bounded_batch(images[middle:])
    return [{"latex": "", "error": error} for _ in images]


def validate_transformers_batch():
    """Use a batch only after checking full outputs against serial inference."""
    global _inference_batch_size, _batch_verified, _batch_validation_error, _batch_validation_timings
    _batch_verified, _batch_validation_error = False, ""
    _batch_validation_timings = {}
    try:
        samples = []
        for index in range(_inference_batch_size):
            image = Image.new("RGB", (300, 100), "white")
            ImageDraw.Draw(image).text((20, 25), f"x + {index + 1}", fill="black", font_size=36)
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            samples.append(buffer.getvalue())
        _infer_transformers(samples[0])  # Exclude first-use kernels from timing.
        serial_started = perf_counter()
        expected = [_infer_transformers(image) for image in samples]
        serial_s = perf_counter() - serial_started
        batch_started = perf_counter()
        actual = _infer_transformers_batch(samples)
        batch_s = perf_counter() - batch_started
        _batch_validation_timings = {"serial_s": serial_s, "batch_s": batch_s}
        if (len(actual) != len(expected) or not all(expected)
                or any(result.get("error") or result.get("latex") != baseline
                       for result, baseline in zip(actual, expected))):
            raise ValueError("Batch output does not match complete serial output")
        if batch_s >= serial_s:
            raise ValueError("Batch output matches, but this startup check was not faster")
        _batch_verified = True
    except Exception as exc:
        _batch_validation_error = str(exc)
        _inference_batch_size = 1


def _cache_get(key, enabled):
    if not enabled:
        return None
    with _cache_lock:
        value = _result_cache.get(key)
        if value:
            _result_cache.move_to_end(key)
        return value


def _cache_put(key, latex, enabled):
    if enabled and latex:
        with _cache_lock:
            _result_cache[key] = latex
            _result_cache.move_to_end(key)
            while len(_result_cache) > _cache_limit:
                _result_cache.popitem(last=False)


def recognize_items(items, use_cache=True):
    started = perf_counter()
    source_groups, results, pending, source_keys = {}, {}, [], {}
    for oid, data, ext in items:
        key = ("source", ext.lower(), hashlib.sha256(data).digest())
        source_groups.setdefault(key, []).append((oid, data, ext))
    for key, group in source_groups.items():
        cached = _cache_get(key, use_cache)
        if cached:
            results.update({oid: {"id": oid, "latex": cached} for oid, _, _ in group})
        else:
            pending.append(group[0])
            source_keys[group[0][0]] = key
    # Cache hits and exact duplicates never enter LibreOffice/crop again.
    prepared, errors = _prepare_images(pending) if pending else ({}, {})
    for oid, error in errors.items():
        for original_id, _, _ in source_groups[source_keys[oid]]:
            results[original_id] = {"id": original_id, "latex": "", "error": error}
    prepare_s = perf_counter() - started
    queue_start = perf_counter()
    with _gpu_lock if prepared else nullcontext():
        queue_s = perf_counter() - queue_start
        inference_start = perf_counter()
        groups = {}
        for oid, png in prepared.items():
            key = ("png", hashlib.sha256(png).digest())
            cached = _cache_get(key, use_cache)
            if cached:
                _cache_put(source_keys[oid], cached, use_cache)
                for original_id, _, _ in source_groups[source_keys[oid]]:
                    results[original_id] = {"id": original_id, "latex": cached}
            else:
                groups.setdefault(key, []).append((oid, png))
        missing = list(groups.items())
        if _backend == "vllm" and missing:
            try:
                inferred = _infer_vllm([group[0][1] for _, group in missing])
            except Exception as exc:
                inferred = [{"latex": "", "error": str(exc)} for _ in missing]
        else:
            inferred = []
            for offset in range(0, len(missing), _inference_batch_size):
                chunk = missing[offset:offset + _inference_batch_size]
                try:
                    if _inference_batch_size > 1:
                        batch_results = _infer_bounded_batch([group[0][1] for _, group in chunk])
                        inferred.extend(batch_results)
                    else:
                        inferred.append({"latex": _infer_transformers(chunk[0][1][0][1])})
                except Exception as exc:
                    inferred.extend({"latex": "", "error": str(exc)} for _ in chunk)
        for (key, group), result in zip(missing, inferred):
            if result.get("error"):
                result["latex"] = ""
            _cache_put(key, result["latex"], use_cache)
            for oid, _ in group:
                _cache_put(source_keys[oid], result["latex"], use_cache)
                for original_id, _, _ in source_groups[source_keys[oid]]:
                    results[original_id] = {"id": original_id, **result}
        infer_s = perf_counter() - inference_start
    return {"results": [results[oid] for oid, _, _ in items],
            "timings": {"prepare_s": prepare_s, "queue_s": queue_s,
                        "infer_s": infer_s, "total_s": perf_counter()-started}}


def run_ocr(png_bytes: bytes) -> str:
    with _gpu_lock:
        return _infer_transformers(png_bytes)


def warmup_model():
    global _warmed_up
    image = Image.new("RGB", (300, 100), "white")
    ImageDraw.Draw(image).text((20, 25), "x + 1", fill="black", font_size=36)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    result = recognize_items([("warmup", buffer.getvalue(), "png")], use_cache=False)["results"][0]
    if not result.get("latex"):
        raise RuntimeError("Model warm-up failed: " + str(result.get("error", "empty OCR result")))
    _warmed_up = True


@app.middleware("http")
async def check_api_key(request, call_next):
    expected = os.getenv("DOCX_OCR_API_KEY", "")
    if expected and request.url.path != "/health":
        actual = request.headers.get("Authorization", "")
        if not hmac.compare_digest(actual, "Bearer " + expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _model is not None,
            "warmed_up": _warmed_up, "dtype": str(_model_dtype),
            "batch": True, "max_batch_size": 32, "backend": _backend,
            "inference_batch_size": _inference_batch_size,
            "batch_verified": _batch_verified,
            "batch_validation_error": _batch_validation_error,
            "batch_validation_timings": _batch_validation_timings,
            "cache_bypass_header": "X-OCR-Cache",
            "cache_namespace": _namespace()}


@app.post("/debug_png")
async def debug_png(file: UploadFile = File(...)):
    """Debug: convert WMF/EMF -> PNG va tra ve chinh anh PNG do (khong chay OCR).

    Dung de kiem tra buoc convert_to_png() co ra anh cong thuc hop le hay khong
    (vd anh trong/loi/qua nho) ma khong can vao Colab xem thu cong.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    ext = ext_of(file.filename or "")
    png = await run_in_threadpool(convert_to_png, data, ext) if needs_conversion(ext) else _crop_whitespace(data)
    return Response(content=png, media_type="image/png")


@app.post("/ocr")
async def ocr(file: UploadFile = File(...), x_ocr_cache: str = Header("on")):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    ext = ext_of(file.filename or "")
    try:
        result = await run_in_threadpool(recognize_items, [("formula", data, ext)], x_ocr_cache.lower() != "off")
        return JSONResponse(result["results"][0])
    except Exception as exc:
        # Lỗi OCR/convert -> vẫn trả 200 với latex rỗng, để client (docx-extract)
        # coi như "không OCR được" (cảnh báo, giữ ảnh gốc) thay vì raise 500 phá batch.
        return JSONResponse({"latex": "", "error": str(exc)})


@app.post("/ocr/batch")
async def ocr_batch(files: list[UploadFile] = File(...), ids: str = Form(...), x_ocr_cache: str = Header("on")):
    try:
        item_ids = json.loads(ids)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid ids")
    if (not isinstance(item_ids, list) or not 1 <= len(files) <= 32
            or len(item_ids) != len(files) or any(not isinstance(x, str) or not x for x in item_ids)
            or len(set(item_ids)) != len(item_ids)):
        raise HTTPException(status_code=400, detail="ids must be unique and match 1..32 files")
    items = [(oid, await file.read(), ext_of(file.filename or "")) for oid, file in zip(item_ids, files)]
    return await run_in_threadpool(recognize_items, items, x_ocr_cache.lower() != "off")
