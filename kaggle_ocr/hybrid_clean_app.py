"""One-screen UI for the attachment's Pandoc + DeepSeek-OCR worker."""
from __future__ import annotations

import base64
from collections import deque
from datetime import datetime
import hashlib
import html
import importlib.util
import io
import json
import mimetypes
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from uuid import uuid4
import zipfile


APP_VERSION = "hybrid-clean-5-live-status"
PROGRESS_PREFIX = "@@HYBRID_PROGRESS@@"
HEARTBEAT_SECONDS = 5.0
# Explicit closure with --no-deps: never download/replace Kaggle's torch stack.
REQUIREMENTS = [
    "transformers==4.46.3", "tokenizers==0.20.3", "huggingface-hub==0.36.2",
    "Pillow>=10.1,<13", "numpy>=1.26,<3", "pymupdf>=1.24,<2",
    "einops>=0.8", "addict>=2.4", "easydict>=1.13", "accelerate>=0.26,<2",
    "safetensors>=0.4.3", "filelock>=3.16", "packaging>=23",
    "pyyaml>=6", "regex>=2024", "requests>=2.32,<3", "tqdm>=4.66",
    "fsspec>=2023.5", "typing-extensions>=4.9", "hf-xet>=1.1.3,<2",
    "psutil>=5.9", "urllib3>=1.26,<3", "certifi>=2024",
    "charset-normalizer>=3,<4", "idna>=3,<4", "pypandoc-binary>=1.14,<2",
]


class InputProblem(ValueError):
    """An actionable input/environment message, not an inference traceback."""


class SubprocessFailure(RuntimeError):
    def __init__(self, step, returncode, tail):
        self.step = step
        self.returncode = returncode
        self.tail = tail
        super().__init__(f"{step} thất bại (mã {returncode}).\n{tail}")


class JobFailure(RuntimeError):
    def __init__(self, message, log_path):
        self.log_path = Path(log_path)
        super().__init__(message)


