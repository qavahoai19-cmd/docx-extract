from lxml import etree
from docx_extract.context import Context
from docx_extract.numbering import read_numbering
from docx_extract.runs import render_paragraph

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def test_original_letter_numbering_labels_formulas_without_replacing_them():
    numbering = f'''<w:numbering xmlns:w="{W}"><w:abstractNum w:abstractNumId="2">
        <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="upperLetter"/><w:lvlText w:val="%1."/></w:lvl>
        </w:abstractNum><w:num w:numId="10"><w:abstractNumId w:val="2"/></w:num></w:numbering>'''
    context = Context(rels={}, assets={}, preserve_formulas=True, numbering=read_numbering(numbering.encode()))
    def paragraph(content):
        return etree.fromstring(f'''<w:p xmlns:w="{W}" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">
            <w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="10"/></w:numPr></w:pPr>
            <m:oMath><m:r><m:t>{content}</m:t></m:r></m:oMath></w:p>''')
    assert render_paragraph(paragraph('x'), context) == 'A. [!m:$mathml_1$]'
    assert render_paragraph(paragraph('y'), context) == 'B. [!m:$mathml_2$]'
    assert context.written['mathml_1.xml'] and not context.latex
    # Default OCR extraction keeps its previous markup convention.
    context.preserve_formulas = False
    assert render_paragraph(paragraph('z'), context) == '[!m:$mathml_3$]'


def test_numbering_start_override_is_honored():
    data = f'''<w:numbering xmlns:w="{W}"><w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0">
        <w:start w:val="1"/><w:numFmt w:val="upperLetter"/><w:lvlText w:val="%1)"/></w:lvl></w:abstractNum>
        <w:num w:numId="3"><w:abstractNumId w:val="1"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="3"/></w:lvlOverride></w:num></w:numbering>'''
    definitions = read_numbering(data.encode())
    assert definitions[('3', '0')] == {'format': 'upperLetter', 'text': '%1)', 'start': 3}


def test_highlighted_answer_with_a_word_generated_option_letter():
    context = Context(rels={}, assets={}, preserve_formulas=True,
                      numbering={('3', '0'): {'format': 'upperLetter', 'text': '%1.', 'start': 3}})
    paragraph = etree.fromstring(f'''<w:p xmlns:w="{W}">
        <w:pPr><w:numPr><w:numId w:val="3"/></w:numPr></w:pPr>
        <w:r><w:rPr><w:highlight w:val="yellow"/></w:rPr><w:t>Urbanisation</w:t></w:r>
        </w:p>''')
    assert render_paragraph(paragraph, context) == '*C. Urbanisation'


def test_lowercase_sentence_labels_are_preserved_for_arrangement_questions():
    context = Context(rels={}, assets={}, preserve_formulas=True,
                      numbering={('1', '0'): {'format': 'lowerLetter', 'text': '%1.', 'start': 1}})
    paragraph = etree.fromstring(f'''<w:p xmlns:w="{W}">
        <w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr>
        <w:r><w:t>However, the fast pace can be overwhelming.</w:t></w:r></w:p>''')
    assert render_paragraph(paragraph, context) == 'a. However, the fast pace can be overwhelming.'
    assert render_paragraph(paragraph, context).startswith('b. ')
