"""Recover DOCX image positions, rasterize vectors and plan image OCR.

No OCR model or legacy DOCX reader is imported here. Native OMML remains for
Pandoc; image previews (including MathType/VML) go to the same DeepSeek worker.
"""
import hashlib
from copy import deepcopy
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit
from uuid import uuid4
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, ImageOps


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_V = "urn:schemas-microsoft-com:vml"
_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_IMAGE_MD = re.compile(r"!\[[^\]]*\]\(([^)]+)\)(?:\{[^}]*\})?")
_VECTORS = {".wmf", ".emf", ".svg"}


def _length_mm(value):
    match = re.fullmatch(r"\s*([\d.]+)\s*(pt|mm|cm|in|px)\s*", value or "", re.IGNORECASE)
    if not match:
        return None
    return float(match[1]) * {"pt": 25.4 / 72, "mm": 1, "cm": 10, "in": 25.4, "px": 25.4 / 96}[match[2].lower()]


def image_geometry(node, parents):
    """Record display geometry separately from raster size used by OCR."""
    ancestors = []
    current = node
    while current is not None:
        ancestors.append(current)
        current = parents.get(current)
    result = dict(width_mm=None, height_mm=None, inline=True, crop={}, baseline_shift_pt=0)
    drawing = next((item for item in ancestors if item.tag == "{" + _W + "}drawing"), None)
    if drawing is not None:
        extent = drawing.find(".//{" + _WP + "}extent")
        if extent is None:
            extent = drawing.find(".//{" + _A + "}ext")
        if extent is not None:
            try:
                result.update(width_mm=float(extent.get("cx")) / 36000,
                              height_mm=float(extent.get("cy")) / 36000)
            except (ValueError, TypeError):
                pass
        result["inline"] = drawing.find(".//{" + _WP + "}anchor") is None
        rectangle = drawing.find(".//{" + _A + "}srcRect")
        if rectangle is not None:
            for side in ("l", "r", "t", "b"):
                try:
                    result["crop"][side] = max(0, min(0.99, float(rectangle.get(side, "0")) / 100000))
                except ValueError:
                    pass
    shape = next((item for item in ancestors if item.tag == "{" + _V + "}shape"), None)
    if shape is not None:
        styles = dict(part.split(":", 1) for part in shape.get("style", "").split(";") if ":" in part)
        styles = {key.strip().lower(): value.strip() for key, value in styles.items()}
        result["width_mm"] = _length_mm(styles.get("width")) or result["width_mm"]
        result["height_mm"] = _length_mm(styles.get("height")) or result["height_mm"]
        if styles.get("position") == "absolute":
            result["inline"] = False
    run = next((item for item in ancestors if item.tag == "{" + _W + "}r"), None)
    if run is not None:
        position = run.find("{" + _W + "}rPr/{" + _W + "}position")
        if position is not None:
            try:
                result["baseline_shift_pt"] = float(position.get("{" + _W + "}val")) / 2
            except (ValueError, TypeError):
                pass
    return result


