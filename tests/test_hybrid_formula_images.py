"""Image recovery/planning tests; no model inference is simulated as a benchmark."""
import ast
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

from PIL import Image, ImageDraw
import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hybrid_formula_images_test", ROOT / "kaggle_ocr/hybrid_formula_images.py")
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)


def png_formula(size=(140, 35), transparent=False, blank=False):
    canvas = Image.new("RGBA" if transparent else "RGB", size, (255, 255, 255, 0) if transparent else "white")
    if not blank:
        ImageDraw.Draw(canvas).text((8, 8), "x + 1 = 2", fill="black")
    stream = io.BytesIO()
    canvas.save(stream, format="PNG")
    return stream.getvalue()


def make_docx(path, members, body):
    relations = []
    for index, (name, content, kind) in enumerate(members, 1):
        relations.append(f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}" Target="{name}"/>')
    document = f'''<w:document xmlns:w="{images._W}" xmlns:r="{images._R}"
        xmlns:a="{images._A}" xmlns:v="{images._V}" xmlns:o="urn:schemas-microsoft-com:office:office"
        xmlns:m="{images._M}"><w:body>{body}<w:sectPr/></w:body></w:document>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
            <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
            <Default Extension="xml" ContentType="application/xml"/>
            <Default Extension="png" ContentType="image/png"/>
            <Default Extension="wmf" ContentType="image/x-wmf"/>
            <Default Extension="bin" ContentType="application/vnd.openxmlformats-officedocument.oleObject"/>
            <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
            </Types>''')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(relations) + '</Relationships>')
        for name, content, _ in members:
            archive.writestr("word/" + name, content)
    return path


def vml_image(rid=1):
    return f'<w:r><w:pict><v:shape><v:imagedata r:id="rId{rid}"/></v:shape></w:pict></w:r>'


def prepare(tmp_path, raw, body=None):
    docx = make_docx(tmp_path / "input.docx", [("media/formula.png", raw, "image")],
                     body or '<w:p><w:r><w:t>BEFORE</w:t></w:r>' + vml_image() + '<w:r><w:t>AFTER</w:t></w:r></w:p>')
    extraction = images.mark_docx_images(docx, tmp_path)
    return extraction


def test_small_formula_and_transparent_formula_are_queued(tmp_path):
    extraction = prepare(tmp_path, png_formula(transparent=True))
    marker = extraction["images"][0]["markers"][0]
    plan = images.prepare_image_plan("BEFORE " + marker + " AFTER", extraction, tmp_path, allow_install=False)
    assert len(plan["tasks"]) == 1
    assert plan["records"][0]["status"] == "queued"
    path = plan["tasks"][0][1]
    with Image.open(path) as image:
        assert image.mode == "RGB" and max(image.size) >= 384
        assert image.getpixel((0, 0)) == (255, 255, 255)
    assert plan["markup"].index("BEFORE") < plan["markup"].index("![](") < plan["markup"].index("AFTER")
    assert marker not in plan["markup"]


def test_blank_only_is_skipped_and_reported(tmp_path):
    extraction = prepare(tmp_path, png_formula(blank=True))
    plan = images.prepare_image_plan(extraction["images"][0]["markers"][0], extraction, tmp_path, allow_install=False)
    assert not plan["tasks"]
    assert plan["summary"]["blank_images"] == 1


def test_repeated_references_do_not_duplicate_ocr_or_markdown_images(tmp_path):
    extraction = prepare(tmp_path, png_formula(), '<w:p>' + vml_image() + vml_image() + '</w:p>')
    record = extraction["images"][0]
    raw_path = record["source_path"]
    markup = " ".join(record["markers"]) + f" ![]({raw_path}) ![]({raw_path})"
    plan = images.prepare_image_plan(markup, extraction, tmp_path, allow_install=False)
    assert len(plan["tasks"]) == 1
    assert plan["markup"].count("![](") == 2  # two source occurrences, no Pandoc duplicates
    assert plan["summary"]["image_occurrences"] == 2


def test_deduplicates_identical_pixels_across_different_members(tmp_path):
    raw = png_formula()
    source = make_docx(tmp_path / "input.docx", [("media/a.png", raw, "image"), ("media/b.png", raw, "image")],
                       '<w:p>' + vml_image(1) + vml_image(2) + '</w:p>')
    extraction = images.mark_docx_images(source, tmp_path)
    markup = " ".join(marker for record in extraction["images"] for marker in record["markers"])
    plan = images.prepare_image_plan(markup, extraction, tmp_path, allow_install=False)
    assert len(plan["tasks"]) == 1 and plan["summary"]["duplicate_images"] == 1
    images.record_ocr_result(plan, plan["tasks"][0][2], "$x*2$", "$x*2$")
    assert all(record["ocr_text"] == "$x*2$" for record in plan["records"])


