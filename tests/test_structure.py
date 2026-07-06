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
