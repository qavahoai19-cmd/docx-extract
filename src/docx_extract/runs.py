import re
from . import ns

TAB_SPACES = "\t"   # tinh chỉnh ở Task 8 theo golden

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
            segments.append(("raw", None, ctx.ole(child)))

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
    for kind, fmt, content in _coalesce(segments):
        if kind == "raw":
            out.append(content)
        else:
            out.append(wrap(content, fmt) if content else "")
    return "".join(out)

def render_paragraph(p, ctx):
    segments = []
    _walk(p, ctx, segments)
    return emit(segments)
