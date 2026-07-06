# Structured export + LaTeX (v2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm 2 tầng hậu xử lý lên v1: convert OMML→LaTeX và bóc cây cấu trúc Phần→Nhóm→Câu (3 loại câu), xuất `structured.json` — không phá đường phẳng `markup.txt`.

**Architecture:** `mathlatex.py` chuyển từng OMML fragment → LaTeX (đệ quy thuần Python là đường CHÍNH; XSLT là tuỳ chọn nâng cấp ở task riêng). `context.omml()` gọi nó, lưu `ctx.latex[oid]`. `structure.py` là máy trạng thái đọc lại `markup.txt` phẳng (đủ marker xác định) + `latex_map` → cây typed. `assemble` ghi thêm `structured.json`.

**Tech Stack:** Python 3.13, lxml, stdlib (json, re), pytest, uv. Nhánh `feat/docx-clean-module` (tiếp tục trên nhánh v1).

## Global Constraints

- Xây trên v1 hiện có: `loader.py`, `runs.py`, `context.py` (class `Context` dataclass: `rels, assets, counter, written, manifest, warnings`), `answer.py`, `tables.py`, `assemble.py` (`clean_docx(path)->(markup, ctx)`, `write_outputs(markup, ctx, out_dir)`), `ns.py` (`W,M,A,R,V,O,PR` Clark strings + `q(prefix,tag)`). Suite hiện 23/23 xanh — KHÔNG được làm đỏ test cũ.
- MathType OLE (`mathtype_N`) giữ nguyên dạng ảnh — KHÔNG convert LaTeX. Chỉ OMML (`mathml_N`) ra LaTeX.
- Output v2: giữ `markup.txt` y nguyên + thêm `out/structured.json`. LaTeX nằm trong JSON; `markup.txt` KHÔNG đổi.
- Loại câu suy từ marker hiện diện, KHÔNG cứng theo số Phần.
- Không crash giữa file: lỗi cục bộ (OMML không convert được, dòng lạ, đáp án không tách được) → warning + giá trị `null`/giữ placeholder, chạy tiếp.
- Placeholder/token trong markup: `[!m:$mathml_N$]` (OMML), `[!m:$mathtype_N$]` (MathType), `[img:$img_N$]` (ảnh). Marker cấu trúc: `[!b:$PHẦN …$]`, `[!b:$Nhóm …$]`, `^Câu\s+\d+[.:]`, `^\*?[A-D][.)]`, dòng mở đầu `[S]`/`[D]`, `[!b:$[GT]…$]`/`[GT]`, `[!b:$[/]$]`/`[/]`, `Đáp án là {a}`.
- OOXML math namespace: `m` = `ns.M`. Tag toán thường gặp: `m:f` (phân số: `m:num`,`m:den`), `m:sSup` (`m:e`,`m:sup`), `m:sSub` (`m:e`,`m:sub`), `m:sSubSup`, `m:rad` (`m:deg`,`m:e`), `m:nary` (`m:naryPr>m:chr`, `m:sub`,`m:sup`,`m:e`), `m:d` (delimiter: `m:dPr>m:begChr/m:endChr`, các `m:e`), `m:r` (run: `m:t` text), `m:acc` (accent).

---

## File Structure

```
src/docx_extract/
  mathlatex.py     (MỚI) OMML element -> LaTeX (đệ quy). Task 1
  context.py       (SỬA) omml() điền ctx.latex. Task 2
  structure.py     (MỚI) markup phẳng -> cây typed. Tasks 3-6
  assemble.py      (SỬA) ghi structured.json + CLI. Task 7
  xslt/            (MỚI, tuỳ chọn) 2 file .xsl. Task 8
tests/
  test_mathlatex.py test_structure.py (mở rộng dần) test_structured_golden.py
```

---

## Task 1: `mathlatex.py` — OMML → LaTeX (đệ quy thuần Python)

**Files:**
- Create: `src/docx_extract/mathlatex.py`
- Test: `tests/test_mathlatex.py`

**Interfaces:**
- Consumes: `ns` (`ns.q('m', tag)`, `ns.M`).
- Produces: `omml_to_latex(elem) -> str | None` — nhận phần tử `m:oMath`/`m:oMathPara` (hoặc con của nó), trả chuỗi LaTeX; trả `None` nếu gặp lỗi không mong đợi (caller giữ placeholder).

- [ ] **Step 1: Viết test thất bại**

```python
from lxml import etree
from docx_extract.mathlatex import omml_to_latex
from docx_extract import ns

def _omath(inner: str):
    return etree.fromstring(
        f'<m:oMath xmlns:m="{ns.M[1:-1]}">{inner}</m:oMath>')

def _r(t):  # m:r run
    return f'<m:r><m:t>{t}</m:t></m:r>'

def test_plain_run():
    assert omml_to_latex(_omath(_r("x") + _r("+") + _r("1"))) == "x+1"

def test_fraction():
    frac = f'<m:f><m:num>{_r("a")}</m:num><m:den>{_r("b")}</m:den></m:f>'
    assert omml_to_latex(_omath(frac)) == r"\frac{a}{b}"

def test_superscript():
    sup = f'<m:sSup><m:e>{_r("x")}</m:e><m:sup>{_r("2")}</m:sup></m:sSup>'
    assert omml_to_latex(_omath(sup)) == "x^{2}"

def test_subscript():
    sub = f'<m:sSub><m:e>{_r("a")}</m:e><m:sub>{_r("n")}</m:sub></m:sSub>'
    assert omml_to_latex(_omath(sub)) == "a_{n}"

def test_radical_default_sqrt():
    rad = f'<m:rad><m:deg/><m:e>{_r("2")}</m:e></m:rad>'
    assert omml_to_latex(_omath(rad)) == r"\sqrt{2}"

def test_delimiter_parens():
    d = f'<m:d><m:e>{_r("x")}</m:e></m:d>'
    assert omml_to_latex(_omath(d)) == r"\left(x\right)"
```

