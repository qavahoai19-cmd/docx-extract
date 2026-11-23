"""Export a DOCX exam to self-contained A4 HTML and, optionally, PDF."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
for folder in ('src', 'kaggle_ocr', 'colab_ocr_server'):
    sys.path.insert(0, str(ROOT / folder))

from docx_extract import clean_docx
from preserve_upload import convert_vectors, make_page
from question_extract import extract_questions


from exam_print import PRINT_CSS, print_page, select_markup


def browser_pdf(source, target, browser=None):
    candidates = [browser] if browser else [
        shutil.which(name) for name in ('chromium', 'chromium-browser', 'google-chrome', 'chrome', 'msedge')
    ]
    if not browser and os.name == 'nt':
        candidates.extend(str(Path(base) / relative) for base in (
            os.environ.get('PROGRAMFILES', ''), os.environ.get('PROGRAMFILES(X86)', '')
        ) if base for relative in ('Google/Chrome/Application/chrome.exe', 'Microsoft/Edge/Application/msedge.exe'))
    executable = next((path for path in candidates if path and Path(path).is_file()), None)
    if executable is None:
        raise RuntimeError('Cần Chrome/Edge/Chromium để xuất PDF; bản HTML vẫn có thể mở và in.')
    with tempfile.TemporaryDirectory(prefix='exam-print-', ignore_cleanup_errors=True) as profile:
        command = [executable, '--headless=new', '--disable-gpu', '--disable-extensions',
                   '--disable-background-networking', '--no-first-run', '--no-pdf-header-footer',
                   '--user-data-dir=' + profile, '--virtual-time-budget=3000',
                   '--print-to-pdf=' + str(target.resolve()), source.resolve().as_uri()]
        subprocess.run(command, check=True, capture_output=True, timeout=90,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if not target.is_file() or target.stat().st_size < 100:
        raise RuntimeError('Trình duyệt chưa tạo được PDF.')


def build(source, output, *, title=None, start_heading=None, pdf=False, browser=None,
          school='', subject='', duration='', code=''):
    source, output = Path(source), Path(output)
    markup, context = clean_docx(source, preserve_formulas=True)
    selected = select_markup(markup, start_heading)
    extracted = extract_questions(selected)
    if not extracted['questions']:
        raise ValueError('Chưa nhận được câu hỏi để tạo bản đề thi.')
    vectors = {hashlib.sha256(data).hexdigest(): (data, Path(name).suffix.lstrip('.'))
               for name, data in context.written.items() if Path(name).suffix.lower() in {'.wmf', '.emf'}}
    converted, errors = convert_vectors(vectors)
    page, warnings = make_page(extracted['markup'], context, title or source.stem, ROOT, converted, errors)
    page = print_page(page, title or source.stem, len(extracted['questions']),
                      school=school, subject=subject, duration=duration, code=code)
    output.mkdir(parents=True, exist_ok=True)
    student = output / 'de-thi.html'
    student.write_text(page, encoding='utf-8')
    (output / 'de-thi-co-dap-an.html').write_text(
        page.replace('class="answers-hidden"', 'class="show-correct-answers"', 1), encoding='utf-8')
    (output / 'questions.json').write_text(json.dumps(extracted['questions'], ensure_ascii=False, indent=2), encoding='utf-8')
    result = {'html': str(student.resolve()), 'questions': len(extracted['questions']),
              'warnings': warnings + extracted['warnings']}
    if pdf:
        target = output / 'de-thi.pdf'
        browser_pdf(student, target, browser)
        result['pdf'] = str(target.resolve())
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=ROOT / 'out/exam-print')
    parser.add_argument('--title')
    parser.add_argument('--school', default='')
    parser.add_argument('--subject', default='')
    parser.add_argument('--duration', default='', help='Ví dụ: 90 phút')
    parser.add_argument('--code', default='')
    parser.add_argument('--start-heading', help='Chỉ cắt phần trước mục được chọn rõ ràng, ví dụ PRACTICE')
    parser.add_argument('--pdf', action='store_true')
    parser.add_argument('--browser', help='Đường dẫn Chrome/Edge/Chromium nếu cần')
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, title=args.title, start_heading=args.start_heading,
                           pdf=args.pdf, browser=args.browser, school=args.school, subject=args.subject,
                           duration=args.duration, code=args.code), ensure_ascii=False))
