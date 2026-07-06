import json
import os
from . import ns
from .loader import load
from .context import Context
from .runs import render_paragraph
from .tables import render_table


def _paragraph_text(p) -> str:
    return "".join(t.text or "" for t in p.iter(ns.q("w", "t")))


# Đề thi luôn mở đầu bằng một section-heading dạng "PHẦN I. ...".
# Trước heading này, file mẫu có các đoạn "metadata" nội bộ (vd "---NTP",
# "Cho biết: ...") không xuất hiện trong panel Azota — NHƯNG các công thức/
# ảnh nằm trong các đoạn đó vẫn được Azota tính vào bộ đếm placeholder toàn
# cục (bằng chứng: golden bắt đầu ở mathtype_3, tức đã "tiêu" 2 số cho đúng
# 2 công thức nằm trong 2 đoạn mở đầu này). Ta tái tạo hành vi đó: vẫn gọi
# render_paragraph/render_table để bộ đếm tăng đúng, nhưng bỏ dòng ra khỏi
# markup cho tới khi gặp heading "PHẦN".
def clean_docx(path: str):
    doc = load(path)
    ctx = Context(rels=doc.rels, assets=doc.assets)
    lines = []
    started = False
    for child in doc.body:
        if child.tag == ns.q("w", "p"):
            if not started and _paragraph_text(child).strip().startswith("PHẦN"):
                started = True
            rendered = render_paragraph(child, ctx)
            if started:
                lines.append(rendered)
        elif child.tag == ns.q("w", "tbl"):
            rendered = render_table(child, ctx)
            if started:
                lines.append(rendered)
        # w:sectPr… bỏ qua
    markup = "\n".join(lines)
    return markup, ctx


def write_outputs(markup: str, ctx: Context, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    side = os.path.join(out_dir, "sidecar")
    os.makedirs(side, exist_ok=True)
    with open(os.path.join(out_dir, "markup.txt"), "w", encoding="utf-8") as f:
        f.write(markup)
    for fn, data in ctx.written.items():
        with open(os.path.join(side, fn), "wb") as f:
            f.write(data)
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"assets": ctx.manifest, "warnings": ctx.warnings}, f,
                  ensure_ascii=False, indent=2)
