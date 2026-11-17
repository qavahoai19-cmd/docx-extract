"""Compare the previous sequential client with cold/warm optimized jobs.

--mock measures HTTP/pipeline overhead with explicit artificial delays and
serial simulated inference. It does NOT benchmark DeepSeek/GPU or OCR accuracy.
Without --mock, --endpoint (or the environment) must name a live OCR server.
No benchmark LaTeX is written into the real exam outputs.
"""

import argparse
from contextlib import contextmanager
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
from time import perf_counter, sleep
import types

from docx_extract import clean_docx
from docx_extract.mathocr import OCRClient

ROOT = Path(__file__).resolve().parent.parent


def load_previous_pipeline(revision):
    modules = []
    for name in ("mathocr", "context", "assemble"):
        if Path(revision).is_dir():
            source = (Path(revision) / f"{name}.py").read_text(encoding="utf-8")
        else:
            source = subprocess.check_output(["git", "show", f"{revision}:src/docx_extract/{name}.py"], cwd=ROOT).decode("utf-8")
        module = types.ModuleType(f"docx_extract._benchmark_previous_{name}")
        module.__package__ = "docx_extract"
        sys.modules[module.__name__] = module
        exec(compile(source, f"{revision}:{name}.py", "exec"), module.__dict__)
        modules.append(module)
    old_ocr, old_context, old_assemble = modules
    original_requests = old_ocr.requests
    def uncached_post(url, **kwargs):
        kwargs["headers"] = {**kwargs.get("headers", {}), "X-OCR-Cache": "off"}
        return original_requests.post(url, **kwargs)
    old_ocr.requests = types.SimpleNamespace(post=uncached_post)
    old_context.mathocr = old_ocr
    old_assemble.Context = old_context.Context
    return old_assemble.clean_docx


