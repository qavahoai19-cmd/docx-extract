import posixpath
from dataclasses import dataclass, field
from lxml import etree
from . import ns


@dataclass
class Context:
    rels: dict
    assets: dict
    counter: int = 0
    written: dict = field(default_factory=dict)     # filename -> bytes
    manifest: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def _next(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.counter}"

    def _ext(self, path: str) -> str:
        return posixpath.splitext(path)[1].lstrip(".").lower() or "bin"

    def omml(self, elem) -> str:
        oid = self._next("mathml")
        frag = etree.tostring(elem, encoding="utf-8")
        self.written[f"{oid}.xml"] = frag
        self.manifest.append({"id": oid, "type": "mathml", "source": "inline-omml"})
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

    def ole(self, w_object) -> str:
        oid = self._next("mathtype")
        # render WMF/EMF nằm ở v:imagedata @r:id
        imagedata = w_object.find(f".//{ns.q('v', 'imagedata')}")
        rid = imagedata.get(ns.q("r", "id")) if imagedata is not None else None
        path, data = self._resolve(rid)
        if data is None:
            self.warnings.append(f"{oid}: OLE render rId {rid} không giải được")
            self.manifest.append({"id": oid, "type": "mathtype", "source": "missing", "rid": rid})
        else:
            fn = f"{oid}.{self._ext(path)}"
            self.written[fn] = data
            self.manifest.append({"id": oid, "type": "mathtype", "source": path})
        return f"[!m:${oid}$]"
