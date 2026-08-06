# MathType OLE → LaTeX (DeepSeek-OCR-2) Implementation Plan

**Goal:** `Context.ole()` OCR ảnh MathType OLE (WMF/EMF) sang LaTeX qua DeepSeek-OCR-2, lưu vào `ctx.latex[oid]` và manifest, không phá hành vi v1.

**Architecture:** Module mới `mathocr.py` (lazy-import torch/transformers bên trong hàm; convert WMF/EMF→PNG qua `pythonnet` + `System.Drawing`). `Context` nhận thêm field `ocr_fn` optional để test tiêm fake, tránh phụ thuộc torch khi chạy test suite.

**Tech Stack:** `torch`, `transformers` (model `deepseek-ai/DeepSeek-OCR-2`), `pythonnet` (GDI+ interop).

---

### Task 1: Khai báo dependency trong `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

- [x] **Step 1: Thêm dependency**
```toml
dependencies = [
    "lxml>=6.1.1",
    "torch>=2.6.0",
    "transformers>=4.46.3",
    "pythonnet>=3.0.5",
]
```
- [x] **Step 2: Không chạy `uv sync` ngay** (torch tải rất nặng, không cần thiết để chạy test suite vì mọi test dùng `ocr_fn` giả lập — chỉ cần khi thực sự chạy pipeline với OLE Equation thật).

---

### Task 2: `mathocr.py` — khung convert + OCR (mock-first)

**Files:**
- Create: `src/docx_extract/mathocr.py`
- Test: `tests/test_mathocr.py`

- [ ] **Step 1: Viết test thất bại cho `image_to_latex` (mock `wmf_to_png` + `_get_model`)**
```python
# tests/test_mathocr.py
from docx_extract import mathocr


def test_image_to_latex_skips_conversion_for_png(monkeypatch):
    monkeypatch.setattr(mathocr, "wmf_to_png", lambda data, ext: (_ for _ in ()).throw(
        AssertionError("wmf_to_png không nên được gọi cho ext=png")))

    class FakeModel:
        def infer(self, tokenizer, prompt, image_file, **kw):
            assert prompt == "<image>\nFree OCR."
            return "x^{2}+1"

    monkeypatch.setattr(mathocr, "_get_model", lambda: (object(), FakeModel()))
    assert mathocr.image_to_latex(b"PNGDATA", "png") == "x^{2}+1"


def test_image_to_latex_converts_wmf_then_ocr(monkeypatch):
    monkeypatch.setattr(mathocr, "wmf_to_png", lambda data, ext: b"PNGBYTES")

    class FakeModel:
        def infer(self, tokenizer, prompt, image_file, **kw):
            with open(image_file, "rb") as f:
                assert f.read() == b"PNGBYTES"
            return "\\frac{a}{b}"

    monkeypatch.setattr(mathocr, "_get_model", lambda: (object(), FakeModel()))
    assert mathocr.image_to_latex(b"WMFDATA", "wmf") == r"\frac{a}{b}"


def test_image_to_latex_returns_none_when_conversion_fails(monkeypatch):
    monkeypatch.setattr(mathocr, "wmf_to_png", lambda data, ext: None)
    assert mathocr.image_to_latex(b"WMFDATA", "wmf") is None


def test_image_to_latex_returns_none_on_model_exception(monkeypatch):
    monkeypatch.setattr(mathocr, "wmf_to_png", lambda data, ext: b"PNGBYTES")

    def boom():
        raise RuntimeError("model load failed")

    monkeypatch.setattr(mathocr, "_get_model", boom)
    assert mathocr.image_to_latex(b"WMFDATA", "wmf") is None


def test_wmf_to_png_returns_none_without_pythonnet(monkeypatch):
    # Môi trường test không cài pythonnet -> import lỗi -> None (không crash)
    assert mathocr.wmf_to_png(b"not a real wmf", "wmf") is None
```

- [ ] **Step 2: Chạy test để thấy fail**
Run: `uv run pytest tests/test_mathocr.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docx_extract.mathocr'`

