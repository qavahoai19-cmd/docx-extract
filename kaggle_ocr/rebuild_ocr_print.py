# COPY TOÀN BỘ VÀO MỘT CELL MỚI Ở CUỐI NOTEBOOK ĐÃ OCR XONG.
# Chỉ dựng lại HTML từ dữ liệu đã lưu. Không gọi model, không cần GPU.
import base64
from copy import deepcopy
from datetime import datetime
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.parse import unquote, urlsplit
from uuid import uuid4
import xml.etree.ElementTree as ET
import zipfile
from IPython.display import HTML, IFrame, display

IMAGE_RE = re.compile(r'!\[[^\]\n]*\]\((<[^>]+>|[^)\n]+)\)(\{[^}]*\})?')

def image_path(ref, work_dir):
    value = unquote(ref.strip().strip("<>").replace(r"\ ", " "))
    if urlsplit(value).scheme and not re.match(r"^[A-Za-z]:[/\\]", value):
        return None
    path = Path(value)
    resolved = (path if path.is_absolute() else Path(work_dir) / path).resolve()
    return resolved if resolved.is_relative_to(Path(work_dir).resolve()) else None

def clean_pandoc_output(text):
    # Không chạy các regex tự đoán ngoặc, xóa dấu nhân, bỏ cột ma trận của bản dán.
    return text.strip()

def is_plot_label_list(text):
    """Chỉ nhận danh sách nhãn rời x/y/O + số, không nhận biểu thức/toán LaTeX."""
    value = (text or "").strip().replace("−", "-").replace("–", "-")
    tokens = value.split()
    if len(tokens) < 6:
        return False
    lowered = {token.lower() for token in tokens}
    if not {"x", "y"}.issubset(lowered):
        return False
    numeric = re.compile(r"[+-]?(?:\d+(?:[.,]\d+)?|[.]\d+)")
    return (sum(bool(numeric.fullmatch(token)) for token in tokens) >= 3
            and all(token.lower() in {"x", "y", "o"} or numeric.fullmatch(token) for token in tokens))

