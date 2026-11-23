"""Syntax, faithful inference settings and CPU execution; not a GPU benchmark."""
import ast
from contextlib import nullcontext
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import warnings

from PIL import Image
import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixed = load("original_fixed_test", "kaggle_ocr/hybrid_ocr_original_fixed.py")
builder = load("original_fixed_builder_test", "kaggle_ocr/build_hybrid_original_fixed_notebook.py")
fixtures = load("original_fixed_fixture_helpers", "tests/test_hybrid_formula_images.py")


def test_whole_source_and_embedded_notebook_compile_without_escape_warnings(tmp_path):
    path = ROOT / "kaggle_ocr/hybrid_ocr_original_fixed.py"
    source = path.read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        compile(source, str(path), "exec")
        notebook = json.loads(builder.build(tmp_path / "ready.ipynb").read_text(encoding="utf-8"))
        cell = "".join(notebook["cells"][1]["source"])
        compile(cell, "notebook-cell", "exec")
    embedded = next(ast.literal_eval(node.value) for node in ast.parse(cell).body
                    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "SCRIPT_SOURCE" for target in node.targets))
    assert embedded == source
    assert "&#xA;" not in source and "&#x20;" not in source
    assert 'picker_namespace["show_exam_picker"](globals(), pipeline)' in cell
    top_calls = [node for node in ast.parse(cell).body if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)]
    assert not any(isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "run" for node in top_calls)
    assert "preserve_upload" not in source and "ipywidgets" not in source
    assert "libreoffice" not in str(fixed.REQUIREMENTS).lower()


@pytest.mark.parametrize("text", ["$x*y$", r"$\mathbf{A}(1+2)$",
                                   r"$\left\{\begin{matrix}x & y\\z & t\end{matrix}\right.$"])
def test_postprocessing_does_not_rewrite_math(text):
    assert fixed.clean_pandoc_output(text) == text
    assert fixed.clean_ocr(text) == text


@pytest.mark.parametrize("text", ["x", "0", "π", r"$\frac{1}{2}$"])
def test_valid_short_formula_does_not_force_a_retry(text):
    assert fixed.clean_ocr(text) == text


def test_original_size_branches_still_reachable_after_preprocessing(tmp_path):
    source = tmp_path / "formula.png"
    source.write_bytes(fixtures.png_formula())
    prepared = tmp_path / "prepared.png"
    size = fixed.preprocess_for_ocr(fixed.load_rgb(source), prepared)
    assert max(size) <= 350
    assert fixed.ocr_configs(size)[0]["image_size"] in {384, 448}
    assert [cfg["image_size"] for cfg in fixed.ocr_configs((100, 50))] == [384]
    assert [cfg["image_size"] for cfg in fixed.ocr_configs((300, 50))] == [448, 512, 640]
    assert [cfg["image_size"] for cfg in fixed.ocr_configs((800, 50))] == [512, 640, 448]
    assert all(cfg["crop_mode"] is False for cfg in fixed.ocr_configs((800, 50)))


def test_small_valid_formula_is_not_dropped_and_diagram_policy_is_explicit(tmp_path, monkeypatch):
    source = tmp_path / "formula.png"
    source.write_bytes(fixtures.png_formula())
    records, _ = fixed.plan_images("![](formula.png)", tmp_path)
    assert records[0]["status"] == "queued"
    records, _ = fixed.plan_images("![](formula.png)", tmp_path, ocr_small_images=False)
    assert records[0]["status"] == "small_skipped"
    monkeypatch.setattr(fixed, "analyze_image_for_ocr", lambda image: "diagram")
    records, _ = fixed.plan_images("![](formula.png)", tmp_path)
    assert records[0]["status"] == "diagram_kept"
    records, _ = fixed.plan_images("![](formula.png)", tmp_path, ocr_diagrams=True)
    assert records[0]["status"] == "queued"


def test_undecodable_vector_is_reported_and_kept_not_replaced_with_fake_ocr(tmp_path):
    source = tmp_path / "formula.wmf"
    source.write_bytes(b"Unsupported vector fixture")
    records, by_ref = fixed.plan_images("![](formula.wmf)", tmp_path)
    assert records[0]["status"] == "unsupported"
    assert records[0]["error"]
    assert fixed.build_final("![](formula.wmf)", by_ref) == "![](formula.wmf)"
    assert source.read_bytes() == b"Unsupported vector fixture"


