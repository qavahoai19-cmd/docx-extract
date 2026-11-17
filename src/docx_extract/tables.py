from . import ns
from .runs import render_paragraph
from .xmlwalk import content_children, iter_blocks

_BORDER_SIDES = ("top", "left", "bottom", "right", "insideH", "insideV")
_NONE_VALS = {"none", "nil"}


def _cell_text(tc, ctx):
    parts = [render_paragraph(block, ctx) if block.tag == ns.q("w", "p")
             else render_table(block, ctx) for block in iter_blocks(tc)]
    return " ".join(s.strip() for s in parts if s.strip())


def _is_layout_table(tbl) -> bool:
    # Bảng dùng để dàn ảnh cạnh nhau (không phải bảng dữ liệu thật) được
    # Azota "làm phẳng" — không bọc [* | *]. Phân biệt bằng bằng chứng cụ
    # thể trong file mẫu: bảng layout khai báo <w:tblBorders> với TẤT CẢ
    # các cạnh val="none" (không viền), trong khi bảng dữ liệu thật (k/t/áp
    # kế) không override tblBorders (dùng viền mặc định của table style).
    tblPr = tbl.find(ns.q("w", "tblPr"))
    if tblPr is None:
        return False
    borders = tblPr.find(ns.q("w", "tblBorders"))
    if borders is None:
        return False
    for side in _BORDER_SIDES:
        el = borders.find(ns.q("w", side))
        if el is None or el.get(ns.q("w", "val")) not in _NONE_VALS:
            return False
    return True


def render_table(tbl, ctx) -> str:
    layout = _is_layout_table(tbl)
    lines = []
    for tr in (child for child in content_children(tbl) if child.tag == ns.q("w", "tr")):
        cells = [_cell_text(tc, ctx) for tc in content_children(tr) if tc.tag == ns.q("w", "tc")]
        if not any(cells):
            # Hàng mà mọi cell đều rỗng không mang nội dung gì — bỏ qua để
            # tránh sinh dòng trắng rác (layout) hoặc "[*  *]" rác (bảng dữ
            # liệu) giữa markup.
            continue
        if layout:
            lines.append("      ".join(c for c in cells if c))
        else:
            lines.append("[* " + " | ".join(cells) + " *]")
    return "\n".join(lines)
