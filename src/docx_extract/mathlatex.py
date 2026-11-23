import re

from . import ns
from .xmlwalk import MC, selected_children


class UnsupportedMath(ValueError):
    """A structure cannot be converted without guessing its meaning."""


_ACCENTS = {"⃗": r"\vec", "→": r"\overrightarrow", "←": r"\overleftarrow",
    "↔": r"\overleftrightarrow", "ˆ": r"\hat", "̂": r"\hat", "^": r"\hat",
    "¯": r"\bar", "̄": r"\bar", "~": r"\tilde", "̃": r"\tilde", "˜": r"\tilde",
    "˙": r"\dot", "̇": r"\dot", "¨": r"\ddot", "̈": r"\ddot", "̆": r"\breve", "ˇ": r"\check"}
_ARROWS = {"→": r"\rightarrow", "←": r"\leftarrow", "↔": r"\leftrightarrow",
    "⇄": r"\rightleftarrows", "⇆": r"\leftrightarrows", "⇌": r"\rightleftharpoons",
    "⇋": r"\leftrightharpoons", "⇇": r"\leftleftarrows", "⇒": r"\Rightarrow", "⇐": r"\Leftarrow", "⇔": r"\Leftrightarrow"}
_DELIMITERS = {"": ".", "(": "(", ")": ")", "[": "[", "]": "]", "{": r"\{", "}": r"\}",
    "|": "|", "‖": r"\Vert ", "⟨": r"\langle ", "⟩": r"\rangle ",
    "⌊": r"\lfloor ", "⌋": r"\rfloor ", "⌈": r"\lceil ", "⌉": r"\rceil "}
_CONTAINERS = {ns.q("m", name) for name in ("oMath", "e", "num", "den", "deg", "sub", "sup", "fName", "lim")}
_PROPERTIES = {ns.q("m", name + "Pr") for name in ("r", "ctrl", "oMathPara", "f", "sSup", "sSub",
    "sSubSup", "sPre", "rad", "d", "nary", "acc", "bar", "groupChr", "eqArr", "m", "limLow", "limUpp", "func")}


def _property(elem, group, key, default):
    parent = elem.find(ns.q("m", group))
    child = parent.find(ns.q("m", key)) if parent is not None else None
    return child.get(ns.q("m", "val"), default) if child is not None else default

def _t(prefix, tag):
    return ns.q(prefix, tag)

def _children_latex(elem) -> str:
    parts = []
    for child in selected_children(elem):
        part = _node(child)
        if not part:
            continue
        if parts and part and part[0].isascii() and part[0].isalpha():
            if re.search(r"\\[A-Za-z]+$", parts[-1]):
                parts.append(" ")
        parts.append(part)
    return "".join(parts)

def _e_latex(parent, child_tag) -> str:
    """LaTeX của con <m:child_tag> (vd m:num, m:e) — rỗng nếu vắng."""
    child = parent.find(ns.q("m", child_tag))
    return _children_latex(child) if child is not None else ""

