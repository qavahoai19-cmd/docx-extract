"""Read explicit LMS question/answer columns without solving the questions."""
import re

TOKEN = re.compile(r"\[(![a-z!]+|img):\$([\s\S]*?)\$\]")
MARKER = re.compile(r"(^[ \t]*|[ \t\r\n]+|(?<=[.\uFFFC]))(\*?)([A-D])[.)][ \t]*")
_TABLE_PART = re.compile(TOKEN.pattern + r"|\[\*|\*\]| \| ")
_HEADING = re.compile(r"^\s*(Câu|Question)\s*(\d+)\s*[.:]\s*", re.IGNORECASE)
_INLINE_HEADING = re.compile(r"\b(?:Câu|Question)\s*\d+\s*[.:]\s*", re.IGNORECASE)


def logical_rows(markup):
    """Keep a table row together even when its cells contain Word line breaks."""
    pending, first, depth = [], 0, 0
    for row_number, line in enumerate(markup.splitlines(), 1):
        if not pending and not line.lstrip().startswith('[* '):
            yield row_number, line
            continue
        if not pending:
            first = row_number
        pending.append(line)
        for part in _TABLE_PART.finditer(line):
            depth += 1 if part[0] == '[*' else -1 if part[0] == '*]' else 0
        if depth <= 0:
            yield first, '\n'.join(pending)
            pending, depth = [], 0
    if pending:
        yield first, '\n'.join(pending)


def table_cells(content):
    cells, start, depth = [], 0, 0
    for part in _TABLE_PART.finditer(content):
        if part[0] == '[*':
            depth += 1
        elif part[0] == '*]':
            depth -= 1
        elif part[0] == ' | ' and depth == 0:
            cells.append(content[start:part.start()])
            start = part.end()
    cells.append(content[start:])
    return cells


def plain(text):
    return TOKEN.sub(lambda match: "\uFFFC" if match[1] in {"!m", "img"} else match[2], text).strip()


def inline_segments(text):
    segments, position, raw_position = [], 0, 0

    def add(value, kind="text", style=""):
        nonlocal position
        visible = "\uFFFC" if kind == "asset" else value
        segments.append((position, position + len(visible), value, kind, style))
        position += len(visible)

    for token in TOKEN.finditer(text):
        add(text[raw_position:token.start()])
        add(token[0] if token[1] in {"!m", "img"} else token[2],
            "asset" if token[1] in {"!m", "img"} else "text", token[1])
        raw_position = token.end()
    add(text[raw_position:])
    visible = "".join("\uFFFC" if kind == "asset" else value for _, _, value, kind, _ in segments)
    return segments, visible


def slice_markup(segments, start, end):
    parts = []
    for first, last, value, kind, style in segments:
        if last <= start or first >= end:
            continue
        if kind == "asset":
            parts.append(value)
        else:
            selected = value[max(0, start - first):min(len(value), end - first)]
            parts.append(f"[{style}:${selected}$]" if style else selected)
    return "".join(parts).strip()


def question_heading(text):
    segments, visible = inline_segments(text)
    match = _HEADING.match(visible)
    if match is None:
        return None
    return {"label": "Question" if match[1].casefold() == 'question' else "Câu",
            "number": int(match[2]), "stem": slice_markup(segments, match.end(), len(visible))}


def split_question_lines(text):
    segments, visible = inline_segments(text)
    if _HEADING.match(visible) is None:
        return [text]
    headings = list(_INLINE_HEADING.finditer(visible))
    if len(headings) < 2:
        return [text]
    starts, previous = [0], headings[0]
    for heading in headings[1:]:
        previous_options = choices(slice_markup(segments, previous.end(), heading.start()))
        if [option['label'] for option in previous_options] == list('ABCD'):
            starts.append(heading.start())
            previous = heading
    ends = [*starts[1:], len(visible)]
    return [slice_markup(segments, start, end) for start, end in zip(starts, ends)]


def choices(text):
    segments, visible = inline_segments(text)
    matches = list(MARKER.finditer(visible))
    labels = [match[3] for match in matches]
    if not matches or matches[0].start() != 0 or len(set(labels)) != len(labels) or labels != sorted(labels):
        return []

    return [{"label": match[3], "inline_correct": bool(match[2]),
             "content": slice_markup(segments, match.end(), matches[index + 1].start() if index + 1 < len(matches) else len(visible))}
            for index, match in enumerate(matches)]


