"""Pack existing extraction results into one HTML file that opens offline."""

import base64
import hashlib
import json
import mimetypes
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
CACHE = OUT / ".preview-cache"
TEMPLATE = Path(__file__).with_name("preview-template.html")


def build():
    raster_path = CACHE / "raster-map.json"
    raster = json.loads(raster_path.read_text(encoding="utf-8")) if raster_path.exists() else {}
    pool = {}
    documents = []
    missing = []

    def image_record(path):
        data = path.read_bytes()
        key = hashlib.sha256(data).hexdigest()
        width = height = None
        if path.suffix.lower() in {".wmf", ".emf"}:
            converted = raster.get(key)
            if not converted:
                return None
            data = Path(converted["path"]).read_bytes()
            width, height = converted["width"], converted["height"]
            mime = "image/png"
        else:
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if key not in pool:
            pool[key] = "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
        return {"image": key, "width": width, "height": height}

    candidates = [(OUT, "Kết quả hiện tại", "current")]
    imported = OUT / "word-import-20261116" / "results"
    if imported.exists():
        for markup in sorted(imported.rglob("markup.txt"), key=lambda p: str(p).casefold()):
            folder = markup.parent
            candidates.append((folder, folder.name, "doc-" + hashlib.sha256(str(folder).encode()).hexdigest()[:12]))

    for folder, title, doc_id in candidates:
        if not (folder / "markup.txt").exists() or not (folder / "manifest.json").exists():
            continue
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        files = {}
        sidecar = folder / "sidecar"
        if sidecar.exists():
            for path in sidecar.iterdir():
                if path.is_file():
                    files.setdefault(path.stem, []).append(path)
        assets = {}
        for item in manifest.get("assets", []):
            asset = dict(item)
            oid = item["id"]
            for path in files.get(oid, []):
                if path.suffix.lower() == ".xml" and item.get("type") == "mathml":
                    try:
                        elem = etree.fromstring(path.read_bytes(), etree.XMLParser(resolve_entities=False, no_network=True))
                        etree.cleanup_namespaces(elem)
                        asset["omml"] = etree.tostring(elem, encoding="unicode", with_tail=False)
                    except etree.XMLSyntaxError:
                        missing.append({"document": title, "asset": oid, "reason": "invalid math XML"})
                elif path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".wmf", ".emf"}:
                    record = image_record(path)
                    if record:
                        asset.update(record)
                    else:
                        missing.append({"document": title, "asset": oid, "reason": "vector image not rendered"})
            assets[oid] = asset
        documents.append({
            "id": doc_id,
            "title": title,
            "path": folder.relative_to(ROOT).as_posix(),
            "markup": (folder / "markup.txt").read_text(encoding="utf-8"),
            "assets": assets,
            "warnings": manifest.get("warnings", []),
        })

    payload = json.dumps({"documents": documents, "images": pool}, ensure_ascii=False, separators=(",", ":"))
    # Embedded data must not be able to terminate its script element.
    payload = payload.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    page = TEMPLATE.read_text(encoding="utf-8").replace("__PREVIEW_DATA__", payload)
    destination = OUT / "preview.html"
    destination.write_text(page, encoding="utf-8")
    report = {"documents": len(documents), "unique_images": len(pool), "bytes": destination.stat().st_size, "unrendered_assets": missing}
    (CACHE / "build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "unrendered_assets"}, ensure_ascii=True))
    print(f"Unrendered assets: {len(missing)}")
    print("Open out/preview.html in a browser.")


if __name__ == "__main__":
    build()
