from lxml import etree
from docx_extract.tables import render_table
from docx_extract import ns

def _tbl(rows):
    def cell(t):
        return (f'<w:tc><w:p><w:r><w:t xml:space="preserve">{t}</w:t>'
                f'</w:r></w:p></w:tc>')
    trs = "".join("<w:tr>" + "".join(cell(c) for c in r) + "</w:tr>" for r in rows)
    return etree.fromstring(f'<w:tbl xmlns:w="{ns.W[1:-1]}">{trs}</w:tbl>')

def test_two_rows():
    t = _tbl([["0", "27", "0"], ["1", "31", "0,11"]])
    got = render_table(t, None)
    assert got == "[* 0 | 27 | 0 *]\n[* 1 | 31 | 0,11 *]"
