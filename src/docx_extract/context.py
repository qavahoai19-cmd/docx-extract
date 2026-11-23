import posixpath
import os
from time import perf_counter
from dataclasses import dataclass, field
from lxml import etree
from . import ns
from . import mathlatex
from . import mathocr
from . import mathnative


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
    defer_ocr: bool = False
    pending_ocr: list = field(default_factory=list)
    ocr_stats: dict = field(default_factory=dict)
    native_stats: dict = field(default_factory=lambda: dict(native_attempted=0, native_success=0, native_fallback=0, native_s=0.0))
    native_math: bool | None = None
    preserve_formulas: bool = False
    numbering: dict = field(default_factory=dict)
    numbering_counters: dict = field(default_factory=dict)

    def _finish_stats(self):
        defaults = dict(http_requests=0, cache_hits=0, remote_images=0, total_s=0.0,
                        server_prepare_s=0.0, server_infer_s=0.0)
        defaults.update(self.ocr_stats)
        defaults["ocr_total"] = defaults.get("total", 0)
        equations = [item for item in self.manifest if item["type"] == "mathtype"]
        defaults["total"] = len(equations)
        defaults["failures"] = sum(not item.get("latex") and not item.get("preserved") for item in equations)
        if self.preserve_formulas:
            defaults["mode"] = "preserve_formulas"
            defaults["preserved_formulas"] = sum(bool(item.get("preserved")) for item in self.manifest)
        defaults.update(self.native_stats)
        self.ocr_stats = defaults

    def _native_mathtype(self, ole_obj, entry):
        enabled = self.native_math if self.native_math is not None else os.getenv("DOCX_EXTRACT_NATIVE_MATH", "0").lower() not in {"off", "0", "false"}
        if self.preserve_formulas or self.ocr_fn is not None or not enabled:
            return False
        started = perf_counter()
        self.native_stats["native_attempted"] += 1
        try:
            rid = ole_obj.get(ns.q("r", "id"))
            _, data = self._resolve(rid)
            if data is None:
                return False
            latex = mathnative.ole_to_latex(data)
            entry.update(latex=latex, method="mtef-v5")
            self.latex[entry["id"]] = latex
            self.native_stats["native_success"] += 1
            return True
        except Exception as exc:
            entry["native_error"] = str(exc)
            return False
        finally:
            self.native_stats["native_s"] += perf_counter()-started
            self.native_stats["native_fallback"] = self.native_stats["native_attempted"]-self.native_stats["native_success"]

    def resolve_ocr(self, client=None):
        if not self.pending_ocr:
            self._finish_stats()
            return
        jobs = self.pending_ocr
        try:
            if client is None:
                with mathocr.OCRClient() as owned:
                    results = owned.recognize([(oid, data, ext) for oid, data, ext, _ in jobs])
                    self.ocr_stats = dict(owned.stats)
            else:
                results = client.recognize([(oid, data, ext) for oid, data, ext, _ in jobs])
                self.ocr_stats = dict(client.stats)
        except Exception as exc:
            results = {oid: {"latex": None, "error": f"OCR thất bại: {exc}"} for oid, _, _, _ in jobs}
        self.apply_ocr_results(results)

    def apply_ocr_results(self, results):
        jobs, self.pending_ocr = self.pending_ocr, []
        for oid, _, _, entry in jobs:
            result = results.get(oid, {"latex": None, "error": "OCR batch thiếu id"})
            entry["latex"] = result["latex"]
            if result["latex"]:
                self.latex[oid] = result["latex"]
            else:
                self.warnings.append(f"{oid}: {result['error']}")
        self._finish_stats()

    def _next(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.counter}"

    def _ext(self, path: str) -> str:
        return posixpath.splitext(path)[1].lstrip(".").lower() or "bin"

    def omml(self, elem) -> str:
        oid = self._next("mathml")
        frag = etree.tostring(elem, encoding="utf-8")
        self.written[f"{oid}.xml"] = frag
        if self.preserve_formulas:
            self.manifest.append({"id": oid, "type": "mathml", "source": "inline-omml",
                                  "latex": None, "preserved": True, "method": "original-omml"})
            return f"[!m:${oid}$]"
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
        if drawing.tag == ns.q("v", "imagedata"):
            rid = drawing.get(ns.q("r", "id"))
        else:
            blip = drawing if drawing.tag == ns.q("a", "blip") else drawing.find(f".//{ns.q('a', 'blip')}")
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
            entry = {"id": oid, "type": "mathtype", "source": "missing", "rid": rid}
            if not self._native_mathtype(ole_obj, entry):
                self.warnings.append(f"{oid}: OLE render rId {rid} không giải được")
            self.manifest.append(entry)
        else:
            ext = self._ext(path)
            fn = f"{oid}.{ext}"
            self.written[fn] = data
            entry = {"id": oid, "type": "mathtype", "source": path, "latex": None}
            if self.preserve_formulas:
                entry.update(preserved=True, method="original-image")
            elif self._native_mathtype(ole_obj, entry):
                pass
            elif self.defer_ocr:
                self.pending_ocr.append((oid, data, ext, entry))
            else:
                self._ocr_mathtype(oid, data, ext)
                entry["latex"] = self.latex.get(oid)
            self.manifest.append(entry)
        return f"[!m:${oid}$]"