- [ ] **Step 2: Chạy — FAIL**

Run: `uv run pytest tests/test_mathlatex.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `mathlatex.py`**

```python
from . import ns

def _t(prefix, tag):
    return ns.q(prefix, tag)

def _children_latex(elem) -> str:
    return "".join(_node(c) for c in elem)

def _e_latex(parent, child_tag) -> str:
    """LaTeX của con <m:child_tag> (vd m:num, m:e) — rỗng nếu vắng."""
    child = parent.find(ns.q("m", child_tag))
    return _children_latex(child) if child is not None else ""

def _node(elem) -> str:
    tag = elem.tag
    if tag == _t("m", "r"):
        txt = elem.find(ns.q("m", "t"))
        return (txt.text or "") if txt is not None else ""
    if tag == _t("m", "t"):
        return elem.text or ""
    if tag == _t("m", "f"):
        return r"\frac{" + _e_latex(elem, "num") + "}{" + _e_latex(elem, "den") + "}"
    if tag == _t("m", "sSup"):
        return _e_latex(elem, "e") + "^{" + _e_latex(elem, "sup") + "}"
    if tag == _t("m", "sSub"):
        return _e_latex(elem, "e") + "_{" + _e_latex(elem, "sub") + "}"
    if tag == _t("m", "sSubSup"):
        return (_e_latex(elem, "e") + "_{" + _e_latex(elem, "sub")
                + "}^{" + _e_latex(elem, "sup") + "}")
    if tag == _t("m", "rad"):
        deg = elem.find(ns.q("m", "deg"))
        base = _e_latex(elem, "e")
        deg_txt = _children_latex(deg) if deg is not None else ""
        if deg_txt:
            return r"\sqrt[" + deg_txt + "]{" + base + "}"
        return r"\sqrt{" + base + "}"
    if tag == _t("m", "d"):
        beg, end = "(", ")"
        dpr = elem.find(ns.q("m", "dPr"))
        if dpr is not None:
            b = dpr.find(ns.q("m", "begChr"))
            e = dpr.find(ns.q("m", "endChr"))
            if b is not None:
                beg = b.get(ns.q("m", "val"), "(")
            if e is not None:
                end = e.get(ns.q("m", "val"), ")")
        inner = "".join(_children_latex(c)
                         for c in elem.findall(ns.q("m", "e")))
        return r"\left" + beg + inner + r"\right" + end
    if tag == _t("m", "nary"):
        # tích phân/tổng: ký hiệu ở naryPr>chr (mặc định ∫)
        chr_map = {"∑": r"\sum", "∏": r"\prod", "∫": r"\int"}
        sym = "∫"
        npr = elem.find(ns.q("m", "naryPr"))
        if npr is not None:
            c = npr.find(ns.q("m", "chr"))
            if c is not None:
                sym = c.get(ns.q("m", "val"), sym)
        latex_sym = chr_map.get(sym, sym)
        out = latex_sym
        sub = _e_latex(elem, "sub")
        sup = _e_latex(elem, "sup")
        if sub:
            out += "_{" + sub + "}"
        if sup:
            out += "^{" + sup + "}"
        out += _e_latex(elem, "e")
        return out
    if tag == _t("m", "acc"):
        return r"\hat{" + _e_latex(elem, "e") + "}"
    # bao (oMath, oMathPara, e, num, den...) hoặc tag chưa xử lý -> duyệt con
    return _children_latex(elem)

def omml_to_latex(elem):
    try:
        return _node(elem)
    except Exception:
        return None
```

- [ ] **Step 4: Chạy — PASS**

Run: `uv run pytest tests/test_mathlatex.py -v`
Expected: PASS (6/6)

- [ ] **Step 5: Commit**

```bash
git add src/docx_extract/mathlatex.py tests/test_mathlatex.py
git commit -m "feat: OMML->LaTeX recursive converter"
```
(Kết đuôi message: 2 dòng trailer Co-Authored-By + Claude-Session như các commit trước.)

---

## Task 2: `context.py` — điền `ctx.latex` khi gặp OMML

**Files:**
- Modify: `src/docx_extract/context.py`
- Test: `tests/test_math_assets.py` (thêm test)

**Interfaces:**
- Consumes: `mathlatex.omml_to_latex`.
- Produces: `Context.latex: dict` (mới, `field(default_factory=dict)`) map `oid -> latex_str`; `omml()` điền nó và thêm khoá `latex` vào manifest entry. Chữ ký `omml()` KHÔNG đổi (vẫn trả `"[!m:$mathml_N$]"`).

- [ ] **Step 1: Viết test thất bại (thêm vào `tests/test_math_assets.py`)**

```python
def test_omml_populates_latex_map():
    from docx_extract.context import Context
    from docx_extract import ns
    from lxml import etree
    c = Context(rels={}, assets={})
    frac = (f'<m:oMath xmlns:m="{ns.M[1:-1]}"><m:f>'
            f'<m:num><m:r><m:t>a</m:t></m:r></m:num>'
            f'<m:den><m:r><m:t>b</m:t></m:r></m:den></m:f></m:oMath>')
    m = etree.fromstring(frac)
    assert c.omml(m) == "[!m:$mathml_1$]"
    assert c.latex["mathml_1"] == r"\frac{a}{b}"
    assert c.manifest[-1]["latex"] == r"\frac{a}{b}"
