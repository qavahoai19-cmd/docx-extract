"""Input/UI regression checks; these are not model-inference benchmarks."""
import ast
import builtins
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import symtable
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "kaggle_ocr" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


app = load_module("hybrid_clean_app_test", "hybrid_clean_app.py")
builder = load_module("hybrid_clean_builder_test", "build_hybrid_clean_notebook.py")


@pytest.fixture
def docx(tmp_path):
    path = tmp_path / "exam.docx"
    path.write_bytes((ROOT / "tests/fixtures/sample.docx").read_bytes())
    return path


@pytest.fixture
def headless(monkeypatch):
    pytest.importorskip("ipywidgets")
    import IPython.display
    monkeypatch.setattr(IPython.display, "display", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "discover_docx", lambda roots: [])
    monkeypatch.setattr(app, "gpu_status", lambda: (True, "Test GPU state; not inference"))


def test_rejects_empty_directory_and_fake_docx(tmp_path, docx):
    fake = tmp_path / "fake.docx"
    fake.write_bytes(b"not a zip archive")
    for value in (None, "", tmp_path, fake):
        with pytest.raises(app.InputProblem):
            app.validate_docx(value)
    assert app.validate_docx(docx) == docx.resolve()


@pytest.mark.parametrize("version", [7, 8])
def test_real_docx_upload_widget_formats_and_idempotency(tmp_path, docx, version):
    content = docx.read_bytes()
    payload = ({"exam.docx": {"metadata": {"name": "../exam.docx"}, "content": content}}
               if version == 7 else ({"name": "../exam.docx", "content": memoryview(content)},))
    folder = tmp_path / "uploads"
    saved = app.save_upload(payload, folder)
    assert saved.parent == folder.resolve()
    assert saved.read_bytes() == content
    assert app.save_upload(payload, folder) == saved
    assert len(list(folder.iterdir())) == 1
    assert app.save_upload((), folder) is None


def test_discovery_in_nested_datasets_and_duplicate_roots(tmp_path, docx):
    nested = tmp_path / "input" / "datasets" / "owner" / "exam"
    nested.mkdir(parents=True)
    uploaded = nested / "MATH.DOCX"
    uploaded.write_bytes(docx.read_bytes())
    assert app.discover_docx([tmp_path / "input", nested]) == [uploaded.resolve()]


def test_fresh_ui_does_not_run_without_input(tmp_path, headless, monkeypatch):
    calls = []
    monkeypatch.setattr(app, "run_job", lambda *args, **kwargs: calls.append(args))
    ui = app.launch(tmp_path / "app", "unused worker")
    assert ui.selected is None
    assert ui.run_button.disabled
    ui.on_run()
    assert calls == []
    assert ui.run_button.disabled


def test_missing_gpu_disables_run_even_with_valid_file(tmp_path, docx, headless, monkeypatch):
    monkeypatch.setattr(app, "gpu_status", lambda: (False, "CUDA unavailable"))
    ui = app.HybridApp(tmp_path / "app", "unused worker")
    ui.select(docx)
    assert ui.selected == docx.resolve()
    assert ui.run_button.disabled


def test_dataset_auto_selection_refresh_and_restart(tmp_path, docx, headless, monkeypatch):
    monkeypatch.setattr(app, "discover_docx", lambda roots: [docx.resolve()])
    ui = app.HybridApp(tmp_path / "app", "unused worker")
    assert ui.selected == docx.resolve()
    assert not ui.run_button.disabled
    ui.refresh()
    assert ui.selected == docx.resolve()
    monkeypatch.setattr(app, "discover_docx", lambda roots: [])
    reused = app.HybridApp(tmp_path / "app", "unused worker")
    assert reused.selected == docx.resolve()
    assert not reused.run_button.disabled


def test_actual_widget_upload_enables_run_and_preserves_content(tmp_path, docx, headless):
    ui = app.HybridApp(tmp_path / "app", "unused worker")
    raw = docx.read_bytes()
    ui.upload.value = ({"name": "exam.docx", "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "size": len(raw), "content": memoryview(raw),
                        "last_modified": datetime.now(timezone.utc)},)
    assert ui.selected.read_bytes() == raw
    assert not ui.run_button.disabled


def test_invalid_new_upload_cannot_leave_old_file_ready(tmp_path, docx, headless):
    ui = app.HybridApp(tmp_path / "app", "unused worker")
    ui.select(docx)
    ui.on_upload({"new": ({"name": "wrong.docx", "content": b"not a DOCX"},)})
    assert ui.selected is None and ui.run_button.disabled


