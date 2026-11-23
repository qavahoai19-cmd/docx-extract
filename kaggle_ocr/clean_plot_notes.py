# COPY TOÀN BỘ FILE NÀY VÀO MỘT CELL SAU KHI OCR XONG.
# Chỉ tạo HTML sạch để in. Không chạy model, không đổi ZIP/Markdown/báo cáo cũ.
import base64
import html
from html.parser import HTMLParser
import hashlib
from pathlib import Path
import re
from IPython.display import HTML, IFrame, display

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
