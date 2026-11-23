"""CPU-only DOCX extraction and original-formula preview for Kaggle."""
import base64
from collections import Counter
from datetime import datetime
import hashlib
import html
import io
import json
import mimetypes
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from time import perf_counter
from uuid import uuid4

from lxml import etree
from PIL import Image

from docx_extract import clean_docx, write_outputs
from docx_extract.raster import prepare_image
from notebook_upload import gather_documents, upload_items
from ocr_logic import build_soffice_batch_cmd, crop_whitespace
from question_extract import extract_questions
from exam_print import print_page, select_markup


def question_markup(markup):
    extracted = extract_questions(markup)
    return extracted["markup"], len(extracted["questions"])


def convert_vectors(vectors):
    """Convert unique vectors for display only; never invoke an OCR model."""
    converted, errors = {}, {}
    if not vectors:
        return converted, errors
    if sys.platform == "win32":
        for key, (data, ext) in vectors.items():
            try:
                png, result_ext = prepare_image(data, ext)
                if result_ext != "png":
                    raise ValueError("Không chuyển được ảnh vector sang PNG")
                converted[key] = crop_whitespace(png)
            except Exception as exc:
                errors[key] = str(exc)
        return converted, errors
    if not shutil.which("soffice"):
        return {}, {key: "Chưa cài LibreOffice để xem ảnh WMF/EMF" for key in vectors}
    items = list(vectors.items())
    for offset in range(0, len(items), 32):
        with tempfile.TemporaryDirectory(prefix="docx-preview-") as tmp:
            sources = []
            for index, (key, (data, ext)) in enumerate(items[offset:offset + 32]):
                source = Path(tmp) / f"image_{index}.{ext}"
                source.write_bytes(data)
                sources.append((key, source))
            try:
                subprocess.run(build_soffice_batch_cmd([str(path) for _, path in sources], tmp,
                    str(Path(tmp) / "profile")), check=False, capture_output=True, timeout=90)
            except Exception as exc:
                errors.update({key: str(exc) for key, _ in sources})
                continue
            for key, source in sources:
                try:
                    converted[key] = crop_whitespace(source.with_suffix(".png").read_bytes())
                except Exception as exc:
                    errors[key] = str(exc)
    return converted, errors


