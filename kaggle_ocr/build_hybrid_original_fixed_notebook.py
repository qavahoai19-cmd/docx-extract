"""Đóng gói đúng script gốc đã sửa thành notebook chạy một cell."""
import ast
import json
from pathlib import Path
import warnings


HERE = Path(__file__).resolve().parent


def build(target=None):
    source = (HERE / "hybrid_ocr_original_fixed.py").read_text(encoding="utf-8")
    picker_source = (HERE / "choose_exam.py").read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        compile(source, "hybrid_ocr_original_fixed.py", "exec")
    tree = ast.parse(source)
    settings = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for name in node.targets:
                if isinstance(name, ast.Name) and name.id in {"INPUT_DOCX", "RUN_ROOT", "OCR_DIAGRAMS", "OCR_SMALL_IMAGES"}:
                    settings[name.id] = ast.literal_eval(node.value)
    instructions = """# Pandoc + DeepSeek-OCR-2 — pipeline đã hợp nhất

Chạy **cell code bên dưới một lần để mở bộ chọn đề**. Chọn đúng DOCX trong danh sách rồi bấm **Đọc đề đã chọn**. Không tự chạy đề Toán mẫu.

- File phải đã được thêm vào Input của Kaggle. Bấm **Làm mới danh sách** nếu vừa thêm file. Đổi đề bằng danh sách này, không sửa các chuỗi đường dẫn bên trong code dài.
- Mỗi lần đổi/chạy đề, tham chiếu kết quả cũ được xóa; nếu chạy lỗi thì không mở lại kết quả cũ. Giao diện hiện tên file đang đọc, tên file của kết quả, và kiểm tra DOCX đính kèm kết quả khớp file đã chọn.
- Bật Internet và GPU để chạy DeepSeek-OCR-2. Lần đầu cài thư viện riêng và tải model; không thay Torch/Transformers của kernel.
- Dùng duy nhất model DeepSeek-OCR-2, BF16, eager và các cấu hình 384/448/512/640. Không hứa thời gian/độ chính xác khi chưa chạy GPU thực tế.
- `OCR_DIAGRAMS=False`: giữ hình sơ đồ, không gửi OCR mặc định như luồng gốc. Heuristic có thể phân loại sai; bật True nếu muốn OCR cả các hình này.
- Nhận diện thêm lưới tọa độ/trục đậm để không OCR nhầm các đồ thị câu 1–2. Danh sách nhãn rời kiểu `y x O -2 -1 ...` không được chèn thành một công thức dưới hình; chữ thô vẫn lưu trong báo cáo. Công thức/ma trận không bị xóa bằng bộ lọc nhãn này.
- `OCR_SMALL_IMAGES=True`: giữ khả năng OCR công thức nhỏ; không phóng mọi ảnh lên 384 px trước khi chọn cấu hình.
- Không sửa nội dung LaTeX/ma trận bằng regex. Không coi alt-text là kết quả model đọc được.
- Bản HTML dựng bảng OCR thành hàng/cột và render công thức `\\(...\\)`, `\\[...\\]`. Mặc định in bảng/công thức đã dựng, không in lặp ảnh gốc và ghi chú; bật **Đối chiếu ảnh gốc / ghi chú OCR** để xem nguồn trên màn hình. Những đoạn chưa đủ cấu trúc giữ ảnh gốc, không tự đoán thành bảng/công thức.
- Chỉ kiểm tra các ảnh Pandoc xuất được. WMF/EMF/OLE không đọc được sẽ được báo, không tự cài LibreOffice. Giữ thêm DOCX gốc trong ZIP để kiểm tra hình bị thiếu.

Sau khi chạy xong, **kết quả trích xuất + OCR hiện ngay dưới cell**. Ảnh gốc giữ nguyên, chữ model đọc được hiện dưới ảnh với nhãn `[OCR — cần đối chiếu]`. Đây là đầu ra thật của pipeline, không phải xuất lại DOCX gốc rồi gọi là OCR.

Có nút tải **HTML kết quả**, **Markdown** và **ZIP**. Mở HTML để In/lưu PDF; công thức dùng MathML, không cần tải MathJax. HTML không cam kết giống tuyệt đối ngắt dòng/ngắt trang Word. Báo cáo ghi thời gian từng bước và các lượt thử; “có chữ trả về” không phải tỷ lệ chính xác.

Ngay dưới kết quả có **TỔNG THỜI GIAN ĐÃ CHẠY** (phút/giây), gồm chuẩn bị thư viện, Pandoc/ảnh, nạp model, OCR, xuất HTML và nén nội dung ZIP. Số đo dừng khi ZIP nội dung đóng xong, trước thao tác ghi báo cáo thời gian và dựng màn hình. `metrics.json` trong ZIP chứa cùng số đo, không cần chạy lại OCR để xem.

Khi chưa có log mới, cứ mỗi 5 giây có dòng PID/thời gian để phân biệt tiến trình chưa kết thúc. Không tự chạy lại cell cùng lúc. Mỗi lượt có thư mục riêng, không xóa kết quả cũ.
"""
    cell = f'''# CHẠY CELL ĐỂ MỞ BỘ CHỌN ĐỀ. KHÔNG TỰ CHẠY ĐỀ MẪU.
INPUT_DOCX = ""
OCR_DIAGRAMS = {settings['OCR_DIAGRAMS']!r}
OCR_SMALL_IMAGES = {settings['OCR_SMALL_IMAGES']!r}
RUN_ROOT = {settings['RUN_ROOT']!r}

import importlib.util
from pathlib import Path

SCRIPT_SOURCE = {source!r}
root = Path(RUN_ROOT)
root.mkdir(parents=True, exist_ok=True)
script_path = root / "hybrid_ocr_original_fixed.py"
script_path.write_text(SCRIPT_SOURCE, encoding="utf-8")
spec = importlib.util.spec_from_file_location("hybrid_original_fixed_run", script_path)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)
result = None
FINAL_PATH = WORK_DIR = CLEAN_HTML = None
PICKER_SOURCE = {picker_source!r}
picker_namespace = {{"__name__": "exam_file_picker"}}
exec(compile(PICKER_SOURCE, "<exam-file-picker>", "exec"), picker_namespace)
exam_picker = picker_namespace["show_exam_picker"](globals(), pipeline)
'''
    compile(cell, "original-fixed-notebook-cell", "exec")
    notebook = dict(nbformat=4, nbformat_minor=5,
                    metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                              "language_info": {"name": "python"}},
                    cells=[dict(cell_type="markdown", id="read-first", metadata={}, source=instructions.splitlines(keepends=True)),
                           dict(cell_type="code", id="run-original-fixed", metadata={}, execution_count=None, outputs=[], source=cell.splitlines(keepends=True))])
    target = Path(target) if target is not None else HERE / "hybrid_ocr_original_fixed.ipynb"
    target.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return target