- [ ] **Step 3: Viết implementation tối thiểu**
```python
# src/docx_extract/mathocr.py
"""MathType OLE (WMF/EMF) -> LaTeX qua OCR (DeepSeek-OCR-2).

torch/transformers/pythonnet được import BÊN TRONG hàm (không ở top-level)
để phần còn lại của package không bắt buộc các gói này khi không đụng OLE.
"""
import os
import tempfile

_MODEL_NAME = "deepseek-ai/DeepSeek-OCR-2"
_MODEL = None
_TOKENIZER = None


def _get_model():
    """Lazy-singleton load model — chỉ tải/khởi tạo một lần cho cả tiến trình."""
    global _MODEL, _TOKENIZER
    if _MODEL is None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        _TOKENIZER = AutoTokenizer.from_pretrained(_MODEL_NAME, trust_remote_code=True)
        model = AutoModel.from_pretrained(
            _MODEL_NAME, trust_remote_code=True, use_safetensors=True
        )
        model = model.eval().to(torch.bfloat16)
        try:
            model = model.cuda()
        except Exception:
            pass  # không có GPU -> chạy CPU (chậm hơn, vẫn chạy được)
        _MODEL = model
    return _TOKENIZER, _MODEL


def wmf_to_png(data: bytes, ext: str) -> bytes | None:
    """Convert WMF/EMF bytes -> PNG bytes qua GDI+ (.NET System.Drawing). None nếu lỗi."""
    try:
        import clr  # pythonnet

        clr.AddReference("System.Drawing")
        from System.Drawing import Image as NetImage
        from System.Drawing.Imaging import ImageFormat
        from System.IO import MemoryStream

        in_stream = MemoryStream(data)
        img = NetImage.FromStream(in_stream)
        out_stream = MemoryStream()
        img.Save(out_stream, ImageFormat.Png)
        return bytes(out_stream.ToArray())
    except Exception:
        return None


def image_to_latex(data: bytes, ext: str) -> str | None:
    """OCR ảnh công thức (WMF/EMF hoặc PNG sẵn) ra LaTeX. None nếu lỗi bất kỳ bước nào."""
    try:
        png = wmf_to_png(data, ext) if ext.lower() in ("wmf", "emf") else data
        if png is None:
            return None
        tokenizer, model = _get_model()
        with tempfile.TemporaryDirectory() as tmp:
            img_path = os.path.join(tmp, "formula.png")
            with open(img_path, "wb") as f:
                f.write(png)
            result = model.infer(
                tokenizer,
                prompt="<image>\nFree OCR.",
                image_file=img_path,
                base_size=1024,
                image_size=640,
                crop_mode=True,
                save_results=False,
                output_path=tmp,
            )
        text = result.strip() if isinstance(result, str) else None
        return text or None
    except Exception:
        return None
```

- [ ] **Step 4: Chạy test để xác nhận pass**
Run: `uv run pytest tests/test_mathocr.py -v`
Expected: PASS (5/5)

- [ ] **Step 5: Commit**
`git add src/docx_extract/mathocr.py tests/test_mathocr.py pyproject.toml && git commit -m "feat: add mathocr module for MathType OLE -> LaTeX via DeepSeek-OCR-2"`

---

### Task 3: Nối `mathocr` vào `Context.ole()`

**Files:**
- Modify: `src/docx_extract/context.py`
- Modify: `tests/test_math_assets.py`

- [ ] **Step 1: Sửa test hiện có (nó sẽ fail vì hành vi mới thêm OCR call)**

Test `test_ole_equation_object_emits_mathtype` hiện assert `not c.warnings`. Với thay đổi mới, `Context()` mặc định (`ocr_fn=None`) sẽ gọi `mathocr.image_to_latex` thật — trong môi trường test không có torch/pythonnet nên sẽ trả `None` → cảnh báo "không trả LaTeX" được thêm → assertion `not c.warnings` FAIL đúng như kỳ vọng (đây là RED cho hành vi mới, xác nhận wiring đã chạy). Sửa test để tiêm `ocr_fn` giả lập:

```python
def test_ole_equation_object_emits_mathtype():
    # ProgID chứa "Equation" (Equation.DSMT4 / Equation.3) -> hành vi cũ,
    # không đổi: placeholder mathtype_N, bộ đếm tăng, asset ghi ra.
    # ocr_fn giả lập để test không phụ thuộc torch/pythonnet thật.
    c = Context(
        rels={"rId5": "word/embeddings/oleObject1.wmf"},
        assets={"word/embeddings/oleObject1.wmf": b"WMF"},
        ocr_fn=lambda data, ext: "x^{2}",
    )
    w_obj = _w_object("Equation.DSMT4")
    assert c.ole(w_obj) == "[!m:$mathtype_1$]"
    assert c.counter == 1
    assert c.written["mathtype_1.wmf"] == b"WMF"
    assert not c.warnings
    assert c.latex["mathtype_1"] == "x^{2}"
    assert c.manifest[-1]["latex"] == "x^{2}"


def test_ole_equation_ocr_failure_warns_but_keeps_placeholder():
    # ocr_fn trả None (OCR thất bại) -> cảnh báo, KHÔNG crash, placeholder ảnh
    # vẫn xuất ra, không có entry trong ctx.latex.
    c = Context(
        rels={"rId5": "word/embeddings/oleObject1.wmf"},
        assets={"word/embeddings/oleObject1.wmf": b"WMF"},
        ocr_fn=lambda data, ext: None,
    )
    w_obj = _w_object("Equation.DSMT4")
    assert c.ole(w_obj) == "[!m:$mathtype_1$]"
    assert "mathtype_1" not in c.latex
    assert c.warnings
    assert c.manifest[-1]["latex"] is None


def test_ole_equation_ocr_exception_warns_but_keeps_placeholder():
    # ocr_fn raise exception -> vẫn bắt lại, cảnh báo, không crash.
    def boom(data, ext):
        raise RuntimeError("model crashed")

    c = Context(
        rels={"rId5": "word/embeddings/oleObject1.wmf"},
        assets={"word/embeddings/oleObject1.wmf": b"WMF"},
        ocr_fn=boom,
    )
    w_obj = _w_object("Equation.DSMT4")
    assert c.ole(w_obj) == "[!m:$mathtype_1$]"
    assert "mathtype_1" not in c.latex
    assert c.warnings
```

