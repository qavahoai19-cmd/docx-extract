"""MathType OLE (WMF/EMF) -> LaTeX qua OCR endpoint ngoài (Colab/RunPod/...).

docx-extract không tự chạy model OCR nữa (máy yếu, không GPU) — chỉ gửi ảnh
công thức tới một endpoint HTTP do người dùng tự host (vd notebook Colab expose
qua ngrok/cloudflared, hoặc RunPod serverless). Endpoint tự lo việc convert
WMF/EMF -> raster và chạy DeepSeek-OCR-2.

Cấu hình qua biến môi trường:
- DOCX_EXTRACT_OCR_ENDPOINT: URL endpoint (bắt buộc, thiếu -> bỏ qua OCR, None)
- DOCX_EXTRACT_OCR_API_KEY: optional, gửi kèm header Authorization: Bearer <key>
- DOCX_EXTRACT_OCR_TIMEOUT: optional, giây (mặc định 30)

Giao thức: POST multipart/form-data, field "file" = (formula.<ext>, bytes gốc).
Response JSON kỳ vọng: {"latex": "<chuỗi LaTeX>"}.
"""
import os

import requests

_DEFAULT_TIMEOUT = 30


def image_to_latex(data: bytes, ext: str) -> str | None:
    """Gửi ảnh công thức tới OCR endpoint ngoài, nhận về LaTeX.
    None nếu lỗi bất kỳ bước nào (endpoint chưa cấu hình, mạng lỗi, timeout,
    response không hợp lệ, hoặc endpoint không trả LaTeX) — KHÔNG crash."""
    endpoint = os.environ.get("DOCX_EXTRACT_OCR_ENDPOINT")
    if not endpoint:
        return None
    headers = {}
    api_key = os.environ.get("DOCX_EXTRACT_OCR_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    timeout = float(os.environ.get("DOCX_EXTRACT_OCR_TIMEOUT", _DEFAULT_TIMEOUT))
    try:
        resp = requests.post(
            endpoint,
            files={"file": (f"formula.{ext}", data)},
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return None
    latex = payload.get("latex")
    return latex or None
