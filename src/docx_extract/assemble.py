import json
import os
import re
from time import perf_counter
from . import ns
from .loader import load
from .context import Context
from .runs import render_paragraph
from .tables import render_table
from .xmlwalk import iter_blocks


def _paragraph_text(p) -> str:
    return "".join(t.text or "" for t in p.iter(ns.q("w", "t")))


# Headings are diagnostic only. Material before the first question can be
# essential reading passages, constants, diagrams or shared data tables.
_ANCHOR_RE = re.compile(r"^(PHẦN|Nhóm|Câu|Question)\b", re.IGNORECASE)


def extract_docx(path: str, *, native_math=None, preserve_formulas=False):
    """Extract content and collect OCR jobs without contacting a model."""
    started = perf_counter()
    doc = load(path, preserve_numbering=True)
    ctx = Context(rels=doc.rels, assets=doc.assets, defer_ocr=True, native_math=native_math,
                  preserve_formulas=preserve_formulas, numbering=doc.numbering)
    all_lines = []
    anchor_idx = None
    for child in iter_blocks(doc.body):
        if child.tag == ns.q("w", "p"):
            if anchor_idx is None and _ANCHOR_RE.match(_paragraph_text(child).strip()):
                anchor_idx = len(all_lines)
            rendered = render_paragraph(child, ctx)
            all_lines.append(rendered)
        elif child.tag == ns.q("w", "tbl"):
            rendered = render_table(child, ctx)
            all_lines.append(rendered)
        # w:sectPr… bỏ qua
    if anchor_idx is None:
        ctx.warnings.append(
            "no PHẦN/Nhóm/Câu anchor found — emitting full body"
        )
    markup = "\n".join(all_lines)
    parse_seconds = perf_counter() - started
    ctx.ocr_stats["parse_s"] = parse_seconds
    return markup, ctx


def clean_docx(path: str, *, ocr_client=None, preserve_formulas=False):
    started = perf_counter()
    markup, ctx = extract_docx(path, preserve_formulas=preserve_formulas)
    parse_seconds = ctx.ocr_stats["parse_s"]
    ctx.resolve_ocr(ocr_client)
    ctx.ocr_stats["parse_s"] = parse_seconds
    ctx.ocr_stats["document_s"] = perf_counter() - started
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
        json.dump({"assets": ctx.manifest, "warnings": ctx.warnings, "ocr": ctx.ocr_stats}, f,
                  ensure_ascii=False, indent=2)