def test_deduplicates_equal_pixels_and_does_not_read_paths_outside_run(tmp_path):
    (tmp_path / "a.png").write_bytes(fixtures.png_formula())
    (tmp_path / "b.png").write_bytes(fixtures.png_formula())
    records, _ = fixed.plan_images("![](a.png) ![](b.png) ![](../outside.png)", tmp_path)
    assert [record["status"] for record in records] == ["queued", "duplicate", "missing"]


def test_fixed_stopper_is_constructible_callable_and_reinitialisable():
    tokenizer = SimpleNamespace(decode=lambda *args, **kwargs: "&& && && &&")
    stopper = fixed.make_stopper(tokenizer, object)
    ids = np.zeros((1, 100), dtype=int)
    assert callable(stopper) and stopper.step == 0
    for _ in range(14):
        assert stopper(ids, None) is False
    assert stopper(ids, None) is True
    stopper.step = 0
    assert stopper(ids, None) is False


def test_model_inference_keeps_prompt_and_returns_short_formula_on_first_try(tmp_path):
    calls = []
    class FakeModel:
        def infer(self, tokenizer, **kwargs):
            calls.append(kwargs)
            destination = Path(kwargs["output_path"])
            destination.mkdir(parents=True)
            (destination / "result.mmd").write_text("x", encoding="utf-8")
    fake_torch = SimpleNamespace(inference_mode=nullcontext,
                                cuda=SimpleNamespace(OutOfMemoryError=MemoryError, empty_cache=lambda: None))
    record = dict(prepared_size=[100, 40], prepared_path="fixture.png", attempts=[])
    fixed.infer_image(FakeModel(), object(), record, tmp_path / "ocr", fake_torch)
    assert len(calls) == 1
    assert calls[0]["prompt"] == "<image>\nFree OCR."
    assert calls[0]["base_size"] == calls[0]["image_size"] == 384
    assert calls[0]["crop_mode"] is False
    assert calls[0]["save_results"] is True and calls[0]["test_compress"] is False
    assert record["ocr_text"] == "x" and record["status"] == "ocr_text_returned"
    assert fixed.MODEL_NAME == "deepseek-ai/DeepSeek-OCR" and fixed.MAX_NEW_TOKENS == 1000
    source = (ROOT / "kaggle_ocr/hybrid_ocr_original_fixed.py").read_text(encoding="utf-8")
    assert "torch_dtype=torch.bfloat16" in source and 'attn_implementation="eager"' in source


def test_actual_ocr_is_in_final_output_without_modifying_source_image_attributes():
    source = '$x*y$\n\n![](formula.png){width="1in" height="0.25in"}'
    by_ref = {"formula.png": {"ocr_text": "$$x*y\\n+1$$"}}
    result = fixed.build_final(source, by_ref)
    assert source in result
    assert "[OCR — cần đối chiếu]" in result
    assert "x*y" in result


def test_html_table_output_is_preserved_as_a_markdown_table():
    assert fixed.clean_ocr('<table><tr><td>A</td><td>B</td></tr><tr><td>$x*y$</td><td>2</td></tr></table>') == (
        '| A | B |\n| --- | --- |\n| $x*y$ | 2 |')


def test_ocr_table_is_reconstructed_for_print_not_flattened_after_label(tmp_path):
    pypandoc = pytest.importorskip("pypandoc")
    (tmp_path / "table.png").write_bytes(fixtures.png_formula())
    table = '| Group | Representative | Frequency |\n| --- | --- | --- |\n| \\( [a_1;a_2) \\) | \\(x_1\\) | \\(n_1\\) |\n| | | \\(n\\) |\n\nTable 1'
    markdown = fixed.build_final('BEFORE\n\n![](table.png)\n\nAFTER', {"table.png": {"ocr_text": table}})
    final = tmp_path / "final.md"
    final.write_text(markdown, encoding="utf-8")
    page = fixed.export_html(final, ROOT / "tests/fixtures/sample.docx", pypandoc.get_pandoc_path()).read_text(encoding="utf-8")
    assert '<table>' in page
    assert page.count('<th>') == 3 and page.count('<td>') == 6
    assert 'class="ocr-pair ocr-table"' in page
    assert 'class="ocr-source"' in page and 'class="ocr-rendered"' in page
    assert '<msub>' in page
    assert page.index('BEFORE') < page.index('<table>') < page.index('AFTER')
    assert '.ocr-source{display:none!important}' in page
    assert 'thead{display:table-header-group}' in page
    assert 'class="ocr-caption"' in page


