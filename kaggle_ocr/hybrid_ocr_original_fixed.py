"""Bản chạy thẳng dựa trên code Pandoc + DeepSeek-OCR người dùng gửi.

Không dùng UI cũ, không clone repository, không tự cài LibreOffice.
Model/cấu hình suy luận giữ theo code gốc. Hậu xử lý không viết lại công thức.
"""
from __future__ import annotations

import argparse
import base64
from collections import deque
from copy import deepcopy
from datetime import datetime
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
from urllib.parse import unquote, urlsplit
from uuid import uuid4
import xml.etree.ElementTree as ET
import zipfile


# Chỉ sửa đường dẫn này nếu dùng file đề khác.
INPUT_DOCX = ""  # Chọn DOCX bằng bộ chọn đề hoặc truyền --input; không mặc định đề Toán.
RUN_ROOT = "/kaggle/working/hybrid_original_fixed"
OCR_DIAGRAMS = False       # Giống luồng gốc: giữ hình sơ đồ, không OCR mặc định.
OCR_SMALL_IMAGES = True    # Không bỏ công thức chỉ vì một cạnh nhỏ hơn 80 px.
MODEL_NAME = "deepseek-ai/DeepSeek-OCR"
MAX_NEW_TOKENS = 1000
HEARTBEAT_SECONDS = 5.0

# Cài riêng cho tiến trình con; tuyệt đối không pip install torch/torchvision.
REQUIREMENTS = [
    "transformers==4.46.3", "tokenizers==0.20.3", "huggingface-hub==0.36.2",
    "Pillow>=10.1,<13", "numpy>=1.26,<3", "pymupdf>=1.24,<2",
    "einops>=0.8", "addict>=2.4", "easydict>=1.13", "accelerate>=0.26,<2",
    "safetensors>=0.4.3", "filelock>=3.16", "packaging>=23",
    "pyyaml>=6", "regex>=2024", "requests>=2.32,<3", "tqdm>=4.66",
    "fsspec>=2023.5", "typing-extensions>=4.9", "hf-xet>=1.1.3,<2",
    "psutil>=5.9", "urllib3>=1.26,<3", "certifi>=2024",
    "charset-normalizer>=3,<4", "idna>=3,<4", "pypandoc-binary>=1.14,<2",
]
IMAGE_RE = re.compile(r'!\[[^\]\n]*\]\((<[^>]+>|[^)\n]+)\)(\{[^}]*\})?')
GARBAGE_PATTERNS = [r'"[Ll]ine":\s*[\[{]', r'Image ID:\s*[A-Z0-9]+',
                    r'"line_type"', r'"line_endpoint"']


def validate_docx(value):
    if value is None or not str(value).strip():
        raise ValueError("Điền đường dẫn đầy đủ vào INPUT_DOCX ở đầu cell.")
    source = Path(value).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".docx":
        raise ValueError("Không phải file DOCX: " + str(source))
    try:
        with zipfile.ZipFile(source) as archive:
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(archive.namelist()):
                raise ValueError("File không có cấu trúc Word DOCX hợp lệ.")
    except zipfile.BadZipFile as error:
        raise ValueError("DOCX bị hỏng hoặc không phải ZIP Word.") from error
    return source


def stream_command(command, *, log, env=None, cwd=None, step="Tiến trình", run_started=None):
    """In log trực tiếp và báo PID khi tiến trình chưa có log mới."""
    print("\n>>> " + step, flush=True)
    log.write("\n>>> " + step + "\n")
    log.flush()
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", bufsize=1,
                               env=env, cwd=cwd, **kwargs)
    pending, tail = queue.Queue(), deque(maxlen=45)
    started = last_output = last_tick = time.monotonic()
    total_started = time.perf_counter() if run_started is None else run_started
    def read_output():
        try:
            for line in process.stdout:
                pending.put(("line", line))
        except Exception as error:
            pending.put(("error", error))
        finally:
            pending.put(("end", None))
    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        while True:
            try:
                kind, value = pending.get(timeout=min(0.5, HEARTBEAT_SECONDS))
            except queue.Empty:
                kind, value = "wait", None
            if kind == "end":
                break
            if kind == "error":
                raise value
            if kind == "line":
                last_output = time.monotonic()
                tail.append(value)
                log.write(value)
                log.flush()
                print(value, end="", flush=True)
            now = time.monotonic()
            if now - last_tick >= HEARTBEAT_SECONDS and process.poll() is None:
                message = (f"[ĐANG CHẠY] {step} · PID {process.pid} · {now-started:.0f}s"
                           f" · tổng đã chạy {time.perf_counter()-total_started:.1f}s"
                           f" · chưa có log mới {now-last_output:.0f}s (không phải % hoàn thành)")
                print(message, flush=True)
                log.write(message + "\n")
                log.flush()
                last_tick = now
        code = process.wait()
    except BaseException:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    finally:
        reader.join(timeout=1)
        process.stdout.close()
    if code:
        raise RuntimeError(f"{step} lỗi, mã {code}.\n" + "".join(tail)[-10000:])