def test_mathtype_preview_recovered_when_pandoc_drops_ole_image(tmp_path):
    body = '<w:p><w:r><w:t>QUESTION</w:t></w:r><w:r><w:object><v:shape><v:imagedata r:id="rId1"/></v:shape><o:OLEObject r:id="rId2"/></w:object></w:r></w:p>'
    source = make_docx(tmp_path / "input.docx", [("media/math.wmf", b"WMF fixture", "image"),
                       ("embeddings/math.bin", b"OLE fixture", "oleObject")], body)
    extraction = images.mark_docx_images(source, tmp_path)
    assert len(extraction["images"]) == 1
    marker = extraction["images"][0]["markers"][0]
    calls = []
    def conversion_stub(records, output, **kwargs):
        calls.append(records)
        target = tmp_path / "converted.png"
        target.write_bytes(png_formula())
        return {records[0]["id"]: target}, {}
    plan = images.prepare_image_plan("QUESTION " + marker, extraction, tmp_path, vector_converter=conversion_stub)
    assert calls and len(plan["tasks"]) == 1
    assert plan["summary"]["vector_images"] == 1
    assert not plan["summary"]["conversion_errors"]


def test_vector_failure_is_not_silently_filtered(tmp_path):
    source = make_docx(tmp_path / "input.docx", [("media/math.emf", b"EMF fixture", "image")], '<w:p>' + vml_image() + '</w:p>')
    extraction = images.mark_docx_images(source, tmp_path)
    record = extraction["images"][0]
    def fail_conversion(records, output, **kwargs):
        return {}, {records[0]["id"]: "renderer unavailable"}
    plan = images.prepare_image_plan(record["markers"][0], extraction, tmp_path, vector_converter=fail_conversion)
    assert not plan["tasks"]
    assert plan["summary"]["conversion_errors"] == plan["summary"]["images_unprocessed"] == 1
    assert "renderer unavailable" in plan["markup"]
    assert Path(record["source_path"]).read_bytes() == b"EMF fixture"
    assert (tmp_path / "image-report.json").is_file()


def test_ole_without_preview_is_explicitly_reported(tmp_path):
    source = make_docx(tmp_path / "input.docx", [("embeddings/math.bin", b"OLE fixture", "oleObject")],
                       '<w:p><w:r><w:object><o:OLEObject r:id="rId1"/></w:object></w:r></w:p>')
    extraction = images.mark_docx_images(source, tmp_path)
    plan = images.prepare_image_plan(extraction["images"][0]["markers"][0], extraction, tmp_path)
    assert not plan["tasks"] and plan["summary"]["images_unprocessed"] == 1
    assert plan["records"][0]["status"] == "ole_no_preview"


