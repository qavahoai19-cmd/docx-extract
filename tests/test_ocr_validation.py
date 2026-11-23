from pathlib import Path
import pytest
from docx_extract.ocr_validation import validation_error


@pytest.mark.parametrize("latex", [
    r"\[\sqrt{2}\frac{x-4}{}\]", r"\frac{}{x}", r"\frac{x}",
    r"\sqrt{}", r"\sqrt[", r"x_{2", r"x}", r"\left(x",
    r"\begin{matrix}x\end{aligned}", r"\[x", r"\[\]",
])
def test_rejects_incomplete_structures(latex):
    assert validation_error(latex)


@pytest.mark.parametrize("latex", [
    r"\[\sqrt{\frac{2}{x-4}}\]", r"\frac12", r"\sqrt x", r"\sqrt[3]{x}",
    r"\vec{B}_C\uparrow\downarrow\vec{B}", r"\left\{x\right.",
    r"\begin{aligned}x&=1\\y&=2\end{aligned}", r"\{x\}",
    "x < 1", "x > 1", r"\frac{\{x\}}{y}",
])
def test_accepts_complete_structures_without_guessing_semantics(latex):
    assert not validation_error(latex)


def test_standalone_server_uses_identical_validator():
    root = Path(__file__).resolve().parents[1]
    assert (root / "colab_ocr_server/ocr_validation.py").read_bytes() == (
        root / "src/docx_extract/ocr_validation.py").read_bytes()
