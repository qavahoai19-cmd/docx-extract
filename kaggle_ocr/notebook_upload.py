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

from docx_extract import write_outputs
from docx_extract.batch import clean_docx_batch
from docx_extract.mathocr import OCRClient


MAX_UPLOAD_BYTES = 50 * 1024 * 1024
KAGGLE_INPUT = Path("/kaggle/input")


def list_input_files(input_root=KAGGLE_INPUT):
    """List selectable exams without reading their contents or running OCR."""
    root = Path(input_root)
    if not root.is_dir():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".docx", ".zip"}
        and not path.name.startswith("~$")
        and path.resolve().is_relative_to(root.resolve())
    )


def input_documents(selection, input_root=KAGGLE_INPUT):
    """Read only the explicitly selected Kaggle Input file."""
    root = Path(input_root).resolve()
    path = (root / selection).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in {".docx", ".zip"}:
        raise ValueError("Đề đã chọn không còn hợp lệ trong Kaggle Input.")
    return gather_documents([(path.name, path.read_bytes())])


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
    rows, sources = [], []
    for index, (name, content) in enumerate(documents, 1):
        stem = re.sub(r"[^\w.-]+", "-", Path(name).stem).strip(".")[:100] or "de"
        label = f"{index:02d}-{stem}"
        source = inputs / (label + ".docx")
        source.write_bytes(content)
        rows.append({"file": name, "output": label})
        sources.append(source)
    with OCRClient(endpoint=endpoint, cache_path=root/"cache"/"ocr.sqlite3",
                   batch_size=32, progress=progress) as client:
        extracted, batch_metrics = clean_docx_batch(sources, client)
    for row, document in zip(rows, extracted):
        started = perf_counter()
        try:
            if document.error:
                raise ValueError(document.error)
            context = document.context
            write_outputs(document.markup, context, str(results/row["output"]))
            row.update(status="needs_review" if context.ocr_stats.get("failures") else "ok",
                       ocr=context.ocr_stats, warnings=context.warnings)
        except Exception as exc:
            row.update(status="error", error=str(exc))
        row["elapsed_s"] = (document.context.ocr_stats.get("document_s", 0) if document.context is not None else 0) + perf_counter() - started
    (results/"batch-metrics.json").write_text(json.dumps(batch_metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (results/"summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    # Only results are archived, not uploaded originals or the shared OCR cache.
    archive = Path(shutil.make_archive(str(root/job_name), "zip", results))
    return archive, rows


def show_upload_ui(work_root, endpoint):
    import ipywidgets as widgets
    from IPython.display import HTML, display

    source = widgets.ToggleButtons(options=[("Kaggle Input", "input"), ("Tải từ máy", "upload")],
                                   value="input", description="Nguồn đề:")
    input_select = widgets.Dropdown(options=[("— Chọn đề trong Input —", "")],
                                    description="Đề:", layout=widgets.Layout(width="90%"))
    refresh = widgets.Button(description="Làm mới Input", icon="refresh")
    uploader = widgets.FileUpload(accept=".docx,.zip", multiple=True, description="Chọn file đề", disabled=True)
    button = widgets.Button(description="Đọc đề", button_style="success", disabled=True)
    selected = widgets.HTML()
    progress = widgets.IntProgress(value=0, min=0, max=1, description="OCR:")
    output = widgets.Output()

    def update_selection(_=None):
        from_input = source.value == "input"
        input_select.disabled = refresh.disabled = not from_input
        uploader.disabled = from_input
        names = [name for name, _ in upload_items(uploader.value)] if not from_input else []
        if from_input:
            choice = input_select.value
            selected.value = ("Đã chọn: " + html.escape(choice)) if choice else "Chọn một đề trong Kaggle Input, rồi bấm Đọc đề."
            button.disabled = not bool(choice)
        else:
            selected.value = ("Đã chọn: " + ", ".join(html.escape(n) for n in names)) if names else "Chọn DOCX hoặc ZIP từ máy."
            button.disabled = not bool(names)

    def refresh_input(_=None):
        current = input_select.value
        files = list_input_files()
        input_select.options = [("— Chọn đề trong Input —", "")] + [(name, name) for name in files]
        input_select.value = current if current in files else ""
        update_selection()

    def update_progress(done, total, stats):
        progress.max = max(1, total)
        progress.value = done
        progress.description = f"{done}/{total}"

    def read_clicked(_):
        source.disabled = input_select.disabled = refresh.disabled = uploader.disabled = button.disabled = True
        output.clear_output(wait=True)
        progress.value = 0
        progress.bar_style = "info"
        try:
            with output:
                job_started = perf_counter()
                documents = (input_documents(input_select.value) if source.value == "input"
                             else gather_documents(upload_items(uploader.value)))
                print(f"Đang đọc {len(documents)} đề…", flush=True)
                archive, rows = process_documents(documents, work_root, endpoint, update_progress)
                with zipfile.ZipFile(archive) as result_zip:
                    batch_metrics = json.loads(result_zip.read("batch-metrics.json"))
                print(f"OCR cả lô: {batch_metrics.get('total',0)} ảnh, {batch_metrics.get('unique',0)} khác nhau, "
                      f"{batch_metrics.get('deduplicated',0)} ảnh trùng, {batch_metrics.get('cache_hits',0)} từ cache, "
                      f"{batch_metrics.get('http_requests',0)} request", flush=True)
                for row in rows:
                    stats = row.get("ocr", {})
                    detail = row.get("error") or f"{stats.get('total',0)} công thức, {stats.get('failures',0)} lỗi OCR"
                    print(f"{row['file']}: {detail}", flush=True)
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
            source.disabled = False
            update_selection()

    source.observe(update_selection, names="value")
    input_select.observe(update_selection, names="value")
    uploader.observe(update_selection, names="value")
    refresh.on_click(refresh_input)
    button.on_click(read_clicked)
    refresh_input()
    display(widgets.VBox([widgets.HTML("<h3>Đọc đề mới</h3>"), source,
                          widgets.HBox([input_select, refresh]), uploader, selected,
                          button, progress, output]))
    return {"uploader": uploader, "input_select": input_select, "button": button, "output": output}