def standard_questions(markup):
    """Collect explicit answer markers in numbered, non-LMS questions."""
    items, warnings, current = [], [], None

    def finish():
        if current is None:
            return
        labels = [option['label'] for option in current['options']]
        valid = len(labels) == len(set(labels)) and labels == sorted(labels)
        correct = [option['label'] for option in current['options'] if option['inline_correct']]
        current['conflict'] = not valid
        current['correct_answer'] = correct if valid and correct else None
        current['answer_source'] = 'inline_marker' if current['correct_answer'] else None
        current['type'] = ('multiple_choice' if len(correct) > 1 else 'single_choice') if labels else 'unclassified'
        if not valid:
            warnings.append(f"{current['label']} {current['number']}: nhãn phương án trùng hoặc sai thứ tự; cần đối chiếu nguồn.")
        current['stem'] = '\n'.join(current['stem']).strip()
        current['raw_answers'] = '\n'.join(current['raw_answers'])
        items.append(current)

    for row_number, line in logical_rows(markup):
        heading = question_heading(line)
        if heading is not None:
            finish()
            current = {**heading, 'stem': [], 'options': [], 'source_row': row_number,
                       'raw_answers': [], 'raw_answer_key': ''}
            line = heading['stem']
        if current is None or not line.strip():
            continue
        options = choices(line)
        if options:
            current['options'].extend(options)
            current['raw_answers'].append(line)
        elif not current['options']:
            current['stem'].append(line)
    finish()
    return items, warnings


def key_labels(text):
    value = plain(text).upper()
    if re.fullmatch(r"[A-D](?:\s*[,;/]\s*[A-D])*", value):
        return re.findall(r"[A-D]", value)
    match = re.fullmatch(r"([A-D])[.)]\s*.+", value)
    return [match[1]] if match else []


