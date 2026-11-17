"""Upload and process new exams in an interactive Kaggle session."""
import base64
from datetime import datetime
import html
import io
import json
from pathlib import Path
import re
import shutil
from time import perf_counter
from uuid import uuid4
import zipfile

from docx_extract import clean_docx, write_outputs
from docx_extract.mathocr import OCRClient


MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def upload_items(value):
    """Accept the FileUpload value shapes used by ipywidgets 7 and 8."""
    entries = value.items() if isinstance(value, dict) else ((None, v) for v in value)
    for fallback, item in entries:
        name = item.get("name") or item.get("metadata", {}).get("name") or fallback
        if not name:
            raise ValueError("Không xác định được tên file.")
        yield str(name), bytes(item["content"])


def gather_documents(uploads):
    """Read DOCX files without extracting arbitrary archive paths to disk."""
    documents = []
    expanded_bytes = 0
    for filename, data in uploads:
        name = filename.replace("\\", "/").rsplit("/", 1)[-1]
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(f"{name}: file vượt quá 50 MB.")
        if name.lower().endswith(".docx"):
            candidates = [(name, data)]
        elif name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = [m for m in archive.infolist() if not m.is_dir()
                           and m.filename.lower().endswith(".docx")
                           and not m.filename.replace("\\", "/").rsplit("/", 1)[-1].startswith("~$")]
                if expanded_bytes + sum(m.file_size for m in members) > MAX_UPLOAD_BYTES:
                    raise ValueError("Tổng DOCX trong một lượt vượt quá 50 MB.")
                candidates = [(m.filename.replace("\\", "/").rsplit("/", 1)[-1], archive.read(m)) for m in members]
        else:
            raise ValueError(f"{name}: chọn file .docx hoặc .zip chứa DOCX.")
        for document_name, content in candidates:
            expanded_bytes += len(content)
            if expanded_bytes > MAX_UPLOAD_BYTES:
                raise ValueError("Tổng DOCX trong một lượt vượt quá 50 MB.")
            with zipfile.ZipFile(io.BytesIO(content)) as document:
                if not {"[Content_Types].xml", "word/document.xml"}.issubset(document.namelist()):
                    raise ValueError(f"{document_name}: không phải file Word DOCX hợp lệ.")
            documents.append((document_name, content))
    if not documents:
        raise ValueError("Chưa có file DOCX trong các file đã chọn.")
    return documents


def process_documents(documents, work_root, endpoint, progress=None):
    root = Path(work_root)
    job_name = "de-thi-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:6]
    job = root / "uploads" / job_name
    inputs = job / "input"
    results = job / "ket-qua"
    inputs.mkdir(parents=True)
    results.mkdir()
    rows = []
    for index, (name, content) in enumerate(documents, 1):
        stem = re.sub(r"[^\w.-]+", "-", Path(name).stem).strip(".")[:100] or "de"
        label = f"{index:02d}-{stem}"
        source = inputs / (label + ".docx")
        source.write_bytes(content)
        started = perf_counter()
        row = {"file": name, "output": label}
        try:
            with OCRClient(endpoint=endpoint, cache_path=root/"cache"/"ocr.sqlite3", progress=progress) as client:
                markup, context = clean_docx(source, ocr_client=client)
            write_outputs(markup, context, str(results/label))
            row.update(status="needs_review" if context.ocr_stats.get("failures") else "ok",
                       ocr=context.ocr_stats, warnings=context.warnings)
        except Exception as exc:
            row.update(status="error", error=str(exc))
        row["elapsed_s"] = perf_counter() - started
        rows.append(row)
    (results/"summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    # Only results are archived, not uploaded originals or the shared OCR cache.
    archive = Path(shutil.make_archive(str(root/job_name), "zip", results))
    return archive, rows


def show_upload_ui(work_root, endpoint):
    import ipywidgets as widgets
    from IPython.display import HTML, display

    uploader = widgets.FileUpload(accept=".docx,.zip", multiple=True, description="Chọn file đề")
    button = widgets.Button(description="Đọc đề", button_style="success", disabled=True)
    selected = widgets.HTML("Chọn DOCX hoặc ZIP chứa DOCX từ máy của bạn.")
    progress = widgets.IntProgress(value=0, min=0, max=1, description="OCR:")
    output = widgets.Output()

    def selection_changed(change):
        names = [name for name, _ in upload_items(change["new"])]
        selected.value = "Đã chọn: " + ", ".join(html.escape(n) for n in names) if names else "Chọn file đề."
        button.disabled = not names

    def update_progress(done, total, stats):
        progress.max = max(1, total)
        progress.value = done
        progress.description = f"{done}/{total}"

    def read_clicked(_):
        uploader.disabled = button.disabled = True
        output.clear_output(wait=True)
        progress.value = 0
        progress.bar_style = "info"
        try:
            with output:
                job_started = perf_counter()
                documents = gather_documents(upload_items(uploader.value))
                print(f"Đang đọc {len(documents)} đề…", flush=True)
                archive, rows = process_documents(documents, work_root, endpoint, update_progress)
                for row in rows:
                    stats = row.get("ocr", {})
                    detail = row.get("error") or f"{stats.get('total',0)} công thức, {stats.get('native_success',0)} đọc trực tiếp, {stats.get('cache_hits',0)} từ cache, {stats.get('failures',0)} lỗi"
                    print(f"{row['file']}: {row['elapsed_s']:.2f}s — {detail}", flush=True)
                total = sum(row.get("ocr", {}).get("total", 0) for row in rows)
                progress.max = max(1, total)
                progress.value = progress.max
                progress.description = f"{total}/{total}"
                progress.bar_style = "warning" if any(r["status"] != "ok" for r in rows) else "success"
                encoded = base64.b64encode(archive.read_bytes()).decode("ascii")
                print(f"Tổng thời gian xử lý (đọc Word + OCR + tạo ZIP): {perf_counter()-job_started:.2f} giây", flush=True)
                display(HTML(f'<p><a download="{archive.name}" href="data:application/zip;base64,{encoded}" '
                             'style="display:inline-block;padding:10px 18px;background:#18824b;color:white;border-radius:6px;text-decoration:none">'
                             'Tải kết quả ZIP</a></p><p>Mỗi đề có markup.txt, manifest.json và thư mục sidecar. Xem summary.json để kiểm tra lỗi.</p>'))
                print("File cũng có trong Output:", archive.name)
        except Exception as exc:
            progress.bar_style = "danger"
            with output:
                print("Chưa đọc được đề:", exc)
        finally:
            uploader.disabled = False
            button.disabled = not bool(uploader.value)

    uploader.observe(selection_changed, names="value")
    button.on_click(read_clicked)
    display(widgets.VBox([widgets.HTML("<h3>Đọc đề mới</h3>"), selected,
                          widgets.HBox([uploader, button]), progress, output]))
    return {"uploader": uploader, "button": button, "output": output}
