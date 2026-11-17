"""Build a small self-contained benchmark notebook, independent of production UI."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
BASELINE = "1d70099e4070ee0995c3d15cc47312152d4559d2"
MODEL_REVISION = "aaa02f3811945a91062062994c5c4a3f4c0af2b0"


def cell(kind, source, name):
    result = {"cell_type": kind, "id": name, "metadata": {}, "source": source.splitlines(keepends=True)}
    if kind == "code":
        result.update(execution_count=None, outputs=[])
    return result


def make_bundle():
    files = {}
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASELINE], cwd=ROOT).decode().splitlines()
    for path in paths:
        if path.endswith(".py") and path.startswith(("src/docx_extract/", "colab_ocr_server/")) and not Path(path).name.startswith("test_"):
            files["baseline/" + path] = subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT)
    for folder in (ROOT / "src/docx_extract", ROOT / "colab_ocr_server"):
        for path in sorted(folder.glob("*.py")):
            if not path.name.startswith("test_"):
                files["optimized/" + path.relative_to(ROOT).as_posix()] = path.read_bytes()
    files["optimized/kaggle_ocr/notebook_upload.py"] = (ROOT / "kaggle_ocr/notebook_upload.py").read_bytes()
    for name in ("server_bridge.py", "worker.py", "runner.py", "ui.py"):
        files["benchmark/" + name] = (HERE / name).read_bytes()
    manifest = {"baseline_revision": BASELINE, "optimized_revision": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(), "model_revision": MODEL_REVISION,
        "files_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        "baseline_adapter": "Original client/parser and convert/crop/infer flow. Shared pinned model loader replaces historical unpinned BF16 loader; same GPU lock."}
    files["bundle.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            # Stable timestamps make the notebook reproducible from identical source.
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 17, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def build():
    payload = make_bundle()
    encoded = base64.b85encode(payload).decode("ascii")
    digest = hashlib.sha256(payload).hexdigest()
    cells = [cell("markdown", """# So sánh DOCX OCR trước / sau tối ưu

Notebook benchmark riêng, có thể xóa sau khi đo. Không sửa notebook đọc đề chính.

1. Giữ notebook **Private**. Bật **GPU T4** (hoặc GPU CUDA phù hợp) và **Internet**.
2. Bấm **Run All**, chờ model sẵn sàng rồi đến ô chọn đề ở cuối.
3. Chọn Word/ZIP và bấm **Chạy cả hai và so sánh**. Cache kết quả luôn tắt.

**Mốc trước tối ưu:** Git `1d70099e4070ee0995c3d15cc47312152d4559d2`.
Hai bản dùng cùng một model DeepSeek-OCR-2 đã warm-up, revision cố định, ảnh 1024,
dtype phù hợp GPU. Bản cũ giữ parser và xử lý ảnh cũ; riêng loader được thay bằng
loader chung để chạy đúng trên T4. Đây không phải khôi phục nguyên môi trường cũ.
Bản mới gom nhiều đề, khử ảnh trùng, xử lý ảnh và thử GPU batch có kiểm tra.

