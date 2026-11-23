"""Self-contained print HTML at DOCX image sizes, plus a native-layout PDF.

The print document uses source content/images. OCR annotations are a separately
labelled comparison layer, not a claim that recognition reproduced the source.
"""
import base64
from collections import Counter
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image


_PRINT_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def read_print_setup(source):
    setup = dict(width_mm=210.0, height_mm=297.0, top_mm=15.0, right_mm=15.0,
                 bottom_mm=15.0, left_mm=15.0, font="Times New Roman", font_pt=12.0,
                 columns=1, section_count=1)
    with zipfile.ZipFile(source) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        sections = list(root.iter("{" + _PRINT_W + "}sectPr"))
        setup["section_count"] = max(1, len(sections))
        if sections:
            section = sections[-1]
            page = section.find("{" + _PRINT_W + "}pgSz")
            margins = section.find("{" + _PRINT_W + "}pgMar")
            for element, names in ((page, {"w": "width_mm", "h": "height_mm"}),
                                   (margins, {"top": "top_mm", "right": "right_mm", "bottom": "bottom_mm", "left": "left_mm"})):
                if element is not None:
                    for attribute, key in names.items():
                        try:
                            setup[key] = float(element.get("{" + _PRINT_W + "}" + attribute)) * 25.4 / 1440
                        except (ValueError, TypeError):
                            pass
            columns = section.find("{" + _PRINT_W + "}cols")
            if columns is not None:
                try:
                    setup["columns"] = max(1, min(4, int(columns.get("{" + _PRINT_W + "}num", "1"))))
                except ValueError:
                    pass
        if "word/styles.xml" in archive.namelist():
            styles = ET.fromstring(archive.read("word/styles.xml"))
            properties = []
            for style in styles.findall("{" + _PRINT_W + "}style"):
                if style.get("{" + _PRINT_W + "}styleId", "").lower() == "normal":
                    props = style.find("{" + _PRINT_W + "}rPr")
                    if props is not None:
                        properties.append(props)
            default = styles.find("{" + _PRINT_W + "}docDefaults/{" + _PRINT_W + "}rPrDefault/{" + _PRINT_W + "}rPr")
            if default is not None:
                properties.insert(0, default)
            for props in properties:
                fonts = props.find("{" + _PRINT_W + "}rFonts")
                size = props.find("{" + _PRINT_W + "}sz")
                if fonts is not None:
                    setup["font"] = fonts.get("{" + _PRINT_W + "}ascii") or fonts.get("{" + _PRINT_W + "}hAnsi") or setup["font"]
                if size is not None:
                    try:
                        setup["font_pt"] = max(8, min(24, float(size.get("{" + _PRINT_W + "}val")) / 2))
                    except (ValueError, TypeError):
                        pass
        font_weights, size_weights, text_weight = Counter(), Counter(), 0
        for run in root.iter("{" + _PRINT_W + "}r"):
            weight = len("".join(node.text or "" for node in run.iter("{" + _PRINT_W + "}t")))
            if not weight:
                continue
            text_weight += weight
            props = run.find("{" + _PRINT_W + "}rPr")
            if props is None:
                continue
            fonts = props.find("{" + _PRINT_W + "}rFonts")
            size = props.find("{" + _PRINT_W + "}sz")
            if fonts is not None:
                family = fonts.get("{" + _PRINT_W + "}ascii") or fonts.get("{" + _PRINT_W + "}hAnsi")
                if family:
                    font_weights[family] += weight
            if size is not None:
                try:
                    size_weights[float(size.get("{" + _PRINT_W + "}val")) / 2] += weight
                except (TypeError, ValueError):
                    pass
        if font_weights and sum(font_weights.values()) >= text_weight / 2:
            setup["font"] = font_weights.most_common(1)[0][0]
        if size_weights and sum(size_weights.values()) >= text_weight / 2:
            setup["font_pt"] = max(8, min(24, size_weights.most_common(1)[0][0]))
    return setup


