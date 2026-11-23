# ================================================================
# HYBRID OCR PIPELINE - BAN TEST 1 FILE (danh cho Kaggle Notebook)
# Chi can sua INPUT_FOLDER va INPUT_NAME roi bam Run All
#
# HUONG DAN CHO NGUOI NHAN:
#   1. Tao notebook moi tren Kaggle (kaggle.com/code -> New Notebook)
#   2. Bat GPU: Settings (ben phai) -> Accelerator -> chon GPU T4 x2 hoac P100
#   3. Upload file .docx cua ban: Add Input -> Upload -> chon file .docx
#      (Kaggle se tao 1 dataset moi, nho lai duong dan hien ra)
#   4. Sua 2 dong INPUT_FOLDER va INPUT_NAME ben duoi cho dung duong dan
#      (duong dan thuong co dang: /kaggle/input/ten-dataset-cua-ban/)
#   5. Copy toan bo code nay vao 1 cell, bam Run (Shift+Enter)
#   6. Cho khoang 1-2 phut (lan dau tai model ~6.7GB co the lau hon)
# ================================================================

# ---- SUA 2 DONG NAY ----
INPUT_FOLDER = "/kaggle/input/ten-dataset-cua-ban"
INPUT_NAME   = "ten_file_cua_ban.docx"
# ================================================================

import os, gc, re, types, shutil, time, hashlib, subprocess, sys
from pathlib import Path

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

print("="*60)
print("  BUOC 0: Kiem tra GPU truoc khi cai thu vien")
print("="*60)


def require_cuda():
    """Fail before pip/apt/model downloads when this kernel cannot use CUDA."""
    import torch

    print("  Python:", sys.version.split()[0])
    print("  PyTorch:", torch.__version__)
    print("  Torch CUDA build:", torch.version.cuda)
    print("  CUDA available:", torch.cuda.is_available())
    print("  CUDA device count:", torch.cuda.device_count())

    if not torch.cuda.is_available():
        raise RuntimeError(
            "Kernel hien tai khong su dung duoc CUDA; chua cai dependency hay tai model. "
            "Trong Kaggle Edit, chon Settings > Accelerator > GPU, "
            "restart session neu can, roi chay lai cell kiem tra GPU. "
            "Neu da chon GPU ma CUDA van False, gui output kiem tra va nvidia-smi. "
            "Cai lai transformers/tokenizers khong bat duoc GPU."
        )
    return torch


torch = require_cuda()
gc.collect(); torch.cuda.empty_cache(); torch.cuda.synchronize()
vram_free, vram_total = (value / 1e9 for value in torch.cuda.mem_get_info(0))
print("\n  GPU  : " + torch.cuda.get_device_properties(0).name)
print("  VRAM : " + str(round(vram_free,1)) + " GB free / " + str(round(vram_total,1)) + " GB total")
if vram_free < 7.0:
    raise RuntimeError("VRAM < 7GB - vao Runtime/Session -> Restart session roi chay lai")
print("  [OK] GPU san sang; bay gio moi cai dependency.")

# ---- Kiem tra file input TRUOC pip/Pandoc/model ----
def validate_docx_input(folder, name):
    """Reject empty paths, directories and non-DOCX files before any work."""
    if folder is None or name is None or not str(folder).strip() or not str(name).strip():
        raise ValueError(
            "Chua nhan file DOCX: INPUT_FOLDER/INPUT_NAME dang rong. "
            "Bam Chon DOCX, cho thong bao Da nhan file, roi chay cell pipeline."
        )

    path = (Path(str(folder).strip()) / str(name).strip()).resolve()
    if not path.is_file():
        raise FileNotFoundError("Dau vao phai la FILE, khong phai thu muc: " + str(path))
    if path.suffix.lower() != ".docx":
        raise ValueError("Hay chon file .docx: " + str(path))

    import zipfile
    try:
        with zipfile.ZipFile(path) as archive:
            members = set(archive.namelist())
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(members):
                raise ValueError("File khong co cau truc DOCX Word hop le: " + str(path))
    except zipfile.BadZipFile as error:
        raise ValueError("File khong phai DOCX hop le: " + str(path)) from error
    return path


