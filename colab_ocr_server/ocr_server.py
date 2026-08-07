"""FastAPI OCR server chạy trong Google Colab (T4 GPU).

Nhận ảnh công thức MathType OLE (WMF/EMF) từ docx-extract, convert sang PNG
(LibreOffice headless — Colab chạy Linux, không có GDI+ Windows), OCR sang
LaTeX bằng DeepSeek-OCR-2. Khớp đúng contract của docx_extract.mathocr.

Cách chạy trong Colab — xem README.md để có đầy đủ các cell.
"""
import io
import os
import subprocess
import tempfile
import threading

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from PIL import Image

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
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    # bbox cua vung khac mau trang (nguong 250 de chiu nhieu anti-aliasing nhe)
    gray = img.convert("L")
    bbox = gray.point(lambda p: 0 if p < 250 else 255).getbbox()
    if bbox is None:
        return png_bytes  # anh toan trang -> tra nguyen goc, de OCR tu bao loi
    left, top, right, bottom = bbox
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(img.width, right + padding)
    bottom = min(img.height, bottom + padding)
    cropped = img.crop((left, top, right, bottom))
    out = io.BytesIO()
    cropped.save(out, format="PNG")
    return out.getvalue()


def convert_to_png(data: bytes, ext: str) -> bytes:
    """Convert WMF/EMF bytes -> PNG bytes qua LibreOffice headless (subprocess),
    sau do crop bot vien trang thua (xem _crop_whitespace)."""
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
            raw_png = f.read()
    return _crop_whitespace(raw_png)


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
                prompt="<image>\nOCR this formula to LaTeX.",
                image_file=img_path,
                # QUAN TRONG: Qwen2Decoder2Encoder.forward() (deepencoderv2.py) chi dinh
                # nghia 2 embedding co dinh cho n_query == 144 (ung voi anh 768) hoac
                # n_query == 256 (ung voi anh 1024) -- khong co nhanh else. base_size=640
                # (hoac 512/1280) se sinh n_query khac 144/256 -> "param_img" khong duoc
                # gan -> UnboundLocalError. Chi 768 va 1024 la gia tri hop le trong thuc
                # te, du comment trong code goc co nhac 640/512/1280.
                base_size=1024,
                image_size=1024,
                crop_mode=False,   # KHÔNG tile — đây là 1 công thức đơn, không phải cả trang
                save_results=False,
                # QUAN TRONG: infer() chi return outputs khi eval_mode=True. Voi
                # eval_mode=False (mac dinh) va save_results=False, ham chay xong OCR
                # (in qua streamer noi bo) nhung KHONG return gi ca (None) -> code goi
                # se luon nhan chuoi rong. Phai bat eval_mode=True de lay duoc ket qua.
                eval_mode=True,
                output_path=tmp,
            )
    return result.strip() if isinstance(result, str) else ""


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _model is not None}


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
    png = convert_to_png(data, ext) if needs_conversion(ext) else data
    return Response(content=png, media_type="image/png")


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
