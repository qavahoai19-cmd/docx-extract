import re
from . import ns
from . import answer


# Azota render w:tab bằng chuỗi dấu cách để căn cột giữa các phương án.
# Golden fixture cho thấy độ rộng thực tế biến thiên theo tab-stop thật
# (8, 12, 13, 4, 20 dấu cách tuỳ dòng — vì Azota mô phỏng tab-stop thực của
# Word, không phải một hằng số cố định). Vì test khớp dòng đã chuẩn hoá mọi
# chuỗi khoảng trắng liên tiếp về 1 dấu cách (xem tests/test_golden.py::_norm),
# giá trị chính xác của hằng số này không ảnh hưởng tới golden-match ratio;
# ta chọn 4 dấu cách làm giá trị gần đúng hợp lý cho output "thô" (markup.txt)
# khi không chuẩn hoá khoảng trắng, thay vì ký tự tab thật (Word tab-stop
# đầy đủ đòi hỏi mô phỏng font-metric — ngoài phạm vi task này).
TAB_SPACES = "    "

def run_format(rpr):
    if rpr is None:
        return (False, False, None, False)
    bold = rpr.find(ns.q("w", "b")) is not None
    italic = rpr.find(ns.q("w", "i")) is not None
    va = rpr.find(ns.q("w", "vertAlign"))
    vert = va.get(ns.q("w", "val")) if va is not None else None
    underline = rpr.find(ns.q("w", "u")) is not None
    return (bold, italic, vert, underline)

def wrap(text, fmt):
    # Azota bỏ qua định dạng (bold/italic/vert) cho các segment chỉ chứa
    # khoảng trắng/tab — bọc tag ở đây chỉ tạo ra rác kiểu "[!b:$ $]" không
    # có trong golden. Text rỗng hoặc toàn whitespace luôn xuất raw.
    if not text or text.strip() == "":
        return text
    bold, italic, vert, _u = fmt
    if vert == "superscript":
        return f"[!sup:${text}$]"
    if vert == "subscript":
        return f"[!sub:${text}$]"
    if bold and italic:
        return f"[!b!i:${text}$]"
    if bold:
        return f"[!b:${text}$]"
    if italic:
        return f"[!i:${text}$]"
    return text

def _render_run(r, ctx, segments):
    fmt = run_format(r.find(ns.q("w", "rPr")))
    for child in r:
        tag = child.tag
        if tag == ns.q("w", "t"):
            segments.append(("text", fmt, child.text or ""))
        elif tag == ns.q("w", "tab"):
            segments.append(("text", fmt, TAB_SPACES))
        elif tag == ns.q("w", "br"):
            segments.append(("raw", None, "\n"))
        elif tag == ns.q("w", "drawing") and ctx is not None:
            segments.append(("raw", None, ctx.image(child)))
        elif tag == ns.q("w", "object") and ctx is not None:
            rendered = ctx.ole(child)
            if rendered is not None:
                segments.append(("raw", None, rendered))

def _walk(parent, ctx, segments):
    for child in parent:
        tag = child.tag
        if tag == ns.q("w", "r"):
            _render_run(child, ctx, segments)
        elif tag in (ns.q("m", "oMath"), ns.q("m", "oMathPara")) and ctx is not None:
            segments.append(("raw", None, ctx.omml(child)))
        elif tag == ns.q("w", "hyperlink"):
            _walk(child, ctx, segments)

def _coalesce(segments):
    merged = []
    for kind, fmt, content in segments:
        if kind == "text" and merged and merged[-1][0] == "text" and merged[-1][1] == fmt:
            merged[-1] = ("text", fmt, merged[-1][2] + content)
        else:
            merged.append((kind, fmt, content))
    return merged

def emit(segments):
    out = []
    coalesced = _coalesce(segments)
    for idx, (kind, fmt, content) in enumerate(coalesced):
        if kind == "raw":
            out.append(content)
        elif content and answer.is_option_marker(content):
            out.append(answer.render_marker(content, fmt))
        elif idx == 0 and content and answer.is_paragraph_start_label(content):
            # Câu N:/Câu N./a).."d)" ở đầu đoạn -> Azota xuất plain dù bold.
            out.append(content)
        else:
            out.append(wrap(content, fmt) if content else "")
    return "".join(out)

def render_paragraph(p, ctx):
    segments = []
    _walk(p, ctx, segments)
    return emit(segments)