```

- [ ] **Step 2: Chạy — FAIL**

Run: `uv run pytest tests/test_math_assets.py::test_omml_populates_latex_map -v`
Expected: FAIL — `AttributeError: 'Context' object has no attribute 'latex'`

- [ ] **Step 3: Sửa `context.py`**

Thêm import đầu file: `from . import mathlatex`
Thêm field vào dataclass (sau `warnings`):

```python
    latex: dict = field(default_factory=dict)     # oid -> LaTeX (chỉ OMML)
```

Sửa `omml()` thành:

```python
    def omml(self, elem) -> str:
        oid = self._next("mathml")
        frag = etree.tostring(elem, encoding="utf-8")
        self.written[f"{oid}.xml"] = frag
        latex = mathlatex.omml_to_latex(elem)
        if latex is None:
            self.warnings.append(f"{oid}: OMML->LaTeX thất bại, giữ placeholder")
        else:
            self.latex[oid] = latex
        self.manifest.append(
            {"id": oid, "type": "mathml", "source": "inline-omml", "latex": latex})
        return f"[!m:${oid}$]"
```

- [ ] **Step 4: Chạy — PASS + suite cũ xanh**

Run: `uv run pytest tests/test_math_assets.py -v && uv run pytest -q`
Expected: test mới PASS; toàn suite xanh.

- [ ] **Step 5: Commit**

```bash
git add src/docx_extract/context.py tests/test_math_assets.py
git commit -m "feat: populate ctx.latex from OMML during extraction"
```

---

## Task 3: `structure.py` — khung máy trạng thái + tách Phần

**Files:**
- Create: `src/docx_extract/structure.py`
- Test: `tests/test_structure.py`

**Interfaces:**
- Produces:
  - `build(markup: str, latex_map: dict) -> dict` — trả `{"source": None, "parts": [...]}` (source điền ở assemble).
  - `subst_latex(text: str, latex_map: dict) -> str` — thay mọi `[!m:$mathml_N$]` bằng `$<latex>$` nếu có trong map, ngược lại giữ nguyên token.
  - Hằng regex module-level: `RE_PART, RE_GROUP, RE_QUESTION, RE_OPTION, RE_TF, RE_GT_OPEN, RE_GT_CLOSE, RE_SHORT`.

Task này chỉ dựng khung + tách **Phần** (title/instruction/type) và gom dòng thô vào `part["_lines"]`; tách câu/nhóm ở Task 4-6.

- [ ] **Step 1: Viết test thất bại**

```python
from docx_extract.structure import build, subst_latex

def test_subst_latex_replaces_known_token():
    out = subst_latex("x = [!m:$mathml_1$] hết", {"mathml_1": r"\frac{a}{b}"})
    assert out == r"x = $\frac{a}{b}$ hết"

def test_subst_latex_keeps_unknown_token():
    out = subst_latex("[!m:$mathml_9$]", {})
    assert out == "[!m:$mathml_9$]"

def test_build_splits_three_parts_with_types():
    markup = "\n".join([
        "[!b:$PHẦN I. Câu trắc nghiệm nhiều phương án lựa chọn.$] [!i:$Thí sinh trả lời từ câu 1 đến câu 18.$]",
        "Câu 1: Nội dung.",
        "A. x.        *B. y.",
        "[!b:$PHẦN II. Câu trắc nghiệm đúng sai.$]",
        "[!b:$Nhóm I.$] Đề chung.",
        "[S] Ý một.",
        "[!b:$PHẦN III. Thí sinh trả lời từ câu 1 đến câu 6$].",
        "Câu 1. Tính.",
        "Đáp án là {a}",
        "A.69,6",
    ])
    tree = build(markup, {})
    parts = tree["parts"]
    assert [p["no"] for p in parts] == ["I", "II", "III"]
    assert parts[0]["type"] == "mcq"
    assert parts[1]["type"] == "true_false"
    assert parts[2]["type"] == "short_answer"
    assert "Thí sinh trả lời từ câu 1 đến câu 18" in parts[0]["instruction"]
```

- [ ] **Step 2: Chạy — FAIL**

Run: `uv run pytest tests/test_structure.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement khung `structure.py`**