def test_dataset_selection_is_not_overridden_by_previous_upload(tmp_path, docx, headless, monkeypatch):
    ui = app.HybridApp(tmp_path / "app", "unused worker")
    raw = docx.read_bytes()
    ui.upload.value = ({"name": "upload.docx", "type": "application/octet-stream",
                        "size": len(raw), "content": memoryview(raw),
                        "last_modified": datetime.now(timezone.utc)},)
    assert ui.source_kind == "upload"
    ui.on_dataset({"new": str(docx)})
    assert ui.source_kind == "dataset"
    received = []
    def stop_after_source(source, *args, **kwargs):
        received.append(source)
        raise RuntimeError("intentional plumbing-test stop, no model executed")
    monkeypatch.setattr(app, "run_job", stop_after_source)
    ui.on_run()
    assert received == [docx.resolve()]


@pytest.mark.parametrize("unprocessed", [0, 1])
def test_click_run_uses_selected_file_and_returns_controls(tmp_path, docx, headless, monkeypatch, unprocessed):
    ui = app.HybridApp(tmp_path / "app", "embedded worker")
    ui.select(docx)
    results = tmp_path / "result"
    results.mkdir()
    (results / "final.md").write_text("CPU/UI plumbing fixture, not OCR output", encoding="utf-8")
    metrics = dict(gpu_inference_ran=False, unique_ocr_images=0, ocr_successes=0,
                   parse_preprocess_s=0.1, model_load_s=0.0, ocr_s=0.0,
                   images_in_docx=1, images_unprocessed=unprocessed, vector_images=1, native_word_equations=0)
    (results / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (results / "image-report.json").write_text("{}", encoding="utf-8")
    archive = tmp_path / "result.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.write(results / "final.md", "final.md")
    calls = []
    def fake_runner(source, root, worker_source, emit):
        calls.append((source, root, worker_source))
        return dict(results=results, archive=archive, metrics=metrics)
    monkeypatch.setattr(app, "run_job", fake_runner)
    ui.run_button.click()
    assert calls == [(docx.resolve(), ui.root, "embedded worker")]
    assert ui.last_result["archive"] == archive
    assert not ui.busy and not ui.run_button.disabled and not ui.upload.disabled
    assert ("cần kiểm tra 1" if unprocessed else "Hoàn tất") in ui.status.value
    assert "ĐÃ XONG" in ui.status.value
    assert ui.run_button.description == "Chạy OCR lại"


def test_real_runner_does_not_install_before_gpu_validation(tmp_path, docx, monkeypatch):
    monkeypatch.setattr(app, "gpu_status", lambda: (False, "No CUDA"))
    def forbidden(*args, **kwargs):
        pytest.fail("dependency installation ran without a usable GPU")
    monkeypatch.setattr(app, "ensure_dependencies", forbidden)
    with pytest.raises(app.InputProblem, match="No CUDA"):
        app.run_job(docx, tmp_path / "app", "unused")


def test_dependency_install_is_private_and_excludes_torch_resolution(tmp_path, monkeypatch):
    calls = []
    def fake_command(command, **kwargs):
        calls.append((command, kwargs))
    monkeypatch.setattr(app, "stream_command", fake_command)
    before_path = list(sys.path)
    target = app.ensure_dependencies(tmp_path, io.StringIO(), lambda line: None)
    install, check = calls
    assert "--target" in install[0] and "--no-deps" in install[0]
    assert not any(requirement.partition("=")[0] in {"torch", "torchvision"} for requirement in app.REQUIREMENTS)
    assert check[1]["env"]["PYTHONPATH"] != os.environ.get("PYTHONPATH")
    assert target.is_dir() and (target / "ready.json").is_file()
    assert sys.path == before_path
    calls.clear()
    assert app.ensure_dependencies(tmp_path, io.StringIO(), lambda line: None) == target
    assert calls == []


def test_new_notebook_is_self_contained_and_does_not_reuse_old_globals(tmp_path, headless, monkeypatch):
    target = builder.build(tmp_path / "clean.ipynb")
    notebook = json.loads(target.read_text(encoding="utf-8"))
    assert [c["cell_type"] for c in notebook["cells"]] == ["markdown", "code"]
    source = "".join(notebook["cells"][1]["source"])
    compile(source, "new-notebook", "exec")
    parsed = ast.parse(source)
    for node in parsed.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "WORKER_SOURCE" for t in node.targets):
            compile(ast.literal_eval(node.value), "embedded-worker", "exec")
    def forbidden(*args, **kwargs):
        pytest.fail("Run All must not start OCR or install model dependencies")
    monkeypatch.setattr(app.subprocess, "run", forbidden)
    monkeypatch.setattr(app.subprocess, "Popen", forbidden)
    namespace = dict(HYBRID_APP_ROOT=str(tmp_path / "notebook"),
                     INPUT_FOLDER="invalid-old-folder", INPUT_NAME="invalid-old-name", choose_docx=forbidden)
    exec(compile(source, "new-notebook", "exec"), namespace)
    ui = namespace["hybrid_app"]
    assert ui.selected is None and ui.run_button.disabled
    assert namespace["INPUT_FOLDER"] == "invalid-old-folder"