def test_inline_ocr_math_replaces_only_the_image_position_and_keeps_native_math(tmp_path):
    pypandoc = pytest.importorskip("pypandoc")
    (tmp_path / "formula.png").write_bytes(fixtures.png_formula())
    markdown = fixed.build_final('BEFORE ![](formula.png) AFTER $a*b$', {"formula.png": {"ocr_text": r'\(x_1+1\)'}})
    final = tmp_path / "final.md"
    final.write_text(markdown, encoding="utf-8")
    page = fixed.export_html(final, ROOT / "tests/fixtures/sample.docx", pypandoc.get_pandoc_path()).read_text(encoding="utf-8")
    assert 'class="ocr-pair ocr-math"' in page
    assert page.index('BEFORE') < page.index('class="ocr-pair ocr-math"') < page.index('AFTER')
    assert '<msub>' in page and 'a*b' in page


def test_uncertain_unstructured_text_does_not_replace_the_figure(tmp_path):
    pypandoc = pytest.importorskip("pypandoc")
    (tmp_path / "figure.png").write_bytes(fixtures.png_formula())
    final = tmp_path / "final.md"
    final.write_text(fixed.build_final('![](figure.png)', {"figure.png": {"ocr_text": "UNSTRUCTURED_REVIEW_TEXT"}}), encoding="utf-8")
    page = fixed.export_html(final, ROOT / "tests/fixtures/sample.docx", pypandoc.get_pandoc_path()).read_text(encoding="utf-8")
    assert 'class="ocr-notes"' in page and 'UNSTRUCTURED_REVIEW_TEXT' in page
    assert 'data:image/png;base64,' in page
    assert '.ocr-notes{display:none!important}' in page


def test_real_pandoc_output_page_contains_actual_recognition_and_native_math(tmp_path):
    pypandoc = pytest.importorskip("pypandoc")
    source = ROOT / "tests/fixtures/sample.docx"
    (tmp_path / "formula.png").write_bytes(fixtures.png_formula())
    final = tmp_path / "final.md"
    final.write_text('$x*y$\n\n![](formula.png){width="1in" height="0.25in"}\n\n> **[OCR — cần đối chiếu]**\n> OCR_SENTINEL $x+1$\n\n<script>alert(1)</script>', encoding="utf-8")
    result = fixed.export_html(final, source, pypandoc.get_pandoc_path())
    page = result.read_text(encoding="utf-8")
    assert "OCR_SENTINEL" in page and "<math" in page and "data:image/png;base64," in page
    assert "<script>" not in page
    assert "window.print()" in page


def test_real_native_only_worker_finishes_without_importing_or_claiming_gpu_inference(tmp_path, monkeypatch):
    pytest.importorskip("pypandoc")
    source = fixtures.make_docx(tmp_path / "native.docx", [],
        '<w:p><w:r><w:t>Native-only CPU fixture</w:t></w:r></w:p>'
        '<w:p><m:oMath><m:r><m:t>x+1</m:t></m:r></m:oMath></w:p>')
    # A sentinel makes accidental Torch access fail immediately in this CPU test.
    import sys
    monkeypatch.setitem(sys.modules, "torch", None)
    result = fixed.run_worker(source, tmp_path / "result")
    assert result["metrics"]["gpu_inference_ran"] is False
    assert result["metrics"]["ocr_text_returned"] == 0
    assert result["metrics"]["native_word_equations_main_doc"] == 1
    assert (tmp_path / "result/input.docx").read_bytes() == source.read_bytes()
    assert "<math" in Path(result["html"]).read_text(encoding="utf-8")


def test_dependency_setup_is_private_and_reuses_ready_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fixed, "stream_command", lambda command, **kwargs: calls.append((command, kwargs)))
    dependencies = fixed.ensure_dependencies(tmp_path, io.StringIO())
    assert "--no-deps" in calls[0][0] and "--target" in calls[0][0]
    assert not any(requirement.split("=")[0] in {"torch", "torchvision"} for requirement in fixed.REQUIREMENTS)
    assert calls[1][1]["env"]["PYTHONPATH"].startswith(str(dependencies.parent))
    calls.clear()
    assert fixed.ensure_dependencies(tmp_path, io.StringIO()) == dependencies
    assert calls == []


