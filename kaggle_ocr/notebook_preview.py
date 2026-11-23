"""Self-contained result viewer for the OCR notebook; never runs OCR."""
import base64
import hashlib
import html
import io
import json
import mimetypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from lxml import etree
from PIL import Image
from docx_extract.raster import prepare_image


def _vector_images(vectors, cache):
    cache.mkdir(parents=True, exist_ok=True)
    ready, errors, pending = {}, {}, []
    for key, (data, ext) in vectors.items():
        target = cache / (key + ".png")
        if target.is_file():
            ready[key] = target.read_bytes()
            continue
        png, kind = prepare_image(data, ext)
        if kind == "png":
            ready[key] = png
            target.write_bytes(png)
        else:
            pending.append((key, data, ext))
    if pending and not shutil.which("soffice"):
        errors.update({key: "Cần LibreOffice để xem ảnh vector; tệp gốc vẫn được giữ." for key, _, _ in pending})
        return ready, errors
    for offset in range(0, len(pending), 32):
        with tempfile.TemporaryDirectory(prefix="docx-result-preview-") as tmp:
            folder = Path(tmp)
            batch = pending[offset:offset + 32]
            sources = []
            for index, (_, data, ext) in enumerate(batch):
                path = folder / f"image_{index}.{ext}"
                path.write_bytes(data)
                sources.append(str(path))
            try:
                subprocess.run(["soffice", "-env:UserInstallation=" + (folder / "profile").as_uri(),
                    "--headless", "--norestore", "--convert-to", "png", "--outdir", str(folder), *sources],
                    capture_output=True, timeout=90, check=False)
                for index, (key, _, _) in enumerate(batch):
                    try:
                        data = (folder / f"image_{index}.png").read_bytes()
                        with Image.open(io.BytesIO(data)) as image:
                            image.verify()
                        ready[key] = data
                        (cache / (key + ".png")).write_bytes(data)
                    except Exception as exc:
                        errors[key] = f"Không chuyển được ảnh vector: {exc}"
            except (OSError, subprocess.SubprocessError) as exc:
                errors.update({key: str(exc) for key, _, _ in batch})
    return ready, errors


def result_page(archive, row, work_root):
    """Render one completed result using original OMML and original images."""
    root = Path(work_root)
    if row.get("status") == "error":
        return "<h2>Không đọc được đề</h2><p>" + html.escape(row.get("error", "Lỗi không xác định")) + "</p>", []
    prefix = row["output"] + "/"
    warnings, vectors, images, assets = [], {}, {}, {}
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read(prefix + "manifest.json"))
        warnings.extend(manifest.get("warnings", []))
        files = {}
        for name in bundle.namelist():
            if name.startswith(prefix + "sidecar/") and not name.endswith("/"):
                files.setdefault(Path(name).stem, []).append(name)
        for entry in manifest.get("assets", []):
            for name in files.get(entry["id"], []):
                ext = Path(name).suffix.lower().lstrip(".")
                if ext in {"wmf", "emf"}:
                    data = bundle.read(name)
                    vectors.setdefault(hashlib.sha256(data).hexdigest(), (data, ext))
        converted, errors = _vector_images(vectors, root / "cache" / "preview-v1") if vectors else ({}, {})
        for entry in manifest.get("assets", []):
            asset = dict(entry)
            for name in files.get(entry["id"], []):
                ext, data = Path(name).suffix.lower(), bundle.read(name)
                if ext == ".xml" and entry["type"] == "mathml":
                    try:
                        xml = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
                        etree.cleanup_namespaces(xml)
                        asset["omml"] = etree.tostring(xml, encoding="unicode", with_tail=False)
                    except etree.XMLSyntaxError:
                        warnings.append(f"{entry['id']}: XML công thức không hợp lệ")
                elif ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".wmf", ".emf"}:
                    key = hashlib.sha256(data).hexdigest()
                    mime = mimetypes.guess_type(name)[0] or "image/png"
                    if ext in {".wmf", ".emf"}:
                        if key not in converted:
                            warnings.append(f"{entry['id']}: {errors.get(key, 'Không có bản xem ảnh vector')}")
                            asset["download"] = "data:application/octet-stream;base64," + base64.b64encode(data).decode("ascii")
                            continue
                        data, mime = converted[key], "image/png"
                    images[key] = "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
                    asset["image"] = key
                    try:
                        with Image.open(io.BytesIO(data)) as image:
                            asset.update(width=image.width, height=image.height)
                    except Exception:
                        warnings.append(f"{entry['id']}: không kiểm tra được ảnh")
            assets[entry["id"]] = asset
        payload = {"documents": [{"id": "result", "title": row["file"], "path": "",
            "markup": bundle.read(prefix + "markup.txt").decode("utf-8"), "assets": assets,
            "warnings": warnings}], "images": images}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    page = (root / "scripts" / "preview-template.html").read_text(encoding="utf-8")
    return page.replace("__PREVIEW_DATA__", encoded), warnings


def result_viewer(archive, rows, work_root):
    import ipywidgets as widgets
    chooser = widgets.Dropdown(options=[(f"{i}. {row['file']}", i - 1) for i, row in enumerate(rows, 1)],
                               description="Xem đề:", layout=widgets.Layout(width="100%"))
    status, frame = widgets.HTML(), widgets.HTML()
    view = widgets.VBox([widgets.HTML("<h3>Kết quả đọc đề — xem ngay tại đây</h3>"), chooser, status, frame])
    def render(_=None):
        frame.value = ""
        if chooser.value is None:
            status.value = "Không có kết quả để xem."
            return
        row = rows[chooser.value]
        status.value = "Đang dựng bản xem… (không chạy lại OCR)"
        try:
            page, warnings = result_page(archive, row, work_root)
            frame.value = ('<iframe title="Kết quả đọc đề" sandbox="allow-scripts allow-downloads allow-modals" '
                'style="width:100%;height:950px;border:1px solid #ddd;background:white" srcdoc="'
                + html.escape(page, quote=True) + '"></iframe>')
            status.value = (f"{len(warnings)} cảnh báo — xem chi tiết trong bản xem. " if warnings else "") + "Word Equation hiển thị từ XML gốc; ảnh công thức giữ bản gốc. LaTeX OCR có thể cần đối chiếu."
        except Exception as exc:
            status.value = "Chưa dựng được bản xem: " + html.escape(str(exc))
    chooser.observe(render, names="value")
    render()
    return {"view": view, "chooser": chooser, "frame": frame, "status": status}