INPUT_PATH = validate_docx_input(globals().get("INPUT_FOLDER"), globals().get("INPUT_NAME"))
print("\n  File input:", str(INPUT_PATH), "|", INPUT_PATH.stat().st_size, "bytes")

# ---- Cai thu vien can thiet ----
# Keep the original OCR dependency pins. Do not upgrade tokenizers/hub merely
# to satisfy unrelated Kaggle packages: that would change the model environment.
print("\n  Dang cai dat thu vien (co the mat 30-60s lan dau)...")
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "transformers==4.46.3", "tokenizers==0.20.3",
    "pymupdf", "einops", "addict", "easydict"], check=True)

if shutil.which("pandoc") is None:
    print("  Dang cai pandoc...")
    subprocess.run(["apt-get", "-qq", "update"], check=False)
    subprocess.run(["apt-get", "-qq", "install", "-y", "pandoc"], check=True)

from pathlib import Path
from PIL import Image, ImageOps
import numpy as np

WORK_DIR   = Path("/kaggle/working/ocr_output")
if WORK_DIR.exists(): shutil.rmtree(WORK_DIR)
MEDIA_DIR  = WORK_DIR / "media"
PREP_DIR   = WORK_DIR / "preprocessed"
OCR_DIR    = WORK_DIR / "ocr_imgs"
FINAL_PATH = WORK_DIR / "final.md"
for d in [WORK_DIR, MEDIA_DIR, PREP_DIR, OCR_DIR]:
    d.mkdir(parents=True, exist_ok=True)
# ================================================================
# HELPER FUNCTIONS
# ================================================================
def img_hash(path):
    try:
        img = Image.open(path).convert("RGB")
        return hashlib.md5(np.array(img).tobytes()).hexdigest()
    except Exception:
        h = hashlib.md5()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk: break
                h.update(chunk)
        return h.hexdigest()

