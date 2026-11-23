"""Execute generated notebook cells in fresh and reused Python processes."""
import ast
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'kaggle_ocr/docx_questions_kaggle.ipynb'


@pytest.mark.parametrize('reused', [False, True], ids=['fresh-kernel', 'old-package-in-kernel'])
@pytest.mark.parametrize('with_widgets', [False, True], ids=['imports', 'full-widget-ui'])
@pytest.mark.parametrize('recovery_cell', [False, True], ids=['notebook-cell', 'paste-recovery-cell'])
def test_generated_notebook_starts_and_reads_sample(tmp_path, reused, with_widgets, recovery_cell):
    if with_widgets:
        pytest.importorskip('ipywidgets')
        pytest.importorskip('IPython')
    script = r'''
import ast, base64, io, json, sys, types, zipfile
from pathlib import Path

notebook = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
cells = {cell['id']: ''.join(cell['source']) for cell in notebook['cells']}
if sys.argv[5] == 'True':
    cells['interface'] = (Path(sys.argv[1]).parent / 'recover_questions_ui.py').read_text(encoding='utf-8')
work = Path(sys.argv[2]) / 'docx-questions-original'
namespace = {'WORK_ROOT': work, 'sys': sys, 'Path': Path}
if sys.argv[3] == 'True':
    # A previous notebook can leave a package whose __path__ points elsewhere.
    tree = ast.parse(cells['unpack'])
    payload = next(node.value for node in tree.body
                   if isinstance(node, ast.Assign) and node.targets[0].id == 'PAYLOAD')
    old = work.parent / 'previous-notebook'
    with zipfile.ZipFile(io.BytesIO(base64.b85decode(ast.literal_eval(payload)))) as archive:
        archive.extractall(old)
    sys.path.insert(0, str(old / 'src'))
    import docx_extract.numbering
    (old / 'src/docx_extract/numbering.py').unlink()
    # Simulate another leftover import from the previous UI, without a spec.
    sys.modules['question_extract'] = types.ModuleType('question_extract')

exec(compile(cells['unpack'], '<notebook-unpack>', 'exec'), namespace)
tree = ast.parse(cells['interface'])
with_widgets = sys.argv[4] == 'True'
if with_widgets:
    import IPython.display
    # Run the real UI, callbacks, default demo, ZIP and preview generation.
    # Only rendering to a notebook frontend is omitted in this headless test.
    IPython.display.display = lambda *args, **kwargs: None
else:
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'questions_ui'
                                           for t in node.targets))]
for attempt in range(2):
    if attempt:
        exec(compile(cells['unpack'], '<notebook-unpack>', 'exec'), namespace)
    exec(compile(tree, '<notebook-interface>', 'exec'), namespace)
    import docx_extract, question_extract, preserve_upload
    active = namespace['WORK_ROOT'].resolve()
    for module in (docx_extract, question_extract, preserve_upload):
        assert Path(module.__file__).resolve().is_relative_to(active), module.__file__
    sample = active / namespace['bundle']['samples'][0]['path']
    markup, context = docx_extract.clean_docx(sample, preserve_formulas=True)
    questions = question_extract.extract_questions(markup)['questions']
    assert len(questions) == 30, len(questions)
    assert ''.join(q['correct_answer'][0] for q in questions) == 'BDADCDADBBACDCCACDBCBCACCCDDDC'
    assert not context.pending_ocr
    if with_widgets:
        ui = namespace['questions_ui']
        rows = ui['state']['rows']
        assert len(rows) == 1 and rows[0]['status'] == 'ok', rows
        assert rows[0]['questions'] == rows[0]['source_answers'] == 30, rows
        assert len(ui['sample_picker'].options) == 2
        assert not ui['demo'].disabled
        assert ui['view_mode'].value == 'exam' and not ui['show_answers'].value
        exam = Path(rows[0]['print_preview']).read_text(encoding='utf-8')
        assert 'exam-heading-grid' in exam and 'In / lưu PDF' in exam and '— HẾT —' in exam
print('STARTUP_OK: 30 questions, 30 source answers, repeated interface works')
'''
    result = subprocess.run(
        [sys.executable, '-X', 'utf8', '-c', script, str(NOTEBOOK), str(tmp_path), str(reused),
         str(with_widgets), str(recovery_cell)],
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'STARTUP_OK' in result.stdout