def test_pasting_whole_python_file_into_one_cell_can_start_worker(tmp_path, monkeypatch):
    import IPython
    source = (ROOT / "kaggle_ocr/hybrid_ocr_original_fixed.py").read_text(encoding="utf-8")
    monkeypatch.delattr(fixed, "__file__")
    shell = SimpleNamespace(history_manager=SimpleNamespace(input_hist_raw=["", source]))
    monkeypatch.setattr(IPython, "get_ipython", lambda: shell)
    path = fixed.self_script_path(tmp_path)
    assert path.read_text(encoding="utf-8") == source
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_result_display_includes_recognized_content_and_downloads(tmp_path, monkeypatch):
    import IPython.display
    shown = []
    monkeypatch.setattr(IPython.display, "display", lambda value: shown.append(value))
    page = tmp_path / "ket-qua-ocr.html"
    page.write_text("<p>ACTUAL_OCR_SENTINEL</p>", encoding="utf-8")
    markdown = tmp_path / "final.md"
    markdown.write_text("ACTUAL_OCR_SENTINEL", encoding="utf-8")
    archive = tmp_path / "result.zip"
    archive.write_bytes(b"test download only")
    fixed.display_result(dict(results=tmp_path, html=page, final=markdown, archive=archive))
    rendered = "\n".join(value._repr_html_() for value in shown)
    assert "ACTUAL_OCR_SENTINEL" in rendered
    assert '<iframe' in rendered and 'title="Kết quả trích xuất và OCR"' in rendered
    assert 'download="final.md"' in rendered and 'download="result.zip"' in rendered


def test_real_parent_worker_and_zip_flow_without_gpu_for_native_only_docx(tmp_path, monkeypatch):
    pytest.importorskip("pypandoc")
    source = fixtures.make_docx(tmp_path / "input.docx", [], '<w:p><w:r><w:t>CPU subprocess test, no OCR inference</w:t></w:r></w:p>')
    dependencies = tmp_path / "private"
    dependencies.mkdir()
    monkeypatch.setattr(fixed, "ensure_dependencies", lambda root, log: dependencies)
    result = fixed.run(source, tmp_path / "app")
    assert result["final"].is_file() and result["html"].is_file()
    assert result["metrics"]["gpu_inference_ran"] is False
    import zipfile
    with zipfile.ZipFile(result["archive"]) as archive:
        assert {"final.md", "ket-qua-ocr.html", "input.docx", "run.log", "metrics.json", "image-report.json"}.issubset(archive.namelist())
        assert archive.read("input.docx") == source.read_bytes()
        assert archive.namelist().count("metrics.json") == 1
        saved_metrics = json.loads(archive.read("metrics.json"))
        assert saved_metrics == result["metrics"]
    assert result["metrics"]["total_s"] >= result["metrics"]["total_before_zip_s"]
    assert result["metrics"]["zip_s"] >= 0


def test_total_time_is_displayed_without_rerunning_ocr(tmp_path, monkeypatch, capsys):
    import IPython.display
    monkeypatch.setattr(IPython.display, "display", lambda value: None)
    page = tmp_path / "result.html"
    page.write_text("<p>saved OCR</p>", encoding="utf-8")
    final = tmp_path / "final.md"
    final.write_text("saved OCR", encoding="utf-8")
    archive = tmp_path / "result.zip"
    archive.write_bytes(b"download fixture")
    metrics = dict(total_s=83.5, dependency_setup_s=10, model_load_s=20,
                   parse_preprocess_s=0.5, ocr_s=50, export_s=1, zip_s=2)
    fixed.display_result(dict(html=page, final=final, archive=archive, results=tmp_path, metrics=metrics))
    text = capsys.readouterr().out
    assert "TỔNG THỜI GIAN ĐÃ CHẠY" in text
    assert "83.50" in text and "1 phút 23.50 giây" in text
    assert "Đóng ZIP" in text


def test_older_results_report_total_without_pretending_zip_was_measured(capsys):
    fixed.print_timing(dict(total_before_zip_s=90))
    text = capsys.readouterr().out
    assert "90.00" in text
    assert "chưa gồm đóng ZIP" in text


@pytest.mark.parametrize("text", ["y\n1\n2\nO\n-2\n-1\nx\n5\n2\n1\n2", "y x O -2 -1 2 -2 -3"])
def test_plot_axis_labels_are_not_inserted_as_an_equation(text):
    assert fixed.is_plot_label_list(text)
    record = dict(ocr_text=text, raw_ocr=text)
    assert fixed.build_final("![](plot.png)", {"plot.png": record}) == "![](plot.png)"
    assert record["raw_ocr"] == text  # Never destroy the recognition evidence.


