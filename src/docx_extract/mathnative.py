"""Read supported MathType MTEF v5 directly; reject incomplete conversions.

Binary layout: Design Science's published MTEF v5 specification, mirrored at
https://rtf2latex2e.sourceforge.net/MTEF5.html . Unknown structures are errors,
so callers can use image OCR instead of silently losing part of an equation.
"""
from dataclasses import dataclass, field
import io
import struct

import olefile


class UnsupportedMath(ValueError):
    pass


@dataclass
class Node:
    kind: int
    data: tuple = ()
    children: list = field(default_factory=list)


class Reader:
    def __init__(self, data):
        self.data, self.pos, self.count = data, 0, 0
        self.styles = {}
        self.fonts = []
        self.custom_styles = 0

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise UnsupportedMath("Truncated MTEF")
        value = self.data[self.pos:self.pos+n]
        self.pos += n
        return value

    def byte(self):
        return self.take(1)[0]

    def uint16(self):
        return int.from_bytes(self.take(2), "little")

    def uint(self):
        value = self.byte()
        return self.uint16() if value == 255 else value

    def string(self):
        end = self.data.find(b"\0", self.pos, self.pos+1024)
        if end < 0:
            raise UnsupportedMath("Unterminated MTEF string")
        value = self.take(end-self.pos)
        self.take(1)
        return value

    def nudge(self, options):
        if options & 8:
            if self.take(2) == b"\x80\x80":
                self.take(4)

    def dimensions(self):
        count, pending = self.byte(), None
        def nibble():
            nonlocal pending
            if pending is not None:
                value, pending = pending, None
                return value
            value = self.byte()
            pending = value & 15
            return value >> 4
        for _ in range(count):
            if nibble() > 4:
                raise UnsupportedMath("Unknown MTEF dimension unit")
            for _ in range(128):
                value = nibble()
                if value == 15:
                    break
                if value > 11:
                    raise UnsupportedMath("Invalid MTEF dimension")
            else:
                raise UnsupportedMath("Unterminated MTEF dimension")
        if pending not in (None, 0):
            raise UnsupportedMath("Invalid dimension padding")

    def objects(self, depth=0):
        if depth > 64:
            raise UnsupportedMath("MTEF nesting limit")
        result = []
        while True:
            tag = self.byte()
            self.count += 1
            if self.count > 20000:
                raise UnsupportedMath("MTEF record limit")
            if tag == 0:
                return result
            node = self.record(tag, depth)
            if node is not None:
                result.append(node)

    def record(self, tag, depth):
        if tag in range(10, 15):
            return None  # Logical font size, not equation content.
        if tag in (1, 2, 3, 4, 5, 6):
            options = self.byte()
            self.nudge(options)
            if tag == 1:
                if options & ~15:
                    raise UnsupportedMath("Unknown LINE options")
                if options & 4:
                    self.take(2)
                if options & 2:
                    raise UnsupportedMath("Embedded ruler")
                return Node(tag, (), [] if options & 1 else self.objects(depth+1))
            if tag == 2:
                if options & ~63 or options & 32 or options & 20 == 20:
                    raise UnsupportedMath("Character without unambiguous MTCode")
                typeface, code = self.byte()-128, self.uint16()
                if options & 4:
                    self.take(1)
                if options & 16:
                    self.take(2)
                embell = self.objects(depth+1) if options & 1 else []
                if any(n.kind != 6 for n in embell):
                    raise UnsupportedMath("Unexpected character embellishment")
                return Node(tag, (code, typeface), embell)
            if tag == 3:
                if options & ~8:
                    raise UnsupportedMath("Unknown template options")
                selector, variation = self.byte(), self.byte()
                if variation & 128:
                    variation = (variation & 127) | (self.byte() << 8)
                specific = self.byte()
                return Node(tag, (selector, variation, specific), self.objects(depth+1))
            if tag == 4:
                if options & ~10 or options & 2:
                    raise UnsupportedMath("Pile with unsupported ruler/options")
                align, valign = self.byte(), self.byte()
                return Node(tag, (align, valign), self.objects(depth+1))
            if tag == 5:
                if options & ~8:
                    raise UnsupportedMath("Unknown matrix options")
                self.take(3)  # Vertical/horizontal justification.
                rows, cols = self.byte(), self.byte()
                if not rows or not cols or rows*cols > 4096:
                    raise UnsupportedMath("Invalid matrix dimensions")
                partitions = self.take((rows+4)//4 + (cols+4)//4)
                if any(partitions):
                    raise UnsupportedMath("Matrix partition lines")
                return Node(tag, (rows, cols), self.objects(depth+1))
            if options & ~8:
                raise UnsupportedMath("Unknown embellishment options")
            return Node(tag, (self.byte(),))
        if tag == 7:
            self.take(self.byte()*3)
        elif tag == 8:
            font, style = self.uint(), self.byte()
            self.custom_styles += 1
            if 0 < font <= len(self.fonts) and style & ~3 == 0:
                if self.fonts[font-1].lower() in {b"times new roman",b"times",b"arial",b"calibri",b"cambria",b"courier new"}:
                    self.styles[-self.custom_styles] = style | 256
        elif tag == 9:
            size = self.byte()
            self.take(2 if size == 101 else 3 if size == 100 else 1)
        elif tag == 15:
            self.uint()
        elif tag == 16:
            options = self.byte()
            if options & ~5:
                raise UnsupportedMath("Unknown color options")
            self.take(8 if options & 1 else 6)
            if options & 4:
                self.string()
        elif tag == 17:
            self.uint(); self.fonts.append(self.string())
        elif tag == 18:
            if self.byte() != 0:
                raise UnsupportedMath("Unknown equation preferences")
            self.dimensions(); self.dimensions()
            for index in range(1, self.byte()+1):
                font = self.uint()
                self.styles[index] = self.byte() if font else 0
        elif tag == 19:
            self.string()
        elif tag == 102:
            # MathType's length-delimited MT_COMMENT metadata record.
            self.take(self.uint())
        else:
            raise UnsupportedMath(f"Unknown MTEF record {tag}")
        return None


_CHAR = dict(zip("αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΥΦΨΩ",
    ("\\"+s+" " for s in "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi pi rho sigma tau upsilon varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega".split())))
_CHAR.update({"−":"-", "⋅":r"\cdot ", "×":r"\times ", "÷":r"\div ",
    "≤":r"\leq ", "≥":r"\geq ", "≠":r"\ne ", "≈":r"\approx ", "≃":r"\simeq ",
    "∞":r"\infty ", "∈":r"\in ", "∉":r"\notin ", "∀":r"\forall ", "∃":r"\exists ",
    "→":r"\rightarrow ", "←":r"\leftarrow ", "⇒":r"\Rightarrow ", "⇔":r"\Leftrightarrow ",
    "↑":r"\uparrow ", "↓":r"\downarrow ", "ℝ":r"\mathbb{R}", "∘":r"\circ ",
    "ϕ":r"\phi ", "∂":r"\partial ", "∑":r"\sum ", "∏":r"\prod ", "∫":r"\int ",
    "±":r"\pm ", "∓":r"\mp ", "∪":r"\cup ", "∩":r"\cap ", "∅":r"\varnothing ",
    "\xa0":r"\,", "\uef02":r"\,", "\uef04":r"\;", "\uef07":r"\,"})
_ESCAPE = {"{":r"\{", "}":r"\}", "_":r"\_", "%":r"\%", "#":r"\#", "&":r"\&", "$":r"\$", "\\":r"\backslash "}
_ACCENTS = {2:r"\dot", 3:r"\ddot", 4:r"\dddot", 8:r"\tilde", 9:r"\hat",
            11:r"\vec", 12:r"\overleftarrow", 13:r"\overleftrightarrow", 17:r"\overline"}
_FENCES = {ord(k):v for k,v in {"(":"(", ")":")", "[":"[", "]":"]", "{":r"\{", "}":r"\}",
    "|":"|", "‖":r"\Vert", "⌊":r"\lfloor", "⌋":r"\rfloor", "⌈":r"\lceil", "⌉":r"\rceil",
    "〈":r"\langle", "〉":r"\rangle", "⟨":r"\langle", "⟩":r"\rangle"}.items()}


def _character(node, styles):
    code, face = node.data
    char = chr(code)
    if char in _CHAR:
        value = _CHAR[char]
    elif 32 <= code < 127 and char not in "^~":
        value = _ESCAPE.get(char, char)
    else:
        raise UnsupportedMath(f"Unsupported MTCode U+{code:04X}")
    custom = face < 0 and bool(styles.get(face, 0) & 256)
    if face not in (*range(1,13),24) and not custom:
        raise UnsupportedMath(f"Unsupported custom typeface {face}")
    if face in (1, 2) or (custom and not styles[face] & 2):
        value = r"\mathrm{" + value + "}"
    if face == 7 or styles.get(face, 0) & 1:
        value = r"\boldsymbol{" + value + "}"
    for embell in node.children:
        code = embell.data[0]
        if code in (5, 6, 18):
            value = "{"+value+"}" + {5:"'", 6:"''", 18:"'''"}[code]
        elif code in _ACCENTS:
            value = _ACCENTS[code] + "{" + value + "}"
        else:
            raise UnsupportedMath(f"Unsupported embellishment {code}")
    return value


def _sequence(nodes, styles):
    parts = []
    for node in nodes:
        if node.kind == 3 and node.data[0] in (27, 28, 29):
            selector, variation, _ = node.data
            if variation & ~1 or any(n.kind != 1 for n in node.children):
                raise UnsupportedMath("Unsupported script variation")
            slots = [_sequence(n.children, styles) for n in node.children]
            if len(slots) != 2:
                raise UnsupportedMath("Unexpected number of script slots")
            sub, sup = slots
            if (selector == 27 and sup) or (selector == 28 and sub):
                raise UnsupportedMath("Script slot/selector mismatch")
            suffix = ("_{"+sub+"}" if sub else "") + ("^{"+sup+"}" if sup else "")
            if not suffix:
                raise UnsupportedMath("Empty script")
            base = "" if variation & 1 else parts.pop() if parts else ""
            parts.append("{"+base+"}"+suffix)
        else:
            parts.append(_render(node, styles))
    return "".join(parts)


def _render(node, styles):
    if node.kind == 1:
        return _sequence(node.children, styles)
    if node.kind == 2:
        return _character(node, styles)
    if node.kind == 4:
        if any(n.kind != 1 for n in node.children):
            raise UnsupportedMath("Unexpected pile content")
        align = {1:"l", 2:"c", 3:"r"}.get(node.data[0])
        if align is None:
            raise UnsupportedMath("Unsupported pile alignment")
        return r"\begin{array}{"+align+"}"+r"\\".join(_render(n, styles) for n in node.children)+r"\end{array}"
    if node.kind == 5:
        rows, cols = node.data
        if len(node.children) != rows*cols or any(n.kind != 1 for n in node.children):
            raise UnsupportedMath("Matrix cell count mismatch")
        values = [_render(n, styles) for n in node.children]
        return r"\begin{matrix}"+r"\\".join("&".join(values[i:i+cols]) for i in range(0,len(values),cols))+r"\end{matrix}"
    if node.kind != 3:
        raise UnsupportedMath("Unexpected structural node")
    selector, variation, specific = node.data
    if specific not in ((0,1,2) if selector <= 9 else (0,1) if selector == 15 else (0,)):
        raise UnsupportedMath("Unknown template-specific options")
    slots = [n for n in node.children if n.kind == 1]
    decorations = [n for n in node.children if n.kind != 1]
    if any(n.kind != 2 or n.children for n in decorations):
        raise UnsupportedMath("Unexpected template decoration")
    values = [_render(n, styles) for n in slots]
    if selector <= 7:
        if variation & ~3 or len(values) != 1 or len(decorations) != bool(variation&1)+bool(variation&2):
            raise UnsupportedMath("Unsupported fence structure")
        try:
            glyphs = iter(_FENCES[n.data[0]] for n in decorations)
            left = next(glyphs) if variation&1 else "."
            right = next(glyphs) if variation&2 else "."
        except KeyError as exc:
            raise UnsupportedMath("Unsupported fence glyph") from exc
        return r"\left"+left+" "+values[0]+r"\right"+right
    if selector == 10:
        if variation not in (0,1) or decorations or len(values) not in (1,2):
            raise UnsupportedMath("Unsupported root structure")
        if variation == 0 and len(values) == 2 and values[1]:
            raise UnsupportedMath("Unexpected square root index")
        if variation == 1 and (len(values) != 2 or not values[1]):
            raise UnsupportedMath("Missing root index")
        return r"\sqrt"+("["+values[1]+"]" if variation else "")+"{"+values[0]+"}"
    if selector == 11:
        if variation & ~7 or decorations or len(values) != 2:
            raise UnsupportedMath("Unsupported fraction structure")
        a,b = values
        # Preserve numerator/denominator grouping even for a slanted bar.
        return r"\frac{"+a+"}{"+b+"}"
    if selector in (12,13):
        if variation & ~1 or decorations or len(values) != 1:
            raise UnsupportedMath("Unsupported bar structure")
        command = r"\underline" if selector == 12 else r"\overline"
        value = command+"{"+values[0]+"}"
        return command+"{"+value+"}" if variation&1 else value
    if selector in (31,32,33):
        if len(values) != 1 or len(decorations) != 1:
            raise UnsupportedMath("Unsupported accent structure")
        if selector == 31:
            if variation not in (1,2,3):
                raise UnsupportedMath("Unsupported vector variation")
            command = {1:r"\overleftarrow",2:r"\overrightarrow",3:r"\overleftrightarrow"}[variation]
            allowed = {1:{0x20D6,0x2190},2:{0x20D7,0x2192},3:{0x20E1,0x2194}}[variation]
        else:
            if variation:
                raise UnsupportedMath("Unsupported accent variation")
            command = r"\widetilde" if selector == 32 else r"\widehat"
            allowed = {0x303} if selector == 32 else {0x302}
        if decorations[0].data[0] not in allowed:
            raise UnsupportedMath("Accent glyph/variation mismatch")
        return command+"{"+values[0]+"}"
    if selector in range(15,23):
        operators = {0x222B:r"\int",0x222C:r"\iint",0x222D:r"\iiint",0x222E:r"\oint",
                     0x2211:r"\sum",0x220F:r"\prod",0x2210:r"\coprod",0x22C3:r"\bigcup",0x22C2:r"\bigcap"}
        if len(values) != 3 or len(decorations) != 1 or decorations[0].data[0] not in operators:
            raise UnsupportedMath("Unsupported large operator structure")
        body, upper, lower = values
        return operators[decorations[0].data[0]]+("_{"+lower+"}" if lower else "")+("^{"+upper+"}" if upper else "")+" "+body
    raise UnsupportedMath(f"Unsupported template {selector}/{variation}")


def mtef_to_latex(data):
    reader = Reader(data)
    if reader.byte() != 5:
        raise UnsupportedMath("Only MTEF v5 is supported")
    reader.take(4)
    reader.string()
    if reader.byte() & ~1:
        raise UnsupportedMath("Unknown equation options")
    nodes = reader.objects()
    if any(reader.take(len(data)-reader.pos)):
        raise UnsupportedMath("Unconsumed MTEF content")
    result = _sequence(nodes, reader.styles).strip()
    if not result:
        raise UnsupportedMath("Empty MTEF equation")
    return result


def ole_to_latex(data):
    if len(data) > 2*1024*1024:
        raise UnsupportedMath("OLE equation too large")
    with olefile.OleFileIO(io.BytesIO(data)) as ole:
        if not ole.exists("Equation Native"):
            raise UnsupportedMath("No Equation Native stream")
        native = ole.openstream("Equation Native").read()
    if len(native) < 28:
        raise UnsupportedMath("Truncated Equation Native header")
    header_size, = struct.unpack_from("<H", native)
    object_size, = struct.unpack_from("<I", native, 8)
    if header_size != 28 or not 0 < object_size <= len(native)-header_size:
        raise UnsupportedMath("Invalid Equation Native length")
    return mtef_to_latex(native[header_size:header_size+object_size])