def is_garbage_image(img_path):
    try:
        img = Image.open(img_path).convert("RGB")
        w, h = img.size
        if w < 80 or h < 80: return True
        pixels = [img.getpixel((w*x//4, h*y//4)) for x in [1,2,3] for y in [1,2,3]]
        dark = sum((r+g+b)/3 < 80 or (b > r*1.3 and (r+g+b)/3 < 130) for r,g,b in pixels)
        return dark >= 7
    except Exception:
        return True

def analyze_image_for_ocr(img_path):
    try:
        img_rgb = Image.open(img_path).convert("RGB")
        small   = img_rgb.resize((64, 64))
        colors  = small.getcolors(64*64)
        if (len(colors) if colors else 9999) > 400:
            return "diagram"
        img  = Image.open(img_path).convert("L")
        arr  = np.array(img, dtype=np.float32)
        h, w = arr.shape
        dark_ratio = (arr < 128).mean()
        dy = np.abs(np.diff(arr, axis=0)); dx = np.abs(np.diff(arr, axis=1))
        edge_density = (dy > 30).mean() + (dx > 30).mean()
        bh, bw = max(1, h//8), max(1, w//8)
        block_vars = [arr[i:i+bh, j:j+bw].std()
                      for i in range(0, h-bh, bh) for j in range(0, w-bw, bw)]
        bvar_spread = np.std(block_vars) if block_vars else 0
        is_text    = dark_ratio > 0.03 and dark_ratio < 0.6 and edge_density > 0.08
        is_diagram = dark_ratio < 0.15 and edge_density < 0.12 and bvar_spread > 20
        if is_diagram and not is_text: return "diagram"
        elif is_text:                  return "text"
        else:                          return "mixed"
    except Exception:
        return "mixed"

def is_tiny_label_image(img_path, max_side=130):
    try:
        w, h = Image.open(img_path).size
        return max(w, h) <= max_side
    except Exception:
        return False

def preprocess_for_ocr(img_path, out_dir):
    try:
        img = Image.open(img_path).convert("RGB")
        w, h = img.size
        arr  = np.array(img.convert("L"))
        mask = (arr < 240)
        rows = np.where(mask.any(axis=1))[0]; cols = np.where(mask.any(axis=0))[0]
        if len(rows) > 0 and len(cols) > 0:
            m = 8
            cropped = img.crop((max(0,cols[0]-m), max(0,rows[0]-m),
                                 min(w,cols[-1]+m), min(h,rows[-1]+m)))
            if cropped.size[0]*cropped.size[1] < w*h*0.85:
                img = cropped; w, h = img.size
        if max(w, h) > 1200:
            s = 1200/max(w,h)
            img = img.resize((int(w*s), int(h*s)), Image.LANCZOS)
        if np.array(img.convert("L")).std() < 40:
            img = ImageOps.autocontrast(img, cutoff=2)
        out = out_dir / ("prep_" + img_path.stem + ".png")
        img.save(str(out), format="PNG", optimize=False)
        return out
    except Exception:
        return img_path

def extract_alt_texts_from_docx(docx_path):
    import zipfile
    try:
        with zipfile.ZipFile(docx_path, 'r') as z:
            xml_content = z.read('word/document.xml').decode('utf-8', errors='ignore')
        return [m.strip() for m in re.findall(r'<wp:docPr\s+[^>]*\bdescr="([^"]*)"', xml_content)]
    except Exception:
        return []

def is_useful_alt_text(text, min_len=15):
    if not text or len(text.strip()) < min_len: return False
    for pat in [r'^Picture\s*\d*$', r'^Image\s*\d*$', r'^Hình\s*\d*$',
                r'^A (picture|screenshot|diagram) containing']:
        if re.match(pat, text.strip(), re.IGNORECASE): return False
    return True
_GARBAGE_PATTERNS = [
    r'"Line":\s*\{', r'"line":\s*\[', r'\(-\d+\.\d+,\s*\d+\.\d+\)\s*--',
    r'Image ID:\s*[A-Z0-9]+', r'"line_type"', r'"line_endpoint"',
]

def is_garbage_ocr(text):
    if not text or len(text.strip()) < 3: return True
    tokens = text.strip().split()
    if len(tokens) > 5 and all(t.isdigit() for t in tokens[:10]): return True
    for pat in _GARBAGE_PATTERNS:
        if re.search(pat, text): return True
    if "Point" in text and text.count("| 10 |") > 5: return True
    if text.startswith("<smiles>") and len(text) > 500: return True
    if "Category" in text and "Value" in text: return True
    if text.count("| 100 |") > 5: return True
    lines = [l.strip() for l in text.split('\n') if '|' in l and '---' not in l and l.strip()]
    if len(lines) > 8:
        values = []
        for line in lines[1:]:
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if cells: values.append(cells[-1])
        if len(values) > 8:
            mc = max(set(values), key=values.count)
            if values.count(mc) / len(values) > 0.8: return True
    tokens2 = re.split(r'[\s|<>/]+', text)
    symbol_re = re.compile(r'^[&#$%^*`]+\d{0,2}\*{0,2}$')
    if len([t for t in tokens2 if t and len(t)<=4 and symbol_re.match(t)]) >= 4: return True
    return False

def clean_ocr_table(text):
    if "<tr>" not in text.lower(): return text
    if text.count("None") > 5 or text.count("<td></td>") > 10: return ""
    rows = re.findall(r'<tr>(.*?)</tr>', text, re.DOTALL)
    md = []
    for i, row in enumerate(rows):
        cells = [c.strip() for c in re.findall(r'<td>(.*?)</td>', row, re.DOTALL)]
        if not cells or not any(cells): continue
        md.append("| " + " | ".join(cells) + " |")
        if i == 0: md.append("|" + " --- |"*len(cells))
    result = "\n".join(md)
    if result.count("Total") > 3 or result.count("| 10 |") > 5: return ""
    return result

def clean_ocr(text):
    if not text: return ""
    s = text.strip()
    if is_garbage_ocr(s): return ""
    if "<tr>" in s.lower():
        c = clean_ocr_table(s)
        if not c or is_garbage_ocr(c): return ""
        return c
    return s

def format_ocr_inline(ocr_text):
    if not ocr_text: return ""
    lines = [l.strip() for l in ocr_text.split('\n') if l.strip()]
    if any('|' in l for l in lines): return ocr_text.strip()
    m = [l for l in lines if len(l) > 2]
    return " | ".join(m) if m else ""

def clean_pandoc_output(text):
    def merge_img_attr_regex(t):
        def _r(m):
            return m.group(1) + re.sub(r'\s+', ' ', m.group(2)).strip()
        return re.sub(r'(!\[\]\([^)\n]+\))\s*\n*\s*(\{[^}]*\})', _r, t, flags=re.DOTALL)
    text = merge_img_attr_regex(text)

    def fix_bracket_wide(m):
        nums = re.findall(r'\d+', m.group(1))
        return "[" + nums[0] + ";" + nums[1] + ")" if len(nums) >= 2 else m.group(0)
    text = re.sub(r'\\mathbf\{[^}]*\}(.*?)(?:\\right\)|\))', fix_bracket_wide, text, flags=re.DOTALL)
    text = re.sub(r'\[\\?\s*(\d+)\s*;\s*(\d+)\s*\)', r'[\1;\2)', text)
    text = re.sub(r'\*\*\[([A-D])\.\*\*', r'**\1.**', text)

    def fix_matrix_block(m):
        content = m.group(1)
        def _rm(mm):
            inner = mm.group(1).replace(r'\&',' ').replace('\\&',' ')
            lines = [re.sub(r'\s*&\s*.*$','',re.sub(r'^\s*&\s*','',l.strip()))
                     for l in re.split(r'\\\\', inner) if l.strip()]
            return "\\begin{cases}" + "\\\\".join(l for l in lines if l) + "\\end{cases}"
        content = re.sub(
            r'\\left\s*\\?\{?\s*\\begin\{(?:matrix|array)[^}]*\}(.*?)'
            r'\\end\{(?:matrix|array)\}\s*\\right[.\|\\]*', _rm, content, flags=re.DOTALL)
        content = re.sub(r'\s{2,}', ' ', re.sub(r'[ \t]*\n[ \t]*', ' ', content)).strip()
        return "$" + content + "$"
    text = re.sub(r'\$((?:(?!\$).){1,800}?\\begin\{(?:matrix|array)\}(?:(?!\$).)*?)\$',
                  fix_matrix_block, text, flags=re.DOTALL)
    text = re.sub(r'\\\-', '-', text)
    text = re.sub(r'^\*\*(-{2,}[^*]+)\*\*$', r'\1', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*\\\[GT\\\]\*\*', '> **[GT]**', text)
    text = re.sub(r'\*\*\\\[([A-Z]+)\\\]\*\*', r'> **[\1]**', text)
    text = re.sub(r'^\\\[GT\\\]$', '> **[GT]**', text, flags=re.MULTILINE)
    text = re.sub(r'^\\\[/[\u2227\u039B]?\\\]$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\\\[/\\\]$', '', text, flags=re.MULTILINE)
    text = text.replace(r'\lbrack','[').replace(r'\rbrack',']')

    def fix_bu(m):
        return "**" + re.sub(r'\[([^\]]+)\]\{\.underline\}', r'\1', m.group(1)) + "**"
    text = re.sub(r'\*\*([^*]*\[[^\]]+\]\{\.underline\}[^*]*)\*\*', fix_bu, text)
    text = re.sub(r'\[([^\]]+)\]\{\.underline\}', r'**\1**', text)
    text = re.sub(r'\*{4,}([^*\n]+)\*{2,}\.?\*{0,2}',
                  lambda m: "**"+m.group(1).rstrip('*')+".**", text)
    text = re.sub(r'\*{4,}', '**', text)
    text = re.sub(r'\bậc\s+b\s+a\b', 'bậc ba', text)
    text = re.sub(r'\bhàm s\s+ố\b', 'hàm số', text)
    text = re.sub(r'\bsố h\s+ạng\b', 'số hạng', text)
    text = re.sub(r'\bcấp s\s+ố\b', 'cấp số', text)
    text = re.sub(r'\bđường th\s+ẳng\b', 'đường thẳng', text)

    def fix_im(m):
        f = m.group(1)
        f = re.sub(r'\\left\.\s*','',f); f = re.sub(r'\\right\.\s*','',f)
        f = re.sub(r'^\\\s+\[','[',f); f = re.sub(r'^\\\s+\{','{',f); f = re.sub(r'^\\\s+','',f)
        if len(re.findall(r'\\right',f)) > len(re.findall(r'\\left',f)):
            f = re.sub(r'\\right\)',')',f); f = re.sub(r'\\right\]',']',f)
            f = re.sub(r'\\right\}','}',f); f = re.sub(r'\\right\|','|',f)
        f = re.sub(r'\\mathbf\{([^a-zA-Z\}]{1,3})\}', r'\1', f)
        cc = [r'\\frac',r'\\sqrt',r'\\sum',r'\\int',r'\\prod',r'\\lim',r'\\begin',r'\\over']
        def sd(mm):
            ld,c,rd = mm.group(1),mm.group(2).strip(),mm.group(3)
            if any(re.search(x,c) for x in cc): return mm.group(0)
            if len(c) <= 40:
                d={'(':'()','[':'[]','{':'{}'}; o,cc2=d.get(ld,(ld,rd))
                return o+c+(cc2[1] if len(cc2)>1 else rd)
            return mm.group(0)
        f = re.sub(r'\\left([\(\[\{])(.*?)\\right([\)\]\}])', sd, f, flags=re.DOTALL)
        f = re.sub(r'\\left\|(.*?)\\right\|', lambda mm: "|"+mm.group(1).strip()+"|", f, flags=re.DOTALL)
        return "$" + re.sub(r'\s{2,}',' ',f.strip()) + "$"
    text = re.sub(r'\$([^$\n]{1,600})\$', fix_im, text)

    text = re.sub(r'\\text\{([^}]+)\}',
                  lambda m: m.group(0) if ' ' in m.group(1) and len(m.group(1))>10 else m.group(1), text)

    text = re.sub(r'([^\n])[ \t]*(!\[\]\([^)]+\)(?:\{[^}]*\})?)', r'\1\n\n\2', text)
    text = re.sub(r'(!\[\]\([^)]+\)(?:\{[^}]*\})?)[ \t]*([^\n>])', r'\1\n\n\2', text)
    text = re.sub(r'(!\[\]\([^)]+\)(?:\{[^}]*\})?)\n(> \*\*\[OCR\]\*\*)', r'\1\n\n\2', text)
    text = re.sub(r'\*\*A\.\*\*[^\n]*(?:\n+\*\*[BCD]\.\*\*[^\n]*){1,3}',
                  lambda m: re.sub(r'\n{1,}(\*\*[BCD]\.\*\*)', r' \1', m.group(0)), text)
    text = re.sub(r'([^\n])\n(\*\*A\.\*\*[^\n])', r'\1\n\n\2', text)
    text = re.sub(r'([^\n])\n(\*\*Câu\s+\d+)', r'\1\n\n\2', text)
    text = merge_img_attr_regex(text)
    text = text.replace('**','').replace('*','')
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s+$', '', text, flags=re.MULTILINE)
    return text.strip()

# ================================================================
print("\n" + "="*60)
print("  BUOC 1: Boc bang code (Pandoc)")
print("="*60)

t_total = time.time()
t0 = time.time()

MD_PATH = WORK_DIR / "step1.md"
proc = subprocess.run([
    "pandoc", "-f", "docx", str(INPUT_PATH),
    "-t", "markdown+tex_math_dollars", "--wrap=none",
    "--extract-media=" + str(MEDIA_DIR), "-o", str(MD_PATH),
], capture_output=True, text=True)

if proc.returncode != 0:
    raise RuntimeError("Pandoc loi: " + proc.stderr)

md_text    = MD_PATH.read_text(encoding="utf-8")
img_refs   = re.findall(r'!\[[^\]]*\]\(([^)]+)\)', md_text)
n_formulas = md_text.count("$") // 2
alt_texts = extract_alt_texts_from_docx(INPUT_PATH)

seen_hashes = {}; ref_to_hash = {}; need_ocr = []; alt_used = {}
n_skip_diagram = 0; n_alt_hit = 0

for idx, ref in enumerate(img_refs):
    p = (MD_PATH.parent / ref).resolve()
    if not p.exists(): continue
    if is_garbage_image(p): continue
    h = img_hash(p)
    if h in seen_hashes:
        ref_to_hash[ref] = h; continue
    alt = alt_texts[idx] if idx < len(alt_texts) else ""
    if is_useful_alt_text(alt):
        seen_hashes[h] = ref; ref_to_hash[ref] = h; alt_used[h] = alt; n_alt_hit += 1
        continue
    label = analyze_image_for_ocr(p)
    if label == "diagram":
        seen_hashes[h] = ref; ref_to_hash[ref] = h; n_skip_diagram += 1
        continue
    prep = preprocess_for_ocr(p, PREP_DIR)
    seen_hashes[h] = ref; ref_to_hash[ref] = h
    need_ocr.append((ref, prep, h))

t_code = time.time() - t0
print("  " + str(n_formulas) + " cong thuc | " + str(len(need_ocr)) + " anh can OCR | "
      + str(n_skip_diagram) + " diagram skip | " + str(n_alt_hit) + " alt-text | "
      + str(round(t_code,1)) + "s")

# ================================================================
ocr_cache = dict(alt_used)
t_load = 0
n_success = 0

if need_ocr:
    print("\n" + "="*60)
    print("  BUOC 2: Load DeepSeek-OCR")
    print("="*60)

    from transformers import AutoModel, AutoTokenizer, StoppingCriteria, StoppingCriteriaList

    class GarbageStoppingCriteria(StoppingCriteria):
        def __init__(self, tokenizer, check_every=15, window=80, min_symbol_tokens=4):
            self.tokenizer = tokenizer; self.check_every = check_every
            self.window = window; self.min_symbol_tokens = min_symbol_tokens
            self.step = 0
            self._re = re.compile(r'^[&#$%^*`]+\d{0,2}\*{0,2}$')
        def __call__(self, input_ids, scores, **kwargs):
            self.step += 1
            if self.step % self.check_every != 0: return False
            if input_ids.shape[1] < self.window: return False
            try:
                text = self.tokenizer.decode(input_ids[0][-self.window:], skip_special_tokens=True)
            except Exception:
                return False
            toks = re.split(r'[\s|<>/]+', text)
            return len([t for t in toks if t and len(t)<=4 and self._re.match(t)]) >= self.min_symbol_tokens

    t0 = time.time()
    gc.collect(); torch.cuda.empty_cache()
    MODEL_NAME = "deepseek-ai/DeepSeek-OCR"
    print("  Dang load " + MODEL_NAME + " (lan dau tai ~6.7GB)...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True, use_fast=True)
    model = AutoModel.from_pretrained(
        MODEL_NAME, trust_remote_code=True, torch_dtype=torch.bfloat16,
        attn_implementation="eager", low_cpu_mem_usage=True).eval().cuda()

    _orig = model.generate
    _stopper = GarbageStoppingCriteria(tokenizer)
    def _capped(self, *a, **kw):
        kw["max_new_tokens"] = 1000
        kw["eos_token_id"] = tokenizer.eos_token_id
        kw["pad_token_id"] = tokenizer.eos_token_id or tokenizer.pad_token_id
        if "stopping_criteria" not in kw or kw["stopping_criteria"] is None:
            kw["stopping_criteria"] = StoppingCriteriaList([_stopper])
        else:
            kw["stopping_criteria"].append(_stopper)
        return _orig(*a, **kw)
    model.generate = types.MethodType(_capped, model)
    t_load = time.time() - t0
    print("  OK | VRAM: " + str(round(torch.cuda.memory_allocated()/1e9,1)) + "GB | " + str(round(t_load,1)) + "s")

    print("\n" + "="*60)
    print("  BUOC 3: OCR " + str(len(need_ocr)) + " anh")
    print("="*60)

    def ocr_img(img_path, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        if is_tiny_label_image(img_path):
            configs = [dict(crop_mode=False, base_size=384, image_size=384)]
        else:
            try:
                w,h = Image.open(img_path).size
                small = max(w,h) <= 350
            except Exception:
                small = False
            configs = ([dict(crop_mode=False, base_size=448, image_size=448),
                        dict(crop_mode=False, base_size=512, image_size=512),
                        dict(crop_mode=False, base_size=640, image_size=640)] if small else
                       [dict(crop_mode=False, base_size=512, image_size=512),
                        dict(crop_mode=False, base_size=640, image_size=640),
                        dict(crop_mode=False, base_size=448, image_size=448)])
        for i, cfg in enumerate(configs):
            try:
                gc.collect(); torch.cuda.empty_cache()
                with torch.inference_mode():
                    model.infer(tokenizer, prompt="<image>\nFree OCR.",
                        image_file=str(img_path), output_path=str(out_dir/("a"+str(i))),
                        save_results=True, test_compress=False, **cfg)
                r = out_dir/("a"+str(i))/"result.mmd"
                t = r.read_text(encoding="utf-8").strip() if r.exists() else ""
                if i == 0 and len(t) < 10: continue
                return t
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache(); torch.cuda.synchronize()
        return ""

    t0_ocr = time.time()
    for i, (ref, path, h) in enumerate(need_ocr):
        t0 = time.time()
        print("\n  [" + str(i+1) + "/" + str(len(need_ocr)) + "] " + Path(ref).name)
        text = clean_ocr(ocr_img(path, OCR_DIR/("img_"+str(i).zfill(3))))
        ocr_cache[h] = text
        dt = time.time()-t0
        if text:
            n_success += 1
            print("       OK " + str(round(dt,1)) + "s | " + str(len(text)) + " ky tu")
        else:
            print("       [rac] " + str(round(dt,1)) + "s | bo qua")

    t_ocr = time.time() - t0_ocr
    print("\n  OCR xong | " + str(round(t_ocr,1)) + "s | " + str(n_success) + "/" + str(len(need_ocr)) + " thanh cong")
    try: del model
    except: pass
    gc.collect(); torch.cuda.empty_cache()
else:
    print("\n  Khong co anh can OCR - bo qua Buoc 2-3!")

# ================================================================
print("\n" + "="*60)
print("  BUOC 4: Ghep ket qua + Fix format")
print("="*60)

for ref in img_refs:
    if ref not in ref_to_hash:
        try: ref_to_hash[ref] = img_hash((MD_PATH.parent/ref).resolve())
        except: pass

def build_final(md_text, ref_to_hash, ocr_cache):
    def _s(m):
        ref, width = m.group(1), m.group(2) or ""
        h = ref_to_hash.get(ref, "")
        raw = ocr_cache.get(h, "").strip() if h else ""
        fmt = format_ocr_inline(raw)
        tag = "![](" + ref + ")" + width
        return tag if not fmt else tag + "\n\n> [OCR]** " + fmt + "\n"
    return re.sub(r'!\[[^\]]*\]\(([^)]+)\)(\{[^}]*\})?', _s, md_text)

final = clean_pandoc_output(build_final(md_text, ref_to_hash, ocr_cache))
FINAL_PATH.write_text(final, encoding="utf-8")
t_end = time.time()

print("\n" + "="*60)
print("  HOAN THANH!")
print("="*60)
print("\n  File ket qua : " + str(FINAL_PATH))
print("  Kich thuoc   : " + str(len(final)) + " ky tu | " + str(final.count(chr(10))) + " dong")
print("\n  THOI GIAN:")
print("     Buoc 1 : " + str(round(t_code,1)) + "s")
if need_ocr:
    print("     Buoc 2 : " + str(round(t_load,1)) + "s (load model)")
    print("     Buoc 3 : " + str(round(t_ocr,1)) + "s (OCR " + str(len(need_ocr)) + " anh)")
print("     TONG   : " + str(round(t_end-t_total,1)) + "s")
print("="*60)

print("\n" + "="*60)
print("  NOI DUNG KET QUA")
print("="*60 + "\n")
print(final)

# ---- Hien thi truc quan (anh render that trong Kaggle) ----
try:
    from IPython.display import Markdown, display
    print("\n" + "="*60)
    print("  XEM TRUC QUAN (anh render that)")
    print("="*60)
    display(Markdown(final))
except Exception as e:
    print("Khong hien thi duoc Markdown: " + str(e))