@pytest.mark.parametrize("text", ["$x*y$", "$y=x+1$", "x = 1", r"$\begin{matrix}x & y\\1 & 2\end{matrix}$", "x y -1", "x", "0"])
def test_plot_label_filter_does_not_remove_formulas(text):
    assert not fixed.is_plot_label_list(text)
    assert text in fixed.build_final("![](formula.png)", {"formula.png": dict(ocr_text=text)})


def test_coordinate_grid_is_a_diagram_but_table_stays_readable(tmp_path):
    from PIL import ImageDraw
    plot = Image.new("RGB", (241, 241), "white")
    draw = ImageDraw.Draw(plot)
    for position in range(10, 240, 30):
        draw.line((position, 0, position, 240), fill=(220, 220, 220))
        draw.line((0, position, 240, position), fill=(220, 220, 220))
    draw.line((100, 0, 100, 240), fill="black")
    draw.line((0, 100, 240, 100), fill="black")
    draw.line((40, 200, 100, 100, 180, 40), fill="black", width=2)
    plot.save(tmp_path / "plot.png")
    assert fixed.analyze_image_for_ocr(plot) == "coordinate_plot"
    records, _ = fixed.plan_images("![](plot.png)", tmp_path)
    assert records[0]["status"] == "diagram_kept"
    records, _ = fixed.plan_images("![](plot.png)", tmp_path, ocr_diagrams=True)
    assert records[0]["status"] == "queued"
    assert records[0]["render_policy"] == "reference_only"
    table = Image.new("RGB", (241, 241), "white")
    draw = ImageDraw.Draw(table)
    for position in range(0, 241, 30):
        draw.line((position, 0, position, 240), fill="black")
        draw.line((0, position, 240, position), fill="black")
    assert not fixed.is_coordinate_plot(table)


def test_existing_html_repair_only_removes_ocr_axis_label_blocks():
    bad = '<blockquote><p><strong>[OCR — cần đối chiếu]</strong> y<br>1<br>2<br>O<br>-2<br>-1<br>x<br>5</p></blockquote>'
    good = '<blockquote><p><strong>[OCR — cần đối chiếu]</strong> x = 1</p></blockquote>'
    other = '<blockquote><p>y x O -2 -1 2 -2 -3</p></blockquote>'
    page = '<html><body><img src="plot.png">' + bad + good + other + '</body></html>'
    cleaned, removed = fixed.remove_axis_label_blocks(page)
    assert removed == 1 and bad not in cleaned
    assert good in cleaned and other in cleaned
    assert '<img src="plot.png">' in cleaned


def test_generated_repair_cell_works_on_saved_result_without_touching_original(tmp_path, monkeypatch):
    import IPython.display
    monkeypatch.setattr(IPython.display, "display", lambda value: None)
    bad = '<blockquote><p><strong>[OCR — cần đối chiếu]</strong> y x O -2 -1 2 -2 -3</p></blockquote>'
    good = '<blockquote><p><strong>[OCR — cần đối chiếu]</strong> <math><mi>x</mi><mo>=</mo><mn>1</mn></math></p></blockquote>'
    style = '<style>p > span{color:black}</style>'
    original = style + '<img src="data:image/png;base64,AA==">' + bad + good
    page = tmp_path / "ket-qua-ocr.html"
    page.write_text(original, encoding="utf-8")
    raw_report = tmp_path / "image-report.json"
    raw_report.write_text('{"raw_ocr":"y x O -2 -1 2 -2 -3"}', encoding="utf-8")
    cell = builder.build_repair_cell(tmp_path / "repair.py").read_text(encoding="utf-8")
    namespace = {"result": {"html": page}}
    exec(compile(cell, "generated-repair-cell", "exec"), namespace)
    cleaned = namespace["CLEAN_HTML"].read_text(encoding="utf-8")
    assert bad not in cleaned and good in cleaned and style in cleaned
    assert 'src="data:image/png;base64,AA=="' in cleaned
    assert page.read_text(encoding="utf-8") == original
    assert '"raw_ocr"' in raw_report.read_text(encoding="utf-8")
    assert "torch" not in cell and "model.infer" not in cell