def mark_docx_images(source, work_dir):
    """Insert text markers next to image runs so Pandoc cannot lose placement."""
    source, work_dir = Path(source), Path(work_dir)
    raw_dir = work_dir / "source_images"
    raw_dir.mkdir(parents=True, exist_ok=True)
    records, by_member, changed = [], {}, {}
    prefix = "HYBRIDIMAGE" + uuid4().hex[:10].upper()
    marker_index, native_equations = 0, 0
    for short, uri in (("w", _W), ("r", _R), ("a", _A), ("v", _V), ("m", _M)):
        ET.register_namespace(short, uri)

    with zipfile.ZipFile(source) as archive:
        members = set(archive.namelist())
        parts = sorted(n for n in members if n.startswith("word/") and n.endswith((".xml", ".vml")))
        for part in parts:
            try:
                root = ET.fromstring(archive.read(part))
            except ET.ParseError:
                continue
            native_equations += sum(1 for node in root.iter("{" + _M + "}oMath"))
            rels_name = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
            relationships = {}
            if rels_name in members:
                try:
                    rels = ET.fromstring(archive.read(rels_name))
                    relationships = {node.get("Id"): node.attrib for node in rels}
                except ET.ParseError:
                    pass
            parents = {child: parent for parent in root.iter() for child in parent}
            modified = False
            for node in list(root.iter()):
                rid = None
                kind = "image"
                if node.tag == "{" + _A + "}blip":
                    rid = node.get("{" + _R + "}embed") or node.get("{" + _R + "}link")
                elif node.tag == "{" + _V + "}imagedata":
                    rid = node.get("{" + _R + "}id")
                elif node.tag.rsplit("}", 1)[-1] == "OLEObject":
                    # A MathType object's preview is processed as an image.
                    # A binary with no preview must instead be reported explicitly.
                    container = parents.get(node)
                    while container is not None and container.tag != "{" + _W + "}object":
                        container = parents.get(container)
                    if container is not None and any(
                        item.tag in {"{" + _V + "}imagedata", "{" + _A + "}blip"}
                        for item in container.iter()
                    ):
                        continue
                    rid = node.get("{" + _R + "}id")
                    kind = "ole_no_preview"
                if not rid:
                    continue
                relationship = relationships.get(rid, {})
                target = unquote(relationship.get("Target", ""))
                external = relationship.get("TargetMode") == "External"
                member = (posixpath.normpath(target.lstrip("/")) if target.startswith("/")
                          else posixpath.normpath(posixpath.join(posixpath.dirname(part), target)))
                key = member if target and not external else part + ":" + rid
                if key not in by_member:
                    asset_id = "image-" + hashlib.sha256(key.encode()).hexdigest()[:16]
                    extension = Path(member).suffix.lower()
                    if not re.fullmatch(r"\.[a-z0-9]{1,8}", extension):
                        extension = ".bin"
                    record = dict(id=asset_id, member=member, kind=kind, extension=extension,
                                  markers=[], occurrences=[], references=0, parts=[], status="extracted", error="")
                    if external:
                        record.update(status="external_unsupported", error="Ảnh liên kết ngoài, không có dữ liệu trong DOCX.")
                    elif not target or member.startswith("../") or member not in members:
                        record.update(status="missing_media", error="Không tìm thấy dữ liệu ảnh trong gói DOCX.")
                    else:
                        data = archive.read(member)
                        path = raw_dir / (asset_id + extension)
                        path.write_bytes(data)
                        record.update(source_path=str(path), source_sha256=hashlib.sha256(data).hexdigest())
                    records.append(record)
                    by_member[key] = record
                record = by_member[key]
                geometry = image_geometry(node, parents)
                record["references"] += 1
                if part not in record["parts"]:
                    record["parts"].append(part)
                # Pandoc may ignore w:t inside a drawing run. Use a separate
                # text run immediately before the image, splitting preceding
                # run content so inline image positions are not shifted.
                anchor = node
                parent = parents.get(anchor)
                while parent is not None and parent.tag != "{" + _W + "}r":
                    anchor, parent = parent, parents.get(parent)
                if parent is not None and parents.get(parent) is not None:
                    container = parents[parent]
                    preceding = [item for item in list(parent)[:list(parent).index(anchor)]
                                 if item.tag != "{" + _W + "}rPr"]
                    if preceding:
                        before_run = ET.Element("{" + _W + "}r")
                        properties = parent.find("{" + _W + "}rPr")
                        if properties is not None:
                            before_run.append(deepcopy(properties))
                        for item in preceding:
                            parent.remove(item)
                            before_run.append(item)
                            parents[item] = before_run
                        container.insert(list(container).index(parent), before_run)
                        parents[before_run] = container
                    following = [item for item in list(parent)[list(parent).index(anchor) + 1:]
                                 if item.tag != "{" + _W + "}rPr"]
                    if following:
                        after_run = ET.Element("{" + _W + "}r")
                        properties = parent.find("{" + _W + "}rPr")
                        if properties is not None:
                            after_run.append(deepcopy(properties))
                        for item in following:
                            parent.remove(item)
                            after_run.append(item)
                            parents[item] = after_run
                        container.insert(list(container).index(parent) + 1, after_run)
                        parents[after_run] = container
                    marker_index += 1
                    marker = prefix + str(marker_index) + "END"
                    marker_run = ET.Element("{" + _W + "}r")
                    text = ET.SubElement(marker_run, "{" + _W + "}t")
                    text.text = marker
                    container.insert(list(container).index(parent), marker_run)
                    record["markers"].append(marker)
                    record["occurrences"].append(dict(marker=marker, **geometry))
                    modified = True
            if modified:
                changed[part] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        marked = work_dir / "pandoc-input.docx"
        with zipfile.ZipFile(marked, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for info in archive.infolist():
                output.writestr(info, changed.get(info.filename, archive.read(info.filename)))
    return dict(docx=marked, images=records, native_word_equations=native_equations)


def _markdown_path(ref, base):
    ref = ref.strip().strip("<>")
    if urlsplit(ref).scheme and not re.match(r"^[A-Za-z]:[/\\]", ref):
        return None
    path = Path(unquote(ref.replace("\\ ", " ")))
    return (path if path.is_absolute() else Path(base) / path).resolve()


def render_vectors(records, output_dir, allow_install=True):
    """Batch LibreOffice conversion; every missing/failed render is returned."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    soffice = shutil.which("soffice")
    if not soffice and allow_install and sys.platform.startswith("linux") and shutil.which("apt-get"):
        print("Ảnh WMF/EMF/SVG: đang cài LibreOffice Draw lần đầu…", flush=True)
        try:
            install_env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", APT_LISTCHANGES_FRONTEND="none")
            apt = ["apt-get", "-o", "Dpkg::Use-Pty=0", "-o", "DPkg::Lock::Timeout=60",
                   "-o", "Acquire::Retries=1", "-o", "Acquire::http::Timeout=30", "-o", "Acquire::https::Timeout=30"]
            print("LibreOffice Draw: cập nhật danh sách gói (giới hạn 240s)…", flush=True)
            subprocess.run([*apt, "update"], check=True, timeout=240, env=install_env, stdin=subprocess.DEVNULL)
            print("LibreOffice Draw: tải / cài gói (giới hạn 480s)…", flush=True)
            subprocess.run([*apt, "install", "-y", "--no-install-recommends", "libreoffice-core", "libreoffice-draw"],
                           check=True, timeout=480, env=install_env, stdin=subprocess.DEVNULL)
            soffice = shutil.which("soffice")
            if soffice:
                print("LibreOffice Draw: đã cài xong, bắt đầu chuyển ảnh vector.", flush=True)
        except (subprocess.SubprocessError, OSError) as error:
            print("Không cài được LibreOffice:", error, flush=True)
    if not soffice:
        return {}, {record["id"]: "Không có LibreOffice để chuyển ảnh vector sang PNG." for record in records}
    converted, errors = {}, {}
    unique = {}
    for record in records:
        unique.setdefault(record["source_sha256"], []).append(record)
    entries = list(unique.values())
    for offset in range(0, len(entries), 32):
        group = entries[offset:offset + 32]
        batch = output_dir / ("batch-" + str(offset))
        batch.mkdir(exist_ok=True)
        sources = [Path(items[0]["source_path"]) for items in group]
        print(f"LibreOffice Draw: đang chuyển ảnh vector {offset + 1}–{offset + len(group)}/{len(entries)}…", flush=True)
        profile = (batch / "profile").resolve().as_uri()
        export_filter = 'png:draw_png_Export:{"PixelWidth":{"type":"long","value":"1600"},"Translucent":{"type":"boolean","value":"false"}}'
        try:
            process = subprocess.run(
                [soffice, "-env:UserInstallation=" + profile, "--headless", "--norestore",
                 "--convert-to", export_filter, "--outdir", str(batch), *map(str, sources)],
                capture_output=True, text=True, timeout=180,
            )
            detail = (process.stdout + "\n" + process.stderr).strip()
            (batch / "conversion.log").write_text(detail, encoding="utf-8")
        except (subprocess.SubprocessError, OSError) as error:
            detail = str(error)
        for items, source in zip(group, sources):
            raster = batch / (source.stem + ".png")
            for record in items:
                if raster.is_file():
                    converted[record["id"]] = raster
                else:
                    errors[record["id"]] = "Chuyển vector thất bại: " + detail[-1200:]
    return converted, errors


def _normalise_image(source, destination, display_destination=None):
    with Image.open(source) as original:
        dpi = original.info.get("dpi", (96, 96))
        rgba = original.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, "white")
        canvas.alpha_composite(rgba)
        image = canvas.convert("RGB")
    if display_destination is not None:
        if not isinstance(dpi, (tuple, list)) or len(dpi) < 2 or not all(isinstance(value, (int, float)) and value > 0 for value in dpi[:2]):
            dpi = (96, 96)
        # Uncropped/unscaled pixels are for printing; OCR gets its own raster.
        image.save(display_destination, format="PNG", dpi=tuple(dpi[:2]))
    bbox = image.convert("L").point(lambda value: 255 if value < 250 else 0).getbbox()
    if bbox is None:
        return None, None
    image = ImageOps.expand(image.crop(bbox), border=12, fill="white")
    longest = max(image.size)
    target = max(384, min(1600, longest))
    if longest != target:
        scale = target / longest
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
    key = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
    image.save(destination, format="PNG")
    return key, list(image.size)


def prepare_image_plan(markdown, extraction, work_dir, vector_converter=None, allow_install=True):
    """Send every nonblank decodable image to OCR, deduplicated by pixels."""
    work_dir = Path(work_dir)
    records = extraction["images"]
    source_hashes = {}
    for record in records:
        if record.get("source_sha256"):
            source_hashes.setdefault(record["source_sha256"], []).append(record)
        record["placed"] = False
    matched_hashes = {}
    for match in _IMAGE_MD.finditer(markdown):
        path = _markdown_path(match[1], work_dir)
        if path is not None and path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            matched_hashes[match[0]] = digest
            if digest not in source_hashes:
                record = dict(id="pandoc-" + digest[:16], member=None, kind="image",
                              extension=path.suffix.lower(), markers=[], references=1, parts=[],
                              status="extracted", error="", source_path=str(path), source_sha256=digest, placed=False)
                records.append(record)
                source_hashes[digest] = [record]

    def replace_pandoc_image(match):
        candidates = source_hashes.get(matched_hashes.get(match[0]), [])
        if not candidates:
            return match[0]
        if any(marker in markdown for record in candidates for marker in record["markers"]):
            return ""  # A marker supplies the same image at its source position.
        record = candidates[0]
        record["placed"] = True
        return "![](" + record["source_path"] + ")"
    result = _IMAGE_MD.sub(replace_pandoc_image, markdown)
    for record in records:
        ref = record.get("source_path")
        placeholder = ("![](" + ref + ")" if ref else "[Ảnh nguồn bị thiếu: " + record["id"] + "]")
        for marker in record["markers"]:
            if marker in result:
                result = result.replace(marker, "\n\n" + placeholder + "\n\n")
                record["placed"] = True
        if not record["placed"]:
            result += "\n\n### Ảnh/công thức khôi phục từ DOCX — chưa gắn được vị trí\n\n" + placeholder + "\n"
            record["placement_warning"] = "Pandoc không giữ vị trí; ảnh được đưa vào mục khôi phục riêng."

    vectors = [record for record in records if record["extension"] in _VECTORS and record.get("source_path")]
    converter = vector_converter or render_vectors
    converted, vector_errors = converter(vectors, work_dir / "converted", allow_install=allow_install) if vectors else ({}, {})
    prepared = work_dir / "formula_png"
    prepared.mkdir(exist_ok=True)
    display_images = work_dir / "display_images"
    display_images.mkdir(exist_ok=True)
    tasks, ref_to_hash, seen = [], {}, {}
    for record in records:
        if record["kind"] == "ole_no_preview":
            record.update(status="ole_no_preview", error="Đối tượng OLE không có ảnh xem trước; không thể đưa tệp nhị phân vào OCR.")
        elif record.get("source_path"):
            source = Path(record["source_path"])
            if record["extension"] in _VECTORS:
                source = converted.get(record["id"])
                if source is None:
                    record.update(status="conversion_error", error=vector_errors.get(record["id"], "Thiếu ảnh PNG đã chuyển đổi."))
            if source is not None:
                destination = prepared / (record["id"] + ".png")
                display_destination = display_images / (record["id"] + ".png")
                try:
                    key, size = _normalise_image(source, destination, display_destination)
                    if key is None:
                        if record["extension"] in _VECTORS:
                            record.update(status="conversion_error", error="Ảnh PNG chuyển từ vector bị trắng; giữ vector gốc để kiểm tra.")
                        else:
                            record["status"] = "blank"
                    else:
                        record.update(pixel_key=key, raster_path=str(destination), raster_size=size, status="queued")
                        record["display_path"] = str(display_destination)
                        ref_to_hash[str(destination)] = key
                        if key in seen:
                            record["duplicate_of"] = seen[key]
                        else:
                            seen[key] = record["id"]
                            tasks.append((str(destination), destination, key))
                except Exception as error:
                    record.update(status="decode_error", error=str(error))
        original_ref = record.get("source_path")
        if original_ref:
            original_tag = "![](" + original_ref + ")"
            if record.get("raster_path"):
                result = result.replace(original_tag, "![](" + record["raster_path"] + ")")
            elif record["status"] != "blank":
                warning = "[Chưa nhận dạng được ảnh/công thức " + record["id"] + ": " + record.get("error", "") + "](" + original_ref + ")"
                result = result.replace(original_tag, warning)
    plan = dict(markup=result, records=records, tasks=tasks, ref_to_hash=ref_to_hash,
                native_word_equations=extraction.get("native_word_equations", 0))
    write_image_report(plan, work_dir)
    return plan


def record_ocr_result(plan, key, raw, cleaned):
    for record in plan["records"]:
        if record.get("pixel_key") == key:
            record.update(status="ocr_success" if cleaned else "ocr_empty", raw_ocr=raw, ocr_text=cleaned)


def write_image_report(plan, work_dir):
    records = plan["records"]
    error_states = {"conversion_error", "decode_error", "missing_media", "external_unsupported", "ole_no_preview", "ocr_empty"}
    summary = {
        "images_in_docx": sum(record["kind"] == "image" for record in records),
        "image_occurrences": sum(record["references"] for record in records),
        "native_word_equations": plan["native_word_equations"],
        "queued_unique_images": len(plan["tasks"]),
        "duplicate_images": sum(bool(record.get("duplicate_of")) for record in records),
        "blank_images": sum(record["status"] == "blank" for record in records),
        "vector_images": sum(record["extension"] in _VECTORS for record in records),
        "conversion_errors": sum(record["status"] == "conversion_error" for record in records),
        "images_unprocessed": sum(record["status"] in error_states for record in records),
    }
    plan["summary"] = summary
    report = dict(summary=summary, images=records)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    serialized = serialized.replace(str(Path(work_dir)) + "/", "")
    (Path(work_dir) / "image-report.json").write_text(serialized, encoding="utf-8")
    return summary
