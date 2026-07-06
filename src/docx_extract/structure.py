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
