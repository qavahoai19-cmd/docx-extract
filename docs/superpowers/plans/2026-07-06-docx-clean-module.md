# DOCX → markup Azota (module làm sạch) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Biến file `.docx` đề thi thành markup phẳng y hệt panel phải của Azota (`[!b:]`, `[!m:$mathml_N$]`, `[img:$img_N$]`, `[* | *]`, `*D.`…), kèm trích asset thô ra `sidecar/`.

**Architecture:** Pipeline tuyến tính. `loader` mở docx (zip) → `assemble` duyệt `w:body` theo document order → mỗi `w:p` render qua `runs` (gộp run + inline tag), math/ảnh qua `math_assets` (placeholder + trích asset, bộ đếm toàn cục), đáp án qua `answer` (strip option-marker + `*`), bảng qua `tables`. Không build cây câu hỏi, không convert công thức.

**Tech Stack:** Python 3.13, lxml, stdlib (zipfile, json, re, dataclasses), pytest. Quản lý bằng `uv`.

## Global Constraints

- Ngôn ngữ: Python ≥ 3.13; chỉ phụ thuộc runtime là `lxml`; test bằng `pytest`.
- Output markup **y hệt cú pháp Azota**: `[!b:$..$]`, `[!i:$..$]`, `[!b!i:$..$]`, `[!sup:$..$]`, `[!sub:$..$]`, `[!m:$mathml_N$]`, `[!m:$mathtype_N$]`, `[img:$img_N$]`, bảng `[* c1 | c2 *]`, đáp án đúng `*<letter>.`.
- **Một bộ đếm placeholder toàn cục** tăng dần theo document order; prefix theo loại (`mathml_`/`mathtype_`/`img_`).
- **Làm sạch = whitelist:** chỉ giữ b/i/sup/sub/math/img/table; vứt màu/cỡ/font/highlight/rsid.
- Không crash giữa file: element lạ/asset thiếu → bỏ qua + gom warning.
- File mẫu (golden oracle): `C:\Users\admin\Downloads\ĐỀ VẬT LÍ LẦN 3_VER 2 (2).docx`; markup đúng = đoạn người dùng cung cấp (lưu thành `tests/fixtures/golden_azota.txt`).
- OOXML namespaces (định nghĩa 1 lần ở `ns.py`):
  - `w  = {http://schemas.openxmlformats.org/wordprocessingml/2006/main}`
  - `m  = {http://schemas.openxmlformats.org/officeDocument/2006/math}`
  - `a  = {http://schemas.openxmlformats.org/drawingml/2006/main}`
  - `r  = {http://schemas.openxmlformats.org/officeDocument/2006/relationships}`
  - `v  = {urn:schemas-microsoft-com:vml}`
  - `o  = {urn:schemas-microsoft-com:office:office}`
  - `pr = {http://schemas.openxmlformats.org/package/2006/relationships}` (file .rels)

---

## File Structure

```
docx-extract/
  pyproject.toml
  src/docx_extract/
    __init__.py        # export clean_docx
    __main__.py        # CLI
    ns.py              # hằng namespace + qname helper
    context.py         # Context (bộ đếm, rels, assets, manifest, warnings)
    loader.py          # mở docx → Document
    runs.py            # w:p → markup (inline tag + gộp run)
    math_assets.py     # placeholder + trích asset
    answer.py          # option-marker + '*'
    tables.py          # w:tbl → [* | *]
    assemble.py        # clean_docx()
  tests/
    fixtures/golden_azota.txt
    test_loader.py test_runs.py test_math_assets.py
    test_answer.py test_tables.py test_assemble.py test_golden.py
```

---

## Task 0: Scaffold dự án

**Files:**
- Create: `pyproject.toml`, `src/docx_extract/__init__.py`, `src/docx_extract/ns.py`
- Create: `tests/fixtures/golden_azota.txt`

**Interfaces:**
- Produces: `ns.W, ns.M, ns.A, ns.R, ns.V, ns.O, ns.PR` (str, dạng Clark `{uri}`); `ns.q(prefix, tag)` → `str`.

- [ ] **Step 1: Khởi tạo project + deps**