def remove_axis_label_blocks(page):
    """Dọn bản HTML đã có: chỉ bỏ block [OCR] chứa danh sách nhãn trục rời.

    Không gọi model, không bỏ hình, không sửa công thức hoặc blockquote khác.
    """
    class BlockFilter(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.output, self.buffer, self.words = [], [], []
            self.depth = self.removed = 0
        def append(self, value):
            (self.buffer if self.depth else self.output).append(value)
        def handle_starttag(self, tag, attrs):
            if tag == "blockquote":
                if not self.depth:
                    self.buffer, self.words = [], []
                self.depth += 1
            self.append(self.get_starttag_text())
        def handle_startendtag(self, tag, attrs):
            self.append(self.get_starttag_text())
        def handle_endtag(self, tag):
            self.append("</" + tag + ">")
            if self.depth and tag == "blockquote":
                self.depth -= 1
                if not self.depth:
                    text = " ".join(self.words).strip()
                    header = re.match(r"^\[OCR\b[^\]]*\]\s*", text, re.IGNORECASE)
                    if header and is_plot_label_list(text[header.end():]):
                        self.removed += 1
                    else:
                        self.output.extend(self.buffer)
                    self.buffer, self.words = [], []
        def handle_data(self, data):
            self.append(data)
            if self.depth:
                self.words.append(data)
        def handle_entityref(self, name):
            self.append("&" + name + ";")
            if self.depth:
                self.words.append(html.unescape("&" + name + ";"))
        def handle_charref(self, name):
            self.append("&#" + name + ";")
            if self.depth:
                self.words.append(html.unescape("&#" + name + ";"))
        def handle_comment(self, data):
            self.append("<!--" + data + "-->")
        def handle_decl(self, decl):
            self.append("<!" + decl + ">")
        def handle_pi(self, data):
            self.append("<?" + data + ">")
    parser = BlockFilter()
    parser.feed(page)
    parser.close()
    if parser.buffer:
        parser.output.extend(parser.buffer)
    return "".join(parser.output), parser.removed

def build_final(markdown, by_ref):
    def replace(match):
        record = by_ref.get(match[1], {})
        text = record.get("ocr_text", "")
        if not text or record.get("render_policy") == "reference_only" or is_plot_label_list(text):
            return match[0]  # Luôn giữ hình gốc, không thay bằng OCR thất bại.
        block = "\n".join("> " + line if line else ">" for line in text.splitlines())
        # A blank line is required before a pipe table. Another blank line
        # after the block keeps following source text outside the blockquote.
        return match[0] + "\n\n> **[OCR — cần đối chiếu]**\n>\n" + block + "\n\n"
    return IMAGE_RE.sub(replace, clean_pandoc_output(markdown))

def ast_text(value, skip_math=False):
    if isinstance(value, dict):
        kind = value.get("t")
        if kind == "Str":
            return value.get("c", "")
        if kind in {"Space", "SoftBreak", "LineBreak"}:
            return " "
        if kind == "Math":
            return "" if skip_math else value["c"][1]
        return ast_text(value.get("c", []), skip_math)
    if isinstance(value, list):
        return "".join(ast_text(item, skip_math) for item in value)
    return ""

def has_ast_type(value, kind):
    if isinstance(value, dict):
        return value.get("t") == kind or has_ast_type(value.get("c", []), kind)
    return isinstance(value, list) and any(has_ast_type(item, kind) for item in value)

def prepare_print_ast(document):
    """Reconstruct only parsed tables/math; preserve original images for review.

    No values, symbols or equations are inferred or repaired here.
    """
    counts = dict(structured_tables=0, inline_math=0, notes_only=0)
    def wrap(kind, classes, content):
        return {"t": kind, "c": [["", classes, []], content]}
    def ocr_parts(block):
        if not isinstance(block, dict) or block.get("t") != "BlockQuote":
            return None
        blocks = block.get("c", [])
        if not blocks or blocks[0].get("t") not in {"Para", "Plain"}:
            return None
        inlines = blocks[0]["c"]
        if not inlines or inlines[0].get("t") != "Strong":
            return None
        if not re.fullmatch(r"\[OCR\b[^\]]*\]", ast_text(inlines[0]).strip(), re.IGNORECASE):
            return None
        remainder = inlines[1:]
        while remainder and remainder[0].get("t") in {"Space", "SoftBreak"}:
            remainder = remainder[1:]
        return ([{"t": "Para", "c": remainder}] if remainder else []) + blocks[1:]
    def process(items):
        output = []
        for block in items:
            parts = ocr_parts(block)
            previous = output[-1] if output else None
            if parts is None or not isinstance(previous, dict) or previous.get("t") not in {"Para", "Plain"}:
                output.append(block)
                continue
            images = [index for index, inline in enumerate(previous["c"]) if inline.get("t") == "Image"]
            if not images:
                output.append(block)
                continue
            is_table = has_ast_type(parts, "Table")
            is_math = (len(parts) == 1 and parts[0].get("t") in {"Para", "Plain"}
                       and has_ast_type(parts, "Math")
                       and not re.sub(r"[\s.,;:()[\]{}…-]", "", ast_text(parts, skip_math=True)))
            if not is_table and not is_math:
                output.append(wrap("Div", ["ocr-notes"], parts))
                counts["notes_only"] += 1
                continue
            index = images[-1]
            before, image, after = previous["c"][:index], previous["c"][index], previous["c"][index+1:]
            output.pop()
            if is_table:
                rendered = [wrap("Div", ["ocr-caption"], [part])
                            if part.get("t") in {"Para", "Plain"}
                            and re.fullmatch(r"(?:Bảng|Table)\s+\d+[.:]?", ast_text(part).strip(), re.IGNORECASE)
                            else part for part in parts]
                if ast_text(before).strip() or has_ast_type(before, "Math") or has_ast_type(before, "Image"):
                    output.append({"t": previous["t"], "c": before})
                output.append(wrap("Div", ["ocr-pair", "ocr-table"], [
                    wrap("Div", ["ocr-source"], [{"t": "Para", "c": [image]}]),
                    wrap("Div", ["ocr-rendered"], rendered),
                ]))
                if ast_text(after).strip() or has_ast_type(after, "Math") or has_ast_type(after, "Image"):
                    output.append({"t": previous["t"], "c": after})
                counts["structured_tables"] += 1
            else:
                pair = wrap("Span", ["ocr-pair", "ocr-math"], [
                    wrap("Span", ["ocr-source"], [image]),
                    wrap("Span", ["ocr-rendered"], parts[0]["c"]),
                ])
                output.append({"t": previous["t"], "c": [*before, pair, *after]})
                counts["inline_math"] += 1
        return output
    def walk(value):
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return process([walk(item) for item in value])
        return value
    return walk(deepcopy(document)), counts

def page_css(source):
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    values = dict(w=210, h=297, top=15, right=15, bottom=15, left=15)
    with zipfile.ZipFile(source) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        sections = list(document.iter(namespace + "sectPr"))
        if sections:
            for name, keys in (("pgSz", ("w", "h")), ("pgMar", ("top", "right", "bottom", "left"))):
                node = sections[-1].find(namespace + name)
                if node is not None:
                    for key in keys:
                        try:
                            values[key] = float(node.get(namespace + key)) * 25.4 / 1440
                        except (ValueError, TypeError):
                            pass
    width = max(50, values["w"] - values["left"] - values["right"])
    return (f"@page{{size:{values['w']}mm {values['h']}mm;margin:{values['top']}mm {values['right']}mm {values['bottom']}mm {values['left']}mm}}"
            f"body{{font:12pt/1.3 'Times New Roman',serif;max-width:{width}mm;margin:20px auto;background:white}}"
            "*{box-sizing:border-box}img{max-width:100%}p{margin:0 0 6pt;orphans:3;widows:3}"
            "table{border-collapse:collapse;max-width:100%;margin:6pt auto;break-inside:auto}"
            "td,th{border:0.6pt solid #222;padding:5pt 7pt;vertical-align:middle;overflow-wrap:anywhere}"
            "th{text-align:center;font-weight:bold}thead{display:table-header-group}tr{break-inside:avoid}"
            "math{font-size:1em}blockquote{margin:6pt 0;padding:0 6pt}"
            ".ocr-source,.ocr-notes{display:none}"
            ".show-source .ocr-source,.show-source .ocr-notes{display:block}"
            ".show-source .ocr-math .ocr-source{display:inline-block;vertical-align:middle;margin-right:6pt}"
            ".show-source .ocr-source,.ocr-notes{border:1px dashed #aaa;padding:5pt;margin:6pt 0;background:#fff9da}"
            ".ocr-pair{max-width:100%}.ocr-rendered{max-width:100%}.ocr-rendered>p:last-child{margin-bottom:0}"
            ".ocr-caption{text-align:center;font-style:italic;margin:3pt 0 8pt}"
            ".toolbar{font:14px Arial;border-bottom:1px solid #bbb;padding:10px;margin-bottom:12px}"
            "@media print{body{max-width:none;margin:0;color:#000;background:#fff}"
            ".toolbar{display:none!important}.ocr-source{display:none!important}.ocr-notes{display:none!important}"
            "img{break-inside:avoid}table{break-inside:auto}tr{break-inside:avoid}"
            "thead{display:table-header-group}a{color:inherit;text-decoration:none}}")

def export_html(final_path, source, pandoc, *, media_root=None, title=None):
    work_dir = Path(final_path).parent
    asset_root = Path(media_root) if media_root is not None else work_dir
    parsed = subprocess.run([pandoc, str(final_path), "-f", "markdown+tex_math_dollars+tex_math_single_backslash-raw_html", "-t", "json"],
                            cwd=asset_root, capture_output=True, text=True, encoding="utf-8", timeout=120)
    if parsed.returncode:
        raise RuntimeError("Không phân tích được kết quả OCR: " + parsed.stderr)
    document, counts = prepare_print_ast(json.loads(parsed.stdout))
    process = subprocess.run([pandoc, "-f", "json", "-t", "html5", "--mathml", "--wrap=none"],
                             input=json.dumps(document), cwd=asset_root, capture_output=True, text=True, encoding="utf-8", timeout=120)
    if process.returncode:
        raise RuntimeError("Không xuất được HTML kết quả OCR: " + process.stderr)
    warnings = (parsed.stderr + "\n" + process.stderr).strip()
    if warnings:
        (work_dir / "html-warnings.log").write_text(warnings, encoding="utf-8")
        print("[CẢNH BÁO XUẤT HTML]", warnings, flush=True)
    def embed(match):
        ref = html.unescape(match[1])
        path = image_path(ref, asset_root)
        if path is None or not path.is_file():
            return match[0]
        suffix = path.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}:
            return '<span style="color:#a00">[Ảnh ' + html.escape(path.name) + ' chưa hiển thị được trong trình duyệt; xem file gốc trong ZIP]</span>'
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}.get(suffix, "image/" + suffix[1:])
        uri = "data:" + mime + ";base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        return match[0].replace(match[1], uri, 1)
    body = re.sub(r'<img\b[^>]*\bsrc="([^"]+)"[^>]*>', embed, process.stdout)
    body, _ = remove_axis_label_blocks(body)
    display_name = title or Path(source).name
    toolbar = ('<div class="toolbar"><strong>Đề đang xem: ' + html.escape(display_name) + '</strong><br>'
               '<button onclick="window.print()">In / lưu PDF kết quả</button>'
               '<label><input type="checkbox" onchange="document.body.classList.toggle(\'show-source\',this.checked)"> Đối chiếu ảnh gốc / ghi chú OCR</label>'
               '<p>Bản in dùng bảng/công thức đã dựng từ OCR khi có cấu trúc; đồ thị và ảnh chưa dựng được giữ nguyên. '
               'Chữ OCR chưa được xác nhận đúng. Bật đối chiếu để kiểm tra; ảnh đối chiếu và ghi chú không in kèm. '
               'In tỷ lệ 100%, tắt Headers/Footers của trình duyệt. Ngắt dòng/ngắt trang có thể khác Word.</p></div>')
    page = ('<!doctype html><html lang="vi"><meta charset="utf-8"><title>Kết quả OCR — '
            + html.escape(display_name) + '</title><style>' + page_css(source)
            + '</style><body>' + toolbar + body + '</body></html>')
    target = work_dir / "ket-qua-ocr.html"
    target.write_text(page, encoding="utf-8")
    (work_dir / "print-layout.json").write_text(json.dumps(dict(**counts, policy="structured_ocr_reconstruction_with_source_comparison",
        validation="layout_only_not_ocr_accuracy", media_root=str(asset_root)), ensure_ascii=False, indent=2), encoding="utf-8")
    return target