def _local_print_path(value, root):
    value = unquote(value.strip().strip("<>"))
    if urlsplit(value).scheme and not re.match(r"^[A-Za-z]:[/\\]", value):
        return None
    path = Path(value)
    return (path if path.is_absolute() else Path(root) / path).resolve()


def _image_source(record):
    path = record.get("display_path")
    if path and Path(path).is_file():
        return Path(path)
    path = record.get("source_path")
    if path and Path(path).is_file() and Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
        return Path(path)
    return None


def source_image_html(record, geometry=None):
    """Use Word's physical box, never the upscaled OCR PNG's pixel dimensions."""
    geometry = geometry or {}
    source = _image_source(record)
    if source is None:
        return '<span class="missing-image">[Ảnh/công thức cần kiểm tra: ' + html.escape(record["id"]) + ']</span>'
    with Image.open(source) as image:
        width_px, height_px = image.size
        dpi = image.info.get("dpi", (96, 96))
    if not isinstance(dpi, (tuple, list)) or len(dpi) < 2 or not all(isinstance(v, (int, float)) and v > 0 for v in dpi[:2]):
        dpi = (96, 96)
    width = geometry.get("width_mm") or width_px / dpi[0] * 25.4
    height = geometry.get("height_mm") or height_px / dpi[1] * 25.4
    if geometry.get("width_mm") and not geometry.get("height_mm"):
        height = width * height_px / max(1, width_px)
    if geometry.get("height_mm") and not geometry.get("width_mm"):
        width = height * width_px / max(1, height_px)
    width, height = max(0.1, width), max(0.1, height)
    crop = geometry.get("crop", {})
    left, right, top, bottom = [crop.get(key, 0) for key in ("l", "r", "t", "b")]
    inner_style = ""
    if any((left, right, top, bottom)):
        horizontal = max(0.01, 1 - left - right)
        vertical = max(0.01, 1 - top - bottom)
        inner_style = (f"left:{-left / horizontal * 100:.5f}%;top:{-top / vertical * 100:.5f}%;"
                       f"width:{100 / horizontal:.5f}%;height:{100 / vertical:.5f}%;object-fit:fill")
    data = base64.b64encode(source.read_bytes()).decode("ascii")
    mime = "image/png" if source.suffix.lower() == ".png" else "image/" + ("jpeg" if source.suffix.lower() in {".jpg", ".jpeg"} else source.suffix[1:].lower())
    shift = geometry.get("baseline_shift_pt", 0)
    alignment = f"{shift:g}pt" if shift else "middle"
    style = f"width:{width:.5f}mm;aspect-ratio:{width:.8f}/{height:.8f};vertical-align:{alignment}"
    return ('<span class="source-image" data-image-id="' + html.escape(record["id"], quote=True)
            + f'" data-width-mm="{width:.5f}" data-height-mm="{height:.5f}" style="{style}">'
            + '<img alt="Ảnh/công thức gốc" style="' + inner_style + '" src="data:' + mime + ';base64,' + data + '"></span>')


