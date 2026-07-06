W  = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M  = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
A  = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R  = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
V  = "{urn:schemas-microsoft-com:vml}"
O  = "{urn:schemas-microsoft-com:office:office}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_MAP = {"w": W, "m": M, "a": A, "r": R, "v": V, "o": O, "pr": PR}

def q(prefix: str, tag: str) -> str:
    """q('w','p') -> '{...main}p'"""
    return _MAP[prefix] + tag