def test_worker_preserves_attachment_model_and_inference_configuration():
    legacy = (ROOT / "kaggle_ocr/hybrid_ocr_test.py").read_text(encoding="utf-8")
    worker = (ROOT / "kaggle_ocr/hybrid_clean_worker.py").read_text(encoding="utf-8")
    def inference_calls(source):
        calls = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if isinstance(node.func.value, ast.Name) and (
                (node.func.value.id in {"AutoModel", "AutoTokenizer"} and node.func.attr == "from_pretrained")
                or (node.func.value.id == "model" and node.func.attr == "infer")
            ):
                calls.append(ast.dump(node))
        return calls
    assert inference_calls(legacy) == inference_calls(worker)
    assert 'MODEL_NAME = "deepseek-ai/DeepSeek-OCR"' in worker
    assert "if w < 80 or h < 80" not in worker
    assert "image_plan = prepare_image_plan(" in worker
    compile(worker, "worker", "exec")


def test_worker_has_no_unbound_global_references():
    source = (ROOT / "kaggle_ocr/hybrid_clean_worker.py").read_text(encoding="utf-8")
    table = symtable.symtable(source, "worker", "exec")
    bound = {symbol.get_name() for symbol in table.get_symbols()
             if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()}
    allowed = bound | set(dir(builtins)) | {"__name__", "__file__", "__builtins__"}
    unresolved = set()
    def visit(scope):
        for symbol in scope.get_symbols():
            if symbol.is_referenced() and symbol.is_global() and symbol.get_name() not in allowed:
                unresolved.add(symbol.get_name())
        for child in scope.get_children():
            visit(child)
    visit(table)
    assert not unresolved, "Worker references names it never imports/defines: " + repr(unresolved)


def test_kernel_output_suppression_cannot_hide_worker_failure(tmp_path, docx, headless, monkeypatch):
    ui = app.HybridApp(tmp_path / "app", "unused worker")
    ui.select(docx)
    # A live IPython kernel's Output.__exit__ suppresses exceptions. Headless
    # Output normally does not, which is why the original tests missed this.
    monkeypatch.setattr(type(ui.logs), "__exit__", lambda *args: True)
    def fail(*args, **kwargs):
        raise RuntimeError("original child-process failure, not a None result")
    monkeypatch.setattr(app, "run_job", fail)
    ui.on_run()
    assert "original child-process failure" in ui.status.value
    assert "NoneType" not in ui.status.value
    assert ui.last_result is None
    assert not ui.busy and not ui.run_button.disabled


def test_subprocess_failure_includes_actual_stderr(tmp_path):
    with (tmp_path / "run.log").open("w", encoding="utf-8") as log:
        with pytest.raises(RuntimeError, match="specific dependency failure"):
            app.stream_command(
                [sys.executable, "-c", "raise ImportError('specific dependency failure')"],
                env=os.environ.copy(), cwd=tmp_path, log=log, emit=lambda line: None,
            )
    assert "ImportError: specific dependency failure" in (tmp_path / "run.log").read_text(encoding="utf-8")


def test_silent_child_reports_live_pid_before_it_finishes(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "HEARTBEAT_SECONDS", 0.05, raising=False)
    finished = tmp_path / "finished.txt"
    heartbeats = []
    def receive(line):
        if line.startswith("@@HYBRID_PROGRESS@@"):
            event = json.loads(line.removeprefix("@@HYBRID_PROGRESS@@"))
            if event["event"] == "heartbeat":
                heartbeats.append((event, finished.exists()))
    with (tmp_path / "run.log").open("w", encoding="utf-8") as log:
        app.stream_command(
            [sys.executable, "-c", "import time,pathlib; time.sleep(0.4); pathlib.Path('finished.txt').touch()"],
            env=os.environ.copy(), cwd=tmp_path, log=log, emit=receive,
            step="Quiet installation test, no packages installed",
        )
    assert heartbeats, "Silent child produced no progress until it exited"
    assert any(not was_finished for event, was_finished in heartbeats)
    assert all(event["pid"] > 0 and event["silence_s"] >= 0 for event, _ in heartbeats)