def build_repair_cell(target=None):
    """Sinh cell vá chỉ dùng thư viện chuẩn từ cùng hàm lọc, không chạy OCR."""
    source = (HERE / "hybrid_ocr_original_fixed.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {"is_plot_label_list", "remove_axis_label_blocks"}
    functions = "\n\n".join(ast.get_source_segment(source, node) for node in tree.body
                             if isinstance(node, ast.FunctionDef) and node.name in names)
    cell = '''# COPY TOÀN BỘ FILE NÀY VÀO MỘT CELL SAU KHI OCR XONG.
# Chỉ tạo HTML sạch để in. Không chạy model, không đổi ZIP/Markdown/báo cáo cũ.
import base64
import html
from html.parser import HTMLParser
import hashlib
from pathlib import Path
import re
from IPython.display import HTML, IFrame, display

''' + functions + '''

current_result = globals().get("result")
if not isinstance(current_result, dict) or not current_result.get("html"):
    raise RuntimeError("Chưa tìm thấy kết quả trong phiên này. Chạy cell này trong cùng notebook đã OCR xong.")
old_page = Path(current_result["html"])
requested = globals().get("INPUT_DOCX")
recorded = current_result.get("source_path") or current_result.get("metrics", {}).get("source_path")
if requested and recorded and Path(requested).resolve() != Path(recorded).resolve():
    raise RuntimeError("Đang chọn đề khác nhưng kết quả còn là đề cũ. Đọc xong đề mới trước khi chạy cell vá.")
if requested and current_result.get("results"):
    requested_path = Path(requested)
    copied_source = Path(current_result["results"]) / "input.docx"
    if requested_path.is_file() and copied_source.is_file() and hashlib.sha256(requested_path.read_bytes()).digest() != hashlib.sha256(copied_source.read_bytes()).digest():
        raise RuntimeError("Đã chặn kết quả đề cũ: nội dung DOCX không khớp đề đang chọn. Cần chạy OCR đề mới trước.")
old_text = old_page.read_text(encoding="utf-8")
title_match = re.search(r"<title>(.*?)</title>", old_text, re.IGNORECASE | re.DOTALL)
source_label = Path(recorded).name if recorded else (html.unescape(title_match[1]) if title_match else str(old_page))
display(HTML("<p><b>Đang dọn kết quả của:</b> " + html.escape(source_label) + "</p>"))
cleaned, removed = remove_axis_label_blocks(old_text)
CLEAN_HTML = old_page.with_name(old_page.stem + "-clean.html")
CLEAN_HTML.write_text(cleaned, encoding="utf-8")
encoded = base64.b64encode(cleaned.encode("utf-8")).decode("ascii")
display(HTML('<p><a download="' + html.escape(CLEAN_HTML.name) + '" href="data:text/html;base64,' + encoded + '">Tải HTML đã dọn nhãn đồ thị — mở để In / lưu PDF</a></p>'))
display(IFrame("about:blank", width="100%", height=1100, extras=[
    'title="Bản in đã dọn nhãn đồ thị"', 'sandbox="allow-scripts allow-modals allow-downloads"',
    'srcdoc="' + html.escape(cleaned, quote=True) + '"',
]))
print("Đã bỏ", removed, "khối OCR chỉ chứa nhãn trục/số rời; vẫn giữ nguyên hình và công thức.")
print("HTML mới:", CLEAN_HTML)
print("Không chạy lại OCR. ZIP/Markdown/báo cáo cũ không bị sửa; dùng HTML mới này để in.")
'''
    compile(cell, "plot-label-repair-cell", "exec")
    target = Path(target) if target is not None else HERE / "clean_plot_notes.py"
    target.write_text(cell, encoding="utf-8")
    return target


def ordered_cells():
    """Ba cell dùng trực tiếp: chuẩn bị, ghi pipeline, mở bộ chọn đề."""
    source = (HERE / "hybrid_ocr_original_fixed.py").read_text(encoding="utf-8")
    picker = (HERE / "choose_exam.py").read_text(encoding="utf-8")
    tree = ast.parse(picker)
    footer = [node for node in tree.body if isinstance(node, ast.If) and ast.unparse(node.test) == "__name__ == '__main__'"]
    if len(footer) != 1:
        raise RuntimeError("Không tìm thấy đúng một footer mở picker")
    picker = "\n".join(picker.splitlines()[:footer[0].lineno - 1])
    first = '''from pathlib import Path

if getattr(globals().get("exam_picker"), "busy", False):
    raise RuntimeError("Đang có lượt OCR chạy. Đợi hoặc dừng lượt đó trước.")

RUN_ROOT = "/kaggle/working/hybrid_original_fixed"
OCR_DIAGRAMS = False
OCR_SMALL_IMAGES = True
INPUT_DOCX = ""
result = None
FINAL_PATH = WORK_DIR = CLEAN_HTML = None
Path(RUN_ROOT).mkdir(parents=True, exist_ok=True)
print("Đã chuẩn bị. Chạy tiếp cell 2, rồi cell 3 để chọn đề.")
'''
    second = "%%writefile /kaggle/working/hybrid_original_fixed/hybrid_ocr_original_fixed.py\n" + source
    third = '''import importlib.util
from pathlib import Path

script_path = Path(RUN_ROOT) / "hybrid_ocr_original_fixed.py"
spec = importlib.util.spec_from_file_location("selected_exam_pipeline", script_path)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

''' + picker + '''

exam_picker = show_exam_picker(globals(), pipeline)
'''
    compile(first, "ordered-cell-1", "exec")
    compile("\n".join(second.splitlines()[1:]), "ordered-cell-2-payload", "exec")
    compile(third, "ordered-cell-3", "exec")
    return first, second, third


def build_reprint_cell(target=None):
    """Standalone cell rebuilding saved OCR, with no model/dependency installation."""
    source = (HERE / "hybrid_ocr_original_fixed.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {"image_path", "clean_pandoc_output", "is_plot_label_list", "remove_axis_label_blocks", "build_final",
             "ast_text", "has_ast_type", "prepare_print_ast", "page_css", "export_html"}
    functions = "\n\n".join(ast.get_source_segment(source, node) for node in tree.body
                             if isinstance(node, ast.FunctionDef) and node.name in names)
    image_regex = next(ast.get_source_segment(source, node) for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(name, ast.Name) and name.id == "IMAGE_RE" for name in node.targets))
    cell = '''# COPY TOÀN BỘ VÀO MỘT CELL MỚI Ở CUỐI NOTEBOOK ĐÃ OCR XONG.
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

''' + image_regex + '\n\n' + functions + '''

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
'''
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        compile(cell, "rebuild-ocr-print-cell", "exec")
    target = Path(target) if target is not None else HERE / "rebuild_ocr_print.py"
    target.write_text(cell, encoding="utf-8")
    return target