```bash
cd "E:/LMS/docx-extract"
git init
uv init --package --name docx-extract --python 3.13
uv add lxml
uv add --dev pytest
```

- [ ] **Step 2: Cấu hình pytest trong `pyproject.toml`**

Thêm vào cuối `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 3: Viết `ns.py`**

```python
W  = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M  = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
A  = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R  = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
V  = "{urn:schemas-microsoft-com:vml}"
O  = "{urn:schemas-microsoft-com:office:office}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_MAP = {"w": W, "m": M, "a": A, "r": R, "v": V, "o": O, "pr": PR}

def q(prefix: str, tag: str) -> str:
    """q('w','p') -> '{...main}p'"""
    return _MAP[prefix] + tag
```

- [ ] **Step 4: Lưu golden fixture**

Tạo `tests/fixtures/golden_azota.txt` chứa nguyên văn đoạn markup Azota người dùng đã cung cấp (từ `[!b:$PHẦN I...` đến hết `[!i:$[/]$]`). Đây là oracle cho Task 8.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: scaffold docx-extract package"
```

---

## Task 1: `loader.py` — mở docx

**Files:**
- Create: `src/docx_extract/loader.py`
- Test: `tests/test_loader.py`

**Interfaces:**
- Produces:
  - `class Document` (dataclass): `body` (`lxml.etree._Element` = phần tử `w:body`), `rels: dict[str,str]` (rId → đường dẫn zip đầy đủ, vd `"word/media/image14.png"`), `assets: dict[str,bytes]` (key = đường dẫn zip đầy đủ).
  - `load(path: str) -> Document`

- [ ] **Step 1: Viết test thất bại**

```python
from docx_extract.loader import load
from docx_extract import ns

DOCX = r"C:\Users\admin\Downloads\ĐỀ VẬT LÍ LẦN 3_VER 2 (2).docx"

def test_load_returns_body_rels_assets():
    doc = load(DOCX)
    assert doc.body.tag == ns.q("w", "body")
    # có ít nhất 1 rId trỏ tới media
    assert any(v.startswith("word/media/") for v in doc.rels.values())
    # asset bytes nạp được
    media = [k for k in doc.assets if k.startswith("word/media/")]
    assert media and isinstance(doc.assets[media[0]], bytes)
```

- [ ] **Step 2: Chạy để xác nhận fail**

Run: `uv run pytest tests/test_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: docx_extract.loader`

- [ ] **Step 3: Implement `loader.py`**

```python
import zipfile
import posixpath
from dataclasses import dataclass
from lxml import etree
from . import ns


@dataclass
class Document:
    body: etree._Element
    rels: dict          # rId -> full zip path
    assets: dict        # full zip path -> bytes


def load(path: str) -> Document:
    with zipfile.ZipFile(path) as z:
        doc_xml = z.read("word/document.xml")
        rels_xml = z.read("word/_rels/document.xml.rels")
        assets = {
            n: z.read(n)
            for n in z.namelist()
            if n.startswith("word/media/") or n.startswith("word/embeddings/")
        }

    root = etree.fromstring(doc_xml)
    body = root.find(ns.q("w", "body"))

    rels = {}
    for rel in etree.fromstring(rels_xml):
        rid = rel.get("Id")
        target = rel.get("Target")
        # Target tương đối với thư mục word/ ; chuẩn hoá về đường dẫn zip
        full = posixpath.normpath(posixpath.join("word", target))
        rels[rid] = full
    return Document(body=body, rels=rels, assets=assets)
```

- [ ] **Step 4: Chạy test — PASS**

Run: `uv run pytest tests/test_loader.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: docx loader (body, rels, assets)"
```

---

## Task 2: `runs.py` — inline tag + gộp run (chưa có math)

**Files:**
- Create: `src/docx_extract/runs.py`
- Test: `tests/test_runs.py`

**Interfaces:**
- Consumes: `ns`.
- Produces:
  - `run_format(rpr) -> tuple[bool,bool,str|None,bool]` = (bold, italic, vert, underline).
  - `wrap(text: str, fmt) -> str` (bỏ qua underline khi bọc tag).
  - `render_paragraph(p, ctx) -> str` — `ctx` có thể là `None` ở task này (chưa dùng math). Trả markup của 1 đoạn.
  - Segment model: list các tuple `(kind, fmt, content)` với `kind ∈ {"text","raw"}`.

- [ ] **Step 1: Viết test thất bại**

```python
from lxml import etree
from docx_extract.runs import render_paragraph
from docx_extract import ns

def _p(xml_inner: str):
    xml = f'<w:p xmlns:w="{ns.W[1:-1]}">{xml_inner}</w:p>'
    return etree.fromstring(xml)

def _run(text, b=False, i=False, vert=None, u=False):
    rpr = "<w:rPr>"
    if b: rpr += "<w:b/>"
    if i: rpr += "<w:i/>"
    if vert: rpr += f'<w:vertAlign w:val="{vert}"/>'
    if u: rpr += '<w:u w:val="single"/>'
    rpr += "</w:rPr>"
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'

def test_plain_text():
    assert render_paragraph(_p(_run("Nội năng")), None) == "Nội năng"

def test_bold():
    assert render_paragraph(_p(_run("không", b=True)), None) == "[!b:$không$]"

def test_bold_italic():
    assert render_paragraph(_p(_run("a", b=True, i=True)), None) == "[!b!i:$a$]"

def test_superscript():
    assert render_paragraph(_p(_run("2", vert="superscript")), None) == "[!sup:$2$]"

def test_subscript():
    assert render_paragraph(_p(_run("0", vert="subscript")), None) == "[!sub:$0$]"

def test_merge_adjacent_same_format():
    inner = _run("ab", b=True) + _run("cd", b=True)
    assert render_paragraph(_p(inner), None) == "[!b:$abcd$]"

def test_no_merge_different_format():
    inner = _run("a", b=True) + _run("b")
    assert render_paragraph(_p(inner), None) == "[!b:$a$]b"
```

- [ ] **Step 2: Chạy — FAIL**

Run: `uv run pytest tests/test_runs.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `runs.py`**

```python
import re
from . import ns

TAB_SPACES = "\t"   # tinh chỉnh ở Task 8 theo golden

def run_format(rpr):
    if rpr is None:
        return (False, False, None, False)
    bold = rpr.find(ns.q("w", "b")) is not None
    italic = rpr.find(ns.q("w", "i")) is not None
    va = rpr.find(ns.q("w", "vertAlign"))
    vert = va.get(ns.q("w", "val")) if va is not None else None
    underline = rpr.find(ns.q("w", "u")) is not None
    return (bold, italic, vert, underline)

def wrap(text, fmt):
    bold, italic, vert, _u = fmt
    if vert == "superscript":
        return f"[!sup:${text}$]"
    if vert == "subscript":
        return f"[!sub:${text}$]"
    if bold and italic:
        return f"[!b!i:${text}$]"
    if bold:
        return f"[!b:${text}$]"
    if italic:
        return f"[!i:${text}$]"
    return text

def _render_run(r, ctx, segments):
    fmt = run_format(r.find(ns.q("w", "rPr")))
    for child in r:
        tag = child.tag
        if tag == ns.q("w", "t"):
            segments.append(("text", fmt, child.text or ""))
        elif tag == ns.q("w", "tab"):
            segments.append(("text", fmt, TAB_SPACES))
        elif tag == ns.q("w", "br"):
            segments.append(("raw", None, "\n"))
        elif tag == ns.q("w", "drawing") and ctx is not None:
            segments.append(("raw", None, ctx.image(child)))
        elif tag == ns.q("w", "object") and ctx is not None:
            segments.append(("raw", None, ctx.ole(child)))

def _walk(parent, ctx, segments):
    for child in parent:
        tag = child.tag
        if tag == ns.q("w", "r"):
            _render_run(child, ctx, segments)
        elif tag in (ns.q("m", "oMath"), ns.q("m", "oMathPara")) and ctx is not None:
            segments.append(("raw", None, ctx.omml(child)))
        elif tag == ns.q("w", "hyperlink"):
            _walk(child, ctx, segments)

def _coalesce(segments):
    merged = []
    for kind, fmt, content in segments:
        if kind == "text" and merged and merged[-1][0] == "text" and merged[-1][1] == fmt:
            merged[-1] = ("text", fmt, merged[-1][2] + content)
        else:
            merged.append((kind, fmt, content))
    return merged

def emit(segments):
    out = []
    for kind, fmt, content in _coalesce(segments):
        if kind == "raw":
            out.append(content)
        else:
            out.append(wrap(content, fmt) if content else "")
    return "".join(out)

def render_paragraph(p, ctx):
    segments = []
    _walk(p, ctx, segments)
    return emit(segments)
```

- [ ] **Step 4: Chạy — PASS**

Run: `uv run pytest tests/test_runs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: run renderer with inline tags + run merge"
```

---

## Task 3: `context.py` + `math_assets.py` — placeholder + trích asset

**Files:**
- Create: `src/docx_extract/context.py`, `src/docx_extract/math_assets.py`
- Test: `tests/test_math_assets.py`

**Interfaces:**
- Consumes: `loader.Document`, `ns`.
- Produces `context.Context` (dataclass) với các method mà `runs`/`tables` gọi:
  - `omml(elem) -> str` → `"[!m:$mathml_N$]"`, lưu OMML fragment.
  - `ole(w_object_elem) -> str` → `"[!m:$mathtype_N$]"`, copy render WMF/EMF.
  - `image(w_drawing_elem) -> str` → `"[img:$img_N$]"`, copy media.
  - Field: `written: dict[str,bytes]` (tên file sidecar → bytes), `manifest: list[dict]`, `warnings: list[str]`.
  - Helper nội bộ `_next(prefix) -> str` tăng bộ đếm toàn cục.

- [ ] **Step 1: Viết test thất bại**

```python
from lxml import etree
from docx_extract.context import Context
from docx_extract import ns

def _ctx(rels=None, assets=None):
    return Context(rels=rels or {}, assets=assets or {})

def test_global_counter_shared_across_types():
    c = _ctx()
    m = etree.fromstring(f'<m:oMath xmlns:m="{ns.M[1:-1]}"><m:r/></m:oMath>')
    assert c.omml(m) == "[!m:$mathml_1$]"
    # ảnh kế tiếp lấy số 2 (chung bộ đếm)
    draw = etree.fromstring(
        f'<w:drawing xmlns:w="{ns.W[1:-1]}" xmlns:a="{ns.A[1:-1]}" xmlns:r="{ns.R[1:-1]}">'
        f'<a:blip r:embed="rId9"/></w:drawing>')
    c2 = Context(rels={"rId9": "word/media/image14.png"}, assets={"word/media/image14.png": b"PNG"})
    c2.counter = 1
    assert c2.image(draw) == "[img:$img_2$]"
    assert c2.written["img_2.png"] == b"PNG"

def test_omml_fragment_saved():
    c = _ctx()
    m = etree.fromstring(f'<m:oMath xmlns:m="{ns.M[1:-1]}"><m:r/></m:oMath>')
    c.omml(m)
    assert "mathml_1.xml" in c.written
    assert b"oMath" in c.written["mathml_1.xml"]

def test_missing_rid_warns_but_emits():
    c = _ctx()
    draw = etree.fromstring(
        f'<w:drawing xmlns:w="{ns.W[1:-1]}" xmlns:a="{ns.A[1:-1]}" xmlns:r="{ns.R[1:-1]}">'
        f'<a:blip r:embed="rNope"/></w:drawing>')
    assert c.image(draw) == "[img:$img_1$]"
    assert c.warnings
```

- [ ] **Step 2: Chạy — FAIL**

Run: `uv run pytest tests/test_math_assets.py -v`
Expected: FAIL — `ModuleNotFoundError: docx_extract.context`

- [ ] **Step 3: Implement `context.py`**

```python
import posixpath
from dataclasses import dataclass, field
from lxml import etree
from . import ns


@dataclass
class Context:
    rels: dict
    assets: dict
    counter: int = 0
    written: dict = field(default_factory=dict)     # filename -> bytes
    manifest: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def _next(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.counter}"

    def _ext(self, path: str) -> str:
        return posixpath.splitext(path)[1].lstrip(".").lower() or "bin"

    def omml(self, elem) -> str:
        oid = self._next("mathml")
        frag = etree.tostring(elem, encoding="utf-8")
        self.written[f"{oid}.xml"] = frag
        self.manifest.append({"id": oid, "type": "mathml", "source": "inline-omml"})
        return f"[!m:${oid}$]"

    def _resolve(self, rid):
        path = self.rels.get(rid)
        if path is None or path not in self.assets:
            return None, None
        return path, self.assets[path]

    def image(self, drawing) -> str:
        oid = self._next("img")
        blip = drawing.find(f".//{ns.q('a', 'blip')}")
        rid = blip.get(ns.q("r", "embed")) if blip is not None else None
        path, data = self._resolve(rid)
        if data is None:
            self.warnings.append(f"{oid}: rId {rid} không giải được")
            self.manifest.append({"id": oid, "type": "img", "source": "missing", "rid": rid})
        else:
            fn = f"{oid}.{self._ext(path)}"
            self.written[fn] = data
            self.manifest.append({"id": oid, "type": "img", "source": path})
        return f"[img:${oid}$]"

    def ole(self, w_object) -> str:
        oid = self._next("mathtype")
        # render WMF/EMF nằm ở v:imagedata @r:id
        imagedata = w_object.find(f".//{ns.q('v', 'imagedata')}")
        rid = imagedata.get(ns.q("r", "id")) if imagedata is not None else None
        path, data = self._resolve(rid)
        if data is None:
            self.warnings.append(f"{oid}: OLE render rId {rid} không giải được")
            self.manifest.append({"id": oid, "type": "mathtype", "source": "missing", "rid": rid})
        else:
            fn = f"{oid}.{self._ext(path)}"
            self.written[fn] = data
            self.manifest.append({"id": oid, "type": "mathtype", "source": path})
        return f"[!m:${oid}$]"
```

- [ ] **Step 4: Tạo `math_assets.py` re-export** (giữ tên module theo spec)

```python
# math_assets.py — placeholder + trích asset sống trong Context.
# Module này giữ tên theo spec và có thể chứa helper thuần tuý về sau.
from .context import Context  # noqa: F401
```

- [ ] **Step 5: Chạy — PASS**

Run: `uv run pytest tests/test_math_assets.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: Context — global placeholder counter + asset extraction"
```

---

## Task 4: `answer.py` — strip option-marker + đánh `*`

**Files:**
- Create: `src/docx_extract/answer.py`
- Modify: `src/docx_extract/runs.py` (gọi hook option-marker trong `emit`)
- Test: `tests/test_answer.py`

**Bối cảnh:** Trong file mẫu, chữ cái phương án là **run riêng**, in đậm; phương án đúng có thêm **gạch chân**. Azota **không** bọc `[!b:]` quanh chữ cái phương án — nó strip định dạng của marker và thêm `*` nếu gạch chân. Quy tắc: một text-segment khớp `^\s*[A-D][.)]\s*$` → coi là option-marker → xuất plain (không tag); nếu segment đó có underline → prefix `*`.

**Interfaces:**
- Consumes: segment model của `runs`.
- Produces: `answer.is_option_marker(text: str) -> bool`; `answer.render_marker(text: str, fmt) -> str` (trả `"*D."` hoặc `"D."`).
- Modify `runs.emit`: với segment `kind=="text"`, nếu `is_option_marker(content)` → dùng `answer.render_marker` thay cho `wrap`.

- [ ] **Step 1: Viết test thất bại**

```python
from docx_extract.answer import is_option_marker, render_marker

