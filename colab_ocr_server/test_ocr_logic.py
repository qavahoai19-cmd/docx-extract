from ocr_logic import ext_of, needs_conversion, build_soffice_cmd


def test_ext_of_returns_lowercase_extension_without_dot():
    assert ext_of("formula.WMF") == "wmf"
    assert ext_of("formula.png") == "png"


def test_ext_of_returns_empty_string_when_no_extension():
    assert ext_of("formula") == ""


def test_needs_conversion_true_for_wmf_and_emf():
    assert needs_conversion("wmf") is True
    assert needs_conversion("emf") is True


def test_needs_conversion_false_for_raster_formats():
    assert needs_conversion("png") is False
    assert needs_conversion("jpg") is False
    assert needs_conversion("jpeg") is False


def test_build_soffice_cmd_shape():
    cmd = build_soffice_cmd("/tmp/x/formula.wmf", "/tmp/x")
    assert cmd[0] == "soffice"
    assert "--convert-to" in cmd
    idx = cmd.index("--convert-to")
    assert cmd[idx + 1] == "png"
    assert "--outdir" in cmd
    outdir_idx = cmd.index("--outdir")
    assert cmd[outdir_idx + 1] == "/tmp/x"
    assert cmd[-1] == "/tmp/x/formula.wmf"