@contextmanager
def environment(**values):
    previous = {key: os.getenv(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def simulated_endpoint(request_delay, inference_delay):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def setup(self):
            super().setup()
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        def log_message(self, *args):
            pass
        def respond(self, payload):
            encoded = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        def do_GET(self):
            sleep(request_delay)
            self.respond({"cache_namespace": "simulated-serial-model-v1", "batch": True})
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            message = BytesParser(policy=default).parsebytes(
                ("Content-Type: " + self.headers["Content-Type"] + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body)
            parts = list(message.iter_parts())
            images = [part for part in parts if part.get_filename()]
            state["requests"] += 1
            state["images"] += len(images)
            state["uploaded_bytes"] += sum(len(part.get_payload(decode=True)) for part in images)
            sleep(request_delay)
            # Inference is SERIAL for both paths. No imaginary GPU speedup.
            for _ in images:
                sleep(inference_delay)
            if self.path.endswith("/batch"):
                ids = json.loads(next(part for part in parts if part.get_param("name", header="content-disposition") == "ids").get_payload(decode=True))
                self.respond({"results": [{"id": oid, "latex": "x^2"} for oid in reversed(ids)]})
            else:
                self.respond({"latex": "x^2"})
    state = dict(requests=0, images=0, uploaded_bytes=0)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/ocr", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def selected_documents():
    imported = ROOT / "out" / "word-import-20261116"
    summary = imported / "summary.json"
    choices = []
    if summary.exists():
        for row in json.loads(summary.read_text(encoding="utf-8")):
            manifest = json.loads((imported / row["output"] / "manifest.json").read_text(encoding="utf-8"))
            count = sum(item["type"] == "mathtype" for item in manifest["assets"])
            if count:
                choices.append((count, imported / "input" / row["source"]))
    choices.sort(reverse=True, key=lambda pair: pair[0])
    return [path for _, path in choices[:2]] + [ROOT / "tests" / "fixtures" / "sample.docx"]


def measure(documents, endpoint, state, repetitions, revision):
    previous = load_previous_pipeline(revision)
    rows = []
    # Keep this comparison about image OCR; native MathType is measured separately.
    with tempfile.TemporaryDirectory(prefix="ocr-benchmark-") as directory, environment(DOCX_EXTRACT_OCR_ENDPOINT=endpoint, DOCX_EXTRACT_NATIVE_MATH="0"):
        for index, document in enumerate(documents):
            runs = []
            for repeat in range(repetitions):
                for key in state:
                    state[key] = 0
                start = perf_counter()
                old_markup, old_ctx = previous(document)
                old_elapsed = perf_counter()-start
                count = sum(item["type"] == "mathtype" for item in old_ctx.manifest)
                legacy_stats = dict(state)
                if any(item["type"] == "mathtype" and not item.get("latex") for item in old_ctx.manifest):
                    raise RuntimeError("Baseline OCR failed; comparison would be misleading")
                results = []
                cache = Path(directory) / f"{index}-{repeat}.sqlite3"
                for phase in ("cold", "warm"):
                    for key in state:
                        state[key] = 0
                    with OCRClient(endpoint=endpoint, cache_path=cache) as client:
                        # Keep baseline/cold inference cold on the new server;
                        # otherwise its in-memory cache biases repeated trials.
                        client.headers["X-OCR-Cache"] = "off"
                        start = perf_counter()
                        markup, ctx = clean_docx(document, ocr_client=client)
                        elapsed = perf_counter()-start
                        stats = dict(client.stats)
                    if markup != old_markup or ctx.counter != old_ctx.counter or ctx.written != old_ctx.written:
                        raise RuntimeError("Markup, placeholder order or original sidecars changed")
                    if stats["failures"]:
                        raise RuntimeError(f"Optimized OCR had {stats['failures']} failures")
                    changed = [{"id": item["id"], "before": old_ctx.latex.get(item["id"]),
                                "after": ctx.latex.get(item["id"])} for item in ctx.manifest
                               if item["type"] == "mathtype" and old_ctx.latex.get(item["id"]) != ctx.latex.get(item["id"])]
                    results.append({"phase": phase, "elapsed_s": elapsed, "stats": stats,
                                    "server": dict(state), "changed_latex": changed})
                runs.append({"baseline_s": old_elapsed, "baseline_server": legacy_stats, "results": results})
            cold = statistics.median(run["results"][0]["elapsed_s"] for run in runs)
            warm = statistics.median(run["results"][1]["elapsed_s"] for run in runs)
            baseline = statistics.median(run["baseline_s"] for run in runs)
            row = {"document": document.name, "formulas": count, "baseline_s": baseline,
                   "cold_s": cold, "warm_s": warm, "cold_speedup": baseline/cold,
                   "warm_speedup": baseline/warm, "runs": runs}
            rows.append(row)
            print(json.dumps({key: value for key, value in row.items() if key != "runs"}, ensure_ascii=True), flush=True)
    return rows


def corpus_check(revision):
    previous = load_previous_pipeline(revision)
    paths = sorted((ROOT / "out" / "word-import-20261116" / "input").rglob("*.docx"))
    checked, skipped = 0, 0
    with environment(DOCX_EXTRACT_OCR_ENDPOINT=None):
        for path in paths:
            if path.name.startswith("~$"):
                skipped += 1
                continue
            old_markup, old_ctx = previous(path)
            markup, ctx = clean_docx(path)
            assert markup == old_markup, path
            assert ctx.counter == old_ctx.counter and ctx.written == old_ctx.written, path
            checked += 1
    return {"documents": checked, "temporary_files_skipped": skipped, "identical_markup_ids_sidecars": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("documents", nargs="*", type=Path)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--endpoint", default=os.getenv("DOCX_EXTRACT_OCR_ENDPOINT"))
    parser.add_argument("--request-delay", type=float, default=.015)
    parser.add_argument("--inference-delay", type=float, default=.003)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--baseline", default="HEAD")
    parser.add_argument("--corpus-check", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT/"out"/"ocr-benchmark.json")
    args = parser.parse_args()
    if not args.mock and not args.endpoint:
        parser.error("Provide --endpoint for real OCR, or explicitly choose --mock (no GPU benchmark).")
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    documents = args.documents or selected_documents()
    report = {"mode": "simulated_http_and_serial_inference" if args.mock else "live_ocr_endpoint",
              "request_delay_s": args.request_delay if args.mock else None,
              "serial_inference_delay_s": args.inference_delay if args.mock else None,
              "repetitions": args.repeat,
              "baseline_revision": ((Path(args.baseline)/"revision.txt").read_text().strip()
                                    if Path(args.baseline).is_dir() else
                                    subprocess.check_output(["git","rev-parse",args.baseline],cwd=ROOT).decode().strip())}
    if args.mock:
        with simulated_endpoint(args.request_delay,args.inference_delay) as (endpoint,state):
            report["documents"] = measure(documents,endpoint,state,args.repeat,args.baseline)
    else:
        report["documents"] = measure(documents,args.endpoint,{},args.repeat,args.baseline)
    if args.corpus_check:
        report["corpus"] = corpus_check(args.baseline)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Saved benchmark report.")


if __name__ == "__main__":
    main()