def test_detect_marker():
    assert is_option_marker("A.")
    assert is_option_marker(" B) ")
    assert not is_option_marker("Chọn D.")
    assert not is_option_marker("Nhóm I.")

def test_marker_plain_when_not_underlined():
    # fmt = (bold, italic, vert, underline)
    assert render_marker("B.", (True, False, None, False)) == "B."

def test_marker_star_when_underlined():
    assert render_marker("D.", (True, False, None, True)) == "*D."
```

- [ ] **Step 2: Chạy — FAIL**

Run: `uv run pytest tests/test_answer.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `answer.py`**

```python
import re

_MARKER = re.compile(r"^\s*([A-D])[.)]\s*$")

def is_option_marker(text: str) -> bool:
    return bool(_MARKER.match(text or ""))

def render_marker(text: str, fmt) -> str:
    underline = fmt[3]
    core = text.strip()
    return ("*" + core) if underline else core
```

- [ ] **Step 4: Nối vào `runs.emit`**

Sửa `emit` trong `runs.py` — thêm import và nhánh option-marker:

```python
from . import answer
...
def emit(segments):
    out = []
    for kind, fmt, content in _coalesce(segments):
        if kind == "raw":
            out.append(content)
        elif content and answer.is_option_marker(content):
            out.append(answer.render_marker(content, fmt))
        else:
            out.append(wrap(content, fmt) if content else "")
    return "".join(out)
```