def test_short_ocr_and_multiplication_are_retained():
    worker = ast.parse((ROOT / "kaggle_ocr/hybrid_clean_worker.py").read_text(encoding="utf-8"))
    names = {"is_garbage_ocr", "clean_ocr_table", "clean_ocr", "format_ocr_inline", "build_final"}
    nodes = [n for n in worker.body if isinstance(n, ast.FunctionDef) and n.name in names]
    nodes += [n for n in worker.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_GARBAGE_PATTERNS" for t in n.targets)]
    import re
    namespace = {"re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "ocr-cleanup", "exec"), namespace)
    for formula in ("x", "0", "π", "$x*y$", r"$\frac{1}{2}$"):
        assert namespace["clean_ocr"](formula) == formula
        assert namespace["format_ocr_inline"](formula) == formula
    final = namespace["build_final"]("![](formula.png)", {"formula.png": "key"}, {"key": "$x*y$"})
    assert "$x*y$" in final
    multiline = "$$\\begin{matrix}1 & 2 \\\\\n3 & 4\\end{matrix}$$"
    assert namespace["format_ocr_inline"](multiline) == multiline
    final = namespace["build_final"]("![](formula.png)", {"formula.png": "key"}, {"key": multiline})
    assert "> 3 & 4" in final


def test_real_pandoc_keeps_marker_and_recovers_small_formula(tmp_path):
    pypandoc = pytest.importorskip("pypandoc")
    extraction = prepare(tmp_path, png_formula())
    target = tmp_path / "step1.md"
    media = tmp_path / "pandoc_media"
    subprocess.run([pypandoc.get_pandoc_path(), "-f", "docx", str(extraction["docx"]),
                    "-t", "markdown+tex_math_dollars", "--wrap=none", "--extract-media=" + str(media),
                    "-o", str(target)], check=True, capture_output=True, text=True)
    markdown = target.read_text(encoding="utf-8")
    assert extraction["images"][0]["markers"][0] in markdown
    plan = images.prepare_image_plan(markdown, extraction, tmp_path, allow_install=False)
    assert len(plan["tasks"]) == 1
    assert plan["markup"].count("![](") == 1
    assert plan["markup"].index("BEFORE") < plan["markup"].index("![](") < plan["markup"].index("AFTER")


def test_real_docx_with_mathtype_has_accounted_images(tmp_path):
    pypandoc = pytest.importorskip("pypandoc")
    extraction = images.mark_docx_images(ROOT / "tests/fixtures/sample.docx", tmp_path)
    assert any(record["extension"] == ".wmf" for record in extraction["images"])
    target = tmp_path / "step1.md"
    subprocess.run([pypandoc.get_pandoc_path(), "-f", "docx", str(extraction["docx"]), "-t", "markdown+tex_math_dollars",
                    "--wrap=none", "--extract-media=" + str(tmp_path / "media"), "-o", str(target)],
                   check=True, capture_output=True, text=True)
    def unavailable(records, output, **kwargs):
        return {}, {record["id"]: "No converter in this CPU test" for record in records}
    plan = images.prepare_image_plan(target.read_text(encoding="utf-8"), extraction, tmp_path,
                                     vector_converter=unavailable, allow_install=False)
    assert plan["summary"]["images_in_docx"] > 10
    assert len(plan["tasks"]) > 0  # actual PNG/JPEG formulas/figures, not a model mock
    assert plan["summary"]["conversion_errors"] > 0
    assert not any(record["status"] == "extracted" for record in plan["records"])


def test_real_pandoc_preserves_text_before_image_inside_same_run(tmp_path):
    pypandoc = pytest.importorskip("pypandoc")
    body = '<w:p><w:r><w:t>BEFORE</w:t><w:pict><v:shape><v:imagedata r:id="rId1"/></v:shape></w:pict><w:t>AFTER</w:t></w:r></w:p>'
    extraction = prepare(tmp_path, png_formula(), body)
    target = tmp_path / "step1.md"
    subprocess.run([pypandoc.get_pandoc_path(), "-f", "docx", str(extraction["docx"]), "-t", "markdown",
                    "--wrap=none", "--extract-media=" + str(tmp_path / "media"), "-o", str(target)],
                   check=True, capture_output=True, text=True)
    plan = images.prepare_image_plan(target.read_text(encoding="utf-8"), extraction, tmp_path, allow_install=False)
    assert plan["markup"].index("BEFORE") < plan["markup"].index("![](") < plan["markup"].index("AFTER")


def test_blank_vector_render_is_conversion_error_not_blank_source(tmp_path):
    source = make_docx(tmp_path / "input.docx", [("media/math.wmf", b"WMF fixture", "image")], '<w:p>' + vml_image() + '</w:p>')
    extraction = images.mark_docx_images(source, tmp_path)
    def blank_conversion(records, output, **kwargs):
        target = tmp_path / "blank.png"
        target.write_bytes(png_formula(blank=True))
        return {records[0]["id"]: target}, {}
    plan = images.prepare_image_plan(extraction["images"][0]["markers"][0], extraction, tmp_path,
                                     vector_converter=blank_conversion)
    assert plan["summary"]["conversion_errors"] == 1
    assert plan["summary"]["blank_images"] == 0


def test_native_word_equation_remains_native_not_fake_image_ocr(tmp_path):
    pypandoc = pytest.importorskip("pypandoc")
    source = make_docx(tmp_path / "input.docx", [],
                       '<w:p><m:oMath><m:r><m:t>x+1</m:t></m:r></m:oMath></w:p>')
    extraction = images.mark_docx_images(source, tmp_path)
    target = tmp_path / "native.md"
    subprocess.run([pypandoc.get_pandoc_path(), "-f", "docx", str(extraction["docx"]), "-t", "markdown+tex_math_dollars", "-o", str(target)],
                   check=True, capture_output=True, text=True)
    plan = images.prepare_image_plan(target.read_text(encoding="utf-8"), extraction, tmp_path, allow_install=False)
    assert plan["native_word_equations"] == 1
    assert not plan["tasks"] and "x+1" in plan["markup"].replace(" ", "")


def test_vector_cli_partial_failure_is_accounted(tmp_path, monkeypatch):
    records = []
    for index in range(2):
        path = tmp_path / f"v{index}.wmf"
        path.write_bytes(f"vector fixture {index}".encode())
        records.append(dict(id=f"v{index}", source_path=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    calls = []
    monkeypatch.setattr(images.shutil, "which", lambda name: "soffice-test")
    def fake_soffice(command, **kwargs):
        calls.append(command)
        output = Path(command[command.index("--outdir") + 1])
        (output / "v0.png").write_bytes(png_formula())
        return SimpleNamespace(stdout="converted first image", stderr="second image failed")
    monkeypatch.setattr(images.subprocess, "run", fake_soffice)
    converted, errors = images.render_vectors(records, tmp_path / "converted", allow_install=False)
    assert set(converted) == {"v0"} and set(errors) == {"v1"}
    assert "draw_png_Export" in calls[0][calls[0].index("--convert-to") + 1]
    assert "second image failed" in errors["v1"]


def test_vector_install_exposes_logs_and_never_waits_for_interactive_input(tmp_path, monkeypatch, capsys):
    source = tmp_path / "formula.wmf"
    source.write_bytes(b"vector fixture; this test does not install system packages")
    records = [dict(id="formula", source_path=str(source), source_sha256="fixture")]
    installed = False
    calls = []
    monkeypatch.setattr(images, "sys", SimpleNamespace(platform="linux"))
    def which(name):
        if name == "apt-get":
            return "apt-test"
        return "soffice-test" if installed and name == "soffice" else None
    monkeypatch.setattr(images.shutil, "which", which)
    def run(command, **kwargs):
        nonlocal installed
        calls.append((command, kwargs))
        if "install" in command:
            installed = True
        if "--convert-to" in command:
            folder = Path(command[command.index("--outdir") + 1])
            (folder / "formula.png").write_bytes(png_formula())
        return SimpleNamespace(stdout="converted fixture", stderr="", returncode=0)
    monkeypatch.setattr(images.subprocess, "run", run)
    converted, errors = images.render_vectors(records, tmp_path / "converted")
    assert converted and not errors
    for command, kwargs in calls[:2]:
        assert "-qq" not in command
        assert not kwargs.get("capture_output")
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["env"]["DEBIAN_FRONTEND"] == "noninteractive"
        assert "DPkg::Lock::Timeout=60" in command
    assert [kwargs["timeout"] for command, kwargs in calls[:2]] == [240, 480]
    output = capsys.readouterr().out
    assert "cập nhật danh sách gói" in output
    assert "tải / cài gói" in output and "đang chuyển ảnh vector" in output


def test_bundled_worker_reaches_ocr_queue_with_real_pandoc(tmp_path, monkeypatch):
    """Only the GPU admission check is stubbed; Pandoc/PIL/DOCX are real.

    Stop before model loading: this is an input-pipeline smoke test, not a GPU
    or inference test, and cannot be used as an OCR benchmark.
    """
    pypandoc = pytest.importorskip("pypandoc")
    builder_spec = importlib.util.spec_from_file_location("formula_builder", ROOT / "kaggle_ocr/build_hybrid_clean_notebook.py")
    builder = importlib.util.module_from_spec(builder_spec)
    builder_spec.loader.exec_module(builder)
    import json
    notebook = json.loads(builder.build(tmp_path / "clean.ipynb").read_text(encoding="utf-8"))
    bootstrap = ast.parse("".join(notebook["cells"][1]["source"]))
    source = next(ast.literal_eval(node.value) for node in bootstrap.body
                  if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "WORKER_SOURCE" for t in node.targets))
    tree = ast.parse(source)
    before_model = []
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "need_ocr":
            break
        before_model.append(node)
    docx = make_docx(tmp_path / "input.docx", [("media/formula.png", png_formula(), "image")], '<w:p>' + vml_image() + '</w:p>')
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: True, mem_get_info=lambda device: (15_000_000_000, 16_000_000_000),
        get_device_name=lambda device: "SIMULATED GPU GATE -- NO INFERENCE",
    ))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(sys, "argv", ["worker", "--input", str(docx), "--output", str(tmp_path / "result")])
    monkeypatch.setenv("PATH", str(Path(pypandoc.get_pandoc_path()).parent) + os.pathsep + os.environ.get("PATH", ""))
    namespace = {"__name__": "__cpu_input_smoke_test__"}
    exec(compile(ast.Module(body=before_model, type_ignores=[]), "embedded-worker-input-stage", "exec"), namespace)
    assert len(namespace["need_ocr"]) == 1
    assert (tmp_path / "result/image-report.json").is_file()
    assert namespace["image_plan"]["summary"]["images_in_docx"] == 1