current_result = globals().get("result")
if not isinstance(current_result, dict) or not current_result.get("results"):
    raise RuntimeError("Chưa có kết quả OCR hoàn tất trong phiên này. Không lấy kết quả cũ tự động.")
media_root = Path(current_result["results"]).resolve()
source_copy = media_root / "input.docx"
step1 = media_root / "step1.md"
report_path = media_root / "image-report.json"
for required in (source_copy, step1, report_path):
    if not required.is_file():
        raise RuntimeError("Thiếu dữ liệu đã lưu để dựng lại: " + str(required))
requested = globals().get("INPUT_DOCX")
recorded = current_result.get("source_path") or current_result.get("metrics", {}).get("source_path")
if requested and recorded and Path(requested).resolve() != Path(recorded).resolve():
    raise RuntimeError("Đang chọn đề khác nhưng kết quả còn thuộc đề cũ. Không dựng nhầm đề.")
if requested and Path(requested).is_file():
    if hashlib.sha256(Path(requested).read_bytes()).digest() != hashlib.sha256(source_copy.read_bytes()).digest():
        raise RuntimeError("Đã chặn: DOCX kết quả không khớp đề đang chọn.")
records = json.loads(report_path.read_text(encoding="utf-8"))
if not isinstance(records, list) or any(not isinstance(item, dict) or "ref" not in item for item in records):
    raise RuntimeError("image-report.json không đúng định dạng của notebook 3 cell.")

