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


def test_unknown_part_type_and_warning():
    markup = "\n".join([
        "[!b:$PHẦN IV. Không rõ loại.$]",
        "Chỉ có văn bản, không có phương án, không [S]/[D], không Đáp án.",
    ])
    warns = []
    tree = build(markup, {}, warns)
    p = tree["parts"][0]
    assert p["type"] == "unknown"
    assert p["content"] and p["content"][0]["stem"]
    assert any("không nhận diện" in w for w in warns)


def test_option_regex_not_triggered_by_prose_in_stem():
    markup = "\n".join([
        "[!b:$PHẦN I. Trắc nghiệm.$]",
        "Câu 1: So sánh vật A. và vật B. trong thí nghiệm",
        "*A. đúng.        B. sai.",
    ])
    q = build(markup, {})["parts"][0]["content"][0]
    # dòng prose "Vật A. và vật B." phải nằm trong stem, KHÔNG thành options
    assert "vật B" in q["stem"]
    assert [o["key"] for o in q["options"]] == ["A", "B"]
    assert q["answer"] == "A"


def test_short_val_keeps_letter_prefixed_value():
    markup = "\n".join([
        "[!b:$PHẦN III. Ngắn$].",
        "Câu 1. Ký hiệu hạt.",
        "Đáp án là {a}",
        "D2",
    ])
    q = build(markup, {})["parts"][0]["content"][0]
    assert q["answer"] == "D2"


def test_clean_bold_strips_partial_bold_in_explanation():
    markup = "\n".join([
        "[!b:$PHẦN I. Trắc nghiệm.$]",
        "Câu 1: Hỏi",
        "*A. đúng.    B. sai.",
        "[!b:$[GT]$]",
        "Do khả năng [!b:$đâm xuyên$] của tia X khác nhau.",
        "[!b:$[/]$]",
    ])
    q = build(markup, {})["parts"][0]["content"][0]
    assert "[!b:" not in q["explanation"]
    assert "đâm xuyên" in q["explanation"]


def test_missing_answer_emits_warning():
    markup = "\n".join([
        "[!b:$PHẦN I. Trắc nghiệm.$]",
        "Câu 1: Hỏi",
        "A. một.    B. hai.",   # không có * -> thiếu đáp án
    ])
    warns = []
    build(markup, {}, warns)
    assert any("không tách được đáp án" in w for w in warns)
