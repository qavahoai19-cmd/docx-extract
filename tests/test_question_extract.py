from collections import Counter
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kaggle_ocr"))
from question_extract import choices, extract_questions


HEADER = '[* Loại câu hỏi | Là câu hỏi con của câu hỏi chùm? | Nội dung câu hỏi | Câu trả lời | Đáp án đúng *]'


def test_choice_boundaries_with_one_space_formatting_and_adjacent_equation():
    options = choices('[!b:$A.$] [!m:$one$]B. hai *C. [!m:$three$] D. [!i:$bốn$]')
    assert [option['label'] for option in options] == list('ABCD')
    assert [option['content'] for option in options] == ['[!m:$one$]', 'hai', '[!m:$three$]', '[!i:$bốn$]']
    assert [option['label'] for option in options if option['inline_correct']] == ['C']


def test_uses_explicit_answer_column_and_reports_conflicting_star():
    raw = HEADER + '\n[* Một lựa chọn |  | Chọn | *A. một B. hai C. ba D. bốn | D *]'
    result = extract_questions(raw)
    question = result['questions'][0]
    assert question['correct_answer'] == ['D'] and question['conflict']
    assert question['answer_source'] == 'answer_key_column'
    assert '*D. bốn' in result['markup'] and '*A. một' not in result['markup']
    assert any('dấu * ghi A' in warning for warning in result['warnings'])


def test_true_false_children_stay_with_their_parent_and_short_answer_is_preserved():
    raw = '\n'.join([HEADER,
        '[* Câu hỏi chùm (câu dẫn) |  | Cho hình [img:$graph$] |  |  *]',
        '[* Đúng/Sai | Có | Nhận định [!m:$one$] | A. Đúng B. Sai | A. Đúng *]',
        '[* Đúng/Sai | Có | Nhận định [!m:$two$] | A. Đúng B. Sai | B. Sai *]',
        '[* Điền khuyết |  | Tính kết quả |  | [!b:$A. 0,09$] *]'])
    result = extract_questions(raw)
    assert len(result['questions']) == 2
    group, short = result['questions']
    assert [item['truth'] for item in group['items']] == [True, False]
    assert '[Đ] a) Nhận định [!m:$one$]' in result['markup']
    assert '[S] b) Nhận định [!m:$two$]' in result['markup']
    assert short['correct_answer'] == '0,09'
    assert 'Đáp án đúng: 0,09' in result['markup']
    assert not result['warnings']
    ids = r'\[(?:!m|img):\$(.*?)\$\]'
    assert Counter(re.findall(ids, raw)) == Counter(re.findall(ids, result['markup']))


def test_missing_key_is_not_solved_and_regular_tables_remain_intact():
    raw = HEADER + '\n[* Một lựa chọn |  | Chọn | A. một B. hai C. ba D. bốn |  *]'
    question = extract_questions(raw)['questions'][0]
    assert question['correct_answer'] is None and question['answer_source'] is None
    ordinary = '[* Nhóm | [0;40) | [40;80) *]\n[* Tần số | 11 | 10 *]'
    assert extract_questions(ordinary)['markup'] == ordinary


def test_true_false_plain_text_and_keys_without_spaces_are_supported():
    raw = '\n'.join([HEADER,
        '[* Câu hỏi chùm (câu dẫn) |  | Cho dữ kiện |  |  *]',
        '[* Đúng/Sai | Có | Ý thứ nhất | Đúng Sai | Đúng *]',
        '[* Đúng/Sai | Có | Ý thứ hai | Đúng Sai | B.Sai *]'])
    result = extract_questions(raw)
    assert [item['truth'] for item in result['questions'][0]['items']] == [True, False]
    assert '[Đ] a) Ý thứ nhất' in result['markup'] and '[S] b) Ý thứ hai' in result['markup']
    assert not result['warnings']