```python
import re

RE_PART = re.compile(r"^\[!b:\$PHẦN\s+([IVX]+)\.?\s*(.*?)\$\](.*)$")
RE_GROUP = re.compile(r"^\[!b:\$Nhóm\s+([IVX]+)\.?\s*\$\]\s*(.*)$")
RE_QUESTION = re.compile(r"^Câu\s+(\d+)\s*[.:]\s*(.*)$")
RE_OPTION = re.compile(r"(\*?)([A-D])[.)]\s*")
RE_TF = re.compile(r"^\[([DS])\]\s*(.*)$")
RE_GT_OPEN = re.compile(r"^(?:\[!b:\$)?\[GT\]")
RE_GT_CLOSE = re.compile(r"^(?:\[!b:\$)?\[/\]")
RE_SHORT = re.compile(r"^Đáp án là \{a\}\s*$")
RE_INSTR = re.compile(r"\[!i:\$(.*?)\$\]")

MARK_MCQ = "mcq"
MARK_TF = "true_false"
MARK_SHORT = "short_answer"


def subst_latex(text: str, latex_map: dict) -> str:
    def repl(m):
        oid = m.group(1)
        if oid in latex_map:
            return f"${latex_map[oid]}$"
        return m.group(0)
    return re.sub(r"\[!m:\$(mathml_\d+)\$\]", repl, text)


def _clean_bold(s: str) -> str:
    # bỏ lớp [!b:$...$] ngoài cùng để lấy text tiêu đề trần
    m = re.match(r"^\[!b:\$(.*)\$\]$", s.strip())
    return m.group(1) if m else s


def _detect_type(lines) -> str:
    for ln in lines:
        if RE_TF.match(ln):
            return MARK_TF
        if RE_SHORT.match(ln):
            return MARK_SHORT
    return MARK_MCQ  # mặc định: trắc nghiệm A-D


def build(markup: str, latex_map: dict) -> dict:
    lines = markup.split("\n")
    parts = []
    cur = None
    for raw in lines:
        mp = RE_PART.match(raw)
        if mp:
            title = "PHẦN " + mp.group(1) + ". " + mp.group(2).strip()
            instr = ""
            mi = RE_INSTR.search(raw)
            if mi:
                instr = mi.group(1).strip()
            cur = {"no": mp.group(1), "type": None,
                   "title": title.strip().rstrip("."), "instruction": instr,
                   "content": [], "_lines": []}
            parts.append(cur)
            continue
        if cur is not None:
            cur["_lines"].append(raw)
        # dòng trước Phần đầu tiên: bỏ (front matter đã bị loại ở v1)
    for p in parts:
        p["type"] = _detect_type(p["_lines"])
    return {"source": None, "parts": parts}
```

- [ ] **Step 4: Chạy — PASS**

Run: `uv run pytest tests/test_structure.py -v`
Expected: PASS (3/3)

- [ ] **Step 5: Commit**

```bash
git add src/docx_extract/structure.py tests/test_structure.py
git commit -m "feat: structure builder skeleton + part splitting + latex subst"
```

---

## Task 4: `structure.py` — bóc câu trắc nghiệm (mcq)

**Files:**
- Modify: `src/docx_extract/structure.py`
- Test: `tests/test_structure.py` (thêm test)

**Interfaces:**
- Produces: hàm nội bộ `_parse_mcq(lines, latex_map) -> list[dict]` trả list node `{"kind":"question","no",int,"stem","options":[{"key","text"}],"answer","explanation","assets"}`; được `build` gọi cho part `type=="mcq"` để điền `content`.
- Consumes: `RE_QUESTION, RE_OPTION, RE_GT_OPEN, RE_GT_CLOSE, subst_latex`, `_collect_assets`.

- [ ] **Step 1: Viết test thất bại**

```python
def test_mcq_question_options_answer_explanation():
    markup = "\n".join([
        "[!b:$PHẦN I. Trắc nghiệm.$]",
        "Câu 1: Nội dung hỏi",
        "A. nóng chảy.        B. bay hơi.        C. ngưng kết.        *D. ngưng tụ.",
        "[!b:$[GT]$]",
        "Giải thích ở đây.",
        "[!b:$Chọn D.$]",
        "[!b:$[/]$]",
        "Câu 2: Câu khác",
        "*A. đúng.    B. sai.",
    ])
    tree = build(markup, {})
    q = tree["parts"][0]["content"]
    assert len(q) == 2
    assert q[0]["no"] == 1
    assert q[0]["stem"] == "Nội dung hỏi"
    assert [o["key"] for o in q[0]["options"]] == ["A", "B", "C", "D"]
    assert q[0]["options"][3]["text"] == "ngưng tụ."
    assert q[0]["answer"] == "D"
    assert "Giải thích" in q[0]["explanation"]
    assert q[1]["answer"] == "A"
```

- [ ] **Step 2: Chạy — FAIL**

Run: `uv run pytest tests/test_structure.py::test_mcq_question_options_answer_explanation -v`
Expected: FAIL (content rỗng — build chưa parse mcq)

- [ ] **Step 3: Thêm parser mcq vào `structure.py`**

Thêm helper + hàm, và gọi trong `build` sau khi set type:

