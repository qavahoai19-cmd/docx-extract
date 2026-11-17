"""Logic thuần (không phụ thuộc torch/fastapi) dùng chung cho ocr_server.py.

Tách riêng để có thể unit-test trên bất kỳ máy nào (kể cả máy không có GPU/
LibreOffice) — ocr_server.py chỉ import các hàm này rồi ghép với FastAPI/model.
"""

_RASTER_EXTS = {"png", "jpg", "jpeg", "bmp", "gif", "webp"}
_VECTOR_EXTS = {"wmf", "emf"}


def ext_of(filename: str) -> str:
    """Lấy phần mở rộng (chữ thường, không dấu chấm) từ tên file."""
    return (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()


def needs_conversion(ext: str) -> bool:
    """WMF/EMF cần convert sang raster (PNG) trước khi đưa vào model OCR."""
    return ext.lower() in _VECTOR_EXTS


def build_soffice_cmd(input_path: str, out_dir: str) -> list[str]:
    """Lệnh LibreOffice headless convert 1 file WMF/EMF sang PNG."""
    return [
        "soffice", "--headless", "--norestore", "--convert-to", "png",
        "--outdir", out_dir, input_path,
    ]


def build_soffice_batch_cmd(input_paths, out_dir, profile_dir):
    from pathlib import Path
    return ["soffice", "-env:UserInstallation=" + Path(profile_dir).resolve().as_uri(),
            "--headless", "--norestore", "--convert-to", "png",
            "--outdir", out_dir, *input_paths]


def crop_whitespace(png_bytes: bytes, padding: int = 20) -> bytes:
    import io
    from PIL import Image
    with Image.open(io.BytesIO(png_bytes)) as original:
        rgba = original.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        background.alpha_composite(rgba)
        image = background.convert("RGB")
    # getbbox finds nonzero pixels: ink must be 255, white must be zero.
    bbox = image.convert("L").point(lambda p: 255 if p < 250 else 0).getbbox()
    if bbox is None:
        raise ValueError("blank formula image")
    left, top, right, bottom = bbox
    crop = image.crop((max(0, left-padding), max(0, top-padding),
                       min(image.width, right+padding), min(image.height, bottom+padding)))
    output = io.BytesIO()
    crop.save(output, format="PNG")
    return output.getvalue()


def select_model_dtype(torch_module, requested="auto"):
    """Prefer native BF16 on Ampere+, FP16 on T4/P100; never emulate BF16."""
    major, _ = torch_module.cuda.get_device_capability(0)
    if requested == "auto":
        requested = "bfloat16" if major >= 8 else "float16"
    if requested in {"float16", "fp16", "half"}:
        return torch_module.float16
    if requested in {"bfloat16", "bf16"} and major >= 8:
        return torch_module.bfloat16
    raise ValueError("Use DOCX_OCR_DTYPE=auto/float16, or bfloat16 on a native BF16 GPU")


def adapt_infer_dtype(model, dtype, torch_module):
    """Adapt only this model instance's hardcoded BF16 input/autocast sites.

    DeepSeek's upstream infer() fixes torch.bfloat16 independently of the model
    weights. Loading weights as FP16 alone does not make it run on T4/P100.
    Clone the method with a private dtype binding; leave torch and the shared
    Hugging Face module/cache unchanged. Pinned model revisions make this
    adaptation reproducible. No global monkeypatches or model-file edits.
    """
    if dtype == torch_module.bfloat16:
        return 0
    import ast
    import inspect
    import textwrap
    import types
    original = model.infer.__func__
    if original.__closure__:
        raise RuntimeError("Cannot adapt a model infer method with closure state")
    tree = ast.parse(textwrap.dedent(inspect.getsource(original)))
    class DtypeAdapter(ast.NodeTransformer):
        count = 0
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == "torch" and node.attr == "bfloat16":
                self.count += 1
                return ast.copy_location(ast.Name(id="_docx_infer_dtype", ctx=ast.Load()), node)
            return self.generic_visit(node)
    adapter = DtypeAdapter()
    tree = ast.fix_missing_locations(adapter.visit(tree))
    if adapter.count:
        namespace = dict(original.__globals__)
        namespace["_docx_infer_dtype"] = dtype
        exec(compile(tree, inspect.getsourcefile(original) or "<ocr-infer-dtype>", "exec"), namespace)
        model.infer = types.MethodType(namespace[original.__name__], model)
    return adapter.count
