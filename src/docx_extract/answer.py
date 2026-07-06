import re

_MARKER = re.compile(r"^(\s*)([A-D][.)])(\s*)$")

def is_option_marker(text: str) -> bool:
    return bool(_MARKER.match(text or ""))

# Azota strip bold khỏi label số câu ("Câu 1:", "Câu 2.") và label ý con
# ("a)".."d)") dù chúng được tô đậm (w:b) trong docx — NHƯNG vẫn giữ bold
# cho "Nhóm I.", "PHẦN I...", "[GT]", "Chọn X.". Hai regex dưới đây match
# TOÀN BỘ nội dung segment (không chỉ prefix) vì bằng chứng thực tế trong
# file mẫu cho thấy label luôn là segment độc lập (coalesce không gộp thêm
# nội dung câu hỏi vào cùng format với label) — không match "Nhóm"/"PHẦN".
_QUESTION_LABEL = re.compile(r"^\s*Câu\s+\d+\s*[.:]\s*$")
_SUBITEM_LABEL = re.compile(r"^\s*[a-d]\)\s*$")

def is_paragraph_start_label(text: str) -> bool:
    t = text or ""
    return bool(_QUESTION_LABEL.match(t) or _SUBITEM_LABEL.match(t))

def render_marker(text: str, fmt) -> str:
    # Marker có thể bị gộp (coalesce) cùng khoảng trắng theo sau nếu chúng
    # chung định dạng (vd "B." + " " cùng bold -> segment "B. "). Giữ
    # nguyên khoảng trắng đuôi đó — chỉ .strip() sẽ nuốt mất dấu cách cần
    # thiết trước nội dung kế tiếp (công thức/chữ tiếp theo).
    m = _MARKER.match(text or "")
    if not m:
        return text
    _lead, core, trail = m.groups()
    underline = fmt[3]
    return (("*" + core) if underline else core) + trail
