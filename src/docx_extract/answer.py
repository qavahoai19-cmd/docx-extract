import re

_MARKER = re.compile(r"^\s*([A-D])[.)]\s*$")

def is_option_marker(text: str) -> bool:
    return bool(_MARKER.match(text or ""))

def render_marker(text: str, fmt) -> str:
    underline = fmt[3]
    core = text.strip()
    return ("*" + core) if underline else core