def child_environment(dependencies):
    return dict(os.environ, PYTHONPATH=str(dependencies), PYTHONUNBUFFERED="1", PYTHONUTF8="1",
                TOKENIZERS_PARALLELISM="false", PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")


def ensure_dependencies(root, log):
    key = hashlib.sha256(json.dumps([list(sys.version_info[:2]), REQUIREMENTS]).encode()).hexdigest()[:12]
    parent = Path(root) / "dependencies"
    target = parent / key
    # Chỉ tái sử dụng THƯ VIỆN đã cài, không nhập code/UI/pipeline cũ.
    for candidate in (target, Path("/kaggle/working/hybrid_ocr_clean/dependencies") / key):
        try:
            if json.loads((candidate / "ready.json").read_text(encoding="utf-8"))["requirements"] == REQUIREMENTS:
                print("Dùng lại thư viện OCR riêng:", candidate, flush=True)
                return candidate
        except (OSError, ValueError, KeyError, TypeError):
            pass
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=key + "-", dir=parent))
    stream_command([sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(stage),
                    "--progress-bar", "off", "--disable-pip-version-check", "--no-warn-conflicts",
                    "--no-warn-script-location", *REQUIREMENTS], log=log, step="Cài thư viện riêng lần đầu")
    check = '''
import importlib.metadata as md
import torch, torchvision, transformers, tokenizers, PIL, numpy, pypandoc
from transformers import AutoModel, AutoTokenizer, StoppingCriteria, StoppingCriteriaList
from packaging.requirements import Requirement
assert transformers.__version__ == "4.46.3"
assert tokenizers.__version__ == "0.20.3"
for package in ("transformers", "tokenizers", "huggingface-hub", "accelerate", "requests", "Pillow", "pypandoc_binary"):
    for raw in md.requires(package) or []:
        requirement = Requirement(raw)
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        if requirement.specifier and md.version(requirement.name) not in requirement.specifier:
            raise RuntimeError(package + ": " + raw)
print("Dependency check OK | torch=" + torch.__version__ + " | transformers=" + transformers.__version__)
'''
    stream_command([sys.executable, "-c", check], log=log, env=child_environment(stage), step="Kiểm tra thư viện")
    (stage / "ready.json").write_text(json.dumps({"requirements": REQUIREMENTS}), encoding="utf-8")
    if not target.exists():
        stage.rename(target)
        return target
    return stage


def image_path(ref, work_dir):
    value = unquote(ref.strip().strip("<>").replace(r"\ ", " "))
    if urlsplit(value).scheme and not re.match(r"^[A-Za-z]:[/\\]", value):
        return None
    path = Path(value)
    resolved = (path if path.is_absolute() else Path(work_dir) / path).resolve()
    return resolved if resolved.is_relative_to(Path(work_dir).resolve()) else None


def load_rgb(path):
    from PIL import Image
    with Image.open(path) as source:
        rgba = source.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, "white")
        canvas.alpha_composite(rgba)
        return canvas.convert("RGB")


def is_coordinate_plot(image):
    """Nhận diện bảo thủ: lưới xám đều + một/vài trục đậm bên trong hình.

    Không coi mọi bảng có đường kẻ là đồ thị. Đây vẫn là heuristic; không phải
    mô hình hiểu/giải đồ thị và không loại được mọi dạng hình tọa độ.
    """
    import numpy as np
    from PIL import Image
    if min(image.size) < 70 or not 0.45 <= image.width / image.height <= 2.5:
        return False
    if max(image.size) > 1000:
        scale = 1000 / max(image.size)
        image = image.resize(tuple(max(1, round(value * scale)) for value in image.size), Image.Resampling.LANCZOS)
    array = np.asarray(image.convert("L"))
    def centres(mask, axis):
        indices = np.flatnonzero(mask.mean(axis=axis) > 0.6)
        if not len(indices):
            return []
        groups = np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
        return [float(group.mean()) for group in groups]
    def regular(points):
        if len(points) < 5:
            return False
        gaps = np.diff(points)
        spacing = float(np.median(gaps))
        return spacing >= 5 and float(((gaps > spacing * 0.7) & (gaps < spacing * 1.3)).mean()) >= 0.75
    light_rows, light_cols = centres(array < 240, 1), centres(array < 240, 0)
    dark_rows, dark_cols = centres(array < 180, 1), centres(array < 180, 0)
    height, width = array.shape
    return (regular(light_rows) and regular(light_cols)
            and 1 <= len(dark_rows) <= 3 and 1 <= len(dark_cols) <= 3
            and len(light_rows) >= len(dark_rows) + 3 and len(light_cols) >= len(dark_cols) + 3
            and any(0.1 * height < point < 0.9 * height for point in dark_rows)
            and any(0.1 * width < point < 0.9 * width for point in dark_cols))


