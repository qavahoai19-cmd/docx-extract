"""Conservative structural checks, not proof of mathematical correctness.

The standalone server copy is generated from this file by build_notebook.py.
"""
import re

VALIDATION_VERSION = "structure-v1"
_TOKENS = re.compile(r"\\[A-Za-z]+|\\[^A-Za-z]|[{}]|[^\\{}]+")


def validation_error(latex):
    if not isinstance(latex, str) or not latex.strip():
        return "empty OCR result"
    text = latex.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            return "unclosed OCR code fence"
        text = "\n".join(lines[1:-1]).strip()
    for opening, closing in ((r"\[", r"\]"), (r"\(", r"\)"), ("$$", "$$"), ("$", "$")):
        if text.startswith(opening):
            if not text.endswith(closing) or len(text) < len(opening) + len(closing):
                return "unclosed math delimiter"
            text = text[len(opening):-len(closing)].strip()
            break
    if not text:
        return "empty OCR formula"
    stack, groups = [], {}
    for match in _TOKENS.finditer(text):
        if match[0] == "{":
            stack.append(match.start())
        elif match[0] == "}":
            if not stack:
                return "unmatched closing brace"
            groups[stack.pop()] = match.start()
    if stack:
        return "unclosed brace"

    def argument(index):
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            return None, index
        if text[index] == "{":
            end = groups[index]
            return text[index + 1:end].strip(), end + 1
        if text[index] in "}^_":
            return None, index
        if text[index] == "\\":
            token = re.match(r"\\(?:[A-Za-z]+|.)", text[index:])
            if token is None:
                return None, index
            return token[0], index + len(token[0])
        return text[index], index + 1

    delimiters = []
    environments = []
    for match in _TOKENS.finditer(text):
        command = match[0]
        if command in {r"\frac", r"\dfrac", r"\tfrac", r"\binom", r"\dbinom", r"\tbinom"}:
            first, end = argument(match.end())
            second, _ = argument(end)
            if not first or not second:
                return "fraction/binomial has an empty or missing argument"
        elif command == r"\sqrt":
            end = match.end()
            while end < len(text) and text[end].isspace():
                end += 1
            if end < len(text) and text[end] == "[":
                close = text.find("]", end + 1)
                if close < 0 or not text[end + 1:close].strip():
                    return "invalid root index"
                end = close + 1
            value, _ = argument(end)
            if not value:
                return "root has an empty or missing argument"
        elif command == r"\left":
            delimiters.append(command)
        elif command == r"\right":
            if not delimiters:
                return "unmatched right delimiter"
            delimiters.pop()
        elif command in {r"\begin", r"\end"}:
            name, _ = argument(match.end())
            if not name:
                return "missing environment name"
            if command == r"\begin":
                environments.append(name)
            elif not environments or environments.pop() != name:
                return "mismatched environment"
    if delimiters or environments:
        return "unclosed delimiter or environment"
    return ""