- [ ] **Step 5: Thêm test tích hợp ở `test_runs.py`**

```python
def test_option_letters_are_stripped_and_correct_starred():
    inner = (_run("A.", b=True) + _run(" nóng chảy.")
             + _run("D.", b=True, u=True) + _run(" ngưng tụ."))
    got = render_paragraph(_p(inner), None)
    assert "A. nóng chảy." in got
    assert "*D. ngưng tụ." in got
    assert "[!b:$A.$]" not in got
```

- [ ] **Step 6: Chạy — PASS**

Run: `uv run pytest tests/test_answer.py tests/test_runs.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: strip option markers + star correct answer via underline"
```

---

## Task 5: `tables.py` — bảng → `[* | *]`

**Files:**
- Create: `src/docx_extract/tables.py`
- Test: `tests/test_tables.py`

**Interfaces:**
- Consumes: `runs.render_paragraph`, `ns`.
- Produces: `render_table(tbl, ctx) -> str` — mỗi `w:tr` một dòng `[* c1 | c2 | c3 *]`; nội dung cell = nối markup các `w:p` trong cell (trim).

- [ ] **Step 1: Viết test thất bại**

```python
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
```

- [ ] **Step 2: Chạy — FAIL**

Run: `uv run pytest tests/test_tables.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `tables.py`**

```python
from . import ns
from .runs import render_paragraph

