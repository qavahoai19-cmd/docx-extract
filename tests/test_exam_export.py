from pathlib import Path

import pytest

from scripts.build_exam import build, select_markup


def test_print_export_preserves_context_unless_start_is_explicit():
    markup = 'Cho biết dữ kiện\nPRACTICE\nRead this passage\nQuestion 1. Choose'
    assert select_markup(markup) == markup
    assert select_markup(markup, 'practice') == 'Read this passage\nQuestion 1. Choose'
    with pytest.raises(ValueError, match='Không tìm thấy'):
        select_markup(markup, 'missing')


def test_export_generates_a_student_exam_and_separate_teacher_copy(tmp_path):
    source = Path(__file__).parent / 'fixtures/highlighted_english.docx'
    result = build(source, tmp_path, title='ĐỀ TIẾNG ANH', start_heading='PRACTICE',
                   school='TRƯỜNG <THPT>', subject='TIẾNG ANH', duration='45 phút', code='101')
    assert result['questions'] == 9 and not result['warnings']
    student = (tmp_path / 'de-thi.html').read_text(encoding='utf-8')
    teacher = (tmp_path / 'de-thi-co-dap-an.html').read_text(encoding='utf-8')
    assert 'class="answers-hidden"' in student
    assert 'class="show-correct-answers"' in teacher
    assert 'ĐỀ TIẾNG ANH' in student and 'size:A4' in student
    assert 'TRƯỜNG &lt;THPT&gt;' in student and 'TRƯỜNG <THPT>' not in student
    assert 'Môn: TIẾNG ANH' in student and 'Thời gian làm bài: 45 phút' in student
    assert 'Mã đề: 101' in student and 'SBD:' in student and '— HẾT —' in student
    assert 'Mark the letter' in student and '[!u:$o$]' in student