def validate_docx(path):
    if path is None or not str(path).strip():
        raise InputProblem("Chưa chọn file DOCX.")
    path = Path(path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".docx":
        raise InputProblem("Không phải file DOCX: " + str(path))
    try:
        with zipfile.ZipFile(path) as archive:
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(archive.namelist()):
                raise InputProblem("File không có cấu trúc Word DOCX hợp lệ.")
    except zipfile.BadZipFile as error:
        raise InputProblem("File bị hỏng hoặc không phải DOCX.") from error
    return path


def save_upload(value, upload_root):
    """Handle widget 7/8 values without relying on notebook globals."""
    entries = list(value.values()) if isinstance(value, dict) else list(value or ())
    if not entries:
        return None
    if len(entries) != 1:
        raise InputProblem("Bản thử này nhận một DOCX mỗi lần.")
    item = entries[0]
    name = item.get("name") or item.get("metadata", {}).get("name", "")
    name = Path(name.replace("\\", "/")).name
    if not name or Path(name).suffix.lower() != ".docx":
        raise InputProblem("Hãy chọn file đề .docx, không phải notebook .ipynb.")
    content = bytes(item["content"])
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(archive.namelist()):
                raise InputProblem("File tải lên không có cấu trúc Word DOCX hợp lệ.")
    except zipfile.BadZipFile as error:
        raise InputProblem("File tải lên bị hỏng hoặc không phải DOCX.") from error
    upload_root = Path(upload_root)
    upload_root.mkdir(parents=True, exist_ok=True)
    destination = upload_root / (hashlib.sha256(content).hexdigest()[:16] + "-" + name)
    if not destination.is_file():
        destination.write_bytes(content)
    return validate_docx(destination)


def discover_docx(roots):
    found, visited = set(), set()
    for root in roots:
        for folder, directories, filenames in os.walk(root, followlinks=True):
            real_folder = Path(folder).resolve()
            if real_folder in visited:
                directories[:] = []
                continue
            visited.add(real_folder)
            for name in filenames:
                path = Path(folder) / name
                if path.suffix.lower() == ".docx" and path.is_file():
                    found.add(path.resolve())
    return sorted(found)


def gpu_status():
    try:
        import torch
        if not torch.cuda.is_available():
            return False, "GPU chưa sẵn sàng. Chọn GPU trong Settings → Accelerator rồi khởi động lại phiên nếu cần."
        free_bytes, _ = torch.cuda.mem_get_info(0)
        name = torch.cuda.get_device_name(0)
        if free_bytes < 7_000_000_000:
            return False, f"{name}: chỉ còn {free_bytes / 1e9:.1f} GB VRAM; code gửi yêu cầu ít nhất 7 GB."
        return True, f"{name} · {free_bytes / 1e9:.1f} GB VRAM trống"
    except Exception as error:
        return False, "Không kiểm tra được GPU: " + str(error)


def child_environment(dependencies):
    env = os.environ.copy()
    # A child interpreter sees private dependencies first; the notebook does not.
    env["PYTHONPATH"] = str(dependencies)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"
    env["TOKENIZERS_PARALLELISM"] = "false"
    return env


def stream_command(command, *, env, cwd, log, emit, step="Tiến trình"):
    tail = deque(maxlen=60)
    log.write("\n=== " + step + " ===\n")
    log.flush()
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen(
        command, cwd=cwd, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        bufsize=1, **kwargs,
    )
    started = last_output = last_heartbeat = time.monotonic()
    pending = queue.Queue()

    def read_output():
        # Only this reader blocks on stdout. The caller can report live state
        # even while apt/model loading produces no newline for several minutes.
        try:
            for line in process.stdout:
                pending.put(("line", line))
        except Exception as error:
            pending.put(("error", error))
        finally:
            pending.put(("eof", None))

    def publish(event, **values):
        line = PROGRESS_PREFIX + json.dumps(dict(event=event, pid=process.pid, **values), ensure_ascii=False)
        log.write(line + "\n")
        log.flush()
        emit(line)

    reader = threading.Thread(target=read_output, name="hybrid-stdout", daemon=True)
    reader.start()
    try:
        publish("phase", phase=step, elapsed_s=0, silence_s=0)
        interval = max(0.01, HEARTBEAT_SECONDS)
        while True:
            try:
                kind, value = pending.get(timeout=min(interval, 0.5))
            except queue.Empty:
                kind, value = "wait", None
            if kind == "eof":
                break
            if kind == "error":
                raise value
            if kind == "line":
                last_output = time.monotonic()
                tail.append(value)
                log.write(value)
                log.flush()
                emit(value.rstrip("\n"))
            now = time.monotonic()
            if now - last_heartbeat >= interval and process.poll() is None:
                publish("heartbeat", elapsed_s=round(now - started, 1), silence_s=round(now - last_output, 1))
                last_heartbeat = now
        code = process.wait()
        publish("exit", returncode=code, elapsed_s=round(time.monotonic() - started, 1))
    except BaseException:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    finally:
        reader.join(timeout=1)
        process.stdout.close()
    if code:
        raise SubprocessFailure(step, code, "".join(tail)[-12000:].strip())


def ensure_dependencies(root, log, emit):
    key = hashlib.sha256(json.dumps([list(sys.version_info[:2]), REQUIREMENTS]).encode()).hexdigest()[:12]
    parent = Path(root) / "dependencies"
    target = parent / key
    marker = target / "ready.json"
    if marker.is_file():
        emit("Dùng lại thư viện OCR đã cài riêng.")
        return target
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=key + "-", dir=parent))
    emit("Lần đầu: cài thư viện OCR riêng, không thay thư viện của notebook.")
    command = [
        sys.executable, "-m", "pip", "install", "--progress-bar", "off",
        "--disable-pip-version-check", "--no-warn-script-location",
        "--no-warn-conflicts", "--no-deps", "--target", str(stage), *REQUIREMENTS,
    ]
    stream_command(command, env=os.environ.copy(), cwd=root, log=log, emit=emit, step="Cài thư viện riêng")
    # Check real imports/declared runtime requirements inside the child, rather
    # than trusting the base environment's unrelated gradio/litellm metadata.
    check = r'''
import importlib.metadata as md
from packaging.requirements import Requirement
from packaging.version import Version
import transformers, tokenizers, torch, torchvision, PIL, numpy, pypandoc
from transformers import AutoModel, AutoTokenizer, StoppingCriteria, StoppingCriteriaList
assert transformers.__version__ == "4.46.3"
assert tokenizers.__version__ == "0.20.3"
for package in ("transformers", "tokenizers", "huggingface-hub", "accelerate", "requests", "Pillow", "pypandoc_binary"):
    for raw in md.requires(package) or []:
        requirement = Requirement(raw)
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        version = md.version(requirement.name)
        if requirement.specifier and Version(version) not in requirement.specifier:
            raise RuntimeError(f"{package}: {raw}, installed={version}")
print("Dependency check OK | torch=" + torch.__version__ + " | transformers=" + transformers.__version__)
'''
    stream_command([sys.executable, "-c", check], env=child_environment(stage), cwd=root, log=log, emit=emit,
                   step="Kiểm tra import và phiên bản thư viện")
    (stage / "ready.json").write_text(json.dumps({"requirements": REQUIREMENTS}), encoding="utf-8")
    if target.exists():
        # A previous interrupted install is preserved; do not merge its files.
        return stage
    stage.rename(target)
    return target


