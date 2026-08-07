"""FastAPI OCR server chạy trong Google Colab (T4 GPU).

Nhận ảnh công thức MathType OLE (WMF/EMF) từ docx-extract, convert sang PNG
(LibreOffice headless — Colab chạy Linux, không có GDI+ Windows), OCR sang
LaTeX bằng DeepSeek-OCR-2. Khớp đúng contract của docx_extract.mathocr.

Cách chạy trong Colab — xem README.md để có đầy đủ các cell.
"""
import os
import subprocess
import tempfile
import threading

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ocr_logic import build_soffice_cmd, ext_of, needs_conversion

app = FastAPI(title="docx-extract mathtype OCR server")

# DeepSeek-OCR-2 (transformers wrapper model.infer()) không phải batch API —
# chạy song song nhiều request trên cùng 1 GPU dễ tranh chấp bộ nhớ/crash.
# Khóa để đảm bảo tại một thời điểm chỉ có 1 lần suy luận GPU chạy.
_gpu_lock = threading.Lock()

_MODEL_NAME = "deepseek-ai/DeepSeek-OCR-2"
_model = None
_tokenizer = None

# Neu bien moi truong HF_HOME duoc dat truoc khi uvicorn start (vd tro vao
# Google Drive da mount), transformers se cache trong so model vao do -> lan
# sau khoi dong lai runtime Colab khong phai tai lai tu HuggingFace.
# Xem Cell 4b trong notebook de dat bien nay.


def _get_model():
    """Lazy-singleton load model — chỉ tải/khởi tạo một lần cho cả process."""
    global _model, _tokenizer
    if _model is None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        _tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME, trust_remote_code=True)
        # dtype=bfloat16 + low_cpu_mem_usage=True: nap thang trong so bf16, tranh
        # buoc trung gian nap fp32 vao RAM CPU truoc (~13-14GB, de gay OOM-kill tren
        # RAM CPU free-tier Colab ~12GB, khac voi VRAM GPU).
        # Luu y: dung torch_dtype (khong phai dtype) -- code remote cua model nay
        # (DeepseekOCR2ForCausalLM, transformers==4.46.3) chi nhan torch_dtype qua
        # __init__, dtype se bao TypeError: unexpected keyword argument 'dtype'.
        m = AutoModel.from_pretrained(
            _MODEL_NAME,
            trust_remote_code=True,
            use_safetensors=True,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
        )
        _model = m.eval().cuda()
    return _tokenizer, _model


@app.on_event("startup")
def _preload_model_on_startup() -> None:
    """Tải + khởi tạo model ngay khi server start, trước khi nhận request đầu tiên.

    Nếu không có bước này, request OCR đầu tiên sẽ tự kích hoạt _get_model() và
    bị treo rất lâu (download + load model ~3-3.4B tham số) ngay giữa lúc client
    tưởng server đã sẵn sàng.
    """
    _get_model()


def convert_to_png(data: bytes, ext: str) -> bytes:
    """Convert WMF/EMF bytes -> PNG bytes qua LibreOffice headless (subprocess)."""
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, f"formula.{ext}")
        with open(in_path, "wb") as f:
            f.write(data)
        subprocess.run(
            build_soffice_cmd(in_path, tmp),
            check=True, capture_output=True, timeout=60,
        )
        out_path = os.path.join(tmp, "formula.png")
        with open(out_path, "rb") as f:
            return f.read()


def run_ocr(png_bytes: bytes) -> str:
    """Chạy DeepSeek-OCR-2 trên ảnh PNG công thức (đã tightly-cropped sẵn)."""
    tokenizer, model = _get_model()
    with tempfile.TemporaryDirectory() as tmp:
        img_path = os.path.join(tmp, "formula.png")
        with open(img_path, "wb") as f:
            f.write(png_bytes)
        with _gpu_lock:
            result = model.infer(
                tokenizer,
                prompt="<image>\nFree OCR.",
                image_file=img_path,
                base_size=640,     # ảnh công thức nhỏ, đã crop sẵn -> không cần 1024
                image_size=640,
                crop_mode=False,   # KHÔNG tile — đây là 1 công thức đơn, không phải cả trang
                save_results=False,
                output_path=tmp,
            )
    return result.strip() if isinstance(result, str) else ""


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _model is not None}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    ext = ext_of(file.filename or "")
    try:
        png = convert_to_png(data, ext) if needs_conversion(ext) else data
        latex = run_ocr(png)
    except Exception as exc:
        # Lỗi OCR/convert -> vẫn trả 200 với latex rỗng, để client (docx-extract)
        # coi như "không OCR được" (cảnh báo, giữ ảnh gốc) thay vì raise 500 phá batch.
        return JSONResponse({"latex": "", "error": str(exc)})
    return JSONResponse({"latex": latex})