def test_repair_cell_refuses_old_math_result_when_new_exam_is_selected(tmp_path, monkeypatch):
    import IPython.display
    monkeypatch.setattr(IPython.display, "display", lambda value: None)
    page = tmp_path / "math.html"
    page.write_text("<title>Old Math</title><p>Old Math</p>", encoding="utf-8")
    cell = builder.build_repair_cell(tmp_path / "repair.py").read_text(encoding="utf-8")
    namespace = {"INPUT_DOCX": str(tmp_path / "bio.docx"),
                 "result": {"html": page, "source_path": str(tmp_path / "math.docx")}}
    with pytest.raises(RuntimeError, match="đề cũ"):
        exec(compile(cell, "repair-cell-stale-state", "exec"), namespace)
    assert not page.with_name("math-clean.html").exists()


def test_reprint_saved_ocr_uses_real_pandoc_without_gpu_or_overwriting_evidence(tmp_path, monkeypatch):
    pypandoc = pytest.importorskip("pypandoc")
    import IPython.display
    monkeypatch.setattr(IPython.display, "display", lambda value: None)
    pandoc_path = pypandoc.get_pandoc_path()
    monkeypatch.setattr(fixed.shutil, "which", lambda name: pandoc_path if name == "pandoc" else None)
    output = tmp_path / "run" / "result"
    output.mkdir(parents=True)
    source = ROOT / "tests/fixtures/sample.docx"
    (output / "input.docx").write_bytes(source.read_bytes())
    (output / "table.png").write_bytes(fixtures.png_formula())
    (output / "step1.md").write_text('BEFORE\n\n![](table.png)\n\nAFTER', encoding="utf-8")
    table = '| A | B |\n| --- | --- |\n| \\(x_1\\) | 2 |'
    raw = json.dumps([dict(ref="table.png", ocr_text=table, raw_ocr=table)])
    (output / "image-report.json").write_text(raw, encoding="utf-8")
    (output / "final.md").write_text("OLD MARKDOWN EVIDENCE", encoding="utf-8")
    cell = builder.build_reprint_cell(tmp_path / "reprint.py").read_text(encoding="utf-8")
    assert "model.infer" not in cell and "import torch" not in cell and '"pip"' not in cell
    namespace = {"result": {"results": output, "source_path": str(source)}, "INPUT_DOCX": str(source)}
    exec(compile(cell, "standalone-reprint", "exec"), namespace)
    page = namespace["PRINT_HTML"].read_text(encoding="utf-8")
    assert '<table>' in page and '<msub>' in page and 'class="ocr-table"' not in page
    assert 'class="ocr-pair ocr-table"' in page
    assert (output / "image-report.json").read_text(encoding="utf-8") == raw
    assert (output / "final.md").read_text(encoding="utf-8") == "OLD MARKDOWN EVIDENCE"
    assert not namespace["PRINT_HTML"].is_relative_to(output)


def test_empty_or_directory_input_is_rejected_before_installation(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No dependencies should be installed for invalid input")
    monkeypatch.setattr(fixed, "ensure_dependencies", forbidden)
    for value in (None, "", tmp_path):
        with pytest.raises(ValueError):
            fixed.run(value, tmp_path / "app")


def test_exact_three_ordered_cells_open_picker_without_starting_ocr(tmp_path, monkeypatch):
    import IPython.display
    import subprocess
    monkeypatch.setattr(IPython.display, "display", lambda value: None)
    def forbidden(*args, **kwargs):
        pytest.fail("Opening the three cells must not run OCR or install model dependencies")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    first, second, third = builder.ordered_cells()
    test_root = tmp_path / "kaggle-working"
    namespace = {"__name__": "__main__"}
    exec(compile(first.replace("/kaggle/working/hybrid_original_fixed", str(test_root).replace("\\", "/")), "cell-1", "exec"), namespace)
    assert second.splitlines()[0].startswith("%%writefile ")
    script = test_root / "hybrid_ocr_original_fixed.py"
    payload = "\n".join(second.splitlines()[1:])
    script.write_text(payload, encoding="utf-8")
    exec(compile(third, "cell-3", "exec"), namespace)
    assert namespace["pipeline"].INPUT_DOCX == ""
    assert namespace["result"] is None
    assert namespace["exam_picker"].choice.value == ""
    assert namespace["exam_picker"].run_button.disabled
    assert not (test_root / "runs").exists()
    notebook = json.loads(builder.build_ordered(tmp_path / "three-cells.ipynb").read_text(encoding="utf-8"))
    assert [cell["cell_type"] for cell in notebook["cells"]] == ["markdown", "code", "code", "code"]