```python
def _collect_assets(text: str) -> list:
    # id ảnh/MathType xuất hiện trong text, giữ thứ tự, không trùng.
    ids = []
    for a, b in re.findall(r"\[!m:\$(mathtype_\d+)\$\]|\[img:\$(img_\d+)\$\]", text):
        oid = a or b
        if oid and oid not in ids:
            ids.append(oid)
    return ids


def _split_options(line: str, latex_map: dict):
    """Một dòng có thể chứa nhiều phương án: tách theo vị trí marker A-D."""
    opts = []
    matches = list(RE_OPTION.finditer(line))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
        text = line[start:end].strip()
        opts.append({"key": m.group(2), "text": subst_latex(text, latex_map),
                     "_star": bool(m.group(1))})
    return opts


def _parse_mcq(lines, latex_map):
    questions = []
    q = None
    in_gt = False
    gt_lines = []

    def flush_gt():
        nonlocal in_gt, gt_lines
        if q is not None and gt_lines:
            q["explanation"] = "\n".join(gt_lines).strip()
        in_gt = False
        gt_lines = []

    for raw in lines:
        if RE_GT_OPEN.match(raw):
            in_gt = True
            continue
        if RE_GT_CLOSE.match(raw):
            flush_gt()
            continue
        if in_gt:
            gt_lines.append(_clean_bold(raw))
            continue
        mq = RE_QUESTION.match(raw)
        if mq:
            flush_gt()
            q = {"kind": "question", "no": int(mq.group(1)),
                 "stem": subst_latex(mq.group(2).strip(), latex_map),
                 "options": [], "answer": None, "explanation": None, "assets": []}
            questions.append(q)
            continue
        if q is None:
            continue
        if RE_OPTION.search(raw):
            for o in _split_options(raw, latex_map):
                if o.pop("_star"):
                    q["answer"] = o["key"]
                q["options"].append(o)
            continue
        # dòng nối tiếp stem (chưa có option)
        if not q["options"]:
            q["stem"] = (q["stem"] + " " + subst_latex(raw.strip(), latex_map)).strip()
    for q in questions:
        text = q["stem"] + " " + " ".join(o["text"] for o in q["options"])
        q["assets"] = _collect_assets(text)
    return questions


# trong build(): sau vòng set type, thêm:
#     for p in parts:
#         if p["type"] == MARK_MCQ:
#             p["content"] = _parse_mcq(p["_lines"], latex_map)
```

Áp dụng đoạn gọi trên vào cuối `build` (thay vòng `for p in parts: p["type"]=...` bằng vòng gộp set-type + dispatch parser). Chưa xử lý `true_false`/`short_answer` (Task 5-6) — để `content` rỗng cho 2 loại đó tạm thời.

- [ ] **Step 4: Chạy — PASS + suite xanh**

Run: `uv run pytest tests/test_structure.py -v && uv run pytest -q`
Expected: test mới + cũ PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docx_extract/structure.py tests/test_structure.py
git commit -m "feat: parse mcq questions (options, answer, explanation)"
```

---

## Task 5: `structure.py` — bóc Đúng/Sai (true_false) theo Nhóm

**Files:**
- Modify: `src/docx_extract/structure.py`
- Test: `tests/test_structure.py` (thêm test)

**Interfaces:**
- Produces: `_parse_true_false(lines, latex_map) -> list[dict]` trả list node `{"kind":"group","label","context","assets","items":[{"key","stem","answer"}],"explanation"}`. Gọi trong `build` cho part `type=="true_false"`.

- [ ] **Step 1: Viết test thất bại**

```python
def test_true_false_group_items():
    markup = "\n".join([
        "[!b:$PHẦN II. Đúng sai.$]",
        "[!b:$Nhóm I.$] Đề chung của nhóm. [img:$img_34$]",
        "[S] Ý a sai.",
        "[S] Ý b sai.",
        "[D] Ý c đúng.",
        "[D] Ý d đúng.",
        "[!b:$[GT]$]",
        "Giải thích nhóm.",
        "[!b:$[/]$]",
    ])
    tree = build(markup, {})
    grp = tree["parts"][0]["content"]
    assert len(grp) == 1
    g = grp[0]
    assert g["kind"] == "group"
    assert g["label"] == "Nhóm I."
    assert "Đề chung" in g["context"]
    assert g["assets"] == ["img_34"]
    assert [it["key"] for it in g["items"]] == ["a", "b", "c", "d"]
    assert [it["answer"] for it in g["items"]] == ["S", "S", "D", "D"]
    assert "Giải thích nhóm" in g["explanation"]
```

- [ ] **Step 2: Chạy — FAIL**

Run: `uv run pytest tests/test_structure.py::test_true_false_group_items -v`
Expected: FAIL (content rỗng)

- [ ] **Step 3: Thêm parser true_false**

```python
def _parse_true_false(lines, latex_map):
    groups = []
    g = None
    in_gt = False
    gt_lines = []
    key_iter = "abcd"

    def flush_gt():
        nonlocal in_gt, gt_lines
        if g is not None and gt_lines:
            g["explanation"] = "\n".join(gt_lines).strip()
        in_gt = False
        gt_lines = []

    for raw in lines:
        mg = RE_GROUP.match(raw)
        if mg:
            flush_gt()
            g = {"kind": "group", "label": "Nhóm " + mg.group(1) + ".",
                 "context": subst_latex(mg.group(2).strip(), latex_map),
                 "assets": [], "items": [], "explanation": None}
            groups.append(g)
            continue
        if g is None:
            continue
        if RE_GT_OPEN.match(raw):
            in_gt = True
            continue
        if RE_GT_CLOSE.match(raw):
            flush_gt()
            continue
        if in_gt:
            gt_lines.append(_clean_bold(raw))
            continue
        mt = RE_TF.match(raw)
        if mt:
            key = key_iter[len(g["items"])] if len(g["items"]) < 4 else "?"
            g["items"].append({"key": key, "answer": mt.group(1),
                               "stem": subst_latex(mt.group(2).strip(), latex_map)})
            continue
        # dòng nối tiếp context (trước item đầu tiên)
        if not g["items"]:
            g["context"] = (g["context"] + " " + subst_latex(raw.strip(), latex_map)).strip()
    for g in groups:
        g["assets"] = _collect_assets(g["context"])
    return groups


