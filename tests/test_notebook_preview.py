import ast
import base64
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from kaggle_ocr import notebook_preview as preview
from kaggle_ocr import notebook_upload as upload

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def result(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/preview-template.html", tmp_path / "scripts/preview-template.html")
    stream = io.BytesIO()
    from PIL import Image
    Image.new("RGB", (12, 8), "white").save(stream, "PNG")
    rows = [{"file": "đề-1.docx", "output": "01", "status": "ok", "ocr": {"total": 0}, "elapsed_s": 0},
            {"file": "đề-2.docx", "output": "02", "status": "ok", "ocr": {"total": 0}, "elapsed_s": 0}]
    archive = tmp_path / "results.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("batch-metrics.json", "{}")
        bundle.writestr("01/markup.txt", "Câu 1 [!m:$mathml_1$] [img:$img_2$] </script><script>alert(1)</script>")
        bundle.writestr("01/manifest.json", json.dumps({"assets": [
            {"id": "mathml_1", "type": "mathml", "latex": r"\hat{n}"},
            {"id": "img_2", "type": "img", "source": "word/media/image.png"}], "warnings": ["Cần đối chiếu"]}))
        bundle.writestr("01/sidecar/mathml_1.xml", '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:acc><m:accPr><m:chr m:val="⃗"/></m:accPr><m:e><m:r><m:t>n</m:t></m:r></m:e></m:acc></m:oMath>')
        bundle.writestr("01/sidecar/img_2.png", stream.getvalue())
        bundle.writestr("02/markup.txt", "Nội dung đề thứ hai")
        bundle.writestr("02/manifest.json", '{"assets":[],"warnings":[]}')
    return archive, rows, tmp_path


def page_data(page):
    return json.loads(page.split('<script id="preview-data" type="application/json">')[1].split("</script>")[0])


def test_preview_keeps_original_xml_and_image_and_escapes_payload(result):
    archive, rows, root = result
    page, warnings = preview.result_page(archive, rows[0], root)
    data = page_data(page)
    asset = data["documents"][0]["assets"]["mathml_1"]
    assert "⃗" in asset["omml"]
    assert asset["latex"] == r"\hat{n}"
    assert data["images"] and all(v.startswith("data:image/png;base64,") for v in data["images"].values())
    assert "</script><script>alert(1)</script>" not in page
    assert warnings == ["Cần đối chiếu"]
    assert "function ommlToMath" in page


def test_preview_vector_failure_is_visible_and_original_remains(result, monkeypatch):
    archive, rows, root = result
    rows[1]["output"] = "03"
    with zipfile.ZipFile(archive, "a") as bundle:
        bundle.writestr("03/markup.txt", "[!m:$mathtype_1$]")
        bundle.writestr("03/manifest.json", '{"assets":[{"id":"mathtype_1","type":"mathtype"}],"warnings":[]}')
        bundle.writestr("03/sidecar/mathtype_1.wmf", b"unrenderable")
    monkeypatch.setattr(preview, "prepare_image", lambda data, ext: (data, ext))
    monkeypatch.setattr(preview.shutil, "which", lambda _: None)
    page, warnings = preview.result_page(archive, rows[1], root)
    assert warnings and "LibreOffice" in warnings[0]
    assert page_data(page)["documents"][0]["assets"]["mathtype_1"]["download"].startswith("data:")


def test_ui_shows_results_outside_output_and_switches_without_rerunning_ocr(result, monkeypatch):
    pytest.importorskip("ipywidgets")
    import IPython.display
    monkeypatch.setattr(IPython.display, "display", lambda *_: None)
    archive, rows, root = result
    inputs = root / "input"
    inputs.mkdir()
    with zipfile.ZipFile(inputs / "de.docx", "w") as doc:
        doc.writestr("[Content_Types].xml", "<Types/>")
        doc.writestr("word/document.xml", "<document/>")
    calls = []
    def process(*args, **kwargs):
        calls.append(args[0])
        return archive, rows
    monkeypatch.setattr(upload, "process_documents", process)
    ui = upload.show_upload_ui(root, "http://unused/ocr", input_root=inputs)
    ui["choose_all"].click()
    ui["button"].click()
    assert len(calls) == 1
    assert ui["preview_box"] in ui["view"].children
    assert ui["state"]["preview"]["view"] in ui["preview_box"].children
    assert "srcdoc=" in ui["state"]["preview"]["frame"].value
    assert "Tải kết quả ZIP" in ui["downloads"].value
    ui["state"]["preview"]["chooser"].value = 1
    assert "Nội dung đề thứ hai" in ui["state"]["preview"]["frame"].value
    assert len(calls) == 1
    assert upload.show_upload_ui(root, "http://unused/ocr", previous=ui, input_root=inputs) is ui
    def fail(*args, **kwargs):
        raise RuntimeError("server unavailable")
    monkeypatch.setattr(upload, "process_documents", fail)
    ui["button"].click()
    assert not ui["preview_box"].children and not ui["downloads"].value
    assert ui["state"]["archive"] is None and not ui["button"].disabled


def test_notebook_bundle_contains_latest_sources_and_runs_unpack(tmp_path):
    path = ROOT / "kaggle_ocr/docx_ocr_kaggle.ipynb"
    assert path.stat().st_size < 1_000_000
    notebook = json.loads(path.read_text(encoding="utf-8"))
    cells = {c["id"]: "".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"}
    for name, source in cells.items():
        compile(source, name, "exec")
    tree = ast.parse(cells["unpack"])
    encoded = next(n.value for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "PAYLOAD")
    with zipfile.ZipFile(io.BytesIO(base64.b85decode(ast.literal_eval(encoded)))) as bundle:
        for folder in (ROOT / "src/docx_extract", ROOT / "colab_ocr_server"):
            for source in folder.glob("*.py"):
                if not source.name.startswith("test_"):
                    assert bundle.read(source.relative_to(ROOT).as_posix()) == source.read_bytes()
        for name in ("kaggle_ocr/notebook_upload.py", "kaggle_ocr/notebook_preview.py", "scripts/preview-template.html"):
            assert bundle.read(name) == (ROOT / name).read_bytes()
        with zipfile.ZipFile(io.BytesIO(bundle.read("tests/fixtures/sample.docx"))) as compact, zipfile.ZipFile(ROOT / "tests/fixtures/sample.docx") as original:
            assert compact.namelist() == original.namelist()
            assert all(compact.read(n) == original.read(n) for n in original.namelist())
    script = '''import json,sys
from pathlib import Path
nb=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
code=next("".join(c["source"]) for c in nb["cells"] if c["id"]=="unpack")
ns={"WORK_ROOT":Path(sys.argv[2])/"old-root","Path":Path,"sys":sys}
for _ in range(2):
 exec(code,ns)
 import docx_extract,notebook_upload,notebook_preview
 assert Path(docx_extract.__file__).is_relative_to(ns["WORK_ROOT"])
 assert Path(notebook_preview.__file__).is_relative_to(ns["WORK_ROOT"])
print("UNPACK_OK")
'''
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", script, str(path), str(tmp_path)],
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    assert "UNPACK_OK" in result.stdout