def test_running_ui_names_stage_and_changes_label_without_relying_on_colour(tmp_path, docx, headless, monkeypatch):
    ui = app.HybridApp(tmp_path / "app", "unused worker")
    ui.select(docx)
    def runner(source, root, worker_source, emit):
        assert ui.run_button.disabled and "Đang chạy" in ui.run_button.description
        emit("Ảnh WMF/EMF/SVG: đang cài LibreOffice Draw lần đầu…")
        assert "Cài LibreOffice Draw" in ui.status.value
        emit('@@HYBRID_PROGRESS@@' + json.dumps(dict(event="heartbeat", pid=12345, elapsed_s=60, silence_s=50)))
        assert "12345" in ui.status.value and "50s" in ui.status.value
        emit("  BUOC 3: OCR 17 anh")
        emit("  [2/17] formula.png")
        assert "2/17" in ui.status.value
        raise RuntimeError("intentional UI-test stop, no OCR inference")
    monkeypatch.setattr(app, "run_job", runner)
    ui.on_run()
    assert "LỖI" in ui.status.value
    assert "intentional UI-test stop" in ui.status.value
    assert "Thử lại" in ui.run_button.description and not ui.run_button.disabled


def test_interruption_does_not_leave_ui_saying_it_is_running(tmp_path, docx, headless, monkeypatch):
    ui = app.HybridApp(tmp_path / "app", "unused worker")
    ui.select(docx)
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(app, "run_job", interrupt)
    ui.on_run()
    assert "ĐÃ DỪNG" in ui.status.value
    assert "ĐANG CHẠY" not in ui.status.value
    assert not ui.busy and not ui.run_button.disabled
    assert ui.run_button.description == "Thử lại OCR"


def test_real_failed_worker_retains_log_and_stage(tmp_path, docx, monkeypatch):
    # Execute a genuine failing Python subprocess, not an OCR/model mock.
    monkeypatch.setattr(app, "gpu_status", lambda: (True, "test environment state"))
    monkeypatch.setattr(app, "ensure_dependencies", lambda root, log, emit: tmp_path / "private")
    with pytest.raises(app.JobFailure, match="child import failed") as caught:
        app.run_job(docx, tmp_path / "app", "raise ImportError('child import failed')", emit=lambda line: None)
    error = caught.value
    assert error.log_path.is_file()
    text = error.log_path.read_text(encoding="utf-8")
    assert "ImportError: child import failed" in text
    assert "Pandoc + DeepSeek-OCR" in text
    assert "mã 1" in str(error)


def test_failure_log_is_downloadable_and_old_results_cleared(tmp_path, docx, headless, monkeypatch):
    ui = app.HybridApp(tmp_path / "app", "unused worker")
    ui.select(docx)
    ui.last_result = {"old": "must not reuse this"}
    log_path = tmp_path / "run.log"
    log_path.write_text("Original traceback from subprocess", encoding="utf-8")
    monkeypatch.setattr(type(ui.logs), "__exit__", lambda *args: True)
    def fail(*args, **kwargs):
        raise app.JobFailure("dependency import failed", log_path)
    monkeypatch.setattr(app, "run_job", fail)
    ui.run_button.click()
    assert ui.last_result is None
    assert "dependency import failed" in ui.status.value
    assert "NoneType" not in ui.status.value
    rich = [output.get("data", {}).get("text/html", "") for output in ui.results.outputs]
    assert any('download="run.log"' in text for text in rich)
    assert not ui.run_button.disabled


def test_none_return_is_reported_without_subscript_error(tmp_path, docx, headless, monkeypatch):
    ui = app.HybridApp(tmp_path / "app", "unused worker")
    ui.select(docx)
    monkeypatch.setattr(app, "run_job", lambda *args, **kwargs: None)
    ui.on_run()
    assert "NoneType" not in ui.status.value
    assert "không trả về kết quả hợp lệ" in ui.status.value
    assert ui.last_result is None


def test_print_preview_has_downloads_and_never_reads_upscaled_markdown(tmp_path, headless):
    ui = app.HybridApp(tmp_path / "app", "unused worker")
    results = tmp_path / "printed"
    results.mkdir()
    (results / "de-thi.html").write_text('<p id="source-print">Source proportions</p>', encoding="utf-8")
    (results / "doi-chieu-ocr.html").write_text("OCR comparison", encoding="utf-8")
    (results / "de-thi-goc.pdf").write_bytes(b"%PDF-1.4\nTest download only")
    # Deliberately no final.md: falling back to the OCR-raster preview must fail.
    archive = tmp_path / "result.zip"
    with zipfile.ZipFile(archive, "w"):
        pass
    metrics = dict(gpu_inference_ran=False, unique_ocr_images=0, ocr_successes=0,
                   parse_preprocess_s=0.1, model_load_s=0, ocr_s=0, print_export_s=0.2)
    ui.render_success(dict(results=results, archive=archive, metrics=metrics))
    rich = "\n".join(output.get("data", {}).get("text/html", "") for output in ui.results.outputs)
    assert '<iframe title="Bản đề in"' in rich
    assert 'id=&quot;source-print&quot;' in rich
    for name in ("de-thi.html", "doi-chieu-ocr.html", "de-thi-goc.pdf"):
        assert 'download="' + name + '"' in rich