def analyze_image_for_ocr(image):
    """Heuristic gốc, thêm trường hợp lưới tọa độ bị nhận nhầm là mixed."""
    import numpy as np
    if is_coordinate_plot(image):
        return "coordinate_plot"
    colors = image.resize((64, 64)).getcolors(64 * 64)
    if (len(colors) if colors else 9999) > 400:
        return "diagram"
    array = np.asarray(image.convert("L"), dtype=np.float32)
    height, width = array.shape
    if min(height, width) < 2:
        return "mixed"
    dark_ratio = (array < 128).mean()
    edge_density = (np.abs(np.diff(array, axis=0)) > 30).mean() + (np.abs(np.diff(array, axis=1)) > 30).mean()
    bh, bw = max(1, height // 8), max(1, width // 8)
    variances = [array[i:i+bh, j:j+bw].std() for i in range(0, height-bh, bh) for j in range(0, width-bw, bw)]
    spread = np.std(variances) if variances else 0
    is_text = 0.03 < dark_ratio < 0.6 and edge_density > 0.08
    if dark_ratio < 0.15 and edge_density < 0.12 and spread > 20 and not is_text:
        return "diagram"
    return "text" if is_text else "mixed"


def preprocess_for_ocr(image, destination):
    """Crop/mốc 1200 px như gốc; không ép mọi ảnh lên 384 px."""
    import numpy as np
    from PIL import Image, ImageOps
    width, height = image.size
    mask = np.asarray(image.convert("L")) < 240
    rows, cols = np.where(mask.any(axis=1))[0], np.where(mask.any(axis=0))[0]
    if len(rows) and len(cols):
        box = (max(0, int(cols[0])-8), max(0, int(rows[0])-8),
               min(width, int(cols[-1])+9), min(height, int(rows[-1])+9))
        if (box[2]-box[0]) * (box[3]-box[1]) < width * height * 0.85:
            image = image.crop(box)
    if max(image.size) > 1200:
        scale = 1200 / max(image.size)
        image = image.resize(tuple(max(1, round(size*scale)) for size in image.size), Image.Resampling.LANCZOS)
    if np.asarray(image.convert("L")).std() < 40:
        image = ImageOps.autocontrast(image, cutoff=2)
    image.save(destination, format="PNG", optimize=False)
    return image.size


def plan_images(markdown, work_dir, *, ocr_diagrams=False, ocr_small_images=True):
    records, by_ref, seen = [], {}, {}
    prepared = Path(work_dir) / "preprocessed"
    prepared.mkdir(exist_ok=True)
    for match in IMAGE_RE.finditer(markdown):
        ref = match[1]
        if ref in by_ref:
            continue
        record = dict(ref=ref, status="pending", ocr_text="", raw_ocr="", attempts=[])
        records.append(record)
        by_ref[ref] = record
        path = image_path(ref, work_dir)
        if path is None or not path.is_file():
            record.update(status="missing", error="Không tìm được ảnh Pandoc tham chiếu.")
            continue
        try:
            image = load_rgb(path)
        except Exception as error:
            record.update(status="unsupported", error=str(error))
            continue
        record["source_size"] = list(image.size)
        key = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
        record["key"] = key
        if key in seen:
            record.update(status="duplicate", duplicate_of=seen[key]["ref"])
            continue
        seen[key] = record
        if image.convert("L").point(lambda pixel: 255 if pixel < 250 else 0).getbbox() is None:
            record["status"] = "blank"
            continue
        if not ocr_small_images and min(image.size) < 80:
            record["status"] = "small_skipped"
            continue
        label = analyze_image_for_ocr(image)
        record["classification"] = label
        record["render_policy"] = "reference_only" if label == "coordinate_plot" else "inline"
        if label in {"diagram", "coordinate_plot"} and not ocr_diagrams:
            record["status"] = "diagram_kept"
            continue
        target = prepared / (key[:20] + ".png")
        record["prepared_size"] = list(preprocess_for_ocr(image, target))
        record.update(status="queued", prepared_path=str(target))
    return records, by_ref


def clean_ocr(text):
    """Chỉ lọc mẫu rác rõ ràng; không tuyên bố chuỗi còn lại là đúng."""
    value = text.strip() if text else ""
    if not value or any(re.search(pattern, value) for pattern in GARBAGE_PATTERNS):
        return ""
    if value.count("| 100 |") > 5 or ("Point" in value and value.count("| 10 |") > 5):
        return ""
    if "Category" in value and "Value" in value:
        return ""
    tokens = re.split(r"[\s|<>/]+", value)
    if sum(bool(re.fullmatch(r"[&#$%^*`]+\d{0,2}\*{0,2}", token)) for token in tokens if len(token) <= 4) >= 4:
        return ""
    if "<tr" in value.lower():
        rows = []
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", value, re.DOTALL | re.IGNORECASE):
            cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
            if cells:
                rows.append([html.unescape(re.sub(r"<[^>]+>", "", cell)).strip().replace("|", r"\|").replace("\n", " ") for cell in cells])
        if rows:
            columns = max(map(len, rows))
            padded = [row + [""] * (columns - len(row)) for row in rows]
            lines = ["| " + " | ".join(row) + " |" for row in padded]
            lines.insert(1, "| " + " | ".join(["---"] * columns) + " |")
            return "\n".join(lines)
    # Không bỏ x, 0, π; không sửa LaTeX, ma trận hay dấu *.
    return value


def clean_pandoc_output(text):
    # Không chạy các regex tự đoán ngoặc, xóa dấu nhân, bỏ cột ma trận của bản dán.
    return text.strip()


def is_plot_label_list(text):
    """Chỉ nhận danh sách nhãn rời x/y/O + số, không nhận biểu thức/toán LaTeX."""
    value = (text or "").strip().replace("−", "-").replace("–", "-")
    tokens = value.split()
    if len(tokens) < 6:
        return False
    lowered = {token.lower() for token in tokens}
    if not {"x", "y"}.issubset(lowered):
        return False
    numeric = re.compile(r"[+-]?(?:\d+(?:[.,]\d+)?|[.]\d+)")
    return (sum(bool(numeric.fullmatch(token)) for token in tokens) >= 3
            and all(token.lower() in {"x", "y", "o"} or numeric.fullmatch(token) for token in tokens))


def remove_axis_label_blocks(page):
    """Dọn bản HTML đã có: chỉ bỏ block [OCR] chứa danh sách nhãn trục rời.

    Không gọi model, không bỏ hình, không sửa công thức hoặc blockquote khác.
    """
    class BlockFilter(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.output, self.buffer, self.words = [], [], []
            self.depth = self.removed = 0
        def append(self, value):
            (self.buffer if self.depth else self.output).append(value)
        def handle_starttag(self, tag, attrs):
            if tag == "blockquote":
                if not self.depth:
                    self.buffer, self.words = [], []
                self.depth += 1
            self.append(self.get_starttag_text())
        def handle_startendtag(self, tag, attrs):
            self.append(self.get_starttag_text())
        def handle_endtag(self, tag):
            self.append("</" + tag + ">")
            if self.depth and tag == "blockquote":
                self.depth -= 1
                if not self.depth:
                    text = " ".join(self.words).strip()
                    header = re.match(r"^\[OCR\b[^\]]*\]\s*", text, re.IGNORECASE)
                    if header and is_plot_label_list(text[header.end():]):
                        self.removed += 1
                    else:
                        self.output.extend(self.buffer)
                    self.buffer, self.words = [], []
        def handle_data(self, data):
            self.append(data)
            if self.depth:
                self.words.append(data)
        def handle_entityref(self, name):
            self.append("&" + name + ";")
            if self.depth:
                self.words.append(html.unescape("&" + name + ";"))
        def handle_charref(self, name):
            self.append("&#" + name + ";")
            if self.depth:
                self.words.append(html.unescape("&#" + name + ";"))
        def handle_comment(self, data):
            self.append("<!--" + data + "-->")
        def handle_decl(self, decl):
            self.append("<!" + decl + ">")
        def handle_pi(self, data):
            self.append("<?" + data + ">")
    parser = BlockFilter()
    parser.feed(page)
    parser.close()
    if parser.buffer:
        parser.output.extend(parser.buffer)
    return "".join(parser.output), parser.removed


def ocr_configs(size):
    longest = max(size)
    sides = [384] if longest <= 130 else ([448, 512, 640] if longest <= 350 else [512, 640, 448])
    return [dict(crop_mode=False, base_size=side, image_size=side) for side in sides]


def make_stopper(tokenizer, base_class):
    class GarbageStoppingCriteria(base_class):
        def __init__(self):
            self.step = 0
        def __call__(self, input_ids, scores, **kwargs):
            self.step += 1
            if self.step % 15 or input_ids.shape[1] < 80:
                return False
            text = tokenizer.decode(input_ids[0][-80:], skip_special_tokens=True)
            tokens = re.split(r"[\s|<>/]+", text)
            return sum(bool(re.fullmatch(r"[&#$%^*`]+\d{0,2}\*{0,2}", token)) for token in tokens if token and len(token) <= 4) >= 4
    return GarbageStoppingCriteria()


def infer_image(model, tokenizer, record, out_dir, torch):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for index, config in enumerate(ocr_configs(record["prepared_size"])):
        started = time.perf_counter()
        attempt_dir = out_dir / f"a{index}"
        attempt = dict(config=config, status="pending")
        record["attempts"].append(attempt)
        print(f"    Lượt {index+1}: {config['image_size']}px", flush=True)
        try:
            with torch.inference_mode():
                model.infer(tokenizer, prompt="<image>\nFree OCR.",
                            image_file=record["prepared_path"], output_path=str(attempt_dir),
                            save_results=True, test_compress=False, **config)
            output = attempt_dir / "result.mmd"
            raw = output.read_text(encoding="utf-8").strip() if output.is_file() else ""
            record["raw_ocr"] = raw
            cleaned = clean_ocr(raw)
            attempt.update(status="text_returned" if cleaned else "empty_or_filtered", characters=len(raw))
            if cleaned:
                record.update(status="ocr_text_returned", ocr_text=cleaned)
                if is_plot_label_list(cleaned):
                    record.update(render_policy="reference_only", annotation_warning="Chỉ có nhãn trục/số rời; không chèn thành công thức trong đề.")
                return
        except torch.cuda.OutOfMemoryError as error:
            attempt.update(status="out_of_memory", error=str(error))
            torch.cuda.empty_cache()
        except Exception as error:
            attempt.update(status="error", error=str(error))
            print("    Lỗi lượt OCR:", error, flush=True)
        finally:
            attempt["seconds"] = round(time.perf_counter() - started, 3)
    record["status"] = "ocr_unread"


def build_final(markdown, by_ref):
    def replace(match):
        record = by_ref.get(match[1], {})
        text = record.get("ocr_text", "")
        if not text or record.get("render_policy") == "reference_only" or is_plot_label_list(text):
            return match[0]  # Luôn giữ hình gốc, không thay bằng OCR thất bại.
        block = "\n".join("> " + line if line else ">" for line in text.splitlines())
        # A blank line is required before a pipe table. Another blank line
        # after the block keeps following source text outside the blockquote.
        return match[0] + "\n\n> **[OCR — cần đối chiếu]**\n>\n" + block + "\n\n"
    return IMAGE_RE.sub(replace, clean_pandoc_output(markdown))


def write_reports(records, metrics, output):
    portable = json.loads(json.dumps(records, ensure_ascii=False))
    for record in portable:
        if record.get("prepared_path"):
            record["prepared_path"] = Path(record["prepared_path"]).relative_to(Path(output)).as_posix()
    (Path(output) / "image-report.json").write_text(json.dumps(portable, ensure_ascii=False, indent=2), encoding="utf-8")
    (Path(output) / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def ast_text(value, skip_math=False):
    if isinstance(value, dict):
        kind = value.get("t")
        if kind == "Str":
            return value.get("c", "")
        if kind in {"Space", "SoftBreak", "LineBreak"}:
            return " "
        if kind == "Math":
            return "" if skip_math else value["c"][1]
        return ast_text(value.get("c", []), skip_math)
    if isinstance(value, list):
        return "".join(ast_text(item, skip_math) for item in value)
    return ""


def has_ast_type(value, kind):
    if isinstance(value, dict):
        return value.get("t") == kind or has_ast_type(value.get("c", []), kind)
    return isinstance(value, list) and any(has_ast_type(item, kind) for item in value)


def prepare_print_ast(document):
    """Reconstruct only parsed tables/math; preserve original images for review.

    No values, symbols or equations are inferred or repaired here.
    """
    counts = dict(structured_tables=0, inline_math=0, notes_only=0)
    def wrap(kind, classes, content):
        return {"t": kind, "c": [["", classes, []], content]}
    def ocr_parts(block):
        if not isinstance(block, dict) or block.get("t") != "BlockQuote":
            return None
        blocks = block.get("c", [])
        if not blocks or blocks[0].get("t") not in {"Para", "Plain"}:
            return None
        inlines = blocks[0]["c"]
        if not inlines or inlines[0].get("t") != "Strong":
            return None
        if not re.fullmatch(r"\[OCR\b[^\]]*\]", ast_text(inlines[0]).strip(), re.IGNORECASE):
            return None
        remainder = inlines[1:]
        while remainder and remainder[0].get("t") in {"Space", "SoftBreak"}:
            remainder = remainder[1:]
        return ([{"t": "Para", "c": remainder}] if remainder else []) + blocks[1:]
    def process(items):
        output = []
        for block in items:
            parts = ocr_parts(block)
            previous = output[-1] if output else None
            if parts is None or not isinstance(previous, dict) or previous.get("t") not in {"Para", "Plain"}:
                output.append(block)
                continue
            images = [index for index, inline in enumerate(previous["c"]) if inline.get("t") == "Image"]
            if not images:
                output.append(block)
                continue
            is_table = has_ast_type(parts, "Table")
            is_math = (len(parts) == 1 and parts[0].get("t") in {"Para", "Plain"}
                       and has_ast_type(parts, "Math")
                       and not re.sub(r"[\s.,;:()[\]{}…-]", "", ast_text(parts, skip_math=True)))
            if not is_table and not is_math:
                output.append(wrap("Div", ["ocr-notes"], parts))
                counts["notes_only"] += 1
                continue
            index = images[-1]
            before, image, after = previous["c"][:index], previous["c"][index], previous["c"][index+1:]
            output.pop()
            if is_table:
                rendered = [wrap("Div", ["ocr-caption"], [part])
                            if part.get("t") in {"Para", "Plain"}
                            and re.fullmatch(r"(?:Bảng|Table)\s+\d+[.:]?", ast_text(part).strip(), re.IGNORECASE)
                            else part for part in parts]
                if ast_text(before).strip() or has_ast_type(before, "Math") or has_ast_type(before, "Image"):
                    output.append({"t": previous["t"], "c": before})
                output.append(wrap("Div", ["ocr-pair", "ocr-table"], [
                    wrap("Div", ["ocr-source"], [{"t": "Para", "c": [image]}]),
                    wrap("Div", ["ocr-rendered"], rendered),
                ]))
                if ast_text(after).strip() or has_ast_type(after, "Math") or has_ast_type(after, "Image"):
                    output.append({"t": previous["t"], "c": after})
                counts["structured_tables"] += 1
            else:
                pair = wrap("Span", ["ocr-pair", "ocr-math"], [
                    wrap("Span", ["ocr-source"], [image]),
                    wrap("Span", ["ocr-rendered"], parts[0]["c"]),
                ])
                output.append({"t": previous["t"], "c": [*before, pair, *after]})
                counts["inline_math"] += 1
        return output
    def walk(value):
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return process([walk(item) for item in value])
        return value
    return walk(deepcopy(document)), counts


def page_css(source):
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    values = dict(w=210, h=297, top=15, right=15, bottom=15, left=15)
    with zipfile.ZipFile(source) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        sections = list(document.iter(namespace + "sectPr"))
        if sections:
            for name, keys in (("pgSz", ("w", "h")), ("pgMar", ("top", "right", "bottom", "left"))):
                node = sections[-1].find(namespace + name)
                if node is not None:
                    for key in keys:
                        try:
                            values[key] = float(node.get(namespace + key)) * 25.4 / 1440
                        except (ValueError, TypeError):
                            pass
    width = max(50, values["w"] - values["left"] - values["right"])
    return (f"@page{{size:{values['w']}mm {values['h']}mm;margin:{values['top']}mm {values['right']}mm {values['bottom']}mm {values['left']}mm}}"
            f"body{{font:12pt/1.3 'Times New Roman',serif;max-width:{width}mm;margin:20px auto;background:white}}"
            "*{box-sizing:border-box}img{max-width:100%}p{margin:0 0 6pt;orphans:3;widows:3}"
            "table{border-collapse:collapse;max-width:100%;margin:6pt auto;break-inside:auto}"
            "td,th{border:0.6pt solid #222;padding:5pt 7pt;vertical-align:middle;overflow-wrap:anywhere}"
            "th{text-align:center;font-weight:bold}thead{display:table-header-group}tr{break-inside:avoid}"
            "math{font-size:1em}blockquote{margin:6pt 0;padding:0 6pt}"
            ".ocr-source,.ocr-notes{display:none}"
            ".show-source .ocr-source,.show-source .ocr-notes{display:block}"
            ".show-source .ocr-math .ocr-source{display:inline-block;vertical-align:middle;margin-right:6pt}"
            ".show-source .ocr-source,.ocr-notes{border:1px dashed #aaa;padding:5pt;margin:6pt 0;background:#fff9da}"
            ".ocr-pair{max-width:100%}.ocr-rendered{max-width:100%}.ocr-rendered>p:last-child{margin-bottom:0}"
            ".ocr-caption{text-align:center;font-style:italic;margin:3pt 0 8pt}"
            ".toolbar{font:14px Arial;border-bottom:1px solid #bbb;padding:10px;margin-bottom:12px}"
            "@media print{body{max-width:none;margin:0;color:#000;background:#fff}"
            ".toolbar{display:none!important}.ocr-source{display:none!important}.ocr-notes{display:none!important}"
            "img{break-inside:avoid}table{break-inside:auto}tr{break-inside:avoid}"
            "thead{display:table-header-group}a{color:inherit;text-decoration:none}}")


def export_html(final_path, source, pandoc, *, media_root=None, title=None):
    work_dir = Path(final_path).parent
    asset_root = Path(media_root) if media_root is not None else work_dir
    parsed = subprocess.run([pandoc, str(final_path), "-f", "markdown+tex_math_dollars+tex_math_single_backslash-raw_html", "-t", "json"],
                            cwd=asset_root, capture_output=True, text=True, encoding="utf-8", timeout=120)
    if parsed.returncode:
        raise RuntimeError("Không phân tích được kết quả OCR: " + parsed.stderr)
    document, counts = prepare_print_ast(json.loads(parsed.stdout))
    process = subprocess.run([pandoc, "-f", "json", "-t", "html5", "--mathml", "--wrap=none"],
                             input=json.dumps(document), cwd=asset_root, capture_output=True, text=True, encoding="utf-8", timeout=120)
    if process.returncode:
        raise RuntimeError("Không xuất được HTML kết quả OCR: " + process.stderr)
    warnings = (parsed.stderr + "\n" + process.stderr).strip()
    if warnings:
        (work_dir / "html-warnings.log").write_text(warnings, encoding="utf-8")
        print("[CẢNH BÁO XUẤT HTML]", warnings, flush=True)
    def embed(match):
        ref = html.unescape(match[1])
        path = image_path(ref, asset_root)
        if path is None or not path.is_file():
            return match[0]
        suffix = path.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}:
            return '<span style="color:#a00">[Ảnh ' + html.escape(path.name) + ' chưa hiển thị được trong trình duyệt; xem file gốc trong ZIP]</span>'
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}.get(suffix, "image/" + suffix[1:])
        uri = "data:" + mime + ";base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        return match[0].replace(match[1], uri, 1)
    body = re.sub(r'<img\b[^>]*\bsrc="([^"]+)"[^>]*>', embed, process.stdout)
    body, _ = remove_axis_label_blocks(body)
    display_name = title or Path(source).name
    toolbar = ('<div class="toolbar"><strong>Đề đang xem: ' + html.escape(display_name) + '</strong><br>'
               '<button onclick="window.print()">In / lưu PDF kết quả</button>'
               '<label><input type="checkbox" onchange="document.body.classList.toggle(\'show-source\',this.checked)"> Đối chiếu ảnh gốc / ghi chú OCR</label>'
               '<p>Bản in dùng bảng/công thức đã dựng từ OCR khi có cấu trúc; đồ thị và ảnh chưa dựng được giữ nguyên. '
               'Chữ OCR chưa được xác nhận đúng. Bật đối chiếu để kiểm tra; ảnh đối chiếu và ghi chú không in kèm. '
               'In tỷ lệ 100%, tắt Headers/Footers của trình duyệt. Ngắt dòng/ngắt trang có thể khác Word.</p></div>')
    page = ('<!doctype html><html lang="vi"><meta charset="utf-8"><title>Kết quả OCR — '
            + html.escape(display_name) + '</title><style>' + page_css(source)
            + '</style><body>' + toolbar + body + '</body></html>')
    target = work_dir / "ket-qua-ocr.html"
    target.write_text(page, encoding="utf-8")
    (work_dir / "print-layout.json").write_text(json.dumps(dict(**counts, policy="structured_ocr_reconstruction_with_source_comparison",
        validation="layout_only_not_ocr_accuracy", media_root=str(asset_root)), ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def run_worker(source, output, *, ocr_diagrams=False, ocr_small_images=True):
    import pypandoc
    source, output = validate_docx(source), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output / "input.docx")
    started = time.perf_counter()
    pandoc = pypandoc.get_pandoc_path()
    step1 = output / "step1.md"
    print("\nBUOC 1: Bóc DOCX bằng Pandoc", flush=True)
    process = subprocess.run([pandoc, "-f", "docx", str(source), "-t", "markdown+tex_math_dollars", "--wrap=none",
                              "--extract-media=media", "-o", str(step1)], cwd=output,
                             capture_output=True, text=True, encoding="utf-8", timeout=120)
    if process.returncode:
        raise RuntimeError("Pandoc lỗi: " + process.stderr)
    if process.stderr.strip():
        (output / "pandoc-warnings.log").write_text(process.stderr, encoding="utf-8")
        print("[CẢNH BÁO PANDOC]", process.stderr, flush=True)
    markdown = step1.read_text(encoding="utf-8")
    records, by_ref = plan_images(markdown, output, ocr_diagrams=ocr_diagrams, ocr_small_images=ocr_small_images)
    tasks = [record for record in records if record["status"] == "queued"]
    metrics = dict(model=MODEL_NAME, dtype="bfloat16", attention="eager", parse_preprocess_s=time.perf_counter()-started,
                   model_load_s=0.0, ocr_s=0.0, gpu_inference_ran=False, images_referenced=len(records),
                   queued_unique_images=len(tasks), ocr_text_returned=0, ocr_diagrams=ocr_diagrams,
                   native_math_policy="unchanged_pandoc_latex", unsupported_images=sum(record["status"] == "unsupported" for record in records))
    with zipfile.ZipFile(source) as archive:
        metrics["source_media_files"] = [name for name in archive.namelist() if name.startswith("word/media/") and not name.endswith("/")]
        document = ET.fromstring(archive.read("word/document.xml"))
        metrics["native_word_equations_main_doc"] = sum(1 for node in document.iter("{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath"))
    print("Kiểm tra ảnh Pandoc xuất được. DOCX gốc được giữ trong ZIP; bản này không chuyển WMF/EMF/OLE bằng LibreOffice.", flush=True)
    print("Word Equation trong văn bản gốc:", metrics["native_word_equations_main_doc"], "— do Pandoc đọc trực tiếp.", flush=True)
    print(f"Ảnh tham chiếu: {len(records)} · ảnh cần OCR: {len(tasks)} · sơ đồ giữ nguyên: "
          f"{sum(record['status'] == 'diagram_kept' for record in records)} · ảnh không đọc được: {metrics['unsupported_images']}", flush=True)
    for record in records:
        if record["status"] in {"unsupported", "missing", "small_skipped"}:
            print("[CHƯA OCR]", record["ref"], record.get("error", record["status"]), flush=True)
    write_reports(records, metrics, output)
    if tasks:
        import gc
        import torch
        from transformers import AutoModel, AutoTokenizer, StoppingCriteria, StoppingCriteriaList
        if not torch.cuda.is_available():
            raise RuntimeError("Ảnh cần OCR nhưng không có GPU CUDA. Bật GPU trong Settings.")
        free, _ = torch.cuda.mem_get_info(0)
        if free < 7_000_000_000:
            raise RuntimeError("GPU còn dưới 7 GB VRAM. Dừng model khác trước khi chạy.")
        print("\nBUOC 2: Nạp", MODEL_NAME, "| GPU:", torch.cuda.get_device_name(0), flush=True)
        load_start = time.perf_counter()
        gc.collect()
        torch.cuda.empty_cache()
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True, use_fast=True)
        model = AutoModel.from_pretrained(MODEL_NAME, trust_remote_code=True, torch_dtype=torch.bfloat16,
                                         attn_implementation="eager", low_cpu_mem_usage=True).eval().cuda()
        original_generate = model.generate
        stopper = make_stopper(tokenizer, StoppingCriteria)
        def capped(self, *args, **kwargs):
            stopper.step = 0
            kwargs["max_new_tokens"] = MAX_NEW_TOKENS
            kwargs["eos_token_id"] = tokenizer.eos_token_id
            kwargs["pad_token_id"] = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
            existing = list(kwargs.get("stopping_criteria") or [])
            kwargs["stopping_criteria"] = StoppingCriteriaList([*existing, stopper])
            return original_generate(*args, **kwargs)
        model.generate = types.MethodType(capped, model)
        metrics["model_load_s"] = time.perf_counter() - load_start
        print("\nBUOC 3: OCR ảnh đã chọn", flush=True)
        ocr_start = time.perf_counter()
        try:
            for index, record in enumerate(tasks, 1):
                print(f"[{index}/{len(tasks)}] {record['ref']}", flush=True)
                metrics["gpu_inference_ran"] = True
                infer_image(model, tokenizer, record, output / "ocr_imgs" / f"img_{index:03d}", torch)
                metrics["ocr_text_returned"] += bool(record["ocr_text"])
                print("    " + ("Có chữ trả về — cần đối chiếu" if record["ocr_text"] else "CHƯA ĐỌC ĐƯỢC"), flush=True)
                write_reports(records, metrics, output)
        finally:
            metrics["ocr_s"] = time.perf_counter() - ocr_start
            del original_generate, model
            gc.collect()
            torch.cuda.empty_cache()
    else:
        print("Không có ảnh được chọn để OCR. Không nạp/chạy model; không phải benchmark OCR.", flush=True)
    for record in records:
        if record["status"] == "duplicate":
            original = by_ref[record["duplicate_of"]]
            record.update(ocr_text=original["ocr_text"], raw_ocr=original["raw_ocr"],
                          render_policy=original.get("render_policy", "inline"))
    print("\nBUOC 4: Ghép và hiển thị nội dung trích xuất + OCR", flush=True)
    final = build_final(markdown, by_ref)
    final_path = output / "final.md"
    final_path.write_text(final, encoding="utf-8")
    export_start = time.perf_counter()
    export_html(final_path, source, pandoc)
    metrics.update(export_s=time.perf_counter()-export_start, pipeline_s=time.perf_counter()-started,
                   images_unread=sum(record["status"] in {"unsupported", "missing", "ocr_unread", "small_skipped"} for record in records),
                   inference_attempts=sum(len(record["attempts"]) for record in records),
                   coordinate_plots=sum(record.get("classification") == "coordinate_plot" for record in records),
                   ocr_reference_only=sum(bool(record["ocr_text"]) and (record.get("render_policy") == "reference_only" or is_plot_label_list(record["ocr_text"])) for record in records))
    write_reports(records, metrics, output)
    print(f"\nPandoc/ảnh: {metrics['parse_preprocess_s']:.2f}s · nạp model: {metrics['model_load_s']:.2f}s"
          f" · OCR: {metrics['ocr_s']:.2f}s · xuất HTML: {metrics['export_s']:.2f}s", flush=True)
    print(f"Ảnh có chữ OCR: {metrics['ocr_text_returned']}/{len(tasks)} — KHÔNG phải tỷ lệ chính xác.", flush=True)
    if metrics["ocr_reference_only"]:
        print(f"{metrics['ocr_reference_only']} kết quả đồ thị/nhãn trục chỉ lưu để đối chiếu trong image-report.json, không chèn vào đề.", flush=True)
    print("\n===== NỘI DUNG KẾT QUẢ =====\n" + final, flush=True)
    return dict(results=str(output), final=str(final_path), html=str(output / "ket-qua-ocr.html"), metrics=metrics)


def self_script_path(root):
    """Hỗ trợ cả chạy file .py và copy toàn bộ file vào một cell notebook."""
    filename = globals().get("__file__")
    if filename and Path(filename).is_file():
        content = Path(filename).read_text(encoding="utf-8")
        if "def self_script_path(" in content and "def run_worker(" in content:
            return Path(filename).resolve()
    from IPython import get_ipython
    shell = get_ipython()
    history = getattr(getattr(shell, "history_manager", None), "input_hist_raw", [])
    source = history[-1] if history else ""
    if "def run_worker(" not in source or "def self_script_path(" not in source:
        raise RuntimeError("Hãy copy TOÀN BỘ file Python vào cùng một cell, hoặc dùng notebook đi kèm.")
    compile(source, "copied-original-fixed-cell", "exec")
    target = Path(root) / "hybrid_ocr_original_fixed.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return target.resolve()


def print_timing(metrics):
    """Hiện lại số đo đã lưu, không chạy lại model để xem thời gian."""
    total = metrics.get("total_s")
    note = ""
    if total is None:
        total = metrics.get("total_before_zip_s")
        note = " — bản cũ: chưa gồm đóng ZIP"
    if total is None:
        return
    minutes, seconds = divmod(round(float(total), 2), 60)
    print(f"\nTỔNG THỜI GIAN ĐÃ CHẠY: {int(minutes)} phút {seconds:.2f} giây ({total:.2f}s){note}", flush=True)
    labels = (("dependency_setup_s", "Chuẩn bị/thư viện"), ("parse_preprocess_s", "Pandoc/ảnh"),
              ("model_load_s", "Nạp model"), ("ocr_s", "OCR"),
              ("export_s", "Xuất HTML"), ("zip_s", "Đóng ZIP"))
    parts = [f"{label}: {metrics[key]:.2f}s" for key, label in labels if key in metrics]
    if parts:
        print(" · ".join(parts), flush=True)


def display_result(result):
    """Hiện đầu ra thật, dùng được ngay khi copy script vào notebook."""
    from IPython.display import HTML, FileLink, IFrame, display
    for path, mime, label in (
        (result["html"], "text/html", "Tải HTML kết quả OCR — mở để In / lưu PDF"),
        (result["final"], "text/markdown", "Tải Markdown kết quả"),
        (result["archive"], "application/zip", "Tải ZIP (kết quả + ảnh + DOCX gốc + báo cáo + log)"),
    ):
        path = Path(path)
        if path.stat().st_size <= 10_000_000:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            display(HTML('<p><a download="' + html.escape(path.name) + '" href="data:' + mime + ';base64,' + encoded + '">' + label + '</a></p>'))
        else:
            display(FileLink(str(path), result_html_prefix=label + ": "))
            print("File lớn: có thể tải ở mục Output của Kaggle:", path)
    page = Path(result["html"]).read_text(encoding="utf-8")
    display(IFrame("about:blank", width="100%", height=1100, extras=[
        'title="Kết quả trích xuất và OCR"', 'sandbox="allow-scripts allow-modals allow-downloads"',
        'srcdoc="' + html.escape(page, quote=True) + '"',
    ]))
    print_timing(result.get("metrics", {}))
    print("Kết quả được lưu tại:", result["results"])


def run(source=INPUT_DOCX, root=RUN_ROOT, *, ocr_diagrams=OCR_DIAGRAMS, ocr_small_images=OCR_SMALL_IMAGES):
    """Chạy trong tiến trình riêng; không thay thư viện của kernel notebook."""
    started = time.perf_counter()
    source = validate_docx(source)  # Chặn đường dẫn rỗng/thư mục trước khi cài gì.
    root = Path(root).resolve()
    job = root / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8])
    job.mkdir(parents=True)
    log_path, output = job / "run.log", job / "result"
    print("File đề:", source, "\nLog:", log_path, flush=True)
    script = self_script_path(root)
    try:
        with log_path.open("w", encoding="utf-8") as log:
            dependencies = ensure_dependencies(root, log)
            setup_s = time.perf_counter() - started
            command = [sys.executable, "-u", str(script), "--worker", "--input", str(source), "--output", str(output)]
            if ocr_diagrams:
                command.append("--ocr-diagrams")
            if not ocr_small_images:
                command.append("--skip-small-images")
            stream_command(command, log=log, env=child_environment(dependencies), step="Pandoc + DeepSeek-OCR gốc", run_started=started)
        metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
        metrics.update(source_path=str(source), source_name=source.name,
                       source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        metrics["dependency_setup_s"] = setup_s
        metrics["total_before_zip_s"] = time.perf_counter() - started
        shutil.copyfile(log_path, output / "run.log")
        archive = job / "ket-qua-ocr.zip"
        zip_started = time.perf_counter()
        # Close the compressed payload before reading the final timer. Append
        # the tiny timing report once afterwards, so ZIP/filesystem/UI agree
        # without duplicate metrics entries or recompressing all images.
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            for path in sorted(output.rglob("*")):
                if path.is_file() and path != output / "metrics.json":
                    zipped.write(path, path.relative_to(output).as_posix())
        metrics["zip_s"] = time.perf_counter() - zip_started
        metrics["total_s"] = time.perf_counter() - started
        metrics["timing_scope"] = "run entry through ZIP payload close; excludes timing-report finalization and screen rendering"
        metrics_path = output / "metrics.json"
        metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        with zipfile.ZipFile(archive, "a", compression=zipfile.ZIP_DEFLATED) as zipped:
            zipped.write(metrics_path, "metrics.json")
        print("\nĐÃ XONG. Kết quả:", output, "\nZIP:", archive, flush=True)
        print_timing(metrics)
        return dict(results=output, archive=archive, final=output / "final.md", html=output / "ket-qua-ocr.html", metrics=metrics,
                    source_path=str(source))
    except BaseException:
        print("\nLượt chạy chưa hoàn tất. Giữ nguyên dữ liệu và log tại:", log_path, flush=True)
        print(f"Thời gian đến lúc dừng/lỗi: {time.perf_counter() - started:.2f}s", flush=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=INPUT_DOCX)
    parser.add_argument("--root", default=RUN_ROOT)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--ocr-diagrams", action="store_true")
    parser.add_argument("--skip-small-images", action="store_true")
    args = parser.parse_args(argv)
    if args.worker:
        if not args.output:
            parser.error("--worker cần --output")
        return run_worker(args.input, args.output, ocr_diagrams=args.ocr_diagrams, ocr_small_images=not args.skip_small_images)
    return run(args.input, args.root, ocr_diagrams=args.ocr_diagrams, ocr_small_images=not args.skip_small_images)


if __name__ == "__main__":
    try:
        from IPython import get_ipython
        running_in_notebook = get_ipython() is not None
    except ImportError:
        running_in_notebook = False
    if running_in_notebook:
        result = None
        FINAL_PATH = WORK_DIR = CLEAN_HTML = None
        result = run(INPUT_DOCX, RUN_ROOT, ocr_diagrams=OCR_DIAGRAMS, ocr_small_images=OCR_SMALL_IMAGES)
        FINAL_PATH, WORK_DIR = result["final"], result["results"]
        display_result(result)
    else:
        main()
