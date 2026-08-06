import posixpath
from dataclasses import dataclass, field
from lxml import etree
from . import ns
from . import mathlatex
from . import mathocr


@dataclass
class Context:
    rels: dict
    assets: dict
    counter: int = 0
    written: dict = field(default_factory=dict)     # filename -> bytes
    manifest: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    latex: dict = field(default_factory=dict)     # oid -> LaTeX (OMML + OCR mathtype)
    ocr_fn: object = None   # Callable[[bytes, str], str | None] | None — tiêm cho test

    def _next(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.counter}"

    def _ext(self, path: str) -> str:
        return posixpath.splitext(path)[1].lstrip(".").lower() or "bin"

    def omml(self, elem) -> str:
        oid = self._next("mathml")
        frag = etree.tostring(elem, encoding="utf-8")
        self.written[f"{oid}.xml"] = frag
        latex = mathlatex.omml_to_latex(elem)
        if latex is None:
            self.warnings.append(f"{oid}: OMML->LaTeX thất bại, giữ placeholder")
        else:
            self.latex[oid] = latex
        self.manifest.append(
            {"id": oid, "type": "mathml", "source": "inline-omml", "latex": latex})
        return f"[!m:${oid}$]"

    def _resolve(self, rid):
        path = self.rels.get(rid)
        if path is None or path not in self.assets:
            return None, None
        return path, self.assets[path]

    def image(self, drawing) -> str:
        oid = self._next("img")
        blip = drawing.find(f".//{ns.q('a', 'blip')}")
        rid = blip.get(ns.q("r", "embed")) if blip is not None else None
        path, data = self._resolve(rid)
        if data is None:
            self.warnings.append(f"{oid}: rId {rid} không giải được")
            self.manifest.append({"id": oid, "type": "img", "source": "missing", "rid": rid})
        else:
            fn = f"{oid}.{self._ext(path)}"
            self.written[fn] = data
            self.manifest.append({"id": oid, "type": "img", "source": path})
        return f"[img:${oid}$]"

    def _ocr_mathtype(self, oid: str, data: bytes, ext: str) -> None:
        """OCR ảnh MathType OLE (WMF/EMF) sang LaTeX -> self.latex[oid].
        Lỗi ở bất kỳ bước nào -> warning, KHÔNG crash, KHÔNG set latex."""
        fn = self.ocr_fn if self.ocr_fn is not None else mathocr.image_to_latex
        try:
            latex = fn(data, ext)
        except Exception as exc:
            self.warnings.append(f"{oid}: OCR MathType lỗi: {exc}")
            return
        if latex:
            self.latex[oid] = latex
        else:
            self.warnings.append(f"{oid}: OCR MathType không trả LaTeX")

    def ole(self, w_object) -> str | None:
        # Spec §4.2: chỉ OLE Equation (Equation.DSMT4 / Equation.3) mới được
        # coi là công thức MathType. w:object cũng có thể chứa các loại OLE
        # khác (bảng Excel nhúng, tài liệu Word nhúng, biểu đồ...) — những
        # thứ đó KHÔNG phải công thức và không được gắn placeholder mathtype
        # (và không được tiêu số của bộ đếm chung).
        ole_obj = w_object.find(f".//{ns.q('o', 'OLEObject')}")
        progid = ole_obj.get("ProgID") if ole_obj is not None else None
        if not progid or "Equation" not in progid:
            self.warnings.append(
                f"w:object bỏ qua: ProgID={progid!r} không phải OLE Equation"
            )
            return None
        oid = self._next("mathtype")
        # render WMF/EMF nằm ở v:imagedata @r:id
        imagedata = w_object.find(f".//{ns.q('v', 'imagedata')}")
        rid = imagedata.get(ns.q("r", "id")) if imagedata is not None else None
        path, data = self._resolve(rid)
        if data is None:
            self.warnings.append(f"{oid}: OLE render rId {rid} không giải được")
            self.manifest.append({"id": oid, "type": "mathtype", "source": "missing", "rid": rid})
        else:
            ext = self._ext(path)
            fn = f"{oid}.{ext}"
            self.written[fn] = data
            self._ocr_mathtype(oid, data, ext)
            self.manifest.append(
                {"id": oid, "type": "mathtype", "source": path, "latex": self.latex.get(oid)}
            )
        return f"[!m:${oid}$]"
