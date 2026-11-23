import re
from . import ns
from . import answer
from .xmlwalk import content_children, iter_blocks
from .numbering import paragraph_label


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

# Word stores legacy Symbol glyphs as font-specific bytes, often in U+F000.
# Decode known glyphs rather than treating these as Unicode private-use text.
_SYMBOL_GLYPHS = dict(zip(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "ΑΒΧΔΕΦΓΗΙϑΚΛΜΝΟΠΘΡΣΤΥςΩΞΨΖαβχδεφγηιϕκλμνοπθρστυϖωξψζ",
))
_SYMBOL_GLYPHS.update({
    '"': '∀', '$': '∃', "'": '∋', '*': '∗', '-': '−', '@': '≅',
    '\\': '∴', '^': '⊥', '`': '‾', '~': '∼',
    '\xa3': '≤', '\xa5': '∞', '\xab': '↔', '\xac': '←', '\xad': '↑',
    '\xae': '→', '\xaf': '↓', '\xb0': '°', '\xb1': '±', '\xb3': '≥',
    '\xb4': '×', '\xb5': '∝', '\xb6': '∂', '\xb7': '•', '\xb8': '÷',
    '\xb9': '≠', '\xba': '≡', '\xbb': '≈', '\xbc': '…',
    '\xc7': '∩', '\xc8': '∪', '\xcc': '⊂', '\xcd': '⊆', '\xce': '∈',
    '\xcf': '∉', '\xd0': '∠', '\xd1': '∇', '\xd5': '∏', '\xd6': '√',
    '\xd7': '⋅', '\xd9': '∧', '\xda': '∨', '\xdb': '⇔', '\xdc': '⇐',
    '\xde': '⇒', '\xe5': '∑', '\xf2': '∫',
})


def _symbol_text(node, ctx):
    font = node.get(ns.q("w", "font"), "")
    code = node.get(ns.q("w", "char"), "")
    try:
        value = int(code, 16)
        text = chr(value)
    except (ValueError, OverflowError):
        text = f"[symbol:{font}:{code}]"
    else:
        byte = value - 0xF000 if 0xF000 <= value <= 0xF0FF else value
        if font.casefold() == "symbol":
            glyph = _SYMBOL_GLYPHS.get(chr(byte))
            if glyph is not None:
                return glyph
            if chr(byte) in " 0123456789!#%&()+,./:;<=>?[]_{|}":
                return chr(byte)
        elif font.casefold() == "wingdings" and byte == 0xE0:
            return "→"
        elif not font or (font.casefold() not in {"symbol", "wingdings", "webdings"}
                          and not 0xE000 <= value <= 0xF8FF):
            return text
    if ctx is not None:
        ctx.warnings.append(f"Ký hiệu chưa giải mã: font={font!r}, char={code}; giữ ký tự gốc")
    return text

def run_format(rpr):
    if rpr is None:
        return (False, False, None, False, False)

    def enabled(name):
        prop = rpr.find(ns.q("w", name))
        return prop is not None and prop.get(ns.q("w", "val"), "1").lower() not in {
            "0", "false", "off", "none",
        }

    bold = enabled("b")
    italic = enabled("i")
    va = rpr.find(ns.q("w", "vertAlign"))
    vert = va.get(ns.q("w", "val")) if va is not None else None
    underline = enabled("u")
    highlight = rpr.find(ns.q("w", "highlight"))
    shaded = rpr.find(ns.q("w", "shd"))
    marked = highlight is not None and highlight.get(ns.q("w", "val"), "none").lower() not in {
        "none", "white", "auto", "",
    }
    if not marked and shaded is not None and shaded.get(ns.q("w", "val"), "clear") != "nil":
        fill = shaded.get(ns.q("w", "fill"), "auto").upper()
        if shaded.get(ns.q("w", "val")) == "solid":
            fill = shaded.get(ns.q("w", "color"), fill).upper()
        marked = fill not in {"AUTO", "FFFFFF", "NONE", ""}
    return (bold, italic, vert, underline, marked)

def wrap(text, fmt):
    # Azota bỏ qua định dạng (bold/italic/vert) cho các segment chỉ chứa
    # khoảng trắng/tab — bọc tag ở đây chỉ tạo ra rác kiểu "[!b:$ $]" không
    # có trong golden. Text rỗng hoặc toàn whitespace luôn xuất raw.
    if not text:
        return text
    if text.strip() == "":
        # An underlined tab/space is an intentional fill-in blank in Word.
        return f"[!u:${text}$]" if fmt[3] else text
    bold, italic, vert, underline = fmt[:4]
    if vert == "superscript":
        style = "!sup"
    elif vert == "subscript":
        style = "!sub"
    else:
        style = ("!b" if bold else "") + ("!i" if italic else "")
    if underline:
        style += "!u"
    return f"[{style}:${text}$]" if style else text

def _render_graphic(node, ctx, segments):
    if node.tag in {ns.q("a", "blip"), ns.q("v", "imagedata")}:
        segments.append(("raw", None, ctx.image(node)))
        return
    if node.tag == ns.q("w", "txbxContent"):
        from .tables import render_table
        parts = [render_paragraph(block, ctx) if block.tag == ns.q("w", "p")
                 else render_table(block, ctx) for block in iter_blocks(node)]
        segments.append(("raw", None, "\n".join(parts)))
        return
    if node.tag in {ns.q("w", "del"), ns.q("w", "moveFrom")}:
        return
    for child in content_children(node):
        _render_graphic(child, ctx, segments)


def _render_run(r, ctx, segments):
    fmt = run_format(r.find(ns.q("w", "rPr")))
    for child in content_children(r):
        _render_inline(child, ctx, segments, fmt)


