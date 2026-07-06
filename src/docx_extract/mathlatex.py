from . import ns

def _t(prefix, tag):
    return ns.q(prefix, tag)

def _children_latex(elem) -> str:
    return "".join(_node(c) for c in elem)

def _e_latex(parent, child_tag) -> str:
    """LaTeX của con <m:child_tag> (vd m:num, m:e) — rỗng nếu vắng."""
    child = parent.find(ns.q("m", child_tag))
    return _children_latex(child) if child is not None else ""

def _node(elem) -> str:
    tag = elem.tag
    if tag == _t("m", "r"):
        txt = elem.find(ns.q("m", "t"))
        return (txt.text or "") if txt is not None else ""
    if tag == _t("m", "t"):
        return elem.text or ""
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
        if deg_txt:
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
        inner = "".join(_children_latex(c)
                         for c in elem.findall(ns.q("m", "e")))
        return r"\left" + beg + inner + r"\right" + end
    if tag == _t("m", "nary"):
        # tích phân/tổng: ký hiệu ở naryPr>chr (mặc định ∫)
        chr_map = {"∑": r"\sum", "∏": r"\prod", "∫": r"\int"}
        sym = "∫"
        npr = elem.find(ns.q("m", "naryPr"))
        if npr is not None:
            c = npr.find(ns.q("m", "chr"))
            if c is not None:
                sym = c.get(ns.q("m", "val"), sym)
        latex_sym = chr_map.get(sym, sym)
        out = latex_sym
        sub = _e_latex(elem, "sub")
        sup = _e_latex(elem, "sup")
        if sub:
            out += "_{" + sub + "}"
        if sup:
            out += "^{" + sup + "}"
        out += _e_latex(elem, "e")
        return out
    if tag == _t("m", "acc"):
        return r"\hat{" + _e_latex(elem, "e") + "}"
    # bao (oMath, oMathPara, e, num, den...) hoặc tag chưa xử lý -> duyệt con
    return _children_latex(elem)

def omml_to_latex(elem):
    try:
        return _node(elem)
    except Exception:
        return None