- [ ] **Step 2: Chạy test suite để thấy fail đúng chỗ**
Run: `uv run pytest tests/test_math_assets.py -v`
Expected: FAIL — `test_ole_equation_object_emits_mathtype` fail ở `assert not c.warnings` (do OCR thật trả None); 2 test mới fail vì `Context.__init__()` chưa có tham số `ocr_fn`.

- [ ] **Step 3: Sửa `context.py`**
```python
@dataclass
class Context:
    rels: dict
    assets: dict
    counter: int = 0
    written: dict = field(default_factory=dict)     # filename -> bytes
    manifest: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    latex: dict = field(default_factory=dict)     # oid -> LaTeX (OMML + OCR mathtype)
    ocr_fn: object = None   # Callable[[bytes, str], str | None] | None — tiêm cho test
```
Thêm helper method (đặt trước `ole`):
```python
    def _ocr_mathtype(self, oid: str, data: bytes, ext: str) -> None:
        """OCR ảnh MathType OLE (WMF/EMF) sang LaTeX -> self.latex[oid].
        Lỗi ở bất kỳ bước nào -> warning, KHÔNG crash, KHÔNG set latex."""
        fn = self.ocr_fn if self.ocr_fn is not None else mathlatex_ocr_fn()
        try:
            latex = fn(data, ext)
        except Exception as exc:
            self.warnings.append(f"{oid}: OCR MathType lỗi: {exc}")
            return
        if latex:
            self.latex[oid] = latex
        else:
            self.warnings.append(f"{oid}: OCR MathType không trả LaTeX")
```
Thêm import ở đầu file: `from . import mathocr` và thay `mathlatex_ocr_fn()` bằng `mathocr.image_to_latex` trực tiếp (bỏ hàm thừa) — bản final:
```python
    def _ocr_mathtype(self, oid: str, data: bytes, ext: str) -> None:
        fn = self.ocr_fn if self.ocr_fn is not None else mathocr.image_to_latex
        try:
            latex = fn(data, ext)
        except Exception as exc:
            self.warnings.append(f"{oid}: OCR MathType lỗi: {exc}")
            return
        if latex:
            self.latex[oid] = latex
        else:
            self.warnings.append(f"{oid}: OCR MathType không trả LaTeX")
```
Sửa `ole()` — nhánh `data is not None`:
```python
        else:
            ext = self._ext(path)
            fn = f"{oid}.{ext}"
            self.written[fn] = data
            self._ocr_mathtype(oid, data, ext)
            self.manifest.append(
                {"id": oid, "type": "mathtype", "source": path, "latex": self.latex.get(oid)}
            )
        return f"[!m:${oid}$]"
```

- [ ] **Step 4: Chạy lại test suite để xác nhận pass**
Run: `uv run pytest tests/test_math_assets.py -v`
Expected: PASS (tất cả case, gồm 2 case mới)

- [ ] **Step 5: Chạy toàn bộ suite để đảm bảo không regression**
Run: `uv run pytest -v`
Expected: PASS toàn bộ

- [ ] **Step 6: Commit**
`git add src/docx_extract/context.py tests/test_math_assets.py && git commit -m "feat: wire mathocr into Context.ole() for MathType OLE -> LaTeX"`

---

### Task 4: Cập nhật spec cũ (đảo quyết định #1)

**Files:**
- Modify: `docs/superpowers/specs/2026-07-06-structured-latex-export-design.md`

- [ ] **Step 1:** Sửa mục 1 quyết định #1 từ "giữ nguyên dạng ảnh — KHÔNG convert sang LaTeX" thành ghi chú tham chiếu spec mới (`2026-08-06-mathtype-ocr-latex-design.md`) đã đảo quyết định này: MathType OLE giờ CÓ convert sang LaTeX qua OCR (DeepSeek-OCR-2), asset ảnh vẫn giữ làm backup/tham chiếu.
- [ ] **Step 2: Commit**
`git add docs/superpowers/specs/2026-07-06-structured-latex-export-design.md && git commit -m "docs: update v2 spec — MathType OLE now converts to LaTeX via OCR"`

---

## Ghi chú thực thi

- Không cài/tải torch thật trong quá trình implement — mọi test dùng `ocr_fn` giả lập hoặc monkeypatch `mathocr._get_model`/`mathocr.wmf_to_png`. Việc cài `torch`/`transformers`/`pythonnet` thật và tải weight 6.67GB để chạy OCR thật để dành cho lúc bạn thực sự chạy pipeline trên máy có sẵn thời gian/băng thông.
- `structure.py` (Phần→Nhóm→Câu) chưa tồn tại trong code — khi được xây dựng sau này sẽ tự động hưởng LaTeX của `mathtype_*` từ `ctx.latex` giống `mathml_*`, không cần sửa gì thêm ở plan này.
