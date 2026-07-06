import json
import os
from . import ns
from .loader import load
from .context import Context
from .runs import render_paragraph
from .tables import render_table


def clean_docx(path: str):
    doc = load(path)
    ctx = Context(rels=doc.rels, assets=doc.assets)
    lines = []
    for child in doc.body:
        if child.tag == ns.q("w", "p"):
            lines.append(render_paragraph(child, ctx))
        elif child.tag == ns.q("w", "tbl"):
            lines.append(render_table(child, ctx))
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
