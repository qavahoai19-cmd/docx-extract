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


def process_documents(documents, work_root, endpoint, progress=None, *, use_cache=True):
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
                   batch_size=32, progress=progress, use_cache=use_cache, debug_images=True) as client:
        extracted, batch_metrics = clean_docx_batch(sources, client)
    for row, document in zip(rows, extracted):
        started = perf_counter()
        try:
            if document.error:
                raise ValueError(document.error)
            context = document.context
            write_outputs(document.markup, context, str(results/row["output"]))
            unresolved = any(context.ocr_stats.get(key, 0) for key in ("failures", "missing_assets", "review_issues"))
            row.update(status="needs_review" if unresolved else "ok",
                       ocr=context.ocr_stats, warnings=context.warnings)
        except Exception as exc:
            row.update(status="error", error=str(exc))
        row["elapsed_s"] = (document.context.ocr_stats.get("document_s", 0) if document.context is not None else 0) + perf_counter() - started
    (results/"batch-metrics.json").write_text(json.dumps(batch_metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (results/"summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    # Only results are archived, not uploaded originals or the shared OCR cache.
    archive = Path(shutil.make_archive(str(root/job_name), "zip", results))
    return archive, rows


def show_upload_ui(work_root, endpoint, previous=None, *, input_root=None):
    import ipywidgets as widgets
    from IPython.display import HTML, display
    if __package__:
        from .notebook_preview import result_viewer
    else:
        from notebook_preview import result_viewer

    if (previous and previous.get("ui_version") == "inline-preview-v3"
            and previous.get("work_root") == str(Path(work_root)) and previous.get("endpoint") == endpoint):
        display(previous["view"])
        return previous

    uploader = widgets.FileUpload(accept=".docx,.zip", multiple=True, description="Chọn file đề")
    button = widgets.Button(description="Đọc đề", button_style="success", disabled=True)
    selected = widgets.HTML("Chọn DOCX hoặc ZIP chứa DOCX từ máy của bạn.")
    progress = widgets.IntProgress(value=0, min=0, max=1, description="OCR:")
    output = widgets.Output()
    preview_box = widgets.VBox()
    downloads = widgets.HTML()
    fresh_read = widgets.Checkbox(value=False, description="Đọc lại không dùng cache", indent=False,
                                 layout=widgets.Layout(width="auto"))
    state = {"archive": None, "rows": [], "preview": None}
    use_input = input_root is not None or str(work_root).startswith("/kaggle/")
    input_root = Path(input_root or "/kaggle/input")
    input_picker = widgets.SelectMultiple(options=[], rows=8, layout=widgets.Layout(width="100%"))
    refresh = widgets.Button(description="Cập nhật danh sách")
    choose_all = widgets.Button(description="Chọn tất cả")

    source_toggle = widgets.ToggleButtons(options=[("Kaggle Input", "input"), ("Upload", "upload")],
                                          value="input" if use_input else "upload")

    def input_changed(_):
        if not use_input:
            return
        selected.value = f"Đã chọn {len(input_picker.value)} file trong Input."
        button.disabled = not bool(input_picker.value)

    def refresh_inputs(_=None):
        kept = set(input_picker.value)
        paths = [input_root / name for name in list_input_files(input_root)]
        input_picker.options = [(str(p.relative_to(input_root)), str(p)) for p in paths]
        input_picker.value = tuple(str(p) for p in paths if str(p) in kept)
        input_changed(None)
        if not paths:
            selected.value = "Thêm DOCX/ZIP bằng Input → Upload bên phải Kaggle, rồi Cập nhật danh sách."

    def selection_changed(change):
        if use_input:
            return
        names = [name for name, _ in upload_items(change["new"])]
        selected.value = "Đã chọn: " + ", ".join(html.escape(n) for n in names) if names else "Chọn file đề."
        button.disabled = not names

    def update_progress(done, total, stats):
        progress.max = max(1, total)
        progress.value = done
        progress.description = f"{done}/{total}"

    def read_clicked(_):
        fresh_read.disabled = True
        source_toggle.disabled = uploader.disabled = button.disabled = True
        input_picker.disabled = refresh.disabled = choose_all.disabled = True
        output.clear_output(wait=False)
        preview_box.children = ()
        downloads.value = ""
        state.update(archive=None, rows=[], preview=None)
        progress.value = 0
        progress.bar_style = "info"
        try:
            with output:
                job_started = perf_counter()
                if use_input:
                    paths = [Path(p) for p in input_picker.value]
                    if sum(p.stat().st_size for p in paths) > MAX_UPLOAD_BYTES:
                        raise ValueError("Tổng file chọn vượt quá 50 MB.")
                    uploads = [(p.name, p.read_bytes()) for p in paths]
                else:
                    uploads = list(upload_items(uploader.value))
                documents = gather_documents(uploads)
                print(f"Đang đọc {len(documents)} đề…", flush=True)
                archive, rows = process_documents(documents, work_root, endpoint, update_progress,
                                                  use_cache=not fresh_read.value)
                state.update(archive=archive, rows=rows)
                with zipfile.ZipFile(archive) as result_zip:
                    batch_metrics = json.loads(result_zip.read("batch-metrics.json"))
                print(f"OCR cả lô: {batch_metrics.get('total',0)} ảnh, {batch_metrics.get('unique',0)} khác nhau, "
                      f"{batch_metrics.get('deduplicated',0)} ảnh trùng, {batch_metrics.get('cache_hits',0)} từ cache, "
                      f"{batch_metrics.get('http_requests',0)} request", flush=True)
                for row in rows:
                    stats = row.get("ocr", {})
                    detail = row.get("error") or (f"{stats.get('total',0)} công thức: {stats.get('omml_total',0)} Word Equation, "
                        f"{stats.get('mathtype_total',0)} MathType; {stats.get('wmf_direct',0)} số WMF đọc trực tiếp; {stats.get('failures',0)} công thức cần kiểm tra, "
                        f"{stats.get('missing_assets',0)} tài nguyên thiếu")
                    print(f"{row['file']}: {detail}", flush=True)
                total = sum(row.get("ocr", {}).get("total", 0) for row in rows)
                progress.max = max(1, total)
                progress.value = progress.max
                progress.description = f"{total}/{total}"
                progress.bar_style = "warning" if any(r["status"] != "ok" for r in rows) else "success"
                encoded = base64.b64encode(archive.read_bytes()).decode("ascii")
                print(f"Tổng thời gian xử lý (đọc Word + OCR + tạo ZIP): {perf_counter()-job_started:.2f} giây", flush=True)
                downloads.value = (f'<details><summary>Lưu kết quả ZIP (tùy chọn)</summary><p><a download="{archive.name}" href="data:application/zip;base64,{encoded}" '
                             'style="display:inline-block;padding:10px 18px;background:#18824b;color:white;border-radius:6px;text-decoration:none">'
                             'Tải kết quả ZIP</a></p></details>')
                print("File cũng có trong Output:", archive.name)
                selected.value = f"Đã xử lý {len(rows)} đề. Kết quả hiển thị bên dưới; không cần tải ZIP."
                state["preview"] = result_viewer(archive, rows, work_root)
                preview_box.children = (state["preview"]["view"],)
        except Exception as exc:
            progress.bar_style = "danger"
            with output:
                print("Chưa đọc được đề:", exc)
            selected.value = "Chưa đọc được đề: " + html.escape(str(exc))
        finally:
            fresh_read.disabled = False
            source_toggle.disabled = uploader.disabled = False
            input_picker.disabled = refresh.disabled = choose_all.disabled = False
            button.disabled = not bool(input_picker.value if use_input else uploader.value)

    uploader.observe(selection_changed, names="value")
    button.on_click(read_clicked)
    input_picker.observe(input_changed, names="value")
    refresh.on_click(refresh_inputs)
    choose_all.on_click(lambda _: setattr(input_picker, "value", tuple(value for _, value in input_picker.options)))
    input_controls = widgets.VBox([widgets.HBox([refresh, choose_all]), input_picker])

    def change_source(_=None):
        nonlocal use_input
        use_input = source_toggle.value == "input"
        input_controls.layout.display = "" if use_input else "none"
        uploader.layout.display = "none" if use_input else ""
        if use_input:
            refresh_inputs()
        else:
            selection_changed({"new": uploader.value})

    source_toggle.observe(change_source, names="value")
    change_source()
    source = [source_toggle, input_controls, uploader]
    view = widgets.VBox([widgets.HTML("<h3>Đọc đề mới</h3>"), *source,
                        fresh_read, widgets.HBox([button]), selected, progress, preview_box, downloads, output])
    display(view)
    return {"uploader": uploader, "button": button, "output": output, "view": view,
            "preview_box": preview_box, "downloads": downloads, "state": state,
            "input_picker": input_picker, "refresh": refresh, "choose_all": choose_all,
            "work_root": str(Path(work_root)), "endpoint": endpoint,
            "source_toggle": source_toggle, "fresh_read": fresh_read, "ui_version": "inline-preview-v3"}