Đo thời gian từ bóc Word đến xuất ZIP, không gồm upload/tải model. Kết quả khác nhau
hoặc thiếu công thức được báo để kiểm tra; không tự xem LaTeX thay đổi là sai.
Tỉ lệ tốc độ có khác biệt đầu ra chỉ mang tính tham khảo. Hai bản không chạy đồng thời.
""", "intro")]
    cells.append(cell("code", f'''import os, sys, json, time, socket, subprocess
from pathlib import Path
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ["HF_HOME"] = "/tmp/docx-ocr-huggingface"
os.environ["DOCX_EXTRACT_NATIVE_MATH"] = "0"
ROOT = Path("/kaggle/working/docx-ocr-benchmark")
MODEL_REVISION = {MODEL_REVISION!r}
OCR_GPU_BATCH_SIZE = 4
import torch
if not torch.cuda.is_available():
    raise RuntimeError("Bật GPU trong Session options rồi chạy lại.")
print("GPU:", torch.cuda.get_device_name(0), "Torch:", torch.__version__)
''', "config"))
    cells.append(cell("code", '''packages = ["fastapi", "uvicorn", "python-multipart", "Pillow>=10.1", "requests", "lxml",
            "transformers==4.46.3", "tokenizers==0.20.3", "accelerate", "einops", "addict", "easydict",
            "ipywidgets>=8,<9", "olefile>=0.47"]
subprocess.run([sys.executable, "-m", "pip", "install", "-q", *packages], check=True)
subprocess.run(["apt-get", "update", "-qq"], check=True)
subprocess.run(["apt-get", "install", "-y", "-qq", "libreoffice-core", "libreoffice-impress"], check=True)
print("Dependencies ready. Torch được giữ nguyên.")
''', "dependencies"))
    cells.append(cell("code", f'''import base64, hashlib, io, zipfile
PAYLOAD = {encoded!r}
payload = base64.b85decode(PAYLOAD)
if hashlib.sha256(payload).hexdigest() != {digest!r}:
    raise RuntimeError("Bundle integrity check failed")
ROOT.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(io.BytesIO(payload)) as archive:
    for member in archive.infolist():
        if not (ROOT/member.filename).resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError("Invalid bundle path")
    archive.extractall(ROOT)
bundle = json.loads((ROOT/"bundle.json").read_text())
for name, expected in bundle["files_sha256"].items():
    if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected:
        raise RuntimeError("Source integrity check failed: " + name)
print("Baseline:", bundle["baseline_revision"])
print("Optimized revision:", bundle["optimized_revision"], "(source hashes in report)")
''', "unpack"))
    cells.append(cell("markdown", "## Nạp model một lần và làm nóng cả hai đường xử lý\nThời gian ở bước này được ghi riêng, không cộng vào thời gian đọc đề. Không cần mở notebook chính cùng lúc.", "startup-note"))
    cells.append(cell("code", '''import requests
previous = globals().get("benchmark_process")
if previous is not None and previous.poll() is None:
    previous.terminate()
    previous.wait(timeout=30)
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    PORT = listener.getsockname()[1]
ENDPOINT = f"http://127.0.0.1:{PORT}/ocr"
environment = os.environ.copy()
environment.update(DOCX_BENCH_ROOT=str(ROOT), DOCX_OCR_MODEL_REVISION=MODEL_REVISION,
    DOCX_OCR_BACKEND="transformers", DOCX_OCR_DTYPE="auto", DOCX_OCR_ATTENTION="eager",
    DOCX_OCR_IMAGE_SIZE="1024", DOCX_OCR_WARMUP="1", DOCX_OCR_INFERENCE_BATCH_SIZE=str(OCR_GPU_BATCH_SIZE))
# Loopback-only benchmark server; it does not need a tunnel or API credentials.
environment.pop("DOCX_OCR_API_KEY", None)
os.environ.pop("DOCX_EXTRACT_OCR_API_KEY", None)
log_path = ROOT/"benchmark-server.log"
log_handle = log_path.open("w")
benchmark_process = subprocess.Popen([sys.executable, "-m", "uvicorn", "server_bridge:app", "--host", "127.0.0.1", "--port", str(PORT)],
    cwd=ROOT/"benchmark", env=environment, stdout=log_handle, stderr=subprocess.STDOUT)
started = time.perf_counter()
for attempt in range(900):
    if benchmark_process.poll() is not None:
        log_handle.flush()
        raise RuntimeError(log_path.read_text(errors="replace")[-7000:])
    try:
        response = requests.get(f"http://127.0.0.1:{PORT}/benchmark/health", timeout=3)
        health = response.json()
        if response.ok and health.get("model_loaded") and health.get("warmed_up"):
            break
    except (requests.RequestException, ValueError):
        pass
    if attempt%30 == 0:
        print(f"Đang nạp model/warm-up: {time.perf_counter()-started:.0f}s", flush=True)
    time.sleep(1)
else:
    benchmark_process.terminate()
    raise TimeoutError("Model chưa sẵn sàng sau 15 phút; xem benchmark-server.log.")
print("Load + warm-up:", round(time.perf_counter()-started, 2), "giây (ngoài benchmark)")
print(json.dumps(health, ensure_ascii=False, indent=2))
''', "startup"))
    cells.append(cell("markdown", "## Chọn đề và đo\nMỗi nút chạy lại thật từ đầu, không dùng cache kết quả. Chọn **Chạy cả hai và so sánh** để có bảng so sánh trên cùng bộ đề. Đo kỹ chạy mỗi bản 3 lượt, đổi thứ tự ở lượt giữa và lấy trung vị. Trong lúc đo, chờ hoàn tất rồi mới bấm tiếp.", "ui-note"))
    cells.append(cell("code", '''sys.path.insert(0, str(ROOT/"benchmark"))
sys.path.insert(0, str(ROOT/"optimized/kaggle_ocr"))
sys.path.insert(0, str(ROOT/"optimized/src"))
from ui import show_benchmark_ui
benchmark_ui = show_benchmark_ui(ROOT, ENDPOINT)
''', "interface"))
    cells.append(cell("markdown", "## Dừng GPU sau khi lấy báo cáo\nĐổi STOP_NOW thành True rồi chạy ô dưới để dừng model. Notebook chính không phụ thuộc notebook benchmark này.", "stop-note"))
    cells.append(cell("code", '''STOP_NOW = False
if STOP_NOW and benchmark_process.poll() is None:
    benchmark_process.terminate()
    benchmark_process.wait(timeout=30)
    log_handle.close()
    print("Đã dừng server benchmark. Có thể tắt session GPU.")
''', "stop"))
    notebook = {"nbformat": 4, "nbformat_minor": 5, "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"}}, "cells": cells}
    target = HERE / "docx_ocr_benchmark.ipynb"
    data = json.dumps(notebook, ensure_ascii=False, indent=1)
    if len(data.encode()) >= 1_000_000:
        raise RuntimeError("Notebook exceeds Kaggle source limit")
    target.write_text(data, encoding="utf-8")
    print(json.dumps({"notebook": str(target), "bytes": target.stat().st_size, "cells": len(cells)}))
    return target


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    build()
