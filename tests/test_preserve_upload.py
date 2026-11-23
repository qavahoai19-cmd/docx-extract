import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kaggle_ocr"))
sys.path.insert(0, str(ROOT / "colab_ocr_server"))
import preserve_upload as upload


def install_viewer(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "kaggle_ocr").mkdir()
    (tmp_path / "scripts/preview-template.html").write_bytes((ROOT / "scripts/preview-template.html").read_bytes())
    (tmp_path / "kaggle_ocr/questions-only.css").write_bytes((ROOT / "kaggle_ocr/questions-only.css").read_bytes())


def test_original_word_equation_has_preview_without_latex_or_ocr(tmp_path, monkeypatch):
    from docx_extract import mathlatex, mathnative, mathocr
    def forbidden(*args, **kwargs):
        raise AssertionError("No OCR or LaTeX conversion allowed")
    monkeypatch.setattr(mathlatex, "omml_to_latex", forbidden)
    monkeypatch.setattr(mathnative, "ole_to_latex", forbidden)
    monkeypatch.setattr(mathocr, "OCRClient", forbidden)
    install_viewer(tmp_path)
    stream = io.BytesIO()
    xml = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><w:body><w:p>
        <w:r><w:t>Câu 1: Tính </w:t></w:r><m:oMath><m:f><m:num><m:r><m:t>1</m:t></m:r></m:num>
        <m:den><m:r><m:t>2</m:t></m:r></m:den></m:f></m:oMath></w:p></w:body></w:document>'''
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", xml)
    result, rows, metrics = upload.process_preserved([("a.docx", stream.getvalue())], tmp_path, lambda message: None)
    assert metrics["ocr_requests"] == metrics["latex_generated"] == 0
    assert rows[0]["word_equations"] == rows[0]["question_labels"] == 1
    assert rows[0]["status"] == "ok"
    with zipfile.ZipFile(result) as archive:
        manifest = json.loads(archive.read("001/manifest.json"))
        assert manifest["assets"][0]["latex"] is None
        assert "001/sidecar/mathml_1.xml" in archive.namelist()
        page = archive.read("001/questions.html").decode()
        assert '"omml":' in page and '"latex":null' in page
        assert "__PREVIEW_DATA__" not in page
        assert "display:none!important" in page
        assert not any(name.endswith(".docx") for name in archive.namelist())


def test_duplicate_docs_share_vector_conversion_and_originals_remain(tmp_path, monkeypatch):
    install_viewer(tmp_path)
    calls = []
    def convert(vectors):
        calls.append(len(vectors))
        stream = io.BytesIO()
        Image.new("RGB", (60, 30), "white").save(stream, "PNG")
        return {key: stream.getvalue() for key in vectors}, {}
    monkeypatch.setattr(upload, "convert_vectors", convert)
    sample = (ROOT / "tests/fixtures/sample.docx").read_bytes()
    archive, rows, metrics = upload.process_preserved([("same.docx", sample), ("same.docx", sample)], tmp_path, lambda _: None)
    assert len(rows) == 2 and calls == [16]
    assert all(row["mathtype_images"] == 16 for row in rows)
    with zipfile.ZipFile(archive) as zipped:
        for index in ("001", "002"):
            assets = json.loads(zipped.read(index + "/manifest.json"))["assets"]
            assert all(item.get("latex") is None for item in assets)
            assert index + "/questions.html" in zipped.namelist()


def test_linux_libreoffice_batch_keeps_partial_failures_visible(monkeypatch):
    monkeypatch.setattr(upload.sys, "platform", "linux")
    monkeypatch.setattr(upload.shutil, "which", lambda name: "/usr/bin/soffice")
    calls = []
    def soffice(command, **kwargs):
        calls.append(command)
        directory = Path(command[command.index("--outdir") + 1])
        image = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(image).rectangle((40, 40, 60, 60), fill="black")
        image.save(directory / "image_0.png")
        # Second vector deliberately fails conversion.
    monkeypatch.setattr(upload.subprocess, "run", soffice)
    converted, errors = upload.convert_vectors({"first": (b"one", "wmf"), "second": (b"two", "emf")})
    assert len(calls) == 1 and set(converted) == {"first"} and set(errors) == {"second"}


def test_cpu_notebook_contains_verified_source_and_no_model_server():
    notebook_path = ROOT / "kaggle_ocr/docx_questions_kaggle.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    assert notebook_path.stat().st_size < 1_000_000
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            ast.parse("".join(cell["source"]))
            assert not cell["outputs"] and cell["execution_count"] is None
    unpack = next(cell for cell in notebook["cells"] if cell["id"] == "unpack")
    assignment = next(node for node in ast.parse("".join(unpack["source"])).body
        if isinstance(node, ast.Assign) and node.targets[0].id == "PAYLOAD")
    with zipfile.ZipFile(io.BytesIO(base64.b85decode(ast.literal_eval(assignment.value)))) as archive:
        manifest = json.loads(archive.read("bundle.json"))
        assert not any(name.endswith("ocr_server.py") for name in archive.namelist())
        for name, digest in manifest["files_sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        assert archive.read("kaggle_ocr/preserve_upload.py") == (ROOT / "kaggle_ocr/preserve_upload.py").read_bytes()
        for path in (ROOT / "src/docx_extract").glob("*.py"):
            assert archive.read(path.relative_to(ROOT).as_posix()) == path.read_bytes()
        for name in ("kaggle_ocr/question_extract.py", "kaggle_ocr/questions-only.css", "scripts/preview-template.html"):
            assert archive.read(name) == (ROOT / name).read_bytes()
        assert archive.read('kaggle_ocr/exam_print.py') == (ROOT / 'kaggle_ocr/exam_print.py').read_bytes()
        interface = ''.join(next(cell for cell in notebook['cells'] if cell['id'] == 'interface')['source'])
        assert manifest['source_version'] in interface


def test_lms_table_becomes_questions_without_internal_columns_or_missing_assets():
    original = ('[* STT | [!b:$Nội dung câu hỏi$] | Câu trả lời | Đáp án đúng | Độ khó *]\n'
        '[*  | Tính [!m:$mathml_1$] | A. [!m:$mathtype_2$] *B. đúng C. saiD. khác | B | Dễ *]')
    questions, count = upload.question_markup(original)
    assert count == 1 and questions.startswith('Câu 1: Tính [!m:$mathml_1$]')
    assert 'Nội dung câu hỏi' not in questions and 'Độ khó' not in questions
    assert '[!m:$mathtype_2$]' in questions
    # Ambiguous plain text is preserved; the helper does not invent split points.
    assert 'saiD. khác' in questions
    normal = '[* Nhóm | [0;40) | [40;80) *]\n[* Tần số | 11 | 10 *]'
    assert upload.question_markup(normal) == (normal, 0)


def test_lms_answers_can_start_immediately_after_formula_placeholder():
    original = ('[* Nội dung câu hỏi | Câu trả lời *]\n'
        '[* Chọn | A. [!m:$a$] *B. [!m:$b$] C. [!m:$c$]D. [!m:$d$] *]')
    questions, count = upload.question_markup(original)
    assert questions.splitlines()[:5] == ['Câu 1: Chọn', 'A. [!m:$a$]', '*B. [!m:$b$]', 'C. [!m:$c$]', 'D. [!m:$d$]']


def test_highlighted_english_answers_reach_notebook_export_and_counts(tmp_path):
    install_viewer(tmp_path)
    sample = (ROOT / 'tests/fixtures/highlighted_english.docx').read_bytes()
    archive, rows, _ = upload.process_preserved([('english.docx', sample)], tmp_path, lambda _: None)
    assert rows[0]['status'] == 'ok'
    assert rows[0]['questions'] == rows[0]['question_labels'] == rows[0]['source_answers'] == 9
    assert rows[0]['lms_questions'] == 0
    with zipfile.ZipFile(archive) as zipped:
        questions = json.loads(zipped.read('001/questions.json'))
        assert [item['correct_answer'] for item in questions] == [[key] for key in 'BDADCDADB']
        page = zipped.read('001/questions-answers.html').decode()
        assert 'class="show-correct-answers"' in page
        assert '*B. aff[!u:$o$]rdable' in page


def test_notebook_zip_includes_printable_exam_with_requested_header(tmp_path):
    install_viewer(tmp_path)
    sample = (ROOT / 'tests/fixtures/highlighted_english.docx').read_bytes()
    result, rows, _ = upload.process_preserved([('english.docx', sample)], tmp_path, lambda _: None,
        exam_options={'school': 'TRƯỜNG THPT', 'title': 'KIỂM TRA HỌC KỲ', 'subject': 'TIẾNG ANH',
                      'duration': '45 phút', 'code': '101', 'start_heading': 'PRACTICE'})
    assert rows[0]['questions'] == 9 and Path(rows[0]['print_preview']).is_file()
    with zipfile.ZipFile(result) as archive:
        student = archive.read('001/de-thi.html').decode('utf-8')
        teacher = archive.read('001/de-thi-co-dap-an.html').decode('utf-8')
        assert 'KIỂM TRA HỌC KỲ' in student and 'TRƯỜNG THPT' in student
        assert '45 phút' in student and 'Mã đề: 101' in student
        assert 'class="answers-hidden"' in student and 'class="show-correct-answers"' in teacher
        assert '[!u:$o$]' in student and 'In / lưu PDF' in student
        assert student.index('exam-heading-grid') < student.index('Question 1')
