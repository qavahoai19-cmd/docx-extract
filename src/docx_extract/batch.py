"""Collect all document jobs before OCR so identical images share inference."""

from dataclasses import dataclass
import hashlib
from time import perf_counter

from .assemble import extract_docx
from .context import Context


@dataclass
class BatchDocument:
    markup: str = ""
    context: Context | None = None
    error: str = ""


def clean_docx_batch(paths, client):
    started = perf_counter()
    documents, jobs, groups = [], [], []
    for index, path in enumerate(paths):
        try:
            markup, ctx = extract_docx(path, native_math=False)
            documents.append(BatchDocument(markup, ctx))
            mappings = []
            for oid, data, ext, _ in ctx.pending_ocr:
                remote_id = f"d{index + 1}__{oid}"
                jobs.append((remote_id, data, ext))
                mappings.append((oid, remote_id, data, ext))
            groups.append(mappings)
        except Exception as exc:
            documents.append(BatchDocument(error=str(exc)))
            groups.append([])
    parse_s = perf_counter() - started
    ocr_started = perf_counter()
    try:
        received = client.recognize(jobs) if jobs else {}
    except Exception as exc:
        received = {oid: {"latex": None, "error": f"OCR thất bại: {exc}"} for oid, _, _ in jobs}
    ocr_s = perf_counter() - ocr_started
    for document, mappings in zip(documents, groups):
        if document.context is None:
            continue
        ctx = document.context
        local_results = {oid: received.get(remote_id, {"latex": None, "error": "OCR batch thiếu id"})
                         for oid, remote_id, _, _ in mappings}
        ctx.apply_ocr_results(local_results)
        entries = {entry['id']: entry for entry in ctx.manifest}
        for oid, remote_id, _, _ in mappings:
            png = getattr(client, 'input_images', {}).get(remote_id)
            if png:
                filename = oid + '.ocr-input.png'
                ctx.written[filename] = png
                entries[oid]['ocr_input'] = filename
                entries[oid]['ocr_input_settings'] = dict(client.input_settings)
        ctx.ocr_stats.update(
            ocr_total=len(mappings),
            unique=len({(ext, hashlib.sha256(data).digest()) for _, _, data, ext in mappings}),
            timing_scope="shared_batch",
            document_s=ctx.ocr_stats["parse_s"] + ocr_s,
        )
    return documents, {**dict(client.stats), "parse_s": parse_s, "ocr_s": ocr_s,
                       "total_s": perf_counter() - started, "documents": len(documents),
                       "failed_documents": sum(bool(item.error) for item in documents)}