# trong build dispatch: elif p["type"] == MARK_TF: p["content"] = _parse_true_false(...)
```

- [ ] **Step 4: Chạy — PASS + suite xanh**

Run: `uv run pytest tests/test_structure.py -v && uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docx_extract/structure.py tests/test_structure.py
git commit -m "feat: parse true_false groups (context, items, group explanation)"
```

---

## Task 6: `structure.py` — bóc trả lời ngắn (short_answer, có nhóm trộn)

**Files:**
- Modify: `src/docx_extract/structure.py`
- Test: `tests/test_structure.py` (thêm test)

**Interfaces:**
- Produces: `_parse_short_answer(lines, latex_map) -> list[dict]` trả list trộn `{"kind":"question","no","stem","answer","explanation","assets"}` và `{"kind":"group","label","context","assets","questions":[...],"explanation"}`, đúng thứ tự tài liệu. Gọi trong `build` cho part `type=="short_answer"`.

- [ ] **Step 1: Viết test thất bại**

```python
def test_short_answer_standalone_and_group():
    markup = "\n".join([
        "[!b:$PHẦN III. Trả lời ngắn$].",
        "Câu 1. Tính độ tăng nhiệt độ.",
        "Đáp án là {a}",
        "A.69,6",
        "[!b:$Nhóm II.$] Bối cảnh máy đo huyết áp. [img:$img_82$]",
        "Câu 2. Số phân tử khí.",
        "Đáp án là {a}",
        "A.3,1",
        "Câu 3. Thể tích túi khí.",
        "Đáp án là {a}",
        "A.70",
        "[!b:$[GT]$]",
        "Giải chung câu 2,3.",
        "[!b:$[/]$]",
    ])
    tree = build(markup, {})
    content = tree["parts"][0]["content"]
    assert content[0]["kind"] == "question"
    assert content[0]["no"] == 1
    assert content[0]["answer"] == "69,6"
    assert content[1]["kind"] == "group"
    assert content[1]["label"] == "Nhóm II."
    assert content[1]["assets"] == ["img_82"]
    assert [q["no"] for q in content[1]["questions"]] == [2, 3]
    assert content[1]["questions"][0]["answer"] == "3,1"
    assert "Giải chung" in content[1]["explanation"]
```

- [ ] **Step 2: Chạy — FAIL**

Run: `uv run pytest tests/test_structure.py::test_short_answer_standalone_and_group -v`
Expected: FAIL

- [ ] **Step 3: Thêm parser short_answer**

```python
RE_SHORT_VAL = re.compile(r"^[A-D]?\.?\s*(.+)$")

def _new_short_q(no, stem, latex_map):
    return {"kind": "question", "no": no,
            "stem": subst_latex(stem, latex_map),
            "answer": None, "explanation": None, "assets": []}

def _parse_short_answer(lines, latex_map):
    content = []
    cur_q = None
    cur_group = None
    in_gt = False
    gt_lines = []
    expect_val = False  # dòng trước là "Đáp án là {a}"

    def target_list():
        return cur_group["questions"] if cur_group is not None else content

    def flush_gt():
        nonlocal in_gt, gt_lines
        if gt_lines:
            holder = cur_group if cur_group is not None else cur_q
            if holder is not None:
                holder["explanation"] = "\n".join(gt_lines).strip()
        in_gt = False
        gt_lines = []

    for raw in lines:
        mg = RE_GROUP.match(raw)
        if mg:
            flush_gt()
            cur_q = None
            cur_group = {"kind": "group", "label": "Nhóm " + mg.group(1) + ".",
                         "context": subst_latex(mg.group(2).strip(), latex_map),
                         "assets": [], "questions": [], "explanation": None}
            content.append(cur_group)
            continue
        if RE_GT_OPEN.match(raw):
            in_gt = True
            continue
        if RE_GT_CLOSE.match(raw):
            flush_gt()
            continue
        if in_gt:
            gt_lines.append(_clean_bold(raw))
            continue
        mq = RE_QUESTION.match(raw)
        if mq:
            cur_q = _new_short_q(int(mq.group(1)), mq.group(2).strip(), latex_map)
            target_list().append(cur_q)
            expect_val = False
            continue
        if RE_SHORT.match(raw):
            expect_val = True
            continue
        if expect_val and cur_q is not None:
            mv = RE_SHORT_VAL.match(raw.strip())
            if mv:
                cur_q["answer"] = mv.group(1).strip()
            expect_val = False
            continue
        # nối tiếp stem của câu hiện tại (hoặc context nhóm nếu chưa có câu)
        if cur_q is not None:
            cur_q["stem"] = (cur_q["stem"] + " " + subst_latex(raw.strip(), latex_map)).strip()
        elif cur_group is not None:
            cur_group["context"] = (cur_group["context"] + " " + subst_latex(raw.strip(), latex_map)).strip()
    for node in content:
        if node["kind"] == "group":
            node["assets"] = _collect_assets(node["context"])
        else:
            node["assets"] = _collect_assets(node["stem"])
    return content

