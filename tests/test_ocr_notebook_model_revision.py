import ast
import json
import pytest
from kaggle_ocr import build_notebook as builder


def test_generated_notebook_pins_the_verified_model_revision():
    notebook = json.loads((builder.HERE / 'docx_ocr_kaggle.ipynb').read_text(encoding='utf-8'))
    assignments = []
    for cell in notebook['cells']:
        if cell['cell_type'] != 'code':
            continue
        for node in ast.parse(''.join(cell['source'])).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'MODEL_REVISION' for t in node.targets):
                assignments.append(ast.literal_eval(node.value))
    assert assignments == [builder.MODEL_REVISION]
    assert builder.MODEL_REVISION == 'aaa02f3811945a91062062994c5c4a3f4c0af2b0'


@pytest.mark.parametrize('revision', ['677ba7e', 'b778039', 'main', ''])
def test_builder_rejects_project_short_hash_before_writing_files(revision):
    with pytest.raises(ValueError, match='Hugging Face'):
        builder.build('test', revision)
