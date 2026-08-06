"""Logic thuần (không phụ thuộc torch/fastapi) dùng chung cho ocr_server.py.

Tách riêng để có thể unit-test trên bất kỳ máy nào (kể cả máy không có GPU/
LibreOffice) — ocr_server.py chỉ import các hàm này rồi ghép với FastAPI/model.
"""

_RASTER_EXTS = {"png", "jpg", "jpeg", "bmp", "gif", "webp"}
_VECTOR_EXTS = {"wmf", "emf"}


def ext_of(filename: str) -> str:
    """Lấy phần mở rộng (chữ thường, không dấu chấm) từ tên file."""
    return (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()


def needs_conversion(ext: str) -> bool:
    """WMF/EMF cần convert sang raster (PNG) trước khi đưa vào model OCR."""
    return ext.lower() in _VECTOR_EXTS


def build_soffice_cmd(input_path: str, out_dir: str) -> list[str]:
    """Lệnh LibreOffice headless convert 1 file WMF/EMF sang PNG."""
    return [
        "soffice", "--headless", "--norestore", "--convert-to", "png",
        "--outdir", out_dir, input_path,
    ]
