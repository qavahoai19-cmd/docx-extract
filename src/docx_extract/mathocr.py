"""Batched HTTP OCR, exact-image deduplication and versioned success cache."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit

import requests

from .raster import prepare_image


def _route(endpoint, suffix):
    parts = urlsplit(endpoint)
    path = parts.path.rstrip("/")
    path = path + "/batch" if suffix == "batch" else path.rsplit("/", 1)[0] + "/health"
    return urlunsplit(parts._replace(path=path))


def _cache_path():
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    return Path(base or Path.home() / ".cache") / "docx-extract" / "ocr.sqlite3"


class OCRClient:
    """One Session/SQLite connection per job, owned by the calling thread.

    Persistent caching requires a model/preprocessing cache_namespace from the
    server. Legacy endpoints remain usable without caching stale model output.
    """

    def __init__(self, *, endpoint=None, cache_path=None, batch_size=None,
                 prepare=None, session=None, progress=None):
        self.endpoint = endpoint if endpoint is not None else os.getenv("DOCX_EXTRACT_OCR_ENDPOINT", "")
        self.timeout = max(1, float(os.getenv("DOCX_EXTRACT_OCR_TIMEOUT", "30")))
        self.batch_size = max(1, min(32, int(batch_size or os.getenv("DOCX_EXTRACT_OCR_BATCH_SIZE", "8"))))
        self.prepare = prepare if prepare is not None else os.getenv("DOCX_EXTRACT_OCR_PREPARE_IMAGES", "1") != "0"
        self.progress = progress
        self.session = session if session is not None else requests.Session()
        self.headers = {}
        key = os.getenv("DOCX_EXTRACT_OCR_API_KEY")
        if key:
            self.headers["Authorization"] = f"Bearer {key}"
        self.auth_scope = hashlib.sha256((key or "").encode()).hexdigest()
        configured = cache_path if cache_path is not None else os.getenv("DOCX_EXTRACT_OCR_CACHE", str(_cache_path()))
        self.cache_path = None if str(configured).lower() in {"off", "0", "false"} else Path(configured)
        self.db = None
        self.namespace = None
        self.batch_supported = True
        self.discovered = False
        self.transport_error = None
        self.stats = dict(total=0, unique=0, deduplicated=0, cache_hits=0,
                          remote_images=0, http_requests=0, failures=0,
                          prepare_s=0.0, http_s=0.0, server_prepare_s=0.0,
                          server_queue_s=0.0, server_infer_s=0.0, total_s=0.0,
                          rasterized=0, cache_errors=0)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.db is not None:
            self.db.close()
        self.session.close()

    def _discover(self):
        if self.discovered:
            return
        self.discovered = True
        try:
            response = self.session.get(_route(self.endpoint, "health"), headers=self.headers, timeout=(3, 3))
            response.raise_for_status()
            metadata = response.json()
            self.namespace = metadata.get("cache_namespace")
            self.batch_supported = metadata.get("batch", True)
        except (requests.RequestException, ValueError, AttributeError):
            pass
        if self.namespace and self.cache_path is not None:
            try:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.db = sqlite3.connect(self.cache_path, timeout=1)
                self.db.execute("CREATE TABLE IF NOT EXISTS ocr (key TEXT PRIMARY KEY, latex TEXT NOT NULL)")
            except (OSError, sqlite3.Error):
                self.stats["cache_errors"] += 1
                if self.db is not None:
                    self.db.close()
                self.db = None

    def _key(self, data, ext):
        scope = [self.endpoint, self.auth_scope, self.namespace,
                 os.getenv("DOCX_EXTRACT_OCR_CACHE_VERSION", "1"),
                 "raster-v1", self.prepare, os.getenv("DOCX_EXTRACT_OCR_RASTER_DPI", "300"), ext]
        return hashlib.sha256(json.dumps(scope, sort_keys=True).encode() + data).hexdigest()

    def _get_cached(self, key):
        if self.db is not None:
            try:
                row = self.db.execute("SELECT latex FROM ocr WHERE key=?", (key,)).fetchone()
                return row[0] if row else None
            except sqlite3.Error:
                self.stats["cache_errors"] += 1
        return None

    def _save_cached(self, pairs):
        if self.db is not None and pairs:
            try:
                self.db.executemany("INSERT OR REPLACE INTO ocr VALUES (?, ?)", pairs)
                self.db.commit()
            except sqlite3.Error:
                self.stats["cache_errors"] += 1

    def _post(self, endpoint, **kwargs):
        started = perf_counter()
        self.stats["http_requests"] += 1
        try:
            return self.session.post(endpoint, headers=self.headers, **kwargs)
        finally:
            self.stats["http_s"] += perf_counter() - started

    @staticmethod
    def _result(payload):
        latex = payload.get("latex")
        latex = latex.strip() if isinstance(latex, str) and latex.strip() else None
        return {"latex": latex, "error": "" if latex else str(payload.get("error") or "OCR không trả LaTeX")}

    def _send(self, chunk):
        if self.batch_supported and len(chunk) > 1:
            response = self._post(
                _route(self.endpoint, "batch"),
                files=[("files", (f"{oid}.{ext}", data)) for oid, data, ext in chunk],
                data={"ids": json.dumps([item[0] for item in chunk])},
                timeout=(5, float(os.getenv("DOCX_EXTRACT_OCR_BATCH_TIMEOUT", str(max(self.timeout, min(120, self.timeout * len(chunk))))))),
            )
            if response.status_code in {404, 405}:
                self.batch_supported = False
            else:
                response.raise_for_status()
                payload = response.json()
                results = payload.get("results")
                if not isinstance(results, list):
                    raise ValueError("OCR batch response thiếu results")
                mapped = {}
                expected = {item[0] for item in chunk}
                for result in results:
                    oid = result.get("id")
                    if oid not in expected or oid in mapped:
                        raise ValueError("OCR batch response có id trùng/không hợp lệ")
                    mapped[oid] = self._result(result)
                timings = payload.get("timings", {})
                for name in ("prepare", "queue", "infer"):
                    self.stats[f"server_{name}_s"] += float(timings.get(f"{name}_s", 0))
                return {oid: mapped.get(oid, {"latex": None, "error": "OCR batch response thiếu id"}) for oid in expected}
        mapped = {}
        for oid, data, ext in chunk:
            if self.transport_error:
                mapped[oid] = {"latex": None, "error": self.transport_error}
                continue
            try:
                response = self._post(self.endpoint, files={"file": (f"formula.{ext}", data)}, timeout=self.timeout)
                response.raise_for_status()
                mapped[oid] = self._result(response.json())
            except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
                self.transport_error = f"OCR request thất bại: {exc}"
                mapped[oid] = {"latex": None, "error": self.transport_error}
        return mapped

    def recognize(self, items):
        """Return results by stable id; failures keep original images, never cache.

        Abort remaining requests after a transport error to avoid N timeouts on
        an unavailable server. Individual OCR errors in a batch remain isolated.
        """
        started = perf_counter()
        self.transport_error = None
        items = list(items)
        self.stats["total"] += len(items)
        output = {}
        if not self.endpoint:
            self.stats["failures"] += len(items)
            self.stats["total_s"] += perf_counter() - started
            return {oid: {"latex": None, "error": "OCR endpoint chưa cấu hình"} for oid, _, _ in items}
        self._discover()
        groups = {}
        for oid, data, ext in items:
            key = self._key(data, ext.lower())
            groups.setdefault(key, []).append((oid, data, ext.lower()))
        self.stats["unique"] += len(groups)
        self.stats["deduplicated"] += len(items) - len(groups)
        pending = []
        for key, group in groups.items():
            cached = self._get_cached(key)
            if cached:
                self.stats["cache_hits"] += len(group)
                output.update({oid: {"latex": cached, "error": ""} for oid, _, _ in group})
            else:
                pending.append((key, group))
        transport_error = None
        for offset in range(0, len(pending), self.batch_size):
            selected = pending[offset:offset + self.batch_size]
            if transport_error:
                for _, group in selected:
                    output.update({oid: {"latex": None, "error": transport_error} for oid, _, _ in group})
                continue
            prepare_start = perf_counter()
            chunk = []
            for _, group in selected:
                oid, data, ext = group[0]
                prepared, prepared_ext = prepare_image(data, ext) if self.prepare else (data, ext)
                self.stats["rasterized"] += int(prepared_ext != ext)
                chunk.append((oid, prepared, prepared_ext))
            self.stats["prepare_s"] += perf_counter() - prepare_start
            self.stats["remote_images"] += len(chunk)
            try:
                received = self._send(chunk)
                transport_error = self.transport_error
            except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
                transport_error = f"OCR request thất bại: {exc}"
                received = {oid: {"latex": None, "error": transport_error} for oid, _, _ in chunk}
            cached = []
            for key, group in selected:
                result = received[group[0][0]]
                output.update({oid: dict(result) for oid, _, _ in group})
                if result["latex"]:
                    cached.append((key, result["latex"]))
            self._save_cached(cached)
            if self.progress:
                self.progress(len(output), len(items), dict(self.stats))
        self.stats["failures"] += sum(not result["latex"] for result in output.values())
        self.stats["total_s"] += perf_counter() - started
        return output


def image_to_latex(data: bytes, ext: str) -> str | None:
    """Compatibility entry point for single-image callers."""
    with OCRClient() as client:
        return client.recognize([("formula", data, ext)])["formula"]["latex"]