# build dispatch: elif p["type"] == MARK_SHORT: p["content"] = _parse_short_answer(...)
```

- [ ] **Step 4: Chạy — PASS + suite xanh**

Run: `uv run pytest tests/test_structure.py -v && uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docx_extract/structure.py tests/test_structure.py
git commit -m "feat: parse short_answer (standalone + Nhóm groups)"
```

---

## Task 7: `assemble.py` — ghi `structured.json` + CLI + golden

**Files:**
- Modify: `src/docx_extract/assemble.py`
- Test: `tests/test_structured_golden.py` (mới), `tests/test_assemble.py` (thêm)

**Interfaces:**
- Consumes: `structure.build`.
- Produces: `write_outputs` ghi thêm `out/structured.json` (`{"source": <basename>, "parts": [...]}`, `ensure_ascii=False, indent=2`). `clean_docx` KHÔNG đổi chữ ký.

- [ ] **Step 1: Viết test golden thất bại (`tests/test_structured_golden.py`)**

```python
from pathlib import Path
from docx_extract.assemble import clean_docx
from docx_extract import structure

DOCX = Path(__file__).parent / "fixtures" / "sample.docx"

def _tree():
    markup, ctx = clean_docx(str(DOCX))
    return structure.build(markup, ctx.latex)

def test_three_parts_with_types():
    parts = _tree()["parts"]
    assert [p["no"] for p in parts] == ["I", "II", "III"]
    assert parts[0]["type"] == "mcq"
    assert parts[1]["type"] == "true_false"
    assert parts[2]["type"] == "short_answer"

def test_part1_has_18_mcq_and_q1_answer_D():
    p1 = _tree()["parts"][0]
    qs = [c for c in p1["content"] if c["kind"] == "question"]
    assert len(qs) == 18
    assert qs[0]["no"] == 1
    assert qs[0]["answer"] == "D"
    assert len(qs[0]["options"]) == 4

def test_part2_four_groups_each_four_items():
    p2 = _tree()["parts"][1]
    groups = [c for c in p2["content"] if c["kind"] == "group"]
    assert len(groups) == 4
    for g in groups:
        assert len(g["items"]) == 4
    # Nhóm I: [S][S][D][D]
    assert [it["answer"] for it in groups[0]["items"]] == ["S", "S", "D", "D"]

def test_part3_six_questions_incl_group():
    p3 = _tree()["parts"][2]
    q_nos = []
    for c in p3["content"]:
        if c["kind"] == "question":
            q_nos.append(c["no"])
        else:
            q_nos.extend(q["no"] for q in c["questions"])
    assert sorted(q_nos) == [1, 2, 3, 4, 5, 6]
```

- [ ] **Step 2: Chạy — FAIL**

Run: `uv run pytest tests/test_structured_golden.py -v`
Expected: FAIL (assertion sai vì số liệu chưa khớp — dùng để tinh chỉnh regex).

- [ ] **Step 3: Nối `structure` vào `assemble` + tinh chỉnh cho khớp golden**

Sửa `write_outputs` trong `assemble.py`:

```python
import json, os
from . import structure

