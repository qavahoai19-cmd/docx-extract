"""Independent benchmark controller; production code never imports this module."""
from collections import Counter, defaultdict, deque
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
from uuid import uuid4

import requests


def asset_key(asset):
    return asset["type"], asset.get("source"), asset["sha256"]


def compare(before, after):
    differences = []
    for left, right in zip(before["documents"], after["documents"]):
        issue = {"file": left["file"]}
        issue["input_changed"] = (left["file"], left["sha256"]) != (right["file"], right["sha256"])
        if left.get("error") or right.get("error"):
            issue["document_error"] = [left.get("error"), right.get("error")]
        else:
            a, b = left["snapshot"], right["snapshot"]
            issue["markup_changed"] = a["markup"] != b["markup"]
            issue["assets_changed"] = Counter(map(asset_key, a["assets"])) != Counter(map(asset_key, b["assets"]))
            by_key = defaultdict(deque)
            for asset in a["assets"]:
                by_key[asset_key(asset)].append(asset)
            changed = []
            for asset in b["assets"]:
                matches = by_key[asset_key(asset)]
                if matches:
                    previous = matches.popleft()
                    if previous.get("latex") != asset.get("latex"):
                        changed.append({"before_id": previous["id"], "after_id": asset["id"],
                                        "before": previous.get("latex"), "after": asset.get("latex")})
            issue["changed_latex"] = changed
        if any(value for key, value in issue.items() if key != "file"):
            differences.append(issue)
    if len(before["documents"]) != len(after["documents"]):
        differences.append({"document_count_changed": True})
    return differences


def summarize(runs):
    summary = {}
    for mode in ("before", "after"):
        selected = [run for run in runs if run["mode"] == mode]
        if not selected:
            continue
        summary[mode] = {"total_s": statistics.median(row["total_s"] for row in selected),
                         "formulas": selected[0]["formulas"],
                         "failures": max(row["failures"] for row in selected),
                         "failed_documents": max(row["failed_documents"] for row in selected)}
        for name in ("server_prepare_s", "server_infer_s", "remote_images", "http_requests", "cache_hits"):
            summary[mode][name] = statistics.median(row["metrics"].get(name, 0) for row in selected)
    return summary


def run_benchmark(uploads, root, endpoint, modes=("before", "after"), repetitions=1, progress=print):
    # Reuse only input validation. Neither benchmark run uses production upload/cache paths.
    from notebook_upload import gather_documents
    if repetitions not in (1, 3) or not modes or any(mode not in ("before", "after") for mode in modes):
        raise ValueError("Invalid benchmark settings")
    root = Path(root).resolve()
    endpoint = endpoint.rstrip("/")
    base = endpoint.rsplit("/", 1)[0]
    headers = {}
    if os.getenv("DOCX_EXTRACT_OCR_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["DOCX_EXTRACT_OCR_API_KEY"]
    response = requests.get(base + "/benchmark/health", headers=headers, timeout=10)
    response.raise_for_status()
    health = response.json()
    if not health.get("model_loaded") or not health.get("warmed_up"):
        raise RuntimeError("Model chưa sẵn sàng; chạy lại ô khởi động server.")
    job = root / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:6])
    inputs = job / "input"
    inputs.mkdir(parents=True)
    sources = []
    for index, (name, data) in enumerate(gather_documents(uploads)):
        path = inputs / f"{index + 1:03d}.docx"
        path.write_bytes(data)
        sources.append({"name": name, "path": str(path), "sha256": hashlib.sha256(data).hexdigest()})
    sources_path = job / "sources.json"
    sources_path.write_text(json.dumps(sources, ensure_ascii=False), encoding="utf-8")
    runs = []
    for repeat in range(repetitions):
        # Alternate order to reduce systematic first/second-run bias.
        order = tuple(reversed(modes)) if repeat % 2 else modes
        for mode in order:
            progress(f"Lượt {repeat + 1}/{repetitions}: {'TRƯỚC' if mode == 'before' else 'SAU'} tối ưu, {len(sources)} đề; cache TẮT…")
            output = job / f"{repeat + 1}-{mode}"
            output.mkdir()
            tree = root / ("baseline" if mode == "before" else "optimized")
            url = base + ("/benchmark/baseline" if mode == "before" else "/benchmark/after")
            environment = {**os.environ, "PYTHONPATH": str(tree / "src"),
                           "PYTHONIOENCODING": "utf-8", "DOCX_EXTRACT_NATIVE_MATH": "0",
                           "DOCX_EXTRACT_OCR_CACHE": "off", "DOCX_EXTRACT_OCR_TIMEOUT": "120",
                           "DOCX_EXTRACT_OCR_ENDPOINT": url}
            with (output / "worker.log").open("w", encoding="utf-8") as log:
                result = subprocess.run([sys.executable, str(root / "benchmark/worker.py"),
                    "--mode", mode, "--sources", str(sources_path), "--endpoint", url,
                    "--output", str(output)], cwd=tree, env=environment, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError((output / "worker.log").read_text(encoding="utf-8", errors="replace")[-5000:])
            row = json.loads((output / "run.json").read_text(encoding="utf-8"))
            row["repetition"] = repeat + 1
            runs.append(row)
            progress(f"Xong: {row['total_s']:.2f}s; {row['formulas']} MathType; {row['failures']} lỗi OCR; {row['failed_documents']} đề lỗi.")
    differences = []
    if set(modes) == {"before", "after"}:
        for repeat in range(1, repetitions + 1):
            pair = {row["mode"]: row for row in runs if row["repetition"] == repeat}
            differences.append({"repetition": repeat, "documents": compare(pair["before"], pair["after"])})
    summary = summarize(runs)
    report = {"scope": "historical client + historical preprocessing vs current batch pipeline; shared pinned model loader",
              "bundle": json.loads((root / "bundle.json").read_text(encoding="utf-8")),
              "health": health, "cache": "off at client and server", "repetitions": repetitions,
              "timing": "Word parsing + image preparation + real OCR + writing results + ZIP; excludes input upload, model startup and report packaging",
              "summary": summary, "runs": runs, "differences": differences,
              "quality_note": "Matching outputs do not prove OCR accuracy; inspect changed LaTeX and source formulas."}
    valid = bool(differences) and not any(row["documents"] for row in differences) and not any(
        row["failures"] or row["failed_documents"] for row in runs)
    report["comparison_without_detected_differences"] = valid
    if "before" in summary and "after" in summary and summary["after"]["total_s"] > 0:
        report["observed_speedup"] = summary["before"]["total_s"] / summary["after"]["total_s"]
        report["observed_reduction_percent"] = 100 * (1 - summary["after"]["total_s"] / summary["before"]["total_s"])
    report_path = job / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # The downloadable report contains outputs and logs, but not uploaded originals.
    export = job / "download"
    export.mkdir()
    shutil.copy2(report_path, export / "report.json")
    for path in job.glob("*-*/results.zip"):
        shutil.copy2(path, export / (path.parent.name + "-results.zip"))
    for path in job.glob("*-*/worker.log"):
        shutil.copy2(path, export / (path.parent.name + "-worker.log"))
    archive = Path(shutil.make_archive(str(root / ("benchmark-" + job.name)), "zip", export))
    return report, archive