def _node(elem) -> str:
    tag = elem.tag
    if not isinstance(tag, str):
        return ""
    if tag == MC + "AlternateContent":
        return _children_latex(elem)
    if tag == ns.q("w", "lastRenderedPageBreak"):
        return ""  # Pagination marker, not mathematical content.
    if tag == ns.q("w", "br"):
        return r"\allowbreak "
    if tag == ns.q("w", "rPr") or tag in _PROPERTIES:
        return ""
    if tag == _t("m", "r"):
        return _children_latex(elem)
    if tag == _t("m", "t"):
        value = (elem.text or "").replace("\u200b", "").replace("\ufeff", "")
        if not value.strip():
            return ""
        escapes = {"\\": r"\backslash ", "{": r"\{", "}": r"\}", "_": r"\_",
                   "&": r"\&", "%": r"\%", "#": r"\#", "$": r"\$", "−": "-"}
        return "".join(escapes.get(c, r"\," if c.isspace() and not c.isascii() else c) for c in value)
    if tag == _t("m", "f"):
        return r"\frac{" + _e_latex(elem, "num") + "}{" + _e_latex(elem, "den") + "}"
    if tag == _t("m", "sSup"):
        return _e_latex(elem, "e") + "^{" + _e_latex(elem, "sup") + "}"
    if tag == _t("m", "sSub"):
        return _e_latex(elem, "e") + "_{" + _e_latex(elem, "sub") + "}"
    if tag == _t("m", "sSubSup"):
        return (_e_latex(elem, "e") + "_{" + _e_latex(elem, "sub")
                + "}^{" + _e_latex(elem, "sup") + "}")
    if tag == _t("m", "rad"):
        deg = elem.find(ns.q("m", "deg"))
        base = _e_latex(elem, "e")
        deg_txt = _children_latex(deg) if deg is not None else ""
        hidden = _property(elem, "radPr", "degHide", "0") not in {"0", "false", "off"}
        if deg_txt and not hidden:
            return r"\sqrt[" + deg_txt + "]{" + base + "}"
        return r"\sqrt{" + base + "}"
    if tag == _t("m", "d"):
        beg, end = "(", ")"
        dpr = elem.find(ns.q("m", "dPr"))
        if dpr is not None:
            b = dpr.find(ns.q("m", "begChr"))
            e = dpr.find(ns.q("m", "endChr"))
            if b is not None:
                beg = b.get(ns.q("m", "val"), "(")
            if e is not None:
                end = e.get(ns.q("m", "val"), ")")
        if beg not in _DELIMITERS or end not in _DELIMITERS:
            raise UnsupportedMath(f"Dấu ngoặc chưa hỗ trợ: {beg!r}, {end!r}")
        inner = _property(elem, "dPr", "sepChr", "|").join(
            _children_latex(c) for c in elem.findall(ns.q("m", "e")))
        return r"\left" + _DELIMITERS[beg] + inner + r"\right" + _DELIMITERS[end]
    if tag == _t("m", "nary"):
        # tích phân/tổng: ký hiệu ở naryPr>chr (mặc định ∫)
        chr_map = {"∑": r"\sum", "∏": r"\prod", "∫": r"\int", "∬": r"\iint", "∭": r"\iiint", "∮": r"\oint"}
        sym = "∫"
        npr = elem.find(ns.q("m", "naryPr"))
        if npr is not None:
            c = npr.find(ns.q("m", "chr"))
            if c is not None:
                sym = c.get(ns.q("m", "val"), sym)
        if sym not in chr_map:
            raise UnsupportedMath(f"Toán tử chưa hỗ trợ: {sym}")
        latex_sym = chr_map[sym]
        out = latex_sym
        sub = _e_latex(elem, "sub")
        sup = _e_latex(elem, "sup")
        if sub and _property(elem, "naryPr", "subHide", "0") in {"0", "false", "off"}:
            out += "_{" + sub + "}"
        if sup and _property(elem, "naryPr", "supHide", "0") in {"0", "false", "off"}:
            out += "^{" + sup + "}"
        body = _e_latex(elem, "e")
        if body and body[0].isascii() and body[0].isalpha() and re.search(r"\\[A-Za-z]+$", out):
            out += " "
        out += body
        return out
    if tag == _t("m", "acc"):
        glyph = _property(elem, "accPr", "chr", "ˆ")
        if glyph not in _ACCENTS:
            raise UnsupportedMath(f"Dấu trên công thức chưa hỗ trợ: {glyph!r}")
        return _ACCENTS[glyph] + "{" + _e_latex(elem, "e") + "}"
    if tag == _t("m", "bar"):
        pos = _property(elem, "barPr", "pos", "top")
        if pos not in {"top", "bot"}:
            raise UnsupportedMath(f"Vị trí dấu gạch chưa hỗ trợ: {pos}")
        return (r"\underline" if pos == "bot" else r"\overline") + "{" + _e_latex(elem, "e") + "}"
    if tag == _t("m", "groupChr"):
        glyph, base = _property(elem, "groupChrPr", "chr", "⏟"), _e_latex(elem, "e")
        pos = _property(elem, "groupChrPr", "pos", "bot")
        if pos not in {"top", "bot"}:
            raise UnsupportedMath(f"Vị trí ký hiệu nhóm chưa hỗ trợ: {pos}")
        if glyph in _ARROWS:
            if not base:
                return _ARROWS[glyph]
            return (r"\underset" if pos == "top" else r"\overset") + "{" + base + "}{" + _ARROWS[glyph] + "}"
        if glyph in {"⏟", "⏞", "︸", "︷"}:
            return (r"\overbrace" if pos == "top" else r"\underbrace") + "{" + base + "}"
        if glyph in {"⏜", "⏝"}:
            return (r"\overset" if pos == "top" else r"\underset") + r"{\frown}{" + base + "}"
        raise UnsupportedMath(f"Ký hiệu nhóm chưa hỗ trợ: {glyph!r}")
    if tag == _t("m", "eqArr"):
        return r"\begin{aligned}" + r"\\".join(_children_latex(c) for c in elem.findall(ns.q("m", "e"))) + r"\end{aligned}"
    if tag == _t("m", "m"):
        rows = [" & ".join(_children_latex(c) for c in row.findall(ns.q("m", "e"))) for row in elem.findall(ns.q("m", "mr"))]
        return r"\begin{matrix}" + r"\\".join(rows) + r"\end{matrix}"
    if tag in {_t("m", "limLow"), _t("m", "limUpp")}:
        return _e_latex(elem, "e") + ("_{" if tag == _t("m", "limLow") else "^{") + _e_latex(elem, "lim") + "}"
    if tag == _t("m", "func"):
        function = _e_latex(elem, "fName")
        if function.isascii() and function.isalpha():
            function = r"\operatorname{" + function + "}"
        return function + _e_latex(elem, "e")
    if tag == _t("m", "sPre"):
        return "{}_{" + _e_latex(elem, "sub") + "}^{" + _e_latex(elem, "sup") + "}{" + _e_latex(elem, "e") + "}"
    if tag == _t("m", "oMathPara"):
        parts = [_node(c) for c in selected_children(elem) if c.tag != _t("m", "oMathParaPr")]
        if len(parts) > 1:
            return r"\begin{gathered}" + r"\\".join(parts) + r"\end{gathered}"
        return "".join(parts)
    if tag in _CONTAINERS:
        return _children_latex(elem)
    raise UnsupportedMath(f"Cấu trúc OMML chưa hỗ trợ: {tag}")

def omml_to_latex(elem, *, strict=False):
    try:
        return _node(elem)
    except (ValueError, TypeError, AttributeError, RecursionError) as exc:
        if strict:
            raise UnsupportedMath(str(exc)) from exc
        return None