def _cell_text(tc, ctx):
    parts = [render_paragraph(p, ctx) for p in tc.findall(ns.q("w", "p"))]
    return " ".join(s.strip() for s in parts if s.strip())

def render_table(tbl, ctx) -> str:
    lines = []
    for tr in tbl.findall(ns.q("w", "tr")):
        cells = [_cell_text(tc, ctx) for tc in tr.findall(ns.q("w", "tc"))]
        lines.append("[* " + " | ".join(cells) + " *]")
    return "\n".join(lines)
```

- [ ] **Step 4: Chạy — PASS**

Run: `uv run pytest tests/test_tables.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: table renderer -> [* | *] rows"
```

---

## Task 6: `assemble.py` + `__main__.py` — pipeline + CLI

**Files:**
- Create: `src/docx_extract/assemble.py`, `src/docx_extract/__main__.py`
- Modify: `src/docx_extract/__init__.py` (export `clean_docx`)
- Test: `tests/test_assemble.py`

**Interfaces:**
- Consumes: `loader.load`, `context.Context`, `runs.render_paragraph`, `tables.render_table`, `ns`.
- Produces:
  - `clean_docx(path: str) -> tuple[str, Context]` — markup phẳng (đoạn nối bằng `\n`) + context (chứa `written`, `manifest`, `warnings`).
  - `write_outputs(markup: str, ctx: Context, out_dir: str) -> None` — ghi `markup.txt`, `sidecar/*`, `manifest.json`.
  - CLI: `python -m docx_extract <docx> -o <out_dir>`.

- [ ] **Step 1: Viết test thất bại**

```python
from docx_extract import clean_docx

DOCX = r"C:\Users\admin\Downloads\ĐỀ VẬT LÍ LẦN 3_VER 2 (2).docx"

def test_clean_docx_runs_endtoend():
    markup, ctx = clean_docx(DOCX)
    assert "Câu 1" in markup
    assert "PHẦN I" in markup
    assert "[!m:$mathtype_" in markup       # có placeholder MathType
    assert "[img:$img_" in markup            # có ảnh
    assert ctx.written                        # có asset trích ra
    # không có định dạng rác lọt vào
    assert "w:color" not in markup
```

- [ ] **Step 2: Chạy — FAIL**

Run: `uv run pytest tests/test_assemble.py -v`
Expected: FAIL — `ImportError: cannot import name 'clean_docx'`

- [ ] **Step 3: Implement `assemble.py`**

```python
import json
import os
from . import ns
from .loader import load
from .context import Context
from .runs import render_paragraph
from .tables import render_table


def clean_docx(path: str):
    doc = load(path)
    ctx = Context(rels=doc.rels, assets=doc.assets)
    lines = []
    for child in doc.body:
        if child.tag == ns.q("w", "p"):
            lines.append(render_paragraph(child, ctx))
        elif child.tag == ns.q("w", "tbl"):
            lines.append(render_table(child, ctx))
        # w:sectPr… bỏ qua
    markup = "\n".join(lines)
    return markup, ctx


def write_outputs(markup: str, ctx: Context, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    side = os.path.join(out_dir, "sidecar")
    os.makedirs(side, exist_ok=True)
    with open(os.path.join(out_dir, "markup.txt"), "w", encoding="utf-8") as f:
        f.write(markup)
    for fn, data in ctx.written.items():
        with open(os.path.join(side, fn), "wb") as f:
            f.write(data)
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"assets": ctx.manifest, "warnings": ctx.warnings}, f,
                  ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Implement `__main__.py`**

```python
import argparse
from .assemble import clean_docx, write_outputs

def main():
    ap = argparse.ArgumentParser(prog="docx_extract")
    ap.add_argument("docx")
    ap.add_argument("-o", "--out", default="out")
    args = ap.parse_args()
    markup, ctx = clean_docx(args.docx)
    write_outputs(markup, ctx, args.out)
    print(f"Ghi {args.out}/markup.txt | assets: {len(ctx.written)} | warnings: {len(ctx.warnings)}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Export ở `__init__.py`**

```python
from .assemble import clean_docx, write_outputs

__all__ = ["clean_docx", "write_outputs"]
```

- [ ] **Step 6: Chạy — PASS + thử CLI**

Run: `uv run pytest tests/test_assemble.py -v`
Expected: PASS

Run: `uv run python -m docx_extract "C:/Users/admin/Downloads/ĐỀ VẬT LÍ LẦN 3_VER 2 (2).docx" -o out`
Expected: in ra dòng "Ghi out/markup.txt | assets: N | warnings: M"

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: assemble pipeline + CLI"
```

---

## Task 7: Golden diff — tinh chỉnh cho khớp Azota

**Files:**
- Create: `tests/test_golden.py`
- Modify (khi tinh chỉnh): `runs.TAB_SPACES`, quy tắc đếm trong `context.py`, strip marker trong `answer.py`.

**Mục tiêu:** đo mức khớp với `tests/fixtures/golden_azota.txt` và ghi lại các khác biệt còn lại kèm lý do (nuance đếm 44/60, tab→space, option-marker gộp run…). Đây là task điều tra, không kỳ vọng khớp 100% ngay.

**Interfaces:**
- Consumes: `clean_docx`, golden fixture.

- [ ] **Step 1: Viết test đo khớp theo dòng có nghĩa**

```python
import re
from pathlib import Path
from docx_extract import clean_docx

DOCX = r"C:\Users\admin\Downloads\ĐỀ VẬT LÍ LẦN 3_VER 2 (2).docx"
GOLDEN = Path(__file__).parent / "fixtures" / "golden_azota.txt"

def _norm(s):
    # so khớp bỏ qua khác biệt khoảng trắng
    return [re.sub(r"\s+", " ", ln).strip() for ln in s.splitlines() if ln.strip()]

def test_key_anchors_present_in_order():
    markup, _ = clean_docx(DOCX)
    got = "\n".join(_norm(markup))
    for anchor in ["PHẦN I", "Câu 1", "*D. ngưng tụ", "[!b:$[GT]$]",
                   "PHẦN II", "Nhóm I", "[* 0 | 27 | 0 *]", "PHẦN III"]:
        assert anchor.replace("  ", " ") in got, f"thiếu: {anchor}"

def test_report_line_match_ratio():
    markup, _ = clean_docx(DOCX)
    got = set(_norm(markup))
    gold = _norm(GOLDEN.read_text(encoding="utf-8"))
    matched = sum(1 for ln in gold if ln in got)
    ratio = matched / len(gold)
    print(f"\nGolden line match: {matched}/{len(gold)} = {ratio:.1%}")
    # nuance đã biết (đếm placeholder 44/60, tab) khiến chưa 100%
    assert ratio >= 0.70
```

- [ ] **Step 2: Chạy để lấy tỉ lệ khớp ban đầu**

Run: `uv run pytest tests/test_golden.py -v -s`
Expected: in ra tỉ lệ; `test_key_anchors_present_in_order` PASS. Nếu `ratio` fail ngưỡng, sang Step 3.

- [ ] **Step 3: Tinh chỉnh theo diff (lặp)**

Với mỗi cụm dòng lệch, xác định nguyên nhân và sửa unit tương ứng:
- Khác biệt **khoảng trắng/tab**: chỉnh `runs.TAB_SPACES` (thử `" "` × N cho khớp căn cột Azota).
- **Số placeholder lệch** (44/60/bắt đầu ở 3): kiểm tra object nào Azota bỏ đếm (equation trong header, ảnh lồng trong OLE). Điều chỉnh điều kiện duyệt trong `context.image/ole` hoặc thứ tự duyệt trong `assemble` để tái tạo đúng chuỗi số. Ghi phát hiện vào comment.
- **Option-marker dính run** (letter + text cùng `<w:t>`): mở rộng `answer` để strip marker ở đầu segment, không chỉ segment cô lập.
Sau mỗi lần sửa, chạy lại toàn bộ: `uv run pytest -q`.

- [ ] **Step 4: Ghi báo cáo khác biệt còn lại**

Tạo `docs/superpowers/plans/2026-07-06-golden-diff-report.md` liệt kê: tỉ lệ khớp cuối, các loại khác biệt còn tồn tại, lý do, và hạng mục để lại cho v2.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "test: golden diff vs Azota output + tuning report"
```

---

## Self-Review (đã thực hiện)

**Spec coverage:** loader(§3)→T1; runs whitelist+merge(§4.1)→T2; placeholder+asset+bộ đếm toàn cục(§4.2)→T3; đáp án đa tín hiệu(§4.3)→T4 (v1: underline; fallback bold/màu ghi ở Step 3 T7/để v2); bảng(§4.4)→T5; assemble+manifest+CLI+error handling(§3,§5)→T6; golden(§6)→T7; bố cục(§7)→T0. Ngoài phạm vi(§8) không có task — đúng.

**Placeholder scan:** không có TBD/TODO; mọi step có code hoặc lệnh cụ thể. `TAB_SPACES` là hằng có giá trị mặc định rõ ràng, tinh chỉnh có hướng dẫn ở T7.

**Type consistency:** `Context.omml/ole/image` (T3) khớp lời gọi `ctx.omml/ole/image` trong `runs._render_run/_walk` (T2). `run_format` trả tuple 4 phần tử; `answer.render_marker` đọc `fmt[3]` (underline) — nhất quán. `clean_docx -> (markup, ctx)` khớp test T6/T7 và CLI.

**Lưu ý fallback đáp án:** §4.3 nêu 4 tầng tín hiệu; T4 chỉ implement underline (đủ cho golden file này). Tầng bold/màu/highlight được đưa vào T7-Step3 khi golden lộ nhu cầu, phần suy từ "Chọn X." để lại v2 (§8). Ghi rõ để không coi là thiếu sót.
