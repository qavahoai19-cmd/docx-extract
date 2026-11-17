"""Isolated CPU worker. PYTHONPATH selects exactly one client implementation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from time import perf_counter


def snapshot(markup, context):
    assets = []
    for entry in context.manifest:
        oid = entry["id"]
        raw = next((data for name, data in context.written.items() if name.rsplit(".", 1)[0] == oid), b"")
        assets.append({"id": oid, "type": entry["type"], "source": entry.get("source"),
                       "sha256": hashlib.sha256(raw).hexdigest(), "latex": entry.get("latex")})
    return {"markup": markup, "assets": assets, "warnings": context.warnings}


def run(mode, sources, endpoint, output):
    from docx_extract import clean_docx, write_outputs
    documents, metrics = [], {"http_requests": 0, "remote_images": 0, "cache_hits": 0,
                              "http_s": 0.0, "server_prepare_s": 0.0, "server_infer_s": 0.0}
    if mode == "before":
        from docx_extract import mathocr
        original = mathocr.requests.post

        def measured_post(*args, **kwargs):
            kwargs["headers"] = {**kwargs.get("headers", {}), "X-OCR-Cache": "off"}
            metrics["http_requests"] += 1
            metrics["remote_images"] += 1
            started = perf_counter()
            try:
                response = original(*args, **kwargs)
                for name in ("prepare", "infer"):
                    metrics[f"server_{name}_s"] += response.json().get("timings", {}).get(f"{name}_s", 0)
                return response
            finally:
                metrics["http_s"] += perf_counter() - started
        mathocr.requests.post = measured_post
    started = perf_counter()
    try:
        if mode == "after":
            import requests
            from docx_extract.batch import clean_docx_batch
            from docx_extract.mathocr import OCRClient
            server_times = {"server_prepare_s": 0.0, "server_infer_s": 0.0}

            class MeasuredSession(requests.Session):
                def post(self, *args, **kwargs):
                    response = super().post(*args, **kwargs)
                    if response.ok:
                        for name in ("prepare", "infer"):
                            server_times[f"server_{name}_s"] += response.json().get("timings", {}).get(f"{name}_s", 0)
                    return response

            with OCRClient(endpoint=endpoint, cache_path="off", batch_size=32, session=MeasuredSession()) as client:
                client.headers["X-OCR-Cache"] = "off"
                extracted, metrics = clean_docx_batch([item["path"] for item in sources], client)
                metrics.update(server_times)
        else:
            extracted = []
            for item in sources:
                try:
                    markup, context = clean_docx(item["path"])
                    extracted.append((markup, context, ""))
                except Exception as exc:
                    extracted.append(("", None, str(exc)))
        for index, (source, result) in enumerate(zip(sources, extracted)):
            if mode == "after":
                markup, context, error = result.markup, result.context, result.error
            else:
                markup, context, error = result
            row = {"file": source["name"], "sha256": source["sha256"], "error": error}
            if context is not None:
                write_outputs(markup, context, str(output / "results" / f"{index + 1:03d}"))
                row["snapshot"] = snapshot(markup, context)
                equations = [entry for entry in context.manifest if entry["type"] == "mathtype"]
                row["formulas"] = len(equations)
                row["failures"] = sum(not entry.get("latex") for entry in equations)
            documents.append(row)
        # Package the same outputs on both sides; upload and model startup excluded.
        output.mkdir(parents=True, exist_ok=True)
        (output / "results").mkdir(exist_ok=True)
        (output / "results/summary.json").write_text(json.dumps(documents, ensure_ascii=False), encoding="utf-8")
        shutil.make_archive(str(output / "results"), "zip", output / "results")
        elapsed = perf_counter() - started
    finally:
        if mode == "before":
            mathocr.requests.post = original
    return {"mode": mode, "total_s": elapsed, "metrics": metrics, "documents": documents,
            "failed_documents": sum(bool(row["error"]) for row in documents),
            "failures": sum(row.get("failures", 0) for row in documents),
            "formulas": sum(row.get("formulas", 0) for row in documents)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("before", "after"), required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.mode, json.loads(args.sources.read_text(encoding="utf-8")), args.endpoint, args.output)
    (args.output / "run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
