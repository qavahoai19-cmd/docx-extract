"""Paste this entire cell over the old final cell after bundle extraction."""
import hashlib
import importlib
import json
import sys
from pathlib import Path

WORK_ROOT = Path(globals().get('WORK_ROOT', '/kaggle/working/docx-questions-original'))
bundle = json.loads((WORK_ROOT / 'bundle.json').read_text(encoding='utf-8'))
for name, digest in bundle['files_sha256'].items():
    if hashlib.sha256((WORK_ROOT / name).read_bytes()).hexdigest() != digest:
        raise RuntimeError('Chạy lại ô giải nén code trước ô này: ' + name)

roots = {'docx_extract', 'notebook_upload', 'question_extract', 'preserve_upload', 'exam_print', 'ocr_logic'}
for name in list(sys.modules):
    if name.partition('.')[0] in roots:
        del sys.modules[name]
for folder in ('src', 'kaggle_ocr', 'colab_ocr_server'):
    entry = str(WORK_ROOT / folder)
    sys.path[:] = [p for p in sys.path if p != entry]
    sys.path.insert(0, entry)
importlib.invalidate_caches()

from preserve_upload import show_preserve_ui

for name, module in list(sys.modules.items()):
    if name.partition('.')[0] in roots:
        if not Path(module.__file__).resolve().is_relative_to(WORK_ROOT.resolve()):
            raise RuntimeError('Module không thuộc bundle đang chạy: ' + name)
print('Bộ đọc đang chạy: ' + bundle['source_version'])
samples = [(item['name'], WORK_ROOT / item['path'], item.get('start_heading', '')) for item in bundle.get('samples', [])]
questions_ui = show_preserve_ui(WORK_ROOT, samples=samples)
