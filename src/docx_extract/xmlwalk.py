"""Walk visible Word content without rendering both compatibility branches."""

from . import ns


MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_SUPPORTED_NAMESPACES = {
    ns.W[1:-1], ns.M[1:-1], ns.A[1:-1], ns.V[1:-1], ns.O[1:-1],
    "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "http://schemas.microsoft.com/office/drawing/2010/main",
    "http://schemas.microsoft.com/office/word/2010/wordml",
}
_TRANSPARENT = {ns.q("w", name) for name in (
    "sdt", "sdtContent", "customXml", "hyperlink", "smartTag", "ins", "moveTo",
)}


def selected_children(parent):
    if parent.tag != MC + "AlternateContent":
        yield from parent
        return
    for choice in parent.findall(MC + "Choice"):
        requirements = choice.get("Requires", "").split()
        if requirements and all(choice.nsmap.get(prefix) in _SUPPORTED_NAMESPACES
                                for prefix in requirements):
            yield from choice
            return
    fallback = parent.find(MC + "Fallback")
    if fallback is not None:
        yield from fallback
    else:
        # Preserve recoverable content even when no fallback was supplied.
        choice = parent.find(MC + "Choice")
        if choice is not None:
            yield from choice


def content_children(parent):
    for child in selected_children(parent):
        if child.tag in _TRANSPARENT or child.tag == MC + "AlternateContent":
            yield from content_children(child)
        else:
            yield child


def iter_blocks(parent):
    for child in content_children(parent):
        if child.tag in {ns.q("w", "p"), ns.q("w", "tbl")}:
            yield child