def test_multiple_choice_and_other_question_types_are_not_forced_to_single_choice():
    raw = '\n'.join([HEADER,
        '[* Nhiều lựa chọn |  | Chọn các ý | A. Một B. Hai C. Ba D. Bốn | [!b:$A,C$] *]',
        '[* Câu tự luận |  | Trình bày |  |  *]',
        '[* Kéo thả |  | Điền vị trí | 123|abc | A.123 *]'])
    result = extract_questions(raw)
    assert [question['type'] for question in result['questions']] == ['multiple_choice', 'essay', 'drag_drop']
    assert result['questions'][0]['correct_answer'] == ['A', 'C']
    assert result['questions'][2]['correct_answer'] == 'A.123'
    assert not result['warnings']


def test_multiline_lms_header_cells_answers_and_legacy_answer_column():
    raw = ('[* STT | Mã câu\ntrong\nNHCH | Loại câu hỏi | Nội dung\ncâu hỏi | Câu trả lời | Đáp án *]\n'
           '[* 1 |  | Một lựa chọn | Dòng đầu\nDòng sau [!m:$stem$] | '
           'A. [!m:$a$]\nB. [!m:$b$]\nC. ba\nD. bốn | B *]')
    result = extract_questions(raw)
    assert result['lms_detected']
    assert len(result['questions']) == 1
    item = result['questions'][0]
    assert item['stem'] == 'Dòng đầu\nDòng sau [!m:$stem$]'
    assert [option['label'] for option in item['options']] == list('ABCD')
    assert item['correct_answer'] == ['B']
    assert '*B. [!m:$b$]' in result['markup']
    assert not result['warnings']


def test_nested_data_table_and_vertical_bars_do_not_split_lms_columns():
    raw = (HEADER + '\n[* Một lựa chọn |  | Cho bảng:\n'
           '[* x | 1 | 2 *]\n[* y | 3 | 4 *]\nTính | A. P(A | B) B. hai C. ba D. bốn | A *]')
    # A literal bar inside option content must be retained; ambiguous columns
    # are preserved as the original row, never silently interpreted.
    result = extract_questions(raw)
    assert 'P(A | B)' in result['markup']
    assert '[* x | 1 | 2 *]' in result['markup']
    assert result['warnings']


def test_nested_data_table_stays_inside_its_question_stem():
    table = '[* x | 1 | 2 *]\n[* y | 3 | 4 *]'
    stem = 'Cho bảng:\n' + table + '\nTính giá trị.'
    raw = HEADER + '\n[* Một lựa chọn |  | ' + stem + ' | A. một B. hai C. ba D. bốn | B *]'
    result = extract_questions(raw)
    assert len(result['questions']) == 1
    assert result['questions'][0]['stem'] == stem
    assert table in result['markup']
    assert '*B. hai' in result['markup']
    assert not result['warnings']


def test_multiline_ordinary_table_is_preserved_without_lms_conversion():
    raw = '[* Dòng một\nDòng hai | [!b:$A | B$] *]\n[* Giá trị | 2 *]'
    assert extract_questions(raw)['markup'] == raw


def test_highlighted_english_exam_extracts_table_and_paragraph_answers():
    from docx_extract import clean_docx

    markup, _ = clean_docx(Path(__file__).parent / 'fixtures/highlighted_english.docx', preserve_formulas=True)
    result = extract_questions(markup)
    assert not result['lms_detected']
    assert len(result['questions']) == 9
    assert [item['correct_answer'] for item in result['questions']] == [[key] for key in 'BDADCDADB']
    assert all([option['label'] for option in item['options']] == list('ABCD') for item in result['questions'])
    assert '[* ' not in result['markup']
    assert '[!u:$o$]' in result['markup']
    assert not result['warnings']


def test_several_questions_in_one_word_paragraph_keep_separate_keys():
    raw = ('Question 17. A. a B. b *C. c D. d '
           'Question 18. A. e B. f C. g *D. h '
           'Question 19. A. i *B. j C. k D. l')
    result = extract_questions(raw)
    assert [item['number'] for item in result['questions']] == [17, 18, 19]
    assert [item['correct_answer'] for item in result['questions']] == [['C'], ['D'], ['B']]
    assert result['markup'].count('\n') == 2
