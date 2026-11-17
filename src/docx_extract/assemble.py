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


# Đề thi thường mở đầu bằng một section-heading dạng "PHẦN I. ...", "Nhóm
# I..." hoặc trực tiếp "Câu 1: ...". Trước heading này, một số file mẫu có
# các đoạn "metadata" nội bộ (vd "---NTP", "Cho biết: ...") không xuất hiện
# trong panel Azota — NHƯNG các công thức/ảnh nằm trong các đoạn đó vẫn được
# Azota tính vào bộ đếm placeholder toàn cục (bằng chứng: golden bắt đầu ở
# mathtype_3, tức đã "tiêu" 2 số cho đúng 2 công thức nằm trong 2 đoạn mở
# đầu này). Ta tái tạo hành vi đó: vẫn gọi render_paragraph/render_table cho
# MỌI đoạn để bộ đếm tăng đúng, nhưng chỉ bỏ dòng ra khỏi markup cho tới khi
# gặp anchor nội dung thật đầu tiên (PHẦN/Nhóm/Câu).
#
# Đây là một content-based heuristic có chủ đích bị giới hạn phạm vi: nếu
# KHÔNG file nào trong toàn bộ body khớp anchor (một đề có heading khác hẳn,
# hoặc không có heading), ta KHÔNG được phép âm thầm trả về markup rỗng —
# phải xuất toàn bộ nội dung đã render và cảnh báo, để lỗi hiển thị thay vì
# biến mất (constraint "không bao giờ crash / luôn xuất output có nghĩa").
_ANCHOR_RE = re.compile(r"^(PHẦN|Nhóm|Câu)\b")


def extract_docx(path: str, *, native_math=None):
    """Extract content and collect OCR jobs without contacting a model."""
    started = perf_counter()
    doc = load(path)
    ctx = Context(rels=doc.rels, assets=doc.assets, defer_ocr=True, native_math=native_math)
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
        lines = all_lines
    else:
        lines = all_lines[anchor_idx:]
    markup = "\n".join(lines)
    parse_seconds = perf_counter() - started
    ctx.ocr_stats["parse_s"] = parse_seconds
    return markup, ctx


def clean_docx(path: str, *, ocr_client=None):
    started = perf_counter()
    markup, ctx = extract_docx(path)
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
