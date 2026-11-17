import io
import os
import zipfile
from pathlib import Path

import pytest

from docx_extract.raster import prepare_image


def test_raster_files_are_not_changed():
    assert prepare_image(b"PNG bytes", "png") == (b"PNG bytes", "png")


def test_bad_vector_preserves_original_for_server_fallback():
    assert prepare_image(b"bad vector", "wmf") == (b"bad vector", "wmf")


@pytest.mark.skipif(os.name != "nt", reason="Windows native rasterizer")
def test_real_wmf_rasterizes_without_blank_output():
    Image = pytest.importorskip("PIL.Image")
    with zipfile.ZipFile(Path(__file__).parent / "fixtures" / "sample.docx") as archive:
        source = next(name for name in archive.namelist() if name.endswith(".wmf"))
        png, ext = prepare_image(archive.read(source), "wmf")
    assert ext == "png" and png.startswith(b"\x89PNG")
    with Image.open(io.BytesIO(png)) as image:
        assert max(image.size) <= 2400
        assert image.convert("L").point(lambda p: 255 if p < 250 else 0).getbbox()
