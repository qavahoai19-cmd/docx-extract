"""MathType OLE (WMF/EMF) -> LaTeX qua OCR (DeepSeek-OCR-2).

torch/transformers/pythonnet được import BÊN TRONG hàm (không ở top-level)
để phần còn lại của package không bắt buộc các gói này khi không đụng OLE.
"""
import os
import tempfile

_MODEL_NAME = "deepseek-ai/DeepSeek-OCR-2"
_MODEL = None
_TOKENIZER = None


def _get_model():
    """Lazy-singleton load model — chỉ tải/khởi tạo một lần cho cả tiến trình."""
    global _MODEL, _TOKENIZER
    if _MODEL is None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        _TOKENIZER = AutoTokenizer.from_pretrained(_MODEL_NAME, trust_remote_code=True)
        model = AutoModel.from_pretrained(
            _MODEL_NAME, trust_remote_code=True, use_safetensors=True
        )
        model = model.eval().to(torch.bfloat16)
        try:
            model = model.cuda()
        except Exception:
            pass  # không có GPU -> chạy CPU (chậm hơn, vẫn chạy được)
        _MODEL = model
    return _TOKENIZER, _MODEL


def wmf_to_png(data: bytes, ext: str) -> bytes | None:
    """Convert WMF/EMF bytes -> PNG bytes qua GDI+ (.NET System.Drawing). None nếu lỗi."""
    try:
        import clr  # pythonnet

        clr.AddReference("System.Drawing")
        from System.Drawing import Image as NetImage
        from System.Drawing.Imaging import ImageFormat
        from System.IO import MemoryStream

        in_stream = MemoryStream(data)
        img = NetImage.FromStream(in_stream)
        out_stream = MemoryStream()
        img.Save(out_stream, ImageFormat.Png)
        return bytes(out_stream.ToArray())
    except Exception:
        return None


def image_to_latex(data: bytes, ext: str) -> str | None:
    """OCR ảnh công thức (WMF/EMF hoặc PNG sẵn) ra LaTeX. None nếu lỗi bất kỳ bước nào."""
    try:
        png = wmf_to_png(data, ext) if ext.lower() in ("wmf", "emf") else data
        if png is None:
            return None
        tokenizer, model = _get_model()
        with tempfile.TemporaryDirectory() as tmp:
            img_path = os.path.join(tmp, "formula.png")
            with open(img_path, "wb") as f:
                f.write(png)
            result = model.infer(
                tokenizer,
                prompt="<image>\nFree OCR.",
                image_file=img_path,
                base_size=1024,
                image_size=640,
                crop_mode=True,
                save_results=False,
                output_path=tmp,
            )
        text = result.strip() if isinstance(result, str) else None
        return text or None
    except Exception:
        return None
