import re
from pathlib import Path
from docx_extract import clean_docx

DOCX = r"C:\Users\admin\Downloads\ĐỀ VẬT LÍ LẦN 3_VER 2 (2).docx"
GOLDEN = Path(__file__).parent / "fixtures" / "golden_azota.txt"

def _norm(s):
    # so khớp bỏ qua khác biệt khoảng trắng
    return [re.sub(r"\s+", " ", ln).strip() for ln in s.splitlines() if ln.strip()]

def test_key_anchors_present_in_order():
    markup, _ = clean_docx(DOCX)
    got = "\n".join(_norm(markup))
    for anchor in ["PHẦN I", "Câu 1", "*D. ngưng tụ", "[!b:$[GT]$]",
                   "PHẦN II", "Nhóm I", "[* 0 | 27 | 0 *]", "PHẦN III"]:
        assert anchor.replace("  ", " ") in got, f"thiếu: {anchor}"

def test_report_line_match_ratio():
    markup, _ = clean_docx(DOCX)
    got = set(_norm(markup))
    gold = _norm(GOLDEN.read_text(encoding="utf-8"))
    matched = sum(1 for ln in gold if ln in got)
    ratio = matched / len(gold)
    print(f"\nGolden line match: {matched}/{len(gold)} = {ratio:.1%}")
    # Task 7b: sau khi sửa whitespace-bold (runs.wrap), strip bold label
    # Câu N/a)-d) (answer.is_paragraph_start_label), và layout-table
    # flatten (tables._is_layout_table), tỉ lệ đạt 184/237 = 77.6%.
    # Ngưỡng khoá lại = floor(0.776, 0.05) = 0.75 để không brittle với
    # thay đổi nhỏ trong tương lai, vẫn chứng minh mức khớp đã đạt.
    # Nuance còn lại (đếm placeholder lệch dần, &quot;, whitespace nguồn)
    # xem docs/superpowers/plans/2026-07-06-golden-diff-report.md.
    assert ratio >= 0.75