def extract_questions(markup):
    headers, questions, result, warnings = None, [], [], []
    active_group = None
    table_detected = False

    def read_item(stem, answers, key, kind, row_number):
        item = {"stem": stem, "type": kind, "source_row": row_number,
                "raw_answers": answers, "raw_answer_key": key, "options": choices(answers),
                "correct_answer": None, "answer_source": None, "conflict": False}
        if kind in {"short_answer", "drag_drop", "essay"}:
            # LMS short-answer cells use e.g. bold "A. 0,09" as a value wrapper.
            value = key.strip()
            value = TOKEN.sub(lambda match: match[0] if match[1] in {"!m", "img"} else match[2], value)
            if kind == 'short_answer':
                value = re.sub(r"^\s*A[.)]\s*", "", value).strip()
            item["correct_answer"] = value or None
            item["answer_source"] = "answer_key_column" if value else None
            if not value and kind != 'essay':
                warnings.append(f'Hàng {row_number}: nguồn chưa có đáp án cho câu này.')
            return item
        if kind == 'true_false' and not item['options']:
            truth = re.fullmatch(r'(?:[AB][.)]\s*)?(Đúng|Sai|Đ|S)', plain(key), re.IGNORECASE)
            item['truth'] = truth[1].casefold() in {'đúng', 'đ'} if truth else None
            item['correct_answer'] = item['truth']
            item['answer_source'] = 'answer_key_column' if truth else None
            if not truth:
                warnings.append(f'Hàng {row_number}: nguồn chưa có đáp án Đúng/Sai hợp lệ.')
            return item
        inline = [option["label"] for option in item["options"] if option["inline_correct"]]
        explicit = key_labels(key)
        valid = {option["label"] for option in item["options"]}
        if explicit and set(explicit) <= valid:
            item["correct_answer"] = explicit
            item["answer_source"] = "answer_key_column"
            if inline and set(inline) != set(explicit):
                item["conflict"] = True
                warnings.append(f"Hàng {row_number}: cột Đáp án đúng ghi {','.join(explicit)}, dấu * ghi {','.join(inline)}; cần kiểm tra nguồn.")
        elif inline:
            item["correct_answer"] = inline
            item["answer_source"] = "inline_marker"
            if key.strip():
                warnings.append(f"Hàng {row_number}: chưa đối chiếu được cột Đáp án đúng với các phương án.")
        elif key.strip():
            warnings.append(f"Hàng {row_number}: chưa nhận được đáp án đúng từ dữ liệu nguồn.")
        elif kind != 'group':
            warnings.append(f'Hàng {row_number}: nguồn chưa có đáp án cho câu này.')
        if kind == "true_false":
            option = next((option for option in item["options"] if item["correct_answer"] and option["label"] in item["correct_answer"]), None)
            value = plain(option["content"]).casefold() if option else ""
            item["truth"] = True if value in {"đúng", "đ"} else False if value in {"sai", "s"} else None
        if kind in {"single_choice", "multiple_choice"} and [option["label"] for option in item["options"]] != list("ABCD"):
            warnings.append(f"Hàng {row_number}: chưa tách đủ bốn phương án A–D; giữ nội dung gốc để kiểm tra.")
        return item

    def item_lines(item, sublabel=None):
        if sublabel:
            flag = "[Đ] " if item.get("truth") is True else "[S] " if item.get("truth") is False else ""
            output = [f"{flag}{sublabel}) {item['stem']}"]
        else:
            output = [f"Câu {item['number']}: {item['stem']}"]
        if item["type"] == "true_false" and sublabel and item.get("truth") is not None:
            return output
        if item['type'] == 'true_false' and isinstance(item['correct_answer'], bool):
            if item['raw_answers']:
                output.append(item['raw_answers'])
            output.append('Đáp án đúng: ' + ('Đúng' if item['truth'] else 'Sai'))
        elif item["type"] in {"short_answer", "drag_drop", "essay"}:
            if item['raw_answers']:
                output.append(item['raw_answers'])
            if item["correct_answer"]:
                output.append("Đáp án đúng: " + item["correct_answer"])
        elif item["options"] and (item["type"] != "single_choice" or [option["label"] for option in item["options"]] == list("ABCD")):
            correct = item["correct_answer"] or []
            output.extend(f"{'*' if option['label'] in correct else ''}{option['label']}. {option['content']}" for option in item["options"])
        elif item["raw_answers"]:
            output.append(item["raw_answers"])
        return output

    # Keep output positions so unrelated data tables and text are never discarded.
    for row_number, line in logical_rows(markup):
        row = re.fullmatch(r"\[\* ([\s\S]*) \*\]", line)
        if row is None:
            headers, active_group = None, None
            result.extend(split_question_lines(line))
            continue
        cells = table_cells(row[1])
        labels = [re.sub(r'\s+', ' ', plain(cell)).casefold() for cell in cells]
        labels = ['đáp án đúng' if label == 'đáp án' else label for label in labels]
        if "nội dung câu hỏi" in labels and "câu trả lời" in labels:
            headers = labels
            table_detected = True
            active_group = None
            continue
        if headers is None and len(cells) in {4, 5}:
            heading = question_heading(cells[0])
            if heading is not None:
                options = choices('\n'.join([heading['stem'], *cells[1:]]))
                if [option['label'] for option in options] == list('ABCD'):
                    # Practice sheets often put Question N + A in the first
                    # cell and B/C/D in adjacent cells, without LMS headers.
                    result.extend(cells)
                    continue
        if headers is None or len(cells) != len(headers):
            if headers is not None:
                warnings.append(f'Hàng {row_number}: số ô không khớp tiêu đề; giữ nguyên nội dung để kiểm tra.')
            result.append(line)
            continue
        fields = dict(zip(headers, cells))
        stem = fields["nội dung câu hỏi"].strip()
        if not stem:
            result.append(line)
            continue
        stem = re.sub(r"^Câu\s+\d+\s*[:.]\s*", "", stem)
        raw_kind = plain(fields.get("loại câu hỏi", "")).casefold()
        kind = ("group" if "câu hỏi chùm" in raw_kind or raw_kind == 'câu hỏi chính - phụ'
                else "true_false" if raw_kind == "đúng/sai"
                else "short_answer" if raw_kind in {"điền khuyết", "trả lời ngắn"}
                else 'drag_drop' if raw_kind == 'kéo thả' else 'essay' if raw_kind == 'câu tự luận'
                else 'multiple_choice' if raw_kind == 'nhiều lựa chọn' else "single_choice")
        item = read_item(stem, fields["câu trả lời"], fields.get("đáp án đúng", ""), kind, row_number)
        child = plain(fields.get("là câu hỏi con của câu hỏi chùm?", "")).casefold() == "có"
        if child and active_group is not None:
            active_group["items"].append(item)
            continue
        if child:
            warnings.append(f"Hàng {row_number}: câu con chưa có câu dẫn; giữ thành mục riêng.")
        active_group = None
        item["number"] = len(questions) + 1
        questions.append(item)
        result.append(item)
        if kind == "group":
            item["items"] = []
            active_group = item
    lines = []
    for entry in result:
        if isinstance(entry, str):
            lines.append(entry)
            continue
        lines.extend(item_lines(entry))
        for index, child in enumerate(entry.get("items", [])):
            lines.extend(item_lines(child, chr(ord('a') + index)))
        lines.append("")
    rendered = "\n".join(lines)
    if not table_detected:
        questions, ordinary_warnings = standard_questions(rendered)
        warnings.extend(ordinary_warnings)
    return {"markup": rendered, "questions": questions, "warnings": warnings,
            "lms_detected": table_detected}
