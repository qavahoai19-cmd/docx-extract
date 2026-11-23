"""File selection and stale-result checks. No GPU/model inference in these tests."""
import builtins
import importlib.util
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


picker_module = load("choose_exam_test", "kaggle_ocr/choose_exam.py")
pipeline = load("choose_exam_real_pipeline_test", "kaggle_ocr/hybrid_ocr_original_fixed.py")
fixtures = load("choose_exam_fixture_helpers", "tests/test_hybrid_formula_images.py")


@pytest.fixture
def inputs(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    math = fixtures.make_docx(folder / "math.docx", [], '<w:p><w:r><w:t>Math content</w:t></w:r></w:p>')
    bio = fixtures.make_docx(folder / "bio.docx", [], '<w:p><w:r><w:t>Biology content, not old Math</w:t></w:r></w:p>')
    return folder, math.resolve(), bio.resolve()


def make_result(folder, source):
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, folder / "input.docx")
    page = folder / "result.html"
    page.write_text("<p>Result for " + source.name + "</p>", encoding="utf-8")
    final = folder / "final.md"
    final.write_text("Result for " + source.name, encoding="utf-8")
    archive = folder / "result.zip"
    archive.write_bytes(b"download fixture, not real archive")
    return dict(results=folder, html=page, final=final, archive=archive, metrics={"total_s": 1.2})


def test_opening_picker_does_not_autoselect_or_run_math(inputs):
    folder, math, bio = inputs
    calls = []
    runner = SimpleNamespace(run=lambda *args, **kwargs: calls.append(args))
    namespace = {"INPUT_DOCX": str(math), "result": {"old": "Math"}}
    picker = picker_module.ExamPicker(namespace, runner=runner, search_root=folder)
    assert picker.choice.value == "" and picker.run_button.disabled
    assert namespace["result"] is None and calls == []
    assert len(picker.choice.options) == 3


def test_selecting_bio_runs_bio_and_replaces_old_result(inputs, tmp_path):
    folder, math, bio = inputs
    calls = []
    namespace = {"INPUT_DOCX": str(math), "RUN_ROOT": str(tmp_path / "runs"), "result": {"old": "Math"}}
    def run(source, root, **kwargs):
        assert namespace["result"] is None
        assert picker.run_button.disabled and "Đang đọc" in picker.run_button.description
        calls.append(source)
        return make_result(tmp_path / "result-bio", source)
    runner = SimpleNamespace(run=run, validate_docx=pipeline.validate_docx, print=builtins.print)
    picker = picker_module.ExamPicker(namespace, runner=runner, search_root=folder)
    picker.choice.value = str(bio)
    assert namespace["INPUT_DOCX"] == str(bio)
    picker.run_button.click()
    assert calls == [bio]
    assert namespace["result"]["source_path"] == str(bio)
    assert "ĐÃ XONG" in picker.status.value and "bio.docx" in picker.status.value
    assert "bio.docx" in str(picker.preview.outputs)
    assert runner.print is builtins.print
    assert not picker.busy and not picker.run_button.disabled


def test_failed_new_exam_cannot_leave_old_result_available(inputs, tmp_path, monkeypatch):
    folder, math, bio = inputs
    namespace = {"result": make_result(tmp_path / "old-math", math)}
    def fail(*args, **kwargs):
        raise RuntimeError("new Bio run failed")
    runner = SimpleNamespace(run=fail, validate_docx=pipeline.validate_docx)
    picker = picker_module.ExamPicker(namespace, runner=runner, search_root=folder)
    # A live Output context suppresses exceptions; execution must not use it.
    monkeypatch.setattr(type(picker.logs), "__exit__", lambda *args: True)
    picker.choice.value = str(bio)
    picker.on_run()
    assert namespace["result"] is None and namespace["CLEAN_HTML"] is None
    assert "new Bio run failed" in picker.status.value
    assert not picker.preview.outputs
    assert not hasattr(runner, "print")


def test_result_containing_wrong_docx_is_not_displayed(inputs, tmp_path):
    folder, math, bio = inputs
    runner = SimpleNamespace(run=lambda *args, **kwargs: make_result(tmp_path / "stale-math", math),
                             validate_docx=pipeline.validate_docx)
    namespace = {}
    picker = picker_module.ExamPicker(namespace, runner=runner, search_root=folder)
    picker.choice.value = str(bio)
    picker.on_run()
    assert namespace["result"] is None
    assert "không khớp" in picker.status.value
    assert not picker.preview.outputs


def test_real_native_only_pipeline_runs_new_selected_source(inputs, tmp_path, monkeypatch):
    pytest.importorskip("pypandoc")
    folder, math, bio = inputs
    private = tmp_path / "private"
    private.mkdir()
    monkeypatch.setattr(pipeline, "ensure_dependencies", lambda root, log: private)
    namespace = {"RUN_ROOT": str(tmp_path / "real-runs")}
    picker = picker_module.ExamPicker(namespace, runner=pipeline, search_root=folder)
    picker.choice.value = str(bio)
    picker.on_run()
    assert namespace["result"] is not None, picker.status.value
    result = namespace["result"]
    assert result["metrics"]["source_name"] == "bio.docx"
    assert result["metrics"]["gpu_inference_ran"] is False
    assert "Biology content, not old Math" in Path(result["html"]).read_text(encoding="utf-8")
    assert (Path(result["results"]) / "input.docx").read_bytes() == bio.read_bytes()


def test_loading_existing_runner_file_does_not_launch_an_exam(tmp_path):
    root = tmp_path / "cached"
    root.mkdir()
    shutil.copyfile(ROOT / "kaggle_ocr/hybrid_ocr_original_fixed.py", root / "hybrid_ocr_original_fixed.py")
    namespace = {"RUN_ROOT": str(root)}
    runner = picker_module.load_existing_pipeline(namespace)
    assert callable(runner.run) and namespace["pipeline"] is runner
    assert not (root / "runs").exists()