pandoc = shutil.which("pandoc")
if not pandoc:
    caches = [Path(globals().get("RUN_ROOT", "/kaggle/working/hybrid_original_fixed")) / "dependencies",
              Path("/kaggle/working/hybrid_ocr_clean/dependencies")]
    for cache in caches:
        for pattern in ("*/pypandoc/files/pandoc", "*/pypandoc/files/pandoc.exe"):
            for candidate in sorted(cache.glob(pattern)):
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    pandoc = str(candidate)
                    break
            if pandoc:
                break
        if pandoc:
            break
if not pandoc:
    try:
        import pypandoc
        pandoc = pypandoc.get_pandoc_path()
    except Exception as error:
        raise RuntimeError("Chưa tìm thấy Pandoc đã cài trong phiên. Không cần chạy lại model.") from error

started = time.perf_counter()
print_root = media_root.parent / ("print-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:6])
print_root.mkdir()
rebuilt_markdown = build_final(step1.read_text(encoding="utf-8"), {item["ref"]: item for item in records})
render_input = print_root / "ket-qua-in.md"
render_input.write_text(rebuilt_markdown, encoding="utf-8")
title = current_result.get("metrics", {}).get("source_name") or (Path(recorded).name if recorded else "Đề thi")
PRINT_HTML = export_html(render_input, source_copy, pandoc, media_root=media_root, title=title)
layout = json.loads((print_root / "print-layout.json").read_text(encoding="utf-8"))
elapsed = time.perf_counter() - started
encoded = base64.b64encode(PRINT_HTML.read_bytes()).decode("ascii")
display(HTML('<h3>Bản in đã dựng: ' + html.escape(title) + '</h3><p><a download="' + html.escape(PRINT_HTML.name) + '" href="data:text/html;base64,' + encoded + '">Tải HTML bản in mới — mở để In / lưu PDF</a></p>'))
display(IFrame("about:blank", width="100%", height=1100, extras=[
    'title="Bản in OCR đã dựng"', 'sandbox="allow-scripts allow-modals allow-downloads"',
    'srcdoc="' + html.escape(PRINT_HTML.read_text(encoding="utf-8"), quote=True) + '"',
]))
print("Đã dựng", layout["structured_tables"], "bảng OCR và", layout["inline_math"], "công thức ảnh.")
print("Ghi chú chưa đủ cấu trúc:", layout["notes_only"], "— giữ ảnh nguồn, chỉ xem ghi chú khi bật đối chiếu.")
print(f"Thời gian dựng lại: {elapsed:.2f}s. Không chạy lại OCR/model.")
print("HTML mới:", PRINT_HTML)
print("Kết quả OCR, chữ thô và ZIP cũ không bị ghi đè. Dùng nút tải HTML mới ở cell này để in.")