def _render_inline(node, ctx, segments, fmt=None):
    tag = node.tag
    if tag == ns.q("w", "r"):
        _render_run(node, ctx, segments)
    elif tag == ns.q("w", "t"):
        segments.append(("text", fmt or run_format(None), node.text or ""))
    elif tag == ns.q("w", "sym"):
        segments.append(("text", fmt or run_format(None), _symbol_text(node, ctx)))
    elif tag == ns.q("w", "tab"):
        segments.append(("text", fmt or run_format(None), TAB_SPACES))
    elif tag in {ns.q("w", "br"), ns.q("w", "cr")}:
        segments.append(("raw", None, "\n"))
    elif tag in {ns.q("w", "noBreakHyphen"), ns.q("w", "softHyphen")}:
        segments.append(("text", fmt or run_format(None),
                         "\u2011" if tag == ns.q("w", "noBreakHyphen") else "\u00ad"))
    elif tag in {ns.q("m", "oMath"), ns.q("m", "oMathPara")}:
        if ctx is not None:
            segments.append(("raw", None, ctx.omml(node)))
    elif tag in {ns.q("w", "drawing"), ns.q("w", "pict")}:
        if ctx is not None:
            _render_graphic(node, ctx, segments)
    elif tag == ns.q("w", "object"):
        if ctx is not None:
            rendered = ctx.ole(node)
            if rendered is not None:
                segments.append(("raw", None, rendered))
            else:
                _render_graphic(node, ctx, segments)
    elif (not isinstance(tag, str) or tag.endswith("Pr") or tag in {
        ns.q("w", name) for name in ("del", "moveFrom", "instrText", "delText")
    }):
        return
    else:
        # Recover visible descendants of unfamiliar inline wrappers. Properties,
        # field instructions and tracked deletions must never become body text.
        for child in content_children(node):
            _render_inline(child, ctx, segments, fmt)

def _walk(parent, ctx, segments):
    for child in content_children(parent):
        _render_inline(child, ctx, segments)

def _coalesce(segments):
    merged = []
    for kind, fmt, content in segments:
        if kind == "text" and merged and merged[-1][0] == "text" and merged[-1][1] == fmt:
            merged[-1] = ("text", fmt, merged[-1][2] + content)
        else:
            merged.append((kind, fmt, content))
    return merged


_INLINE_OPTION = re.compile(r"(^|[ \t\r\n]+|(?<=[.\uFFFC]))(\*?[A-D][.)])", re.MULTILINE)
_QUESTION_OPTION_PREFIX = re.compile(r"^(?:Câu|Question)\s*\d+\s*[.:]\s*$", re.IGNORECASE)
_INLINE_QUESTION = re.compile(r"\b(?:Câu|Question)\s*\d+\s*[.:]\s*", re.IGNORECASE)


def _option_segments(segments):
    """Read option labels across formatting boundaries without altering content."""
    spans, visible, position = [], [], 0
    for kind, fmt, content in segments:
        text = content if kind == "text" or content == "\n" else "\uFFFC"
        spans.append((position, position + len(text), kind, fmt, content))
        visible.append(text)
        position += len(text)
    visible = "".join(visible)
    matches = list(_INLINE_OPTION.finditer(visible))
    questions = list(_INLINE_QUESTION.finditer(visible))

    def sliced(start, end):
        for first, last, kind, fmt, content in spans:
            if first >= end:
                break
            if last <= start:
                continue
            yield (kind, fmt, content[max(0, start - first):min(len(content), end - first)]
                   if kind == "text" else content)

    result, position = [], 0
    for index, match in enumerate(matches):
        start, end = match.span(2)
        question_start = max((q.end() for q in questions if q.end() <= start), default=0)
        question_end = min((q.start() for q in questions if q.start() > start), default=len(visible))
        local = [m[2].lstrip('*')[0] for m in matches if question_start <= m.start(2) < question_end]
        option_list = len(local) > 1 and len(set(local)) == len(local) and local == sorted(local)
        # A solitary underlined reference in prose ("vì sao chọn B.") is
        # not evidence of a correct option. Labels at line starts are safe.
        prefix = visible[max(question_start, visible.rfind("\n", 0, start) + 1):start]
        if prefix.strip() and not option_list and not _QUESTION_OPTION_PREFIX.fullmatch(prefix.strip()):
            continue
        result.extend(sliced(position, start))
        underline = any(kind == "text" and fmt[3]
                        for kind, fmt, _ in sliced(start, end))
        answer_end = min(question_end, matches[index + 1].start(2) if index + 1 < len(matches) else len(visible))
        highlighted = any(kind == "text" and len(fmt) > 4 and fmt[4] and content.strip()
                          for kind, fmt, content in sliced(start, answer_end))
        marker = match[2]
        result.append(("raw", None, ("*" if (underline or highlighted) and not marker.startswith("*") else "") + marker))
        position = end
    result.extend(sliced(position, len(visible)))
    return result


def emit(segments):
    out = []
    coalesced = _option_segments(_coalesce(segments))
    for idx, (kind, fmt, content) in enumerate(coalesced):
        if kind == "raw":
            out.append(content)
        elif idx == 0 and content and answer.is_paragraph_start_label(content):
            # Câu N:/Câu N./a).."d)" ở đầu đoạn -> Azota xuất plain dù bold.
            out.append(content)
        else:
            out.append(wrap(content, fmt) if content else "")
    return "".join(out)

def render_paragraph(p, ctx):
    segments = []
    label = paragraph_label(p, ctx.numbering, ctx.numbering_counters) if ctx is not None else ''
    if label:
        # The generated A–D label must participate in answer detection too:
        # its content can carry the highlight even though no w:t holds A–D.
        segments.append(('text', run_format(None), label))
    _walk(p, ctx, segments)
    return emit(segments)
