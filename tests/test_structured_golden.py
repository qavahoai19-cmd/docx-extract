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


def test_omml_substituted_to_latex_no_internal_leak():
    import json
    tree = _tree()
    blob = json.dumps(tree, ensure_ascii=False)
    # mọi OMML (mathml_N) đã thành LaTeX -> không còn token nào
    assert "mathml_" not in blob
    # trường làm việc nội bộ không lọt ra
    assert "_lines" not in tree["parts"][0]
    # MathType giữ nguyên dạng tham chiếu (theo thiết kế)
    assert "mathtype_" in blob
    # Câu 4 explanation chứa LaTeX đã convert
    q4 = [c for c in tree["parts"][0]["content"] if c.get("no") == 4][0]
    assert "$" in q4["explanation"] and "130" in q4["explanation"]
