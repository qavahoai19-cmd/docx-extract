import re

RE_PART = re.compile(r"^\[!b:\$PHẦN\s+([IVX]+)\.?\s*(.*?)\$\](.*)$")
RE_GROUP = re.compile(r"^\[!b:\$Nhóm\s+([IVX]+)\.?\s*\$\]\s*(.*)$")
RE_QUESTION = re.compile(r"^Câu\s+(\d+)\s*[.:]\s*(.*)$")
RE_OPTION = re.compile(r"(\*?)([A-D])[.)]\s*")
# Dòng phương án LUÔN bắt đầu bằng marker; anchor để prose "Vật A. và B."
# giữa stem không bị nhận nhầm thành dòng option.
RE_OPTION_LINE = re.compile(r"^\s*\*?[A-D][.)]")
RE_TF = re.compile(r"^\[([DS])\]\s*(.*)$")
RE_GT_OPEN = re.compile(r"^(?:\[!b:\$)?\[GT\]")
RE_GT_CLOSE = re.compile(r"^(?:\[!b:\$)?\[/\]")
RE_SHORT = re.compile(r"^Đáp án là \{a\}\s*$")
RE_INSTR = re.compile(r"\[!i:\$(.*?)\$\]")
# Giá trị đáp án ngắn: chỉ bỏ ký tự phương án đầu dòng khi có dấu . hoặc )
# theo sau (vd "A.69,6" -> "69,6"), KHÔNG cắt "D2" thành "2".
RE_SHORT_VAL = re.compile(r"^(?:[A-D][.)])?\s*(.+)$")
# Lớp định dạng nhấn mạnh (đậm/nghiêng) — strip về nội dung trần cho text
# đã bóc cấu trúc. KHÔNG đụng sup/sub (mang nghĩa mũ/chỉ số) hay math token.
RE_EMPH = re.compile(r"\[!(?:b|i|b!i)?:?\$?|\$\]|\[!b:\$|\[!i:\$|\[!b!i:\$")
RE_EMPH_WRAP = re.compile(r"\[!(?:b|i|b!i):\$(.*?)\$\]")

MARK_MCQ = "mcq"
MARK_TF = "true_false"
MARK_SHORT = "short_answer"
MARK_UNKNOWN = "unknown"


def subst_latex(text: str, latex_map: dict) -> str:
    def repl(m):
        oid = m.group(1)
        if oid in latex_map:
            return f"${latex_map[oid]}$"
        return m.group(0)
    return re.sub(r"\[!m:\$(mathml_\d+)\$\]", repl, text)


def _clean_bold(s: str) -> str:
    # Bỏ MỌI lớp nhấn mạnh [!b:$...$]/[!i:$...$]/[!b!i:$...$] (kể cả nằm giữa
    # dòng — partial bold), giữ lại nội dung bên trong. Không đụng sup/sub/math.
    prev = None
    out = s
    while prev != out:
        prev = out
        out = RE_EMPH_WRAP.sub(r"\1", out)
    return out


def _detect_type(lines) -> str:
    has_option = False
    for ln in lines:
        if RE_TF.match(ln):
            return MARK_TF
        if RE_SHORT.match(ln):
            return MARK_SHORT
        if RE_OPTION_LINE.match(ln):
            has_option = True
    # Trắc nghiệm A-D nhận diện bằng sự hiện diện của dòng phương án.
    # Không có tín hiệu nào -> unknown (spec §7), không mặc định mcq.
    return MARK_MCQ if has_option else MARK_UNKNOWN


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
            gt_lines.append(subst_latex(_clean_bold(raw), latex_map))
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
        if RE_OPTION_LINE.match(raw):
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
            gt_lines.append(subst_latex(_clean_bold(raw), latex_map))
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
            gt_lines.append(subst_latex(_clean_bold(raw), latex_map))
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


def _parse_unknown(lines, latex_map):
    body = "\n".join(subst_latex(_clean_bold(l), latex_map)
                     for l in lines if l.strip())
    return [{"kind": "question", "no": None, "stem": body,
             "options": [], "answer": None, "explanation": None,
             "assets": _collect_assets("\n".join(lines))}]


def _scan_answers(part, warnings):
    if part["type"] == MARK_UNKNOWN:
        return
    for node in part["content"]:
        if node["kind"] == "question" and node.get("answer") is None:
            warnings.append(
                f"PHẦN {part['no']} câu {node.get('no')}: không tách được đáp án")
        elif node["kind"] == "group":
            for it in node.get("items", []):
                if it.get("answer") is None:
                    warnings.append(
                        f"PHẦN {part['no']} {node['label']} ý {it.get('key')}: thiếu đáp án")
            for q in node.get("questions", []):
                if q.get("answer") is None:
                    warnings.append(
                        f"PHẦN {part['no']} {node['label']} câu {q.get('no')}: thiếu đáp án")


def build(markup: str, latex_map: dict, warnings: list = None) -> dict:
    if warnings is None:
        warnings = []
    lines = markup.split("\n")
    parts = []
    cur = None
    for raw in lines:
        mp = RE_PART.match(raw)
        if mp:
            title = ("PHẦN " + mp.group(1) + ". " + mp.group(2).strip()).strip()
            instr = ""
            mi = RE_INSTR.search(raw)
            if mi:
                instr = mi.group(1).strip()
            cur = {"no": mp.group(1), "type": None,
                   "title": title.removesuffix("."), "instruction": instr,
                   "content": [], "_lines": []}
            parts.append(cur)
            continue
        if cur is not None:
            cur["_lines"].append(raw)
        # dòng trước Phần đầu tiên: bỏ (front matter đã bị loại ở v1)
    for p in parts:
        p["type"] = _detect_type(p["_lines"])
        if p["type"] == MARK_MCQ:
            p["content"] = _parse_mcq(p["_lines"], latex_map)
        elif p["type"] == MARK_TF:
            p["content"] = _parse_true_false(p["_lines"], latex_map)
        elif p["type"] == MARK_SHORT:
            p["content"] = _parse_short_answer(p["_lines"], latex_map)
        else:  # unknown
            warnings.append(
                f"PHẦN {p['no']}: không nhận diện được loại câu, giữ nội dung thô")
            p["content"] = _parse_unknown(p["_lines"], latex_map)
    for p in parts:
        _scan_answers(p, warnings)
    for p in parts:
        del p["_lines"]  # trường làm việc nội bộ, không xuất ra JSON
    return {"source": None, "parts": parts}