def make_page(markup, context, title, root, converted, errors):
    pool, assets, warnings = {}, {}, list(context.warnings)
    files = {}
    for name, data in context.written.items():
        files.setdefault(Path(name).stem, []).append((Path(name).suffix.lower(), data))
    for entry in context.manifest:
        asset = dict(entry)
        for ext, data in files.get(entry["id"], []):
            if ext == ".xml" and entry["type"] == "mathml":
                parser = etree.XMLParser(resolve_entities=False, no_network=True)
                element = etree.fromstring(data, parser)
                etree.cleanup_namespaces(element)
                asset["omml"] = etree.tostring(element, encoding="unicode", with_tail=False)
            elif ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".wmf", ".emf"}:
                key = hashlib.sha256(data).hexdigest()
                if ext in {".wmf", ".emf"}:
                    if key not in converted:
                        warnings.append(f"{entry['id']}: chưa có bản xem ảnh; {errors.get(key, 'conversion failed')}")
                        asset["download"] = "data:application/octet-stream;base64," + base64.b64encode(data).decode("ascii")
                        continue
                    display_data, mime = converted[key], "image/png"
                else:
                    display_data = data
                    mime = mimetypes.guess_type("asset" + ext)[0] or "image/png"
                try:
                    with Image.open(io.BytesIO(display_data)) as image:
                        asset.update(width=image.width, height=image.height)
                except Exception:
                    warnings.append(f"{entry['id']}: không kiểm tra được ảnh hiển thị")
                pool[key] = "data:" + mime + ";base64," + base64.b64encode(display_data).decode("ascii")
                asset["image"] = key
        assets[entry["id"]] = asset
    payload = json.dumps({"documents": [{"id": "exam", "title": title, "path": "",
        "markup": markup, "assets": assets, "warnings": warnings}], "images": pool},
        ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = (Path(root) / "scripts/preview-template.html").read_text(encoding="utf-8")
    css = (Path(root) / "kaggle_ocr/questions-only.css").read_text(encoding="utf-8")
    page = template.replace("__PREVIEW_DATA__", payload).replace("</head>", "<style>" + css + "</style>\n</head>")
    page = page.replace("<body>", '<body class="answers-hidden">', 1)
    return page, warnings


def process_preserved(uploads, root, progress=print, *, exam_options=None):
    started = perf_counter()
    root = Path(root)
    options = dict(exam_options or {})
    job = root / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:6])
    inputs, results = job / "input", job / "results"
    inputs.mkdir(parents=True)
    results.mkdir()
    extracted, vectors, rows = [], {}, []
    for index, (name, data) in enumerate(gather_documents(uploads), 1):
        progress(f"Bóc {index}: {name}")
        source = inputs / f"{index:03d}.docx"
        source.write_bytes(data)
        row = {"file": name, "output": f"{index:03d}"}
        try:
            markup, context = clean_docx(str(source), preserve_formulas=True)
            for filename, raw in context.written.items():
                ext = Path(filename).suffix.lower().lstrip(".")
                if ext in {"wmf", "emf"}:
                    vectors.setdefault(hashlib.sha256(raw).hexdigest(), (raw, ext))
            selected = select_markup(markup, options.get('start_heading'))
            extracted.append((row, markup, context, selected))
        except Exception as exc:
            row.update(status="error", error=str(exc))
        rows.append(row)
    parse_s = perf_counter() - started
    progress(f"Chuẩn bị bản xem: {len(vectors)} ảnh vector khác nhau; không chạy OCR.")
    convert_started = perf_counter()
    converted, errors = convert_vectors(vectors)
    convert_s = perf_counter() - convert_started
    for row, markup, context, selected in extracted:
        output = results / row["output"]
        extracted_questions = extract_questions(selected)
        display_markup = extracted_questions["markup"]
        question_count = len(extracted_questions["questions"])
        lms_questions = question_count if extracted_questions['lms_detected'] else 0
        context.warnings.extend(extracted_questions["warnings"])
        write_outputs(markup, context, str(output))
        page, warnings = make_page(display_markup, context, row["file"], root, converted, errors)
        (output / "questions.html").write_text(page, encoding="utf-8")
        (output / "questions-answers.html").write_text(page.replace('class="answers-hidden"', 'class="show-correct-answers"', 1), encoding="utf-8")
        exam_page = print_page(page, options.get('title') or Path(row['file']).stem, question_count,
                               **{key: options.get(key, '') for key in ('school', 'subject', 'duration', 'code')})
        (output / 'de-thi.html').write_text(exam_page, encoding='utf-8')
        (output / 'de-thi-co-dap-an.html').write_text(
            exam_page.replace('class="answers-hidden"', 'class="show-correct-answers"', 1), encoding='utf-8')
        (output / "questions.txt").write_text(display_markup, encoding="utf-8")
        (output / "questions.json").write_text(json.dumps(extracted_questions["questions"], ensure_ascii=False, indent=2), encoding="utf-8")
        counts = Counter(entry["type"] for entry in context.manifest)
        answer_items = [child for question in extracted_questions["questions"]
                        for child in (question.get("items", []) if question["type"] == "group" else [question])]
        row.update(status="needs_review" if warnings else "ok", warnings=warnings,
            question_labels=len(re.findall(r"\b(?:Câu|Question)\s+\d+\s*[:.]", display_markup, re.IGNORECASE)),
            questions=question_count, lms_questions=lms_questions,
            subquestions=sum(len(question.get("items", [])) for question in extracted_questions["questions"]),
            source_answers=sum(item["correct_answer"] is not None for item in answer_items),
            answer_conflicts=sum(item["conflict"] for item in answer_items),
            word_equations=counts["mathml"], mathtype_images=counts["mathtype"], images=counts["img"],
            ocr=context.ocr_stats, preview=str(output / "questions.html"), print_preview=str(output / 'de-thi.html'))
    metrics = {"mode": "preserve_formulas", "documents": len(rows), "parse_s": parse_s,
        "convert_images_s": convert_s, "ocr_requests": 0, "latex_generated": 0,
        "preview_conversion_errors": len(errors)}
    (results / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (results / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    archive = Path(shutil.make_archive(str(root / ("questions-" + job.name)), "zip", results))
    metrics["total_s"] = perf_counter() - started
    # Write the final duration alongside ZIP so it includes creation of that ZIP.
    (job / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return archive, rows, metrics


def show_preserve_ui(root, sample=None, samples=None):
    import ipywidgets as widgets
    from IPython.display import HTML, display

    examples = list(samples) if samples is not None else [sample] if sample is not None else []
    uploader = widgets.FileUpload(accept=".docx,.zip", multiple=True, description="Chọn Word/ZIP")
    read = widgets.Button(description="Bóc câu hỏi", button_style="success", disabled=True)
    demo = widgets.Button(description="Chạy đề mẫu", disabled=not examples)
    sample_picker = widgets.Dropdown(options=[(item[0], index) for index, item in enumerate(examples)],
        description="Đề mẫu:", disabled=not examples, layout=widgets.Layout(width="75%"))
    show_answers = widgets.Checkbox(value=False, description="Hiện đáp án đúng trong file")
    view_mode = widgets.ToggleButtons(options=[('Đề thi A4', 'exam'), ('Xem câu hỏi', 'questions')], value='exam')
    fields = {
        'school': widgets.Text(description='Trường/đơn vị:', layout=widgets.Layout(width='95%')),
        'title': widgets.Text(description='Tên kỳ thi:', placeholder='Để trống để dùng tên file', layout=widgets.Layout(width='95%')),
        'subject': widgets.Text(description='Môn thi:'),
        'duration': widgets.Text(description='Thời gian:', placeholder='Ví dụ: 90 phút'),
        'code': widgets.Text(description='Mã đề:'),
        'start_heading': widgets.Text(description='Bắt đầu từ:', placeholder='Để trống để giữ toàn bộ nội dung', layout=widgets.Layout(width='95%')),
    }
    settings = widgets.Accordion(children=[widgets.VBox([
        widgets.HTML('Điền thông tin trước khi bấm Bóc câu hỏi/Chạy đề mẫu. Chỉ chọn mục bắt đầu khi cần bỏ phần ôn tập trước đề.'),
        *fields.values(),
    ])], selected_index=None)
    settings.set_title(0, 'Thông tin bản in')
    chooser = widgets.Dropdown(options=[], description="Xem đề:", layout=widgets.Layout(width="95%"))
    status, output, viewer = widgets.Output(), widgets.Output(), widgets.Output()
    state = {"rows": []}

    def show_selected(change=None):
        viewer.clear_output(wait=True)
        if chooser.value is None:
            return
        selected = next(row for row in state['rows'] if row.get('preview') == chooser.value)
        path = selected['print_preview'] if view_mode.value == 'exam' else selected['preview']
        page = Path(path).read_text(encoding="utf-8")
        if show_answers.value:
            page = page.replace('class="answers-hidden"', 'class="show-correct-answers"', 1)
        with viewer:
            # srcdoc is self-contained: MathML, images and scripts work without a public server.
            display(HTML('<iframe title="Các câu hỏi đã bóc" sandbox="allow-scripts allow-downloads allow-modals" '
                'style="display:block;width:100%;max-width:100%;min-width:0;height:1050px;border:1px solid #ddd;background:white" srcdoc="'
                + html.escape(page, quote=True) + '"></iframe>'))

    def run(uploads, sample_start_heading=''):
        uploader.disabled = read.disabled = demo.disabled = sample_picker.disabled = True
        for field in fields.values():
            field.disabled = True
        output.clear_output(wait=True)
        status.clear_output(wait=True)
        viewer.clear_output(wait=True)
        try:
            with status:
                options = {key: field.value.strip() for key, field in fields.items()}
                if sample_start_heading and not options['start_heading']:
                    options['start_heading'] = sample_start_heading
                    print('Đề mẫu: bắt đầu từ mục ' + sample_start_heading)
                archive, rows, metrics = process_preserved(uploads, root,
                    progress=lambda message: print(message, flush=True), exam_options=options)
                state["rows"] = rows
                print(f"Hoàn tất {len(rows)} file: {metrics['total_s']:.2f}s. OCR: 0 request; không chuyển LaTeX.")
                for row in rows:
                    if row["status"] == "error":
                        print(row["file"], ":", row["error"])
                    else:
                        print(f"{row['file']}: {row['word_equations']} Word Equation, {row['mathtype_images']} ảnh MathType, {row['images']} hình.")
                        if row["lms_questions"]:
                            print(f"Đã tách {row['lms_questions']} câu chính, {row['subquestions']} ý con từ bảng LMS; đọc {row['source_answers']} trường đáp án nguồn.")
                        elif row["questions"]:
                            print(f"Đã tách {row['questions']} câu; nhận dấu đáp án nguồn ở {row['source_answers']} câu.")
                        for warning in row["warnings"][:5]:
                            print("Lưu ý:", warning)
            options = [(row["file"], row["preview"]) for row in rows if "preview" in row]
            chooser.options = options
            if options:
                chooser.value = options[0][1]
                show_selected()
            with output:
                encoded = base64.b64encode(archive.read_bytes()).decode("ascii")
                display(HTML(f'<a download="{html.escape(archive.name)}" href="data:application/zip;base64,{encoded}">Tải kết quả ZIP</a>'))
                for row in rows:
                    if 'print_preview' in row:
                        encoded_page = base64.b64encode(Path(row['print_preview']).read_bytes()).decode('ascii')
                        filename = 'de-thi-' + Path(row['file']).stem + '.html'
                        display(HTML('<p><a download="' + html.escape(filename, quote=True)
                            + '" href="data:text/html;charset=utf-8;base64,' + encoded_page
                            + '">Tải bản đề thi A4: ' + html.escape(row['file']) + '</a></p>'))
                print('Mở bản đề thi A4 và bấm In / lưu PDF. ZIP có de-thi.html và bản riêng có đáp án.')
        except Exception as exc:
            with status:
                print("Chưa bóc được đề:", exc)
        finally:
            uploader.disabled = False
            read.disabled = not bool(uploader.value)
            demo.disabled = sample_picker.disabled = not examples
            for field in fields.values():
                field.disabled = False

    uploader.observe(lambda change: setattr(read, "disabled", not bool(change["new"])), names="value")
    read.on_click(lambda _: run(list(upload_items(uploader.value))))
    def run_sample(_=None):
        selected = examples[sample_picker.value]
        run([(selected[0], Path(selected[1]).read_bytes())], selected[2] if len(selected) > 2 else '')

    demo.on_click(run_sample)
    chooser.observe(show_selected, names="value")
    show_answers.observe(show_selected, names="value")
    view_mode.observe(show_selected, names='value')
    display(widgets.VBox([widgets.HBox([uploader, read]), widgets.HBox([sample_picker, demo]),
                         settings, view_mode, show_answers, status, output, chooser, viewer]))
    if examples:
        run_sample()
    return {"uploader": uploader, "read": read, "demo": demo, "sample_picker": sample_picker, "state": state,
            'view_mode': view_mode, 'show_answers': show_answers, 'exam_fields': fields}
