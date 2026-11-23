"""Bundle a CPU-only Kaggle notebook that shows original equations and images."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent


def cell(kind, source, name):
    item = {"cell_type": kind, "id": name, "metadata": {}, "source": source.splitlines(keepends=True)}
    if kind == "code":
        item.update(execution_count=None, outputs=[])
    return item


def build(sample=None, sample_start_heading=None):
    files = {}
    for path in sorted((ROOT / "src/docx_extract").glob("*.py")):
        files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for name in ("notebook_upload.py", "preserve_upload.py", "question_extract.py", "exam_print.py", "questions-only.css"):
        files["kaggle_ocr/" + name] = (HERE / name).read_bytes()
    for name in ("scripts/preview-template.html", "colab_ocr_server/ocr_logic.py"):
        files[name] = (ROOT / name).read_bytes()
    sample_paths = [] if sample is None else [sample] if isinstance(sample, (str, Path)) else list(sample)
    samples = []
    for index, path in enumerate(sample_paths):
        path = Path(path)
        name = 'data/sample.docx' if index == 0 else f'data/sample-{index + 1}.docx'
        files[name] = path.read_bytes()
        samples.append({'name': path.name, 'path': name})
        if index == 0 and sample_start_heading:
            samples[-1]['start_heading'] = sample_start_heading
    metadata = {"mode": "preserve_formulas", "startup_version": 2,
                "sample_name": samples[0]['name'] if samples else None,
                "samples": samples,
                "files_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    metadata["source_version"] = hashlib.sha256(
        json.dumps(metadata, sort_keys=True).encode()
    ).hexdigest()[:12]
    files["bundle.json"] = json.dumps(metadata, ensure_ascii=False).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 18, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    payload = stream.getvalue()
    encoded, digest = base64.b85encode(payload).decode(), hashlib.sha256(payload).hexdigest()
    cells = [cell("markdown", """# Bóc câu hỏi — giữ công thức gốc

Xuất đề thi A4 có đầu đề, thông tin thí sinh, ngữ liệu, câu hỏi, công thức, hình và A–D.

