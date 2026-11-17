from ocr_logic import ext_of, needs_conversion, build_soffice_cmd
from ocr_logic import adapt_infer_dtype, select_model_dtype
from types import SimpleNamespace
import pytest

torch = SimpleNamespace(float16="fp16", bfloat16="bf16")


class ExampleModel:
    def infer(self):
        return torch.bfloat16, "torch.bfloat16"


def test_dtype_follows_native_gpu_capability():
    for major, expected in [(6,"fp16"),(7,"fp16"),(8,"bf16"),(9,"bf16")]:
        fake = SimpleNamespace(float16="fp16", bfloat16="bf16",
                               cuda=SimpleNamespace(get_device_capability=lambda index: (major,0)))
        assert select_model_dtype(fake)==expected
        if major<8:
            with pytest.raises(ValueError):
                select_model_dtype(fake,"bfloat16")


def test_dtype_adapter_is_local_to_model_instance():
    first, second = ExampleModel(), ExampleModel()
    assert adapt_infer_dtype(first,"fp16",torch)==1
    assert first.infer()==("fp16","torch.bfloat16")
    assert second.infer()==("bf16","torch.bfloat16")
    assert torch.bfloat16=="bf16"


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
