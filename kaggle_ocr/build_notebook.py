"""Build a self-contained, private Kaggle notebook without credentials."""
import argparse
import base64
import hashlib
import io
import json
import re
from pathlib import Path
import subprocess
import textwrap
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
BASELINE = "1d70099e4070ee0995c3d15cc47312152d4559d2"
MODEL_REVISION = "aaa02f3811945a91062062994c5c4a3f4c0af2b0"


def cell(kind, source, name):
    if kind == "code" and name in {"benchmark", "export"}:
        source = "if RUN_BENCHMARK:\n" + textwrap.indent(source, "    ") + '\nelse:\n    print("Bỏ qua đề mẫu; dùng ô Đọc đề mới ở cuối notebook.")\n'
    result = {"cell_type":kind,"id":name,"metadata":{},"source":source}
    if kind == "code":
        result.update(execution_count=None,outputs=[])
    return result


def build(owner, revision=MODEL_REVISION, datasets=()):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Model revision must be a full 40-character Hugging Face model commit, not a project Git commit")
    # Keep the server runnable without installing the client package.
    (ROOT/"colab_ocr_server/ocr_validation.py").write_bytes(
        (ROOT/"src/docx_extract/ocr_validation.py").read_bytes())
    for directory in (HERE, ROOT/"colab_ocr_server"):
        (directory/"vector_fonts.py").write_bytes((ROOT/"src/docx_extract/vector_fonts.py").read_bytes())
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for folder in (ROOT/"src/docx_extract",ROOT/"colab_ocr_server"):
            for path in sorted(folder.glob("*.py")):
                if not path.name.startswith("test_"):
                    archive.write(path,path.relative_to(ROOT).as_posix())
        archive.write(ROOT/"scripts/benchmark_ocr.py","scripts/benchmark_ocr.py")
        archive.write(HERE/"notebook_upload.py", "kaggle_ocr/notebook_upload.py")
        archive.write(HERE/"notebook_preview.py", "kaggle_ocr/notebook_preview.py")
        archive.write(ROOT/"scripts/preview-template.html", "scripts/preview-template.html")
        # Store DOCX parts, then compress the whole entry with LZMA. The inner
        # DOCX stays Word-compatible; all original part bytes are unchanged.
        compact=io.BytesIO()
        with zipfile.ZipFile(ROOT/"tests/fixtures/sample.docx") as sample, zipfile.ZipFile(
                compact,"w",compression=zipfile.ZIP_STORED) as packed:
            for member in sample.infolist():
                packed.writestr(member,sample.read(member),compress_type=zipfile.ZIP_STORED)
        archive.writestr("tests/fixtures/sample.docx",compact.getvalue(),compress_type=zipfile.ZIP_LZMA)
        for name in ("mathocr","context","assemble"):
            source=subprocess.check_output(["git","show",f"{BASELINE}:src/docx_extract/{name}.py"],cwd=ROOT)
            archive.writestr(f"baseline/{name}.py",source)
        archive.writestr("baseline/revision.txt",BASELINE)
        # A PNG produced locally isolates GPU smoke testing from LibreOffice.
        from docx_extract.raster import prepare_image
        with zipfile.ZipFile(ROOT/"tests/fixtures/sample.docx") as sample:
            original=next(p for p in sample.namelist() if p.lower().endswith(".wmf"))
            png, ext=prepare_image(sample.read(original),"wmf")
            if ext!="png":
                raise RuntimeError("Build the smoke PNG on Windows before packaging")
            archive.writestr("data/smoke-formula.png",png)
    payload=buffer.getvalue()
    # Kaggle limits notebook source to 1 MB. Base85 keeps the original small
    # DOCX embedded; larger exams are attached privately as notebook inputs.
    encoded=base64.b85encode(payload).decode()
    digest=hashlib.sha256(payload).hexdigest()
    cells=[]
    cells.append(cell("markdown","""# DOCX OCR — Kaggle GPU

Giữ notebook **Private**. Bật **GPU** và **Internet**, rồi bấm **Run All**.

**Bản xem trực tiếp:** dùng code nguồn hiện tại, hiển thị đề/công thức/hình ngay trong notebook. ZIP chỉ để lưu thêm.

**Đã sửa OMML:** giữ vector, dấu gạch và mũi tên; công thức chưa hỗ trợ được giữ XML gốc và báo cần kiểm tra. Thống kê gồm cả Word Equation và MathType.

- Đọc DOCX, cache và đọc dữ liệu MathType không cần GPU. DeepSeek-OCR-2 dùng GPU CUDA.
- Chọn **Settings → Accelerator → GPU T4 ×2** (hoặc L4 nếu có), bật **Internet**.
- Bấm **Run All** lần đầu. Thêm DOCX/ZIP bằng **Input → Upload** bên phải Kaggle. Ở ô **Đọc đề mới**, bấm **Cập nhật danh sách → chọn đề → Đọc đề**. Kết quả tự hiện bên dưới; menu **Xem đề** đổi giữa các đề, không chạy OCR lại.
- Phần đo tốc độ mặc định tắt. Đặt `RUN_BENCHMARK=True` nếu muốn chạy lại đề mẫu 16 công thức; có thể bật thêm `RUN_HEAVY_BENCHMARK` và đặt `HEAVY_DOCX_PATH` để đo đề lớn.
- Chỉ GPU 0 được dùng. Hai T4 không tự gộp thành một bộ nhớ 32 GB.
- T4/P100 dùng FP16; GPU có BF16 native dùng BF16. Có warm-up và kiểm tra OCR thật trước khi benchmark.
- Tunnel HTTP là tùy chọn cho phiên tương tác, không phải dịch vụ hoạt động liên tục. Notebook batch vẫn chạy khi không có ngrok.
""","intro"))
    cells.append(cell("code",f'''import os, sys, json, time, socket, subprocess
from pathlib import Path
RUN_BENCHMARK = False
RUN_HEAVY_BENCHMARK = False
HEAVY_DOCX_PATH = ""  # Đường dẫn DOCX được gắn riêng trong /kaggle/input
ENABLE_TUNNEL = False
OCR_GPU_BATCH_SIZE = 2  # 1024px quality mode; startup verifies parity and speed.
MODEL_REVISION = {revision!r}
WORK_ROOT = Path("/kaggle/working/docx-ocr")
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ["DOCX_EXTRACT_NATIVE_MATH"] = "0"  # Keep real OCR in the measured pipeline.
os.environ["HF_HOME"] = "/tmp/docx-ocr-huggingface"
import torch
if not torch.cuda.is_available():
    raise RuntimeError("Bật Accelerator GPU trong Session options rồi chạy lại.")
capability = torch.cuda.get_device_capability(0)
print(json.dumps({{"torch":torch.__version__,"cuda":torch.version.cuda,
    "gpu":torch.cuda.get_device_name(0),"capability":capability,
    "vram_gb":round(torch.cuda.get_device_properties(0).total_memory/2**30,1),
    "dtype":"bfloat16" if capability[0]>=8 else "float16"}},indent=2))
if capability[0]<7:
    print("GPU P100: kiểm tra CUDA wheel hỗ trợ sm_60; ưu tiên T4/L4 nếu có.")
''',"gpu-preflight"))
    cells.append(cell("markdown","## Cài dependencies\nGiữ nguyên Torch/Torchvision của Kaggle. Nếu Transformers đã được import trước khi đổi phiên bản, khởi động lại session rồi chạy lại từ đầu.","deps-note"))
    cells.append(cell("code",'''packages=["fastapi","uvicorn","python-multipart","Pillow>=10.1","requests","lxml",
          "transformers==4.46.3","tokenizers==0.20.3","accelerate","einops","addict","easydict","ipywidgets>=8,<9","olefile>=0.47"]
subprocess.run([sys.executable,"-m","pip","install","-q",*packages],check=True)
apt_options=["-o","Acquire::Retries=1","-o","Acquire::http::Timeout=30",
             "-o","Acquire::https::Timeout=30","-o","DPkg::Lock::Timeout=60"]
print("Cài LibreOffice và font toán; tiến trình apt hiển thị bên dưới.",flush=True)
subprocess.run(["apt-get",*apt_options,"update"],check=True,timeout=180)
subprocess.run(["apt-get",*apt_options,"install","-y","--no-install-recommends",
                "libreoffice-core","libreoffice-impress","fonts-dejavu-core",
                "fonts-liberation2","fonts-urw-base35","fonts-opensymbol"],check=True,timeout=480)
font_config=Path.home()/".config/fontconfig/conf.d/99-docx-symbol.conf"
font_config.parent.mkdir(parents=True,exist_ok=True)
font_config.write_text('<fontconfig><alias><family>Symbol</family><prefer><family>Standard Symbols PS</family></prefer></alias></fontconfig>')
subprocess.run(["fc-cache","-f"],check=True,timeout=60)
subprocess.run(["fc-match","Symbol"],check=True,timeout=10)
print("Dependencies ready; Torch was not replaced.")
''',"install"))
    cells.append(cell("code",f'''import base64, hashlib, io, zipfile, importlib
PAYLOAD = {encoded!r}
payload=base64.b85decode(PAYLOAD)
if hashlib.sha256(payload).hexdigest()!={digest!r}:
    raise RuntimeError("Bundle integrity check failed")
SOURCE_VERSION = {digest[:12]!r}
WORK_ROOT = WORK_ROOT.parent / ("docx-ocr-" + SOURCE_VERSION)
WORK_ROOT.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(io.BytesIO(payload)) as archive:
    for member in archive.infolist():
        destination=(WORK_ROOT/member.filename).resolve()
        if not destination.is_relative_to(WORK_ROOT.resolve()):
            raise RuntimeError("Invalid bundle path")
    archive.extractall(WORK_ROOT)
for name in list(sys.modules):
    if name == "docx_extract" or name.startswith("docx_extract.") or name in {{"notebook_upload", "notebook_preview"}}:
        sys.modules.pop(name, None)
importlib.invalidate_caches()
sys.path.insert(0,str(WORK_ROOT/"src"))
sys.path.insert(0,str(WORK_ROOT/"kaggle_ocr"))
print("Code nguồn:",SOURCE_VERSION,"—",WORK_ROOT)
''',"unpack"))
    cells.append(cell("markdown","## Khởi động model, warm-up và chờ sẵn sàng\nLần đầu tải model mất thời gian riêng. Log được lưu trong output. Mô hình chỉ được nạp một lần cho phiên này.","server-note"))
    cells.append(cell("code",'''import requests
def optional_secret(name):
    try:
        from kaggle_secrets import UserSecretsClient
        return UserSecretsClient().get_secret(name)
    except Exception:
        return None
server_key=optional_secret("DOCX_OCR_API_KEY")
if server_key:
    os.environ["DOCX_EXTRACT_OCR_API_KEY"]=server_key
previous=globals().get("ocr_process")
if previous is not None and previous.poll() is None:
    previous.terminate();previous.wait(timeout=15)
with socket.socket() as listener:
    listener.bind(("127.0.0.1",0));PORT=listener.getsockname()[1]
ENDPOINT=f"http://127.0.0.1:{PORT}/ocr"
environment=os.environ.copy()
environment.update(DOCX_OCR_BACKEND="transformers",DOCX_OCR_DTYPE="auto",
                   DOCX_OCR_INFERENCE_BATCH_SIZE=str(OCR_GPU_BATCH_SIZE),
                   DOCX_OCR_ATTENTION="eager",DOCX_OCR_WARMUP="1",
                   DOCX_OCR_IMAGE_SIZE="1024",DOCX_OCR_MODEL_REVISION=MODEL_REVISION,
                   PYTHONPATH=str(WORK_ROOT/"src"))
if server_key: environment["DOCX_OCR_API_KEY"]=server_key
log_path=Path("/kaggle/working/ocr-server.log")
log_handle=log_path.open("w")
ocr_process=subprocess.Popen([sys.executable,"-m","uvicorn","ocr_server:app",
    "--host","127.0.0.1","--port",str(PORT)],cwd=WORK_ROOT/"colab_ocr_server",
    env=environment,stdout=log_handle,stderr=subprocess.STDOUT)
started=time.perf_counter()
for attempt in range(600):
    if ocr_process.poll() is not None:
        log_handle.flush()
        raise RuntimeError(log_path.read_text(errors="replace")[-7000:])
    try:
        response=requests.get(f"http://127.0.0.1:{PORT}/health",timeout=3)
        health=response.json()
        if response.ok and health.get("model_loaded") and health.get("warmed_up"):
            break
    except requests.RequestException:
        pass
    if attempt%30==0: print(f"Đang nạp model/warm-up: {time.perf_counter()-started:.0f}s",flush=True)
    time.sleep(1)
else:
    ocr_process.terminate()
    raise TimeoutError("Server chưa sẵn sàng sau 10 phút. Xem ocr-server.log.")
os.environ["DOCX_EXTRACT_OCR_ENDPOINT"]=ENDPOINT
print("Model ready:",json.dumps(health,indent=2))
print(f"Load + warm-up: {time.perf_counter()-started:.1f}s (tách khỏi benchmark)")
''',"start-server"))
    cells.append(cell("code",'''headers={"Authorization":"Bearer "+server_key} if server_key else {}
smoke_started=time.perf_counter()
with (WORK_ROOT/"data/smoke-formula.png").open("rb") as formula:
    response=requests.post(ENDPOINT,headers=headers,files={"file":("smoke.png",formula)},timeout=120)
response.raise_for_status()
smoke=response.json()
if not smoke.get("latex"):
    raise RuntimeError("GPU OCR smoke test failed: "+str(smoke))
smoke["elapsed_s"]=time.perf_counter()-smoke_started
Path("/kaggle/working/gpu-smoke.json").write_text(json.dumps(smoke,ensure_ascii=False,indent=2))
print("OCR thật trên GPU:",smoke)
''',"gpu-smoke"))
    cells.append(cell("markdown","## Đo trước/sau bằng model thật\nSo sánh client từng ảnh với client batch/cache trên cùng model đã warm-up. Tắt cache RAM server trong các lượt cold để tránh sai số. Kết quả LaTeX khác nhau được ghi để đối chiếu, không tự kết luận chính xác chỉ vì chạy nhanh hơn.","benchmark-note"))
    cells.append(cell("code",'''documents=[WORK_ROOT/"tests/fixtures/sample.docx"]
if RUN_HEAVY_BENCHMARK:
    if not HEAVY_DOCX_PATH or not Path(HEAVY_DOCX_PATH).is_file():
        raise FileNotFoundError("Gắn đề lớn bằng Input (Private), rồi đặt HEAVY_DOCX_PATH.")
    documents.append(Path(HEAVY_DOCX_PATH))
benchmark_path=Path("/kaggle/working/ocr-live-benchmark.json")
command=[sys.executable,str(WORK_ROOT/"scripts/benchmark_ocr.py"),
         *map(str,documents),"--endpoint",ENDPOINT,"--baseline",str(WORK_ROOT/"baseline"),
         "--repeat","1","--output",str(benchmark_path)]
subprocess.run(command,cwd=WORK_ROOT,env={**os.environ,"PYTHONPATH":str(WORK_ROOT/"src")},check=True,timeout=2400)
benchmark=json.loads(benchmark_path.read_text())
assert benchmark["mode"]=="live_ocr_endpoint"
for result in benchmark["documents"]:
    print({key:value for key,value in result.items() if key!="runs"})
''',"benchmark"))
    cells.append(cell("code",'''from docx_extract import clean_docx, write_outputs
markup,context=clean_docx(WORK_ROOT/"tests/fixtures/sample.docx")
write_outputs(markup,context,"/kaggle/working/ocr-result")
import shutil
shutil.make_archive("/kaggle/working/ocr-result","zip","/kaggle/working/ocr-result")
print("Kết quả: ocr-result.zip; số liệu GPU: ocr-live-benchmark.json")
''',"export"))
    cells.append(cell("markdown","## Tùy chọn: endpoint cho máy Windows\nDùng trong phiên tương tác, bật `ENABLE_TUNNEL=True`. Tạo và bật các Kaggle Secrets `NGROK_AUTHTOKEN`, `DOCX_OCR_API_KEY`; tùy chọn `NGROK_DOMAIN`. Dùng cùng API key tại biến môi trường `DOCX_EXTRACT_OCR_API_KEY` trên máy. Không in token/key vào output. Endpoint chỉ tồn tại khi session còn chạy.","tunnel-note"))
    cells.append(cell("code",'''if ENABLE_TUNNEL:
    auth=optional_secret("NGROK_AUTHTOKEN")
    if not auth or not server_key:
        raise RuntimeError("Bật Kaggle Secrets NGROK_AUTHTOKEN và DOCX_OCR_API_KEY trước khi mở tunnel.")
    import tarfile
    binary=Path("/tmp/docx-ocr-ngrok")
    if not binary.exists():
        response=requests.get("https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz",timeout=120)
        response.raise_for_status()
        with tarfile.open(fileobj=io.BytesIO(response.content),mode="r:gz") as archive:
            binary.write_bytes(archive.extractfile("ngrok").read())
        binary.chmod(0o700)
    previous=globals().get("tunnel_process")
    if previous is not None and previous.poll() is None:
        previous.terminate();previous.wait(timeout=10)
    arguments=[str(binary),"http",str(PORT),"--log","stdout","--log-format","json"]
    domain=optional_secret("NGROK_DOMAIN")
    if domain: arguments.append("--domain="+domain)
    tunnel_log=open("/tmp/docx-ocr-ngrok.log","w")
    tunnel_process=subprocess.Popen(arguments,env={**os.environ,"NGROK_AUTHTOKEN":auth},stdout=tunnel_log,stderr=subprocess.STDOUT)
    for attempt in range(30):
        if tunnel_process.poll() is not None: raise RuntimeError("Ngrok không khởi động được. Kiểm tra token/domain trong Secrets.")
        try:
            tunnels=requests.get("http://127.0.0.1:4040/api/tunnels",timeout=2).json()["tunnels"]
            public=next(t["public_url"] for t in tunnels if t["public_url"].startswith("https://"))
            check=requests.get(public+"/health",timeout=10);check.raise_for_status()
            print('PowerShell: $env:DOCX_EXTRACT_OCR_ENDPOINT = "'+public+'/ocr"')
            print("Đặt DOCX_EXTRACT_OCR_API_KEY trùng Secret DOCX_OCR_API_KEY; không chia sẻ key trong output.")
            break
        except (requests.RequestException,KeyError,StopIteration): time.sleep(1)
    else: raise TimeoutError("Không mở được tunnel. Benchmark batch vẫn có thể dùng độc lập.")
else:
    print("Tunnel đang tắt. Các phép đo GPU và file kết quả ở phần Output vẫn dùng được.")
''',"tunnel"))
    cells.append(cell("markdown","## Dừng sau khi dùng\nChạy cell dưới khi đã lấy kết quả hoặc không cần endpoint nữa. Không dùng script chống idle. Kaggle có giới hạn phiên/quota nên không coi notebook là server 24/7.","stop-note"))
    cells.append(cell("code",'''STOP_NOW = False
if STOP_NOW:
    for name in ("tunnel_process","ocr_process"):
        process=globals().get(name)
        if process is not None and process.poll() is None:
            process.terminate();process.wait(timeout=15)
    print("Đã dừng các process của notebook; có thể tắt session GPU.")
''',"stop"))
    cells.append(cell("markdown", "## Đọc và xem kết quả\nThêm DOCX/ZIP bằng **Input → Upload**, chờ tải xong. Bấm **Cập nhật danh sách**, chọn file (Ctrl/Shift hoặc Chọn tất cả), rồi **Đọc đề**. Nội dung, công thức gốc và hình tự hiện trong khung xem. Chọn **Xem đề** để đổi tài liệu. Cảnh báo hiện trong bản xem; LaTeX OCR vẫn cần đối chiếu. ZIP là tùy chọn lưu thêm. Dựng bản xem/chuyển ảnh vector có thời gian riêng, không phải inference OCR. Lần sau dùng lại giao diện, không cần Run All.", "upload-note"))
    cells.append(cell("code", '''sys.path.insert(0,str(WORK_ROOT/"kaggle_ocr"))
from notebook_upload import show_upload_ui
print("Phiên bản code đang dùng:", SOURCE_VERSION)
exam_upload = show_upload_ui(WORK_ROOT, ENDPOINT, previous=globals().get("exam_upload"))
''', "upload"))
    notebook={"nbformat":4,"nbformat_minor":5,"metadata":{"kernelspec":{"display_name":"Python 3","language":"python","name":"python3"},"language_info":{"name":"python"},"docx_ocr_source_version":digest[:12]},"cells":cells}
    target=HERE/"docx_ocr_kaggle.ipynb"
    serialized=json.dumps(notebook,ensure_ascii=False,separators=(",", ":"))
    if len(serialized.encode("utf-8"))>=1_000_000:
        raise RuntimeError("Notebook exceeds Kaggle's 1 MB source limit")
    target.write_text(serialized,encoding="utf-8",newline="\n")
    metadata={"id":f"{owner}/docx-ocr-kaggle-gpu","title":"DOCX OCR Kaggle GPU","code_file":target.name,
              "language":"python","kernel_type":"notebook","is_private":True,"enable_gpu":True,
              "enable_internet":True,"machine_shape":"NvidiaTeslaT4","dataset_sources":list(datasets),"competition_sources":[],"kernel_sources":[],"model_sources":[]}
    (HERE/"kernel-metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
    print(json.dumps({"notebook":str(target),"bytes":target.stat().st_size,"bundle_bytes":len(payload),"cells":len(cells)},ensure_ascii=True))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--owner",default="YOUR_KAGGLE_USERNAME")
    parser.add_argument("--model-revision", "--revision", dest="revision", default=MODEL_REVISION,
                        help="Full Hugging Face DeepSeek-OCR-2 commit; NOT the project's Git revision")
    parser.add_argument("--dataset", action="append", default=[])
    args=parser.parse_args()
    build(args.owner,args.revision,args.dataset)