def write_outputs(markup, ctx, out_dir, source_name="sample.docx"):
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
    tree = structure.build(markup, ctx.latex)
    tree["source"] = source_name
    with open(os.path.join(out_dir, "structured.json"), "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False, indent=2)
```

Cập nhật `__main__.py` truyền `source_name=os.path.basename(args.docx)` vào `write_outputs`.

Chạy `test_structured_golden.py`; với mỗi assertion đỏ, xem tại `structure.py`/regex chỗ nào lệch với markup thật (vd `RE_QUESTION` gặp `Câu N` in đậm/không, dòng option xuống dòng giữa chừng, `Nhóm` có số La Mã kèm `.`). Tinh chỉnh regex/parser tới khi 4 test golden xanh. Sau mỗi sửa chạy `uv run pytest -q` để không làm đỏ test cũ. Nếu một loại (vd Phần III item lồng) không đạt đủ 6 câu, log rõ khác biệt còn lại trong report cuối.

- [ ] **Step 4: Chạy — PASS toàn bộ**

Run: `uv run pytest -q`
Expected: toàn suite xanh (bao gồm 4 golden structured).

- [ ] **Step 5: Chạy CLI thật + kiểm mắt**

Run: `uv run python -m docx_extract "tests/fixtures/sample.docx" -o out`
Expected: `out/structured.json` tồn tại; mở xem `parts[0].content[0]` có stem/options/answer=D/explanation; công thức trong stem hiện `$...$` LaTeX cho OMML.

- [ ] **Step 6: Commit**

```bash
git add src/docx_extract/assemble.py src/docx_extract/__main__.py tests/test_structured_golden.py tests/test_assemble.py
git commit -m "feat: emit structured.json + golden structure tests"
```

---

## Task 8 (tuỳ chọn nâng cấp): XSLT OMML→LaTeX thay converter đệ quy

**Chỉ làm nếu** converter đệ quy Task 1 phủ không đủ công thức thật (kiểm bằng số warning `OMML->LaTeX thất bại` khi chạy CLI, hoặc LaTeX sai rõ ở kiểm mắt Task 7 Step 5).

**Files:**
- Create: `src/docx_extract/xslt/omml2mml.xsl`, `src/docx_extract/xslt/mml2tex.xsl` (bản mã nguồn mở — omml→mathml open + `mml2tex` giấy phép MIT)
- Modify: `src/docx_extract/mathlatex.py`
- Test: `tests/test_mathlatex.py`

**Interfaces:**
- `omml_to_latex` giữ nguyên chữ ký; ưu tiên XSLT, fallback về converter đệ quy khi XSLT lỗi hoặc file .xsl vắng.

- [ ] **Step 1: Thêm file .xsl (mã nguồn mở) vào `src/docx_extract/xslt/`, đăng ký vào package data trong `pyproject.toml`**

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/docx_extract"]
[tool.hatch.build]
include = ["src/docx_extract/xslt/*.xsl"]
```

- [ ] **Step 2: Viết test dùng XSLT**

```python
def test_xslt_fraction_matches_or_falls_back():
    from lxml import etree
    from docx_extract import ns
    from docx_extract.mathlatex import omml_to_latex
    frac = (f'<m:oMath xmlns:m="{ns.M[1:-1]}"><m:f>'
            f'<m:num><m:r><m:t>a</m:t></m:r></m:num>'
            f'<m:den><m:r><m:t>b</m:t></m:r></m:den></m:f></m:oMath>')
    out = omml_to_latex(etree.fromstring(frac))
    assert out is not None and "a" in out and "b" in out and "frac" in out
```

- [ ] **Step 3: Sửa `mathlatex.py` — thử XSLT trước, fallback đệ quy**

```python
import importlib.resources as res
from lxml import etree
from . import ns

_XSLT = None
def _load_xslt():
    global _XSLT
    if _XSLT is not None:
        return _XSLT
    try:
        base = res.files("docx_extract").joinpath("xslt")
        mml = etree.XSLT(etree.parse(str(base.joinpath("omml2mml.xsl"))))
        tex = etree.XSLT(etree.parse(str(base.joinpath("mml2tex.xsl"))))
        _XSLT = (mml, tex)
    except Exception:
        _XSLT = (None, None)
    return _XSLT

def _via_xslt(elem):
    mml, tex = _load_xslt()
    if mml is None:
        return None
    try:
        return str(tex(mml(elem))).strip()
    except Exception:
        return None

# omml_to_latex: thử _via_xslt trước, nếu None dùng _node đệ quy như Task 1
def omml_to_latex(elem):
    out = _via_xslt(elem)
    if out:
        return out
    try:
        return _node(elem)
    except Exception:
        return None
```

- [ ] **Step 4: Chạy — PASS + suite xanh**

Run: `uv run pytest tests/test_mathlatex.py -v && uv run pytest -q`

- [ ] **Step 5: Commit**

```bash
git add src/docx_extract/xslt src/docx_extract/mathlatex.py tests/test_mathlatex.py pyproject.toml
git commit -m "feat: XSLT OMML->LaTeX with recursive fallback"
```

---

## Self-Review (đã thực hiện)

**Spec coverage:** OMML→LaTeX đệ quy(§1.2, §9)→T1; ctx.latex + manifest latex(§3)→T2; khung + tách Phần + subst_latex(§5,§6)→T3; mcq(§6)→T4; true_false + group context(§6)→T5; short_answer trộn nhóm(§6)→T6; structured.json + CLI + golden(§2,§4,§8)→T7; XSLT fallback(§9 rủi ro 1)→T8 (tuỳ chọn). Xử lý lỗi(§7): answer=null+warning ở T4/T6, dòng lạ nối node mở ở T4/T5/T6, thiếu latex giữ token ở T3 subst, OMML lỗi giữ placeholder ở T2. Ngoài phạm vi(§10) không có task — đúng.

**Placeholder scan:** không TBD/TODO; mọi step code có code cụ thể; T7 Step 3 là task tinh chỉnh golden (có tiêu chí + lệnh rõ), không phải placeholder.

**Type consistency:** `omml_to_latex(elem)->str|None` (T1) khớp lời gọi ở T2 và T8. `Context.latex` dict (T2) khớp `structure.build(markup, ctx.latex)` (T3, T7). `build(markup, latex_map)->{"source","parts"}` nhất quán T3→T7. Node shape `{"kind":"question"|"group",...}` nhất quán T4/T5/T6 và test golden T7. `subst_latex`, `_collect_assets`, `_clean_bold`, các `RE_*` định nghĩa ở T3, dùng lại T4-T6 — khớp.

**Lưu ý DRY:** `_parse_mcq/_parse_true_false/_parse_short_answer` chia sẻ mẫu xử lý `[GT]` (in_gt/gt_lines/flush_gt). Chấp nhận lặp có kiểm soát ở v2 để mỗi parser đọc độc lập; nếu T7 thấy trùng lặp gây lỗi đồng bộ, gom `_GTScanner` helper là cải thiện hợp lệ (ghi chú cho reviewer, không bắt buộc).
