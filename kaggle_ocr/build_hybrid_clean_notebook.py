"""Build a self-contained, one-screen notebook for the forwarded OCR code."""
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
TARGET = HERE / "hybrid_ocr_clean.ipynb"


def build(target=TARGET):
    app = (HERE / "hybrid_clean_app.py").read_text(encoding="utf-8")
    worker = (HERE / "hybrid_clean_worker.py").read_text(encoding="utf-8")
    image_helpers = (HERE / "hybrid_formula_images.py").read_text(encoding="utf-8")
    helper_import = "from hybrid_formula_images import mark_docx_images, prepare_image_plan, record_ocr_result, write_image_report"
    if worker.count(helper_import) != 1:
        raise RuntimeError("Image helper embedding marker missing")
    # Embed the adapter, not an import from GitHub or an old notebook checkout.
    worker = worker.replace(helper_import, image_helpers, 1)
    print_helpers = (HERE / "hybrid_exam_export.py").read_text(encoding="utf-8")
    print_import = "from hybrid_exam_export import export_exam_pages"
    if worker.count(print_import) != 1:
        raise RuntimeError("Print helper embedding marker missing")
    worker = worker.replace(print_import, print_helpers, 1)
    version = hashlib.sha256((app + worker).encode()).hexdigest()[:12]
    introduction = """# Chạy thử DOCX — Pandoc + DeepSeek-OCR-2


1. Giữ notebook **Private**, bật **Internet** và chọn **GPU** trong Settings.
2. Bấm **Run All** một lần. Notebook chỉ mở giao diện, chưa chạy OCR.
3. Bấm **Chọn DOCX** ở giao diện bên dưới → đợi hiện tên file → bấm **Chạy OCR**.
4. Đợi hoàn tất rồi bấm **Tải kết quả ZIP**.

Khi chạy, nút đổi chữ thành **Đang chạy — xem trạng thái**. Khung trạng thái ghi bước hiện tại, thời gian và PID; mỗi 5 giây có tín hiệu tiến trình còn chạy kể cả khi chưa có log mới. Đây không phải phần trăm hoàn thành hay bằng chứng tiến trình không bị kẹt. Cài LibreOffice hiện log trực tiếp, có giới hạn chờ. Hoàn tất, lỗi hoặc bị ngắt đều được ghi bằng chữ; không cần đoán theo màu nút.

Kết quả có **de-thi.html** để in ở kích thước ảnh/công thức của DOCX, không dùng kích thước PNG đã phóng lớn cho OCR. Mở HTML rồi bấm **In / lưu PDF**, chọn tỉ lệ 100% và tắt header/footer của trình duyệt. Phần OCR được tách sang bản đối chiếu, không chèn thêm vào trang đề khi in. Nếu LibreOffice Writer chuyển được DOCX, ZIP còn có **de-thi-goc.pdf** giữ bố cục Word gốc (không phải PDF do OCR sinh). HTML có thể khác ngắt trang; PDF có thể thay phông nếu thiếu phông Word.

Nếu xử lý thất bại, giao diện hiển thị lỗi gốc và nút **Tải log lỗi (run.log)**. Gửi log đó để xác định bước/thư viện lỗi; không cần sửa cell.

Nếu DOCX đã nằm trong dataset, mở **Hoặc chọn DOCX đã có trên Kaggle**, bấm **Làm mới** rồi chọn file. Nếu chỉ có một DOCX, notebook tự chọn. Thiếu file/GPU thì nút chạy bị khóa, không cần sửa code.

Lần đầu cần tải model và cài thư viện OCR riêng. Thư viện OCR chạy trong tiến trình riêng, không hạ phiên bản Transformers/Tokenizers của kernel notebook.
Trong lúc cài, log hiển thị gói đang tải/cài; chỉ khi xuất hiện bước nạp DeepSeek-OCR-2/OCR ảnh thì model mới bắt đầu làm việc.

Giữ model `deepseek-ai/DeepSeek-OCR-2`, BF16, eager attention và cấu hình OCR hiện tại. Bản này đọc trực tiếp quan hệ ảnh trong DOCX (kể cả preview MathType/VML), giữ vị trí bằng marker, gửi mọi ảnh đọc được và không trắng vào OCR. Không bỏ ảnh vì nhỏ hơn 80 px, bị đoán là hình vẽ hoặc có alt-text. Ảnh trùng chỉ OCR một lần.

WMF/EMF/SVG được chuyển sang PNG bằng LibreOffice Draw. Nếu cần, lần đầu tự cài LibreOffice nên sẽ lâu hơn; nếu chuyển đổi lỗi thì giữ file gốc và báo cần kiểm tra, không âm thầm bỏ ảnh. ZIP có `image-report.json` ghi trạng thái từng ảnh, kết quả OCR thô và số lỗi. Word Equation gốc vẫn do Pandoc đọc trực tiếp, không giả là đã OCR.

Nếu không có ảnh cần OCR, giao diện ghi rõ **không có inference model**, không coi đó là benchmark OCR. Kết quả ZIP có Markdown, ảnh, báo cáo từng ảnh, log và metrics. Mỗi lượt có thư mục riêng, không xóa kết quả cũ.

Đã kiểm tra luồng nhập file/UI và cú pháp local; chưa xác nhận inference GPU của bản notebook này trên Kaggle.

Tham khảo kỹ thuật: [model](https://huggingface.co/deepseek-ai/DeepSeek-OCR-2), [pip --target](https://pip.pypa.io/en/stable/cli/pip_install/#cmdoption-t).
"""
    bootstrap = f'''# Chạy cell này một lần. Mọi thao tác tiếp theo ở các nút bên dưới.
import importlib.util
from pathlib import Path
import subprocess
import sys

if importlib.util.find_spec("ipywidgets") is None:
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "ipywidgets>=8,<9"], check=True)

APP_SOURCE = {app!r}
WORKER_SOURCE = {worker!r}
APP_BUILD = {version!r}

# Isolated namespace: never reuse INPUT_FOLDER/choose_docx from an older cell.
app_namespace = {{"__name__": "hybrid_clean_ui"}}
exec(compile(APP_SOURCE, "<hybrid-clean-ui>", "exec"), app_namespace)
hybrid_app = app_namespace["launch"](
    globals().get("HYBRID_APP_ROOT", "/kaggle/working/hybrid_ocr_clean"),
    WORKER_SOURCE,
)
'''
    notebook = {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
            "hybrid_clean_build": version,
        },
        "cells": [
            {"cell_type": "markdown", "id": "instructions", "metadata": {}, "source": introduction.splitlines(keepends=True)},
            {"cell_type": "code", "id": "open-interface", "metadata": {}, "execution_count": None,
             "outputs": [], "source": bootstrap.splitlines(keepends=True)},
        ],
    }
    target = Path(target)
    serialized = json.dumps(notebook, ensure_ascii=False, indent=1)
    if len(serialized.encode()) >= 1_000_000:
        raise RuntimeError("Notebook exceeds the Kaggle source limit")
    target.write_text(serialized + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    target = build()
    print(target)
    print(f"{target.stat().st_size:,} bytes")
