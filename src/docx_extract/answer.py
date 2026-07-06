import re

_MARKER = re.compile(r"^(\s*)([A-D][.)])(\s*)$")

def is_option_marker(text: str) -> bool:
    return bool(_MARKER.match(text or ""))

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
