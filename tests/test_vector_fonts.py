import io
from pathlib import Path
import struct

import pytest
from PIL import Image
from lxml import etree
from docx_extract import ns
from docx_extract.context import Context
from docx_extract.vector_fonts import prepare_wmf, read_wmf_number, _records


def record(function, payload=b''):
    payload += b'\0' * (len(payload) % 2)
    return struct.pack('<IH', 3 + len(payload) // 2, function) + payload


def numeric_wmf(text=b'1', font='Euclid', y=100):
    header = struct.pack('<HHHIHIH', 1, 9, 0x300, 0, 8, 0, 0)
    logfont = bytearray(50)
    struct.pack_into('<h', logfont, 0, -384)
    logfont[13] = 1
    logfont[18:50] = font.encode().ljust(32, b'\0')
    return (header + record(0x12E, struct.pack('<H', 25)) + record(0x2FB, bytes(logfont))
            + record(0x12D, struct.pack('<H', 0)) + record(0x214, struct.pack('<hh', y, 100))
            + record(0xA32, struct.pack('<hhHH', 0, 0, len(text), 0) + text)
            + record(0))


def test_symbol_font_charset_repairs_infinity_without_changing_glyph_bytes():
    original = numeric_wmf(b'\xa5', 'Euclid Symbol')
    repaired, kind = prepare_wmf(original)
    assert kind == 'wmf' and len(repaired) == len(original)
    font = next(p for _, f, p in _records(repaired) if f == 0x2FB)
    assert font[13] == 2 and font[18:50].split(b'\0')[0] == b'Symbol'
    assert b'\xa5' in repaired and b'Euclid Symbol' in original


def test_verified_real_number_set_glyph_has_a_nonblank_png():
    png, kind = prepare_wmf(numeric_wmf(b'\xa1', 'Euclid Extra'))
    assert kind == 'png'
    with Image.open(io.BytesIO(png)) as image:
        assert image.width > 100 and image.height > 100
        assert image.convert('L').getextrema() == (0, 255)


def test_unknown_extra_glyph_is_not_guessed():
    with pytest.raises(ValueError, match='unsupported Euclid Extra'):
        prepare_wmf(numeric_wmf(b'\xa2', 'Euclid Extra'))


@pytest.mark.parametrize('text,expected', [(b'1', '1'), (b'0', '0'), (b'-1', '-1'),
                                           (b'3.5', '3.5'), (b'T', None), (b'1/2', None)])
def test_single_numeric_run_is_read_without_ocr(text, expected):
    assert read_wmf_number(numeric_wmf(text)) == expected


def test_spatial_sign_is_sorted_but_scripts_and_multiple_numbers_are_not_flattened():
    first = numeric_wmf(b'1')[:-6]
    sign_font = bytearray(50)
    struct.pack_into('<h', sign_font, 0, -384)
    sign_font[18:50] = b'Euclid Symbol'.ljust(32, b'\0')
    tail = (record(0x2FB, bytes(sign_font)) + record(0x12D, struct.pack('<H', 1))
            + record(0x214, struct.pack('<hh', 100, 10))
            + record(0xA32, struct.pack('<hhHH', 0, 0, 1, 0) + b'-') + record(0))
    assert read_wmf_number(first + tail) == '-1'
    assert read_wmf_number(first + tail.replace(struct.pack('<hh', 100, 10), struct.pack('<hh', 50, 10))) is None
    assert read_wmf_number(numeric_wmf()[:-6] + record(0x213, b'\0' * 4) + record(0)) is None


def test_context_keeps_original_wmf_and_direct_number_without_ocr_job():
    raw = numeric_wmf(b'-1')
    ctx = Context(rels={'preview': 'word/media/image.wmf'}, assets={'word/media/image.wmf': raw}, defer_ocr=True)
    node = etree.fromstring(f'<w:object xmlns:w="{ns.W[1:-1]}" xmlns:v="{ns.V[1:-1]}" '
                           f'xmlns:o="{ns.O[1:-1]}" xmlns:r="{ns.R[1:-1]}"><v:imagedata r:id="preview"/>'
                           '<o:OLEObject ProgID="Equation.DSMT4"/></w:object>')
    ctx.ole(node)
    ctx.resolve_ocr()
    assert ctx.manifest[0]['latex'] == '-1' and ctx.manifest[0]['method'] == 'wmf-number'
    assert ctx.written['mathtype_1.wmf'] == raw and not ctx.pending_ocr
    assert ctx.ocr_stats['wmf_direct'] == 1


def test_standalone_font_helpers_match_canonical_source():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'src/docx_extract/vector_fonts.py').read_bytes()
    for name in ['colab_ocr_server/vector_fonts.py', 'kaggle_ocr/vector_fonts.py']:
        assert (root / name).read_bytes() == source
