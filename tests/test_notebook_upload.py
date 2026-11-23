import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from kaggle_ocr import notebook_upload as upload


def docx_bytes():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    return stream.getvalue()


def test_both_widget_versions_and_zip_names_are_supported():
    data = docx_bytes()
    legacy = {"de.docx": {"metadata": {"name": "de.docx"}, "content": data}}
    modern = ({"name": "de.docx", "content": memoryview(data)},)
    assert list(upload.upload_items(legacy)) == list(upload.upload_items(modern))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../de.docx", data)
        archive.writestr("folder/de.docx", data)
        archive.writestr("folder/~$lock.docx", b"not a document")
        archive.writestr("notes.txt", b"ignored")
    assert upload.gather_documents([("de.zip", stream.getvalue())]) == [("de.docx", data)] * 2


def test_invalid_or_empty_upload_does_not_look_successful():
    for name, data in [("old.doc", b"legacy"), ("bad.docx", b"broken"), ("image.png", b"png")]:
        with pytest.raises((ValueError, zipfile.BadZipFile)):
            upload.gather_documents([(name, data)])
    with pytest.raises(ValueError, match="Chưa có"):
        upload.gather_documents([])


def test_kaggle_input_requires_explicit_file_selection(tmp_path):
    first = tmp_path / "dataset-a" / "de-1.docx"
    second = tmp_path / "dataset-b" / "de-2.docx"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(docx_bytes())
    second.write_bytes(docx_bytes())
    assert upload.list_input_files(tmp_path) == ["dataset-a/de-1.docx", "dataset-b/de-2.docx"]
    assert upload.input_documents("dataset-b/de-2.docx", tmp_path) == [("de-2.docx", second.read_bytes())]
    with pytest.raises(ValueError):
        upload.input_documents("../other.docx", tmp_path)


def test_duplicate_names_and_partial_ocr_failure_are_preserved(tmp_path, monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            self.settings = kwargs
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    calls = []
    def clean(paths, client):
        documents = []
        for path in paths:
            calls.append(Path(path))
            failures = int(len(calls) == 2)
            context = SimpleNamespace(written={"image.wmf": b"original"},
                manifest=[{"type": "mathtype", "id": "mathtype_1", "latex": "" if failures else "x"}],
                warnings=[], ocr_stats={"total": 1, "failures": failures})
            documents.append(SimpleNamespace(markup="Câu 1", context=context, error=""))
        return documents, {"total": 2}

    monkeypatch.setattr(upload, "OCRClient", Client)
    monkeypatch.setattr(upload, "clean_docx_batch", clean)
    archive, rows = upload.process_documents([("de.docx", b"first"), ("de.docx", b"second")], tmp_path, "http://test/ocr")
    assert len(set(calls)) == 2 and [p.read_bytes() for p in calls] == [b"first", b"second"]
    assert [r["status"] for r in rows] == ["ok", "needs_review"]
    with zipfile.ZipFile(archive) as result:
        saved = json.loads(result.read("summary.json"))
        assert saved[1]["ocr"]["failures"] == 1
        assert "01-de/manifest.json" in result.namelist()
        assert "02-de/manifest.json" in result.namelist()
        assert not any("input/" in n or "cache/" in n for n in result.namelist())


def test_unsupported_omml_is_needs_review_and_preserved_in_zip(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as doc:
        doc.writestr("[Content_Types].xml", "<Types/>")
        doc.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><w:body><w:p><m:oMath><m:futureMath><m:r><m:t>x</m:t></m:r></m:futureMath></m:oMath></w:p></w:body></w:document>')
    archive, rows = upload.process_documents([("unsupported.docx", stream.getvalue())], tmp_path, "http://unused/ocr")
    assert rows[0]["status"] == "needs_review"
    assert rows[0]["ocr"]["failures"] == rows[0]["ocr"]["omml_total"] == 1
    with zipfile.ZipFile(archive) as result:
        manifest = json.loads(result.read(rows[0]["output"] + "/manifest.json"))
        assert manifest["assets"][0]["review_required"]
        assert b"futureMath" in result.read(rows[0]["output"] + "/sidecar/mathml_1.xml")


def test_merged_input_picker_keeps_selection_and_upload_mode(tmp_path, monkeypatch):
    monkeypatch.setattr("IPython.display.display", lambda *_: None)
    (tmp_path / "first.docx").write_bytes(docx_bytes())
    (tmp_path / "second.docx").write_bytes(docx_bytes())
    ui = upload.show_upload_ui(tmp_path / "work", "http://unused/ocr", input_root=tmp_path)
    assert ui["button"].disabled
    ui["input_picker"].value = (str(tmp_path / "second.docx"),)
    assert not ui["button"].disabled
    ui["refresh"].click()
    assert ui["input_picker"].value == (str(tmp_path / "second.docx"),)
    ui["source_toggle"].value = "upload"
    assert ui["button"].disabled
    ui["source_toggle"].value = "input"
    assert not ui["button"].disabled