def build_ordered(target=None):
    cells = ordered_cells()
    intro = """# OCR — 3 cell theo thứ tự

Chỉ dùng 3 cell Code này, không trộn các cell vá cũ. Bật Internet/GPU và thêm DOCX vào Input.
Chạy 1 → 2 → 3; chọn đúng DOCX rồi bấm **Đọc đề đã chọn**. Không tự chạy đề mẫu.
Kết quả có tên file, tổng thời gian và nút tải HTML/ZIP. Đổi đề ngay trong bộ chọn, không sửa code.
Không xác nhận chất lượng/tốc độ model khi chưa chạy trên GPU thực tế. WMF/EMF/OLE không đọc được sẽ được báo.
"""
    notebook = dict(nbformat=4, nbformat_minor=5,
                    metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                              "language_info": {"name": "python"}},
                    cells=[dict(cell_type="markdown", id="instructions", metadata={}, source=intro.splitlines(keepends=True))]
                    + [dict(cell_type="code", id=f"step-{index}", metadata={}, execution_count=None, outputs=[],
                            source=cell.splitlines(keepends=True)) for index, cell in enumerate(cells, 1)])
    target = Path(target) if target is not None else HERE / "hybrid_ocr_3_cells.ipynb"
    target.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    print(build())
    print(build_repair_cell())
    print(build_reprint_cell())
    print(build_ordered())