class _OCRFragments(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.fragments, self.current, self.depth, self.buffer = {}, None, 0, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.current is None and tag == "div" and attrs.get("id", "").startswith("ocr-"):
            self.current, self.depth, self.buffer = attrs["id"][4:], 1, []
            return
        if self.current is not None:
            if tag == "div":
                self.depth += 1
            self.buffer.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.current is not None:
            if tag == "div":
                self.depth -= 1
                if not self.depth:
                    self.fragments[self.current] = "".join(self.buffer)
                    self.current = None
                    return
            self.buffer.append("</" + tag + ">")

    def handle_startendtag(self, tag, attrs):
        if self.current is not None:
            self.buffer.append(self.get_starttag_text())

    def handle_data(self, data):
        if self.current is not None:
            self.buffer.append(html.escape(data, quote=False))

    def handle_entityref(self, name):
        if self.current is not None:
            self.buffer.append("&" + name + ";")

    def handle_charref(self, name):
        if self.current is not None:
            self.buffer.append("&#" + name + ";")


def _render_ocr_fragments(records, pandoc, output_dir):
    blocks = []
    for record in records:
        if record.get("ocr_text"):
            blocks.append("::: {#ocr-" + record["id"] + "}\n" + record["ocr_text"] + "\n:::")
    if not blocks:
        return {}
    process = subprocess.run(
        [pandoc, "-f", "markdown+fenced_divs+tex_math_dollars-raw_html", "-t", "html5", "--mathml", "--wrap=none"],
        input="\n\n".join(blocks), capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    if process.returncode:
        return {}
    parser = _OCRFragments()
    parser.feed(process.stdout)
    return parser.fragments


class _ExamBody(HTMLParser):
    def __init__(self, source_html, records, root, fragments):
        super().__init__(convert_charrefs=False)
        self.root, self.fragments, self.output, self.placed = Path(root), fragments, [], set()
        self.records, self.by_digest, self.markers = records, {}, {}
        for record in records:
            if record.get("source_sha256"):
                self.by_digest.setdefault(record["source_sha256"], []).append(record)
            for occurrence in record.get("occurrences", []):
                self.markers[occurrence["marker"]] = (record, occurrence)
        self.present_markers = {marker for marker in self.markers if marker in source_html}
        self.pattern = re.compile("(" + "|".join(re.escape(m) for m in sorted(self.markers, key=len, reverse=True)) + ")") if self.markers else None

    def image(self, record, geometry=None):
        self.placed.add(record["id"])
        return source_image_html(record, geometry)

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            ref = dict(attrs).get("src", "")
            path = _local_print_path(ref, self.root)
            if path is not None and path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                candidates = self.by_digest.get(digest, [])
                if candidates:
                    if any(marker in self.present_markers for record in candidates for marker in record.get("markers", [])):
                        return
                    record = candidates[0]
                    self.output.append(self.image(record, (record.get("occurrences") or [{}])[0]))
                    return
        self.output.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag not in {"img", "br", "hr", "meta", "link", "input", "wbr", "source"}:
            self.output.append("</" + tag + ">")

    def handle_data(self, data):
        if not self.pattern:
            self.output.append(html.escape(data, quote=False))
            return
        for part in self.pattern.split(data):
            if part in self.markers:
                record, geometry = self.markers[part]
                self.output.append(self.image(record, geometry))
            else:
                self.output.append(html.escape(part, quote=False))

    def handle_entityref(self, name):
        self.output.append("&" + name + ";")

    def handle_charref(self, name):
        self.output.append("&#" + name + ";")


def _page_html(title, body, setup, comparison=False, unplaced="", ocr_notes=""):
    font = re.sub(r"[^\w \-]", "", setup["font"])
    content_width = max(50, setup["width_mm"] - setup["left_mm"] - setup["right_mm"])
    css = f'''
@page{{size:{setup['width_mm']:.3f}mm {setup['height_mm']:.3f}mm;margin:{setup['top_mm']:.3f}mm {setup['right_mm']:.3f}mm {setup['bottom_mm']:.3f}mm {setup['left_mm']:.3f}mm}}
*{{box-sizing:border-box}}body{{margin:0;background:#e9ecef;color:#000;font:{setup['font_pt']:g}pt/1.35 "{font}","Times New Roman",serif}}
.toolbar{{position:sticky;top:0;z-index:5;padding:12px;background:#fff;border-bottom:1px solid #bbb;font:14px/1.5 Arial,sans-serif}}
.toolbar button{{padding:7px 14px;margin-right:15px;cursor:pointer}}.toolbar small{{display:block;color:#444}}
.paper{{width:{content_width:.3f}mm;max-width:100%;margin:20px auto;padding:0;background:white;box-shadow:0 1px 10px #bbb}}
.paper-inner{{padding:0;overflow-wrap:break-word}}p{{margin:0 0 5pt}}h1,h2,h3{{break-after:avoid;margin:9pt 0 5pt}}h1{{font-size:16pt}}h2{{font-size:14pt}}h3{{font-size:1em}}
table{{border-collapse:collapse;max-width:100%;margin:5pt 0}}td,th{{padding:3pt 5pt;vertical-align:top}}tr{{break-inside:avoid}}img{{max-width:100%}}
.source-image{{position:relative;display:inline-block;max-width:100%;overflow:hidden;break-inside:avoid;line-height:0}}
.source-image>img{{position:absolute;inset:0;width:100%;height:100%;max-width:none;object-fit:fill}}
math{{font-size:1em}}.ocr-notes{{display:none;background:#fff9dc;border-top:2px solid #cc9;padding:8pt;margin-top:15pt;line-height:1.3}}
.show-ocr .ocr-notes{{display:block}}.ocr-notes pre{{white-space:pre-wrap;font-size:.9em}}
.missing-image{{color:#a00;border:1px dashed #c77;padding:2pt;font-size:.9em}}.recovered{{border-top:1px dashed #aaa;margin-top:15pt}}
@media screen{{.paper{{padding:12mm;box-sizing:content-box}}}}
@media print{{body{{background:white}}.toolbar{{display:none!important}}.paper{{width:auto;max-width:none;margin:0;padding:0;box-shadow:none}}.ocr-notes{{display:none!important}}p{{orphans:3;widows:3}}a{{color:inherit;text-decoration:none}}}}
'''
    checked = " checked" if comparison else ""
    klass = ' class="show-ocr"' if comparison else ""
    return ('<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            + '<title>' + html.escape(title) + '</title><style>' + css + '</style></head><body' + klass + '>'
            + '<div class="toolbar"><button onclick="window.print()">In / lưu PDF</button>'
            + '<label><input type="checkbox"' + checked + ' onchange="document.body.classList.toggle(\'show-ocr\',this.checked)"> Hiện OCR để đối chiếu trên màn hình</label>'
            + '<small>Bản in dùng nội dung và ảnh gốc ở kích thước DOCX; phần OCR đối chiếu không được in kèm. Bố cục xuống dòng/ngắt trang HTML có thể khác Word. PDF giữ bố cục gốc được cung cấp riêng khi chuyển đổi thành công.</small></div>'
            + '<main class="paper"><article class="paper-inner">' + body + unplaced + ocr_notes + '</article></main></body></html>')


def original_layout_pdf(source, output_dir, allow_install=True):
    """Best-effort original-DOCX render, explicitly not an OCR-derived PDF."""
    source, output_dir = Path(source), Path(output_dir)
    executable = shutil.which("soffice")
    for attempt in range(2):
        if executable:
            try:
                with tempfile.TemporaryDirectory(prefix="print-profile-", dir=output_dir.parent) as profile:
                    process = subprocess.run(
                        [executable, "-env:UserInstallation=" + Path(profile).resolve().as_uri(), "--headless", "--norestore",
                         "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(output_dir), str(source)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
                    )
                produced = output_dir / (source.stem + ".pdf")
                if produced.is_file() and produced.stat().st_size > 100:
                    target = output_dir / "de-thi-goc.pdf"
                    if produced != target:
                        produced.rename(target)
                    return dict(ok=True, path=str(target), kind="original_docx_layout_not_ocr")
                detail = (process.stdout + "\n" + process.stderr).strip()
            except (OSError, subprocess.SubprocessError) as error:
                detail = str(error)
        else:
            detail = "Chưa có LibreOffice Writer."
        if attempt == 0 and allow_install and sys.platform.startswith("linux") and shutil.which("apt-get"):
            print("Bản in gốc: đang cài LibreOffice Writer lần đầu…", flush=True)
            try:
                install_env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", APT_LISTCHANGES_FRONTEND="none")
                apt = ["apt-get", "-o", "Dpkg::Use-Pty=0", "-o", "DPkg::Lock::Timeout=60",
                       "-o", "Acquire::Retries=1", "-o", "Acquire::http::Timeout=30", "-o", "Acquire::https::Timeout=30"]
                print("Bản in gốc: cập nhật danh sách gói (giới hạn 240s)…", flush=True)
                subprocess.run([*apt, "update"], check=True, timeout=240, env=install_env, stdin=subprocess.DEVNULL)
                print("Bản in gốc: tải / cài Writer (giới hạn 480s)…", flush=True)
                subprocess.run([*apt, "install", "-y", "--no-install-recommends", "libreoffice-writer"],
                               check=True, timeout=480, env=install_env, stdin=subprocess.DEVNULL)
                executable = shutil.which("soffice")
                continue
            except (OSError, subprocess.SubprocessError) as error:
                detail += " " + str(error)
        break
    return dict(ok=False, error=detail, kind="original_docx_layout_not_ocr")


def export_exam_pages(source, extraction, plan, output_dir, title="Đề thi", pandoc="pandoc", make_pdf=True):
    output_dir = Path(output_dir)
    setup = read_print_setup(source)
    process = subprocess.run(
        [pandoc, "-f", "docx", str(extraction["docx"]), "-t", "html5", "--mathml", "--wrap=none",
         "--extract-media=" + str(output_dir / "print-media")],
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    if process.returncode:
        raise RuntimeError("Không tạo được HTML bản in: " + process.stderr)
    fragments = _render_ocr_fragments(plan["records"], pandoc, output_dir)
    parser = _ExamBody(process.stdout, plan["records"], output_dir, fragments)
    parser.feed(process.stdout)
    recovered = [record for record in plan["records"] if record["id"] not in parser.placed]
    unplaced = ""
    if recovered:
        unplaced = '<section class="recovered"><h2>Ảnh/công thức khôi phục — cần kiểm tra vị trí</h2>'
        unplaced += "".join('<p>' + parser.image(record, (record.get("occurrences") or [{}])[0]) + '</p>' for record in recovered)
        unplaced += '</section>'
    body = "".join(parser.output)
    ocr_notes = '<section class="ocr-notes"><h2>Kết quả OCR để đối chiếu — không in kèm đề</h2>'
    for index, record in enumerate(plan["records"], 1):
        if record.get("ocr_text"):
            fragment = fragments.get(record["id"]) or '<pre>' + html.escape(record["ocr_text"]) + '</pre>'
            ocr_notes += '<div><h3>Ảnh/công thức ' + str(index) + '</h3>' + source_image_html(record, (record.get("occurrences") or [{}])[0]) + fragment + '</div>'
    ocr_notes += '</section>'
    for filename, comparison in (("de-thi.html", False), ("doi-chieu-ocr.html", True)):
        (output_dir / filename).write_text(_page_html(title, body, setup, comparison, unplaced, ocr_notes), encoding="utf-8")
    report = dict(html="de-thi.html", comparison_html="doi-chieu-ocr.html", page=setup,
                  print_content="source_docx_images_and_native_math", ocr_annotations="screen_only",
                  recovered_unplaced_images=len(recovered),
                  limitations=["HTML reflow có thể khác xuống dòng/ngắt trang của Word.",
                               "Ảnh thả nổi và nhiều section không được tái tạo vị trí tuyệt đối trong HTML.",
                               "PDF gốc có thể thay phông nếu máy chuyển đổi thiếu phông Word."])
    report["original_pdf"] = original_layout_pdf(source, output_dir) if make_pdf else dict(ok=False, error="Không yêu cầu chuyển PDF gốc trong lượt này.")
    (output_dir / "print-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