- Giữ notebook **Private** vì có đề mẫu/đề tải lên. Accelerator để **None (CPU)**, bật **Internet** lần đầu để cài thư viện.
- Bấm **Run All**. Đề mẫu đầu tiên tự hiện ở cuối. Dùng menu **Đề mẫu → Chạy đề mẫu** để đổi đề, hoặc **Chọn Word/ZIP → Bóc câu hỏi** để đọc đề khác.
- Mở **Thông tin bản in** để điền trường/đơn vị, tên kỳ thi, môn, thời gian và mã đề trước khi bóc. Bản **Đề thi A4** mặc định ẩn đáp án; bấm **Tải bản đề thi A4**, mở HTML và **In / lưu PDF**.
- Đáp án tô nền ở chữ A–D hoặc nội dung phương án được nhận từ định dạng Word. Gạch chân trong từ của bài phát âm được giữ nguyên; chữ in đậm/màu xanh không tự được coi là đáp án đúng.
- Công thức Word Equation hiển thị trực tiếp từ XML gốc; công thức dạng ảnh giữ ảnh.
- **Không chuyển sang LaTeX, không nạp model, không gọi OCR.** Đây là chế độ xem/bóc đề, không phải benchmark tốc độ OCR.
- MathType WMF/EMF được chuyển định dạng sang PNG bằng LibreOffice để trình duyệt xem được. Nếu chuyển ảnh lỗi, thông báo sẽ hiện và tệp gốc vẫn có trong ZIP.
- Bản xem nằm ngay dưới nút tải kết quả ZIP. Có thể mở `questions.html` trong ZIP trên máy để xem toàn màn hình/in.
""", "intro"), cell("code", '''import os, sys, subprocess
from pathlib import Path
WORK_ROOT = Path("/kaggle/working/docx-questions-original")
os.environ["DOCX_EXTRACT_NATIVE_MATH"] = "0"
packages = ["lxml", "requests", "olefile>=0.47", "Pillow>=10.1", "ipywidgets>=8,<9"]
subprocess.run([sys.executable, "-m", "pip", "install", "-q", *packages], check=True)
import shutil
if not shutil.which("soffice"):
    subprocess.run(["apt-get", "update", "-qq"], check=True)
    subprocess.run(["apt-get", "install", "-y", "-qq", "libreoffice-core", "libreoffice-impress"], check=True)
print("Sẵn sàng bóc đề trên CPU; không tải model OCR.")
''', "dependencies"), cell("code", f'''import base64, hashlib, io, json, sys, zipfile
from pathlib import Path
PAYLOAD = {encoded!r}
payload = base64.b85decode(PAYLOAD)
if hashlib.sha256(payload).hexdigest() != {digest!r}:
    raise RuntimeError("Bundle integrity check failed")
# A new bundle gets its own source directory, including its bytecode cache.
WORK_ROOT = WORK_ROOT.parent / {('docx-questions-original-' + digest[:12])!r}
WORK_ROOT.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(io.BytesIO(payload)) as archive:
    for member in archive.infolist():
        if not (WORK_ROOT/member.filename).resolve().is_relative_to(WORK_ROOT.resolve()):
            raise RuntimeError("Invalid bundle path")
    archive.extractall(WORK_ROOT)
bundle = json.loads((WORK_ROOT/"bundle.json").read_text(encoding="utf-8"))
for name, expected in bundle["files_sha256"].items():
    if hashlib.sha256((WORK_ROOT/name).read_bytes()).hexdigest() != expected:
        raise RuntimeError("Source integrity check failed: " + name)
for folder in ("src", "kaggle_ocr", "colab_ocr_server"):
    sys.path.insert(0, str(WORK_ROOT/folder))
print("Đã giải nén code và đề mẫu.")
''', "unpack"), cell("markdown", "## Bóc và xem câu hỏi\nĐề mẫu tự chạy một lần khi chạy ô dưới. Công thức không cần LaTeX. Không suy luận tính đúng của đáp án.", "ui-note"), cell("code", f'''import importlib
EXPECTED_SOURCE_VERSION = {metadata["source_version"]!r}
if bundle.get("source_version") != EXPECTED_SOURCE_VERSION:
    raise RuntimeError("Phiên đang dùng bundle cũ. Chạy Run All trong bản notebook mới để cập nhật bộ đọc.")
for name, expected in bundle["files_sha256"].items():
    if hashlib.sha256((WORK_ROOT/name).read_bytes()).hexdigest() != expected:
        raise RuntimeError("Mã nguồn trong phiên không khớp notebook. Chạy Run All để giải nén lại: " + name)
# Reloading a child module retains the old parent package's __path__.
# Remove only this bundle's modules, including the parent, and import afresh.
module_roots = {{"docx_extract", "notebook_upload", "question_extract", "preserve_upload", "exam_print", "ocr_logic"}}
for name in list(sys.modules):
    if name.partition(".")[0] in module_roots:
        del sys.modules[name]
for folder in ("src", "kaggle_ocr", "colab_ocr_server"):
    entry = str(WORK_ROOT/folder)
    sys.path[:] = [path for path in sys.path if path != entry]
    sys.path.insert(0, entry)
importlib.invalidate_caches()
from preserve_upload import show_preserve_ui
for name, module in list(sys.modules.items()):
    if name.partition(".")[0] in module_roots:
        origin = getattr(module, "__file__", None)
        if not origin or not Path(origin).resolve().is_relative_to(WORK_ROOT.resolve()):
            raise RuntimeError("Module không thuộc bundle đang chạy: " + name)
print("Bộ đọc đang chạy: " + EXPECTED_SOURCE_VERSION)
samples = [(item["name"], WORK_ROOT/item["path"], item.get("start_heading", "")) for item in bundle.get("samples", [])]
questions_ui = show_preserve_ui(WORK_ROOT, samples=samples)
''', "interface")]
    notebook = {"nbformat": 4, "nbformat_minor": 5, "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"}}, "cells": cells}
    target = HERE / "docx_questions_kaggle.ipynb"
    serialized = json.dumps(notebook, ensure_ascii=False, indent=1)
    if len(serialized.encode()) >= 1_000_000:
        raise RuntimeError("Notebook exceeds Kaggle source limit")
    target.write_text(serialized, encoding="utf-8")
    print(json.dumps({"notebook": str(target), "bytes": target.stat().st_size, "sample": metadata["sample_name"]}))
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, action="append", help="Có thể lặp lại để đóng gói nhiều đề mẫu")
    parser.add_argument('--sample-start-heading', help='Mục bắt đầu được chọn rõ ràng cho đề mẫu đầu tiên')
    args = parser.parse_args()
    build(args.sample, args.sample_start_heading)
