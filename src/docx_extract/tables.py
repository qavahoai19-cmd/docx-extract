from . import ns
from .runs import render_paragraph

def _cell_text(tc, ctx):
    parts = [render_paragraph(p, ctx) for p in tc.findall(ns.q("w", "p"))]
    return " ".join(s.strip() for s in parts if s.strip())

def render_table(tbl, ctx) -> str:
    lines = []
    for tr in tbl.findall(ns.q("w", "tr")):
        cells = [_cell_text(tc, ctx) for tc in tr.findall(ns.q("w", "tc"))]
        lines.append("[* " + " | ".join(cells) + " *]")
    return "\n".join(lines)
