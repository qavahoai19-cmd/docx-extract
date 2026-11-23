import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_preview_option_parser_recognizes_packed_and_styled_options():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is only needed for the frontend parser regression test')
    template = (Path(__file__).resolve().parents[1] / 'scripts/preview-template.html').read_text(encoding='utf-8')
    token_pattern = next(line for line in template.splitlines() if line.startswith('const tokenPattern ='))
    escape = next(line for line in template.splitlines() if line.startswith('const escapeHTML ='))
    function = template[template.index('function optionsFrom(line)'):template.index('\nfunction addParagraph')]
    cases = ['A. Một B. Hai C. Ba D. Bốn',
             'A. Một *B. Hai C. Ba D. Bốn',
             '[!b:$A.$] một B. hai C. ba D. bốn',
             'A. [!m:$a$]B. [!m:$b$]C. [!m:$c$]D. [!m:$d$]']
    script = '\n'.join([token_pattern, escape,
        'const renderAsset = id => `<asset>${id}</asset>`;', function,
        'console.log(JSON.stringify(' + json.dumps(cases, ensure_ascii=True) + '.map(value=>optionsFrom(value))));'])
    completed = subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', check=True)
    results = json.loads(completed.stdout)
    assert all([option['letter'] for option in group] == list('ABCD') for group in results)
    assert [option['letter'] for option in results[1] if option['correct']] == ['B']
    assert [option['html'] for option in results[3]] == ['<asset>a</asset>', '<asset>b</asset>', '<asset>c</asset>', '<asset>d</asset>']


def test_preview_preserves_multiline_cells_nested_tables_and_literal_bars():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is needed for the frontend parser regression test')
    template = (Path(__file__).resolve().parents[1] / 'scripts/preview-template.html').read_text(encoding='utf-8')
    helpers = template[template.index('const tablePartPattern ='):template.index('function optionsFrom(line)')]
    table = '[* Dòng đầu\nDòng sau | [!b:$a | b$] *]'
    nested = '[* x | 1 *]\n[* y | 2 *]'
    script = '\n'.join([
        'const renderInline = text => text;', helpers,
        'const table=' + json.dumps(table) + ';',
        'const nested=' + json.dumps(nested) + ';',
        "console.log(JSON.stringify({lines:markupLines('trước\\n'+table+'\\nsau'),"
        "cells:tableCells('a|b | [!b:$a | b$] | '+nested),html:renderTableCell(nested)}));",
    ])
    completed = subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', check=True)
    result = json.loads(completed.stdout)
    assert result['lines'] == ['trước', table, 'sau']
    assert result['cells'] == ['a|b', '[!b:$a | b$]', nested]
    assert result['html'].count('<tr>') == 2
    assert result['html'].count('<td>') == 4


def test_english_question_heading_and_pronunciation_underlines():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is needed for the frontend parser regression test')
    template = (Path(__file__).resolve().parents[1] / 'scripts/preview-template.html').read_text(encoding='utf-8')
    token = next(line for line in template.splitlines() if line.startswith('const tokenPattern ='))
    escape = next(line for line in template.splitlines() if line.startswith('const escapeHTML ='))
    functions = template[template.index('function questionFrom(line)'):template.index('\nfunction addParagraph')]
    script = '\n'.join([
        token, escape, "const renderAsset=id=>id;", functions,
        "const heading=questionFrom('[!b:$Question$] [!i:$3.$] *A. aff[!u:$o$]rd');",
        "console.log(JSON.stringify({heading,options:optionsFrom(heading.stem)}));",
    ])
    completed = subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', check=True)
    result = json.loads(completed.stdout)
    assert result['heading']['label'] == 'Question'
    assert result['heading']['number'] == '3'
    assert result['options'][0]['correct']
    assert result['options'][0]['html'] == 'aff<u>o</u>rd'