def run_job(source, root, worker_source, emit=print):
    """Validate first; only then install dependencies and start real inference."""
    source = validate_docx(source)
    ready, message = gpu_status()
    if not ready:
        raise InputProblem(message)
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    job = root / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8])
    job.mkdir(parents=True)
    started = time.perf_counter()
    copied = job / "input.docx"
    shutil.copyfile(source, copied)
    worker = job / "worker.py"
    worker.write_text(worker_source, encoding="utf-8")
    log_path = job / "run.log"
    try:
        with log_path.open("w", encoding="utf-8") as log:
            log.write("Source: " + str(source) + "\n")
            dependencies = ensure_dependencies(root, log, emit)
            setup_s = time.perf_counter() - started
            emit("Đang chạy đúng pipeline Pandoc + DeepSeek-OCR đã gửi…")
            stream_command(
                [sys.executable, "-u", str(worker), "--input", str(copied), "--output", str(job / "result"),
                 "--title", re.sub(r"^[0-9a-f]{16}-", "", source.stem)],
                env=child_environment(dependencies), cwd=job, log=log, emit=emit,
                step="Pandoc + DeepSeek-OCR",
            )
        results = job / "result"
        if not (results / "final.md").is_file():
            raise RuntimeError("Tiến trình kết thúc nhưng chưa tạo final.md: " + str(job))
        metrics = json.loads((results / "metrics.json").read_text(encoding="utf-8"))
        metrics["source_name"] = source.name
        metrics["setup_s"] = setup_s
        shutil.copyfile(log_path, results / "run.log")
        metrics["notebook_job_s_before_zip"] = time.perf_counter() - started
        (results / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        emit(PROGRESS_PREFIX + json.dumps(dict(event="phase", phase="Đóng gói kết quả ZIP", pid=None)))
        archive = Path(shutil.make_archive(str(job / "ket-qua"), "zip", results))
        return {"job": job, "results": results, "archive": archive, "metrics": metrics}
    except Exception as error:
        try:
            with log_path.open("a", encoding="utf-8") as log:
                traceback.print_exc(file=log)
        except OSError:
            pass
        raise JobFailure(str(error), log_path) from error


class HybridApp:
    def __init__(self, root, worker_source):
        import ipywidgets as widgets
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.worker_source = worker_source
        self.selected = None
        self.source_kind = None
        self.busy = False
        self.last_result = None
        self.outcome = None
        self.phase = "Chưa chạy"
        self._started_at = self._phase_started = self._last_output_at = time.monotonic()
        self._last_ui_update = 0.0
        self._active_pid = None
        self._last_log_line = ""
        self.upload = widgets.FileUpload(accept=".docx", multiple=False, description="Chọn DOCX")
        self.refresh_button = widgets.Button(description="Làm mới")
        self.dataset = widgets.Dropdown(description="File có sẵn:", layout=widgets.Layout(width="98%"))
        self.manual_path = widgets.Text(description="Đường dẫn:", layout=widgets.Layout(width="98%"))
        self.path_button = widgets.Button(description="Dùng đường dẫn")
        self.run_button = widgets.Button(description="Chạy OCR", button_style="success", icon="play", disabled=True,
                                         layout=widgets.Layout(width="300px"))
        self.status = widgets.HTML()
        self.gpu = widgets.HTML()
        self.logs = widgets.Output(layout=widgets.Layout(max_height="360px", overflow="auto"))
        self.results = widgets.Output()
        self.upload.observe(self.on_upload, names="value")
        self.dataset.observe(self.on_dataset, names="value")
        self.path_button.on_click(self.on_manual_path)
        self.refresh_button.on_click(self.refresh)
        self.run_button.on_click(self.on_run)
        alternative = widgets.Accordion(children=[widgets.VBox([
            self.dataset, widgets.HBox([self.manual_path, self.path_button]), self.refresh_button,
        ])], selected_index=None)
        alternative.set_title(0, "Hoặc chọn DOCX đã có trên Kaggle")
        self.view = widgets.VBox([
            widgets.HTML("<h3>DOCX → Pandoc + DeepSeek-OCR</h3><p>Chọn file đề, chờ hiện tên file, rồi bấm <b>Chạy OCR</b>.</p>"
                         "<small>Bản 5 · trạng thái trực tiếp mỗi 5 giây</small>"),
            self.gpu, self.upload, alternative, self.status, self.run_button,
            widgets.HTML("<b>Nhật ký chi tiết</b> (cuộn trong khung bên dưới)"), self.logs, self.results,
        ])
        self.restore_selection()
        self.refresh()

    def restore_selection(self):
        try:
            saved = json.loads((self.root / "selected.json").read_text(encoding="utf-8"))
            self.selected = validate_docx(saved["path"])
            self.source_kind = "saved"
        except (OSError, ValueError, KeyError, TypeError):
            self.selected = None

    def select(self, path, source_kind=None):
        selected = validate_docx(path)
        if selected != self.selected:
            self.outcome = None
        self.selected = selected
        if source_kind is not None:
            self.source_kind = source_kind
        (self.root / "selected.json").write_text(json.dumps({"path": str(selected)}), encoding="utf-8")
        self.status.value = "<b>Đã chọn:</b> " + html.escape(selected.name) + f" · {selected.stat().st_size:,} bytes"
        self.update_ready()

    def update_ready(self):
        ready, message = gpu_status()
        self.gpu.value = html.escape(message)
        self.run_button.disabled = self.busy or self.selected is None or not self.selected.is_file() or not ready
        if self.busy:
            self.run_button.description = "Đang chạy — xem trạng thái"
            self.run_button.icon = "hourglass-half"
            self.run_button.button_style = "warning"
        elif self.outcome in {"error", "stopped"}:
            self.run_button.description = "Thử lại OCR"
            self.run_button.icon = "repeat"
            self.run_button.button_style = "danger"
        else:
            self.run_button.description = "Chạy OCR lại" if self.outcome else "Chạy OCR"
            self.run_button.icon = "repeat" if self.outcome else "play"
            self.run_button.button_style = "success"

    def show_running(self, *, silence_s=None, force=False):
        if not self.busy:
            return
        now = time.monotonic()
        if not force and now - self._last_ui_update < 0.5:
            return
        self._last_ui_update = now
        silence = max(0, now - self._last_output_at) if silence_s is None else silence_s
        pid = f" · PID {self._active_pid}" if self._active_pid is not None else ""
        quiet = ("<br><b>Chưa có log mới. Tiến trình chưa kết thúc; chưa xác nhận tiến độ bên trong.</b>"
                 if silence >= 30 else "")
        self.status.value = (
            '<div style="border:2px solid #9a6700;padding:10px;background:#fff8dc;color:#111">'
            '<b>ĐANG CHẠY — ' + html.escape(self.phase) + '</b><br>'
            + f"Tổng {now - self._started_at:.0f}s · bước hiện tại {now - self._phase_started:.0f}s{pid}<br>"
            + f"Log mới nhất cách đây {silence:.0f}s. Trạng thái tiến trình cập nhật mỗi 5 giây."
            + quiet + '<br><small>' + html.escape(self._last_log_line[:220]) + '</small></div>'
        )

    def on_log(self, line):
        """Separate actual output from process-alive signals; do not invent % progress."""
        now = time.monotonic()
        if line.startswith(PROGRESS_PREFIX):
            try:
                event = json.loads(line[len(PROGRESS_PREFIX):])
            except (ValueError, TypeError):
                event = {}
            if not isinstance(event, dict):
                event = {}
            kind = event.get("event")
            if kind == "heartbeat":
                self._active_pid = event.get("pid")
                self.show_running(silence_s=event.get("silence_s", 0), force=True)
                self.logs.append_stdout(
                    f"[ĐANG CHẠY] PID {self._active_pid} · tiến trình {event.get('elapsed_s', 0):.0f}s"
                    f" · không có log mới {event.get('silence_s', 0):.0f}s\n"
                )
                return
            if kind == "phase":
                self.phase = event["phase"]
                self._active_pid = event.get("pid")
                self._phase_started = self._last_output_at = now
                self.show_running(force=True)
                self.logs.append_stdout("[BƯỚC] " + self.phase + "\n")
                return
            if kind == "exit":
                self._active_pid = None
                self.logs.append_stdout(f"[TIẾN TRÌNH KẾT THÚC] mã {event.get('returncode')}\n")
                return
        self.logs.append_stdout(line + "\n")
        self._last_output_at = now
        clean = line.strip()
        if clean:
            self._last_log_line = clean
        phase = None
        if "đang cài LibreOffice Draw" in clean:
            phase = "Cài LibreOffice Draw — chưa chạy OCR"
        elif clean.startswith("LibreOffice Draw:"):
            phase = clean
        elif clean.startswith("Bản in gốc:"):
            phase = clean
        elif "Đang tạo bản in" in clean:
            phase = "Tạo bản in / PDF"
        elif clean.startswith("Lần đầu: cài thư viện"):
            phase = "Cài thư viện OCR riêng — chưa chạy OCR"
        match = re.search(r"BUOC\s+([1-4])\s*:", clean)
        if match:
            phase = {"1": "Bóc DOCX / chuẩn bị ảnh", "2": "Tải / nạp model DeepSeek-OCR",
                     "3": "Nhận dạng ảnh OCR", "4": "Ghép kết quả OCR"}[match[1]]
        image = re.match(r"\[(\d+)/(\d+)\]", clean)
        if image and self.phase.startswith("Nhận dạng"):
            phase = f"Nhận dạng ảnh OCR {image[1]}/{image[2]}"
        if phase and phase != self.phase:
            self.phase = phase
            self._phase_started = now
        self.show_running(force=bool(phase))

    def input_error(self, error):
        self.selected = None
        self.source_kind = None
        self.status.value = html.escape(str(error))
        self.update_ready()

    def refresh(self, _=None):
        if self.source_kind in (None, "upload") and self.upload.value:
            try:
                uploaded = save_upload(self.upload.value, self.root / "uploads")
                if uploaded:
                    self.select(uploaded, "upload")
            except InputProblem as error:
                self.input_error(error)
        candidates = discover_docx([Path("/kaggle/input"), self.root / "uploads"])
        previous = self.dataset.value
        self.dataset.options = [("— Chọn DOCX —", "")] + [(str(p), str(p)) for p in candidates]
        if previous in {str(p) for p in candidates}:
            self.dataset.value = previous
        if self.selected is not None:
            try:
                self.select(self.selected)
            except InputProblem:
                self.selected = None
        if self.selected is None and len(candidates) == 1:
            try:
                self.select(candidates[0], "dataset")
            except InputProblem as error:
                self.status.value = html.escape(str(error))
        if self.selected is None:
            self.status.value = "Chưa chọn DOCX. Bấm <b>Chọn DOCX</b> ở trên. Nếu file nằm trong dataset, mở mục bên dưới và bấm Làm mới."
        self.update_ready()

    def on_upload(self, change):
        if self.busy:
            return
        try:
            selected = save_upload(change["new"], self.root / "uploads")
            if selected:
                self.select(selected, "upload")
        except InputProblem as error:
            self.input_error(error)

    def on_dataset(self, change):
        if self.busy or not change["new"]:
            return
        try:
            self.select(change["new"], "dataset")
        except InputProblem as error:
            self.input_error(error)

    def on_manual_path(self, _=None):
        try:
            self.select(self.manual_path.value.strip(), "manual")
        except InputProblem as error:
            self.input_error(error)

    def on_run(self, _=None):
        if self.busy:
            return
        self.logs.clear_output(wait=True)
        self.results.clear_output(wait=True)
        try:
            # Read the upload again to handle a delayed observer callback.
            if self.source_kind in (None, "upload"):
                uploaded = save_upload(self.upload.value, self.root / "uploads")
                if uploaded:
                    self.select(uploaded, "upload")
            source = validate_docx(self.selected)
            ready, message = gpu_status()
            if not ready:
                raise InputProblem(message)
        except InputProblem as error:
            self.status.value = html.escape(str(error))
            self.update_ready()
            return
        self.busy = True
        self.outcome = None
        self.phase = "Chuẩn bị thư viện / môi trường"
        self._started_at = self._phase_started = self._last_output_at = time.monotonic()
        self._active_pid = None
        self._last_log_line = source.name
        for control in (self.upload, self.dataset, self.manual_path, self.path_button, self.refresh_button, self.run_button):
            control.disabled = True
        self.update_ready()
        self.show_running(force=True)
        self.last_result = None
        try:
            # Do NOT wrap execution in `with self.logs`: live IPython Output
            # suppresses exceptions in __exit__, then execution continues with
            # no result. Append logs explicitly and let this try catch errors.
            result = run_job(
                source, self.root, self.worker_source,
                emit=self.on_log,
            )
            if not isinstance(result, dict) or not isinstance(result.get("metrics"), dict):
                raise RuntimeError("Tiến trình không trả về kết quả hợp lệ; chưa có kết quả để hiển thị.")
            self.last_result = result
            self.render_success(result)
            self.outcome = "success"
            unprocessed = result["metrics"].get("images_unprocessed", 0)
            if unprocessed:
                self.status.value = f"<b>Đã tạo kết quả, cần kiểm tra {unprocessed} ảnh/công thức chưa nhận được:</b> " + html.escape(source.name)
            elif result["metrics"].get("print_export_error"):
                self.status.value = "Đã tạo dữ liệu OCR nhưng bản in gặp lỗi: " + html.escape(result["metrics"]["print_export_error"])
            elif result["metrics"].get("print_unplaced_images"):
                self.status.value = "Đã tạo bản in, cần kiểm tra vị trí ảnh/công thức trong mục khôi phục."
            else:
                self.status.value = "<b>Hoàn tất:</b> " + html.escape(source.name)
            self.status.value += f"<br><b>ĐÃ XONG</b> · Tổng {time.monotonic() - self._started_at:.0f}s. Kết quả ở bên dưới."
        except (Exception, KeyboardInterrupt) as error:
            self.outcome = "stopped" if isinstance(error, KeyboardInterrupt) else "error"
            self.status.value = ("<b>ĐÃ DỪNG — lượt chạy bị ngắt.</b>" if self.outcome == "stopped" else
                                 "<b>LỖI — tiến trình đã dừng.</b> Lỗi gốc nằm trong log bên dưới.")
            self.logs.append_stderr(traceback.format_exc())
            self.logs.append_stderr("\n" + str(error) + "\n")
            # Keep an actionable root message in status as well as the log.
            self.status.value += "<pre style='white-space:pre-wrap'>" + html.escape(str(error)) + "</pre>"
            log_path = getattr(error, "log_path", None)
            if log_path is not None and Path(log_path).is_file():
                self.render_log_download(Path(log_path))
        finally:
            self.busy = False
            for control in (self.upload, self.dataset, self.manual_path, self.path_button, self.refresh_button):
                control.disabled = False
            self.update_ready()

    def render_log_download(self, log_path):
        from IPython.display import HTML
        try:
            encoded = base64.b64encode(log_path.read_bytes()).decode("ascii")
            self.results.append_display_data(HTML(
                '<p><a download="run.log" href="data:text/plain;charset=utf-8;base64,'
                + encoded + '">⬇ Tải log lỗi (run.log)</a></p>'
            ))
            self.logs.append_stdout("Log đầy đủ: " + str(log_path) + "\n")
        except OSError as error:
            self.logs.append_stderr("Không đọc được log: " + str(error) + "\n")

    def render_success(self, result):
        from IPython.display import FileLink, HTML, Markdown
        metrics = result["metrics"]
        if not metrics["gpu_inference_ran"]:
            self.results.append_stdout("Không chạy model OCR trong lượt này. Xem số ảnh nguồn và image-report.json để phân biệt không có ảnh với ảnh chưa chuyển được; đây KHÔNG phải benchmark model.\n")
        if "images_in_docx" in metrics:
            self.results.append_stdout(
                f"Ảnh nguồn: {metrics['images_in_docx']} · ảnh vector: {metrics.get('vector_images', 0)} · "
                f"Word Equation gốc: {metrics.get('native_word_equations', 0)} · "
                f"ảnh/công thức cần kiểm tra: {metrics.get('images_unprocessed', 0)}\n"
            )
        self.results.append_stdout(f"Ảnh OCR: {metrics['unique_ocr_images']} · thành công: {metrics['ocr_successes']}\n")
        self.results.append_stdout(f"Pandoc/tiền xử lý: {metrics['parse_preprocess_s']:.2f}s · nạp model: {metrics['model_load_s']:.2f}s · OCR: {metrics['ocr_s']:.2f}s\n")
        if "print_export_s" in metrics:
            self.results.append_stdout(f"Xuất bản in/PDF: {metrics['print_export_s']:.2f}s (lần đầu có thể gồm cài LibreOffice).\n")
        archive = result["archive"]
        encoded = base64.b64encode(archive.read_bytes()).decode("ascii")
        self.results.append_display_data(HTML('<p><a download="ket-qua-ocr.zip" href="data:application/zip;base64,' + encoded + '">⬇ Tải kết quả ZIP</a></p>'))
        self.results.append_display_data(FileLink(str(result["results"] / "final.md")))
        self.results.append_display_data(FileLink(str(result["results"] / "metrics.json")))
        report = result["results"] / "image-report.json"
        if report.is_file():
            self.results.append_display_data(FileLink(str(report)))
        exam_html = result["results"] / "de-thi.html"
        if exam_html.is_file():
            self.results.append_stdout("Bản in dưới đây dùng ảnh và nội dung gốc theo DOCX. OCR được tách riêng để đối chiếu.\n")
            for name, mime, label in (
                ("de-thi.html", "text/html", "Tải đề in HTML — mở để In / lưu PDF"),
                ("doi-chieu-ocr.html", "text/html", "Tải bản đối chiếu OCR"),
                ("de-thi-goc.pdf", "application/pdf", "Tải PDF giữ bố cục Word gốc (không phải OCR sinh)"),
            ):
                path = result["results"] / name
                if path.is_file():
                    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                    self.results.append_display_data(HTML('<p><a download="' + name + '" href="data:' + mime + ';base64,' + encoded + '">' + label + '</a></p>'))
            page = exam_html.read_text(encoding="utf-8")
            self.results.append_display_data(HTML(
                '<iframe title="Bản đề in" sandbox="allow-scripts allow-modals allow-downloads" '
                'style="width:100%;height:1000px;border:1px solid #ccc" srcdoc="' + html.escape(page, quote=True) + '"></iframe>'
            ))
            return  # Do not show the upscaled OCR rasters as the print preview.
        text = (result["results"] / "final.md").read_text(encoding="utf-8")
        def image_data(match):
            path = (result["results"] / match[2]).resolve()
            if not path.is_relative_to(result["results"].resolve()) or not path.is_file():
                return match[0]
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return "![" + match[1] + "](data:" + mime + ";base64," + base64.b64encode(path.read_bytes()).decode("ascii") + ")"
        self.results.append_display_data(Markdown(re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", image_data, text)))


def launch(root, worker_source):
    from IPython.display import display
    app = HybridApp(root, worker_source)
    display(app.view)
    return app
