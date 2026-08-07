# colab_ocr_server — OCR endpoint cho docx-extract chạy trên Google Colab (T4)

Server FastAPI nhỏ, chạy trong notebook Colab, nhận ảnh công thức MathType OLE
(WMF/EMF) từ `docx_extract.mathocr`, convert sang PNG (LibreOffice headless —
Colab chạy Linux, không dùng GDI+ Windows như thiết kế ban đầu), OCR sang LaTeX
bằng DeepSeek-OCR-2, trả JSON `{"latex": "..."}`.

**Khuyến nghị: dùng notebook có sẵn `docx_extract_ocr_server.ipynb`** trong cùng thư mục
(mở trực tiếp trong Colab, chạy lần lượt từng cell) — file này thực hiện đúng các bước dưới
đây, đã đóng gói sẵn. Phần dưới đây giải thích ý nghĩa từng bước cho ai muốn tự ráp thủ công.

## 1. Cell cài đặt (chạy 1 lần / phiên Colab)

```python
!apt-get -qq update && apt-get -qq install -y libreoffice-core libreoffice-impress
# Không pin torch/torchvision — Colab đã có sẵn bản khớp với driver/CUDA của máy.
# Pin thêm torch sẽ gây xung đột (vd: torchvision requires torch==2.11.0, but you have torch 2.6.0).
!pip install -q fastapi "uvicorn[standard]" python-multipart \
    transformers==4.46.3 tokenizers==0.20.3 einops addict easydict

# Ngrok binary that (khong dung thu vien python pyngrok), + domain co dinh o buoc sau
!wget -q -O /content/ngrok-v3-stable-linux-amd64.tgz \
    https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
!tar xzf /content/ngrok-v3-stable-linux-amd64.tgz -C /content
```

> **Lưu ý:** các dòng bắt đầu bằng `!` (như `!apt-get`, `!pip`) chỉ chạy được **bên trong 1 ô (cell) của notebook Colab**, không phải lệnh PowerShell/terminal trên máy bạn.

## 2. Chạy server + ngrok tunnel ở chế độ nền, dùng domain cố định

Trước tiên đăng ký 1 domain tĩnh miễn phí tại https://dashboard.ngrok.com/domains
(free plan cho 1 domain cố định, ví dụ `ten-cua-ban.ngrok-free.app`) — nhờ đó URL
endpoint **không đổi** giữa các lần chạy lại, khác với `ngrok http 8000` không domain
(sinh URL ngẫu nhiên mỗi lần, dễ gây lỗi "gọi nhầm URL cũ đã tắt").

```python
NGROK_AUTHTOKEN = "<token của bạn>"
NGROK_DOMAIN = "ten-cua-ban.ngrok-free.app"

!/content/ngrok authtoken "$NGROK_AUTHTOKEN"

!nohup uvicorn ocr_server:app --host 0.0.0.0 --port 8000 --log-level info \
    > /content/uvicorn.log 2>&1 &
!nohup /content/ngrok http 8000 --domain="$NGROK_DOMAIN" --log stdout \
    > /content/ngrok.log 2>&1 &
```

Cả 2 tiến trình chạy nền (`&`, `nohup`) — không cần giữ cell ở trạng thái "đang chạy" mãi,
chỉ cần **runtime Colab (container) chưa bị ngắt**. Xem log khi cần:
```python
!tail -n 50 /content/uvicorn.log
!tail -n 50 /content/ngrok.log
```

Đặt biến môi trường trên máy chạy `docx-extract` (chỉ cần đặt 1 lần vì domain cố định):
```powershell
$env:DOCX_EXTRACT_OCR_ENDPOINT = "https://ten-cua-ban.ngrok-free.app/ocr"
```

## 3. Benchmark trước khi chạy hàng loạt (đo số thật trên máy/model của bạn)

```python
import time, requests
N = 20
t0 = time.time()
for _ in range(N):
    with open("sample_formula.png", "rb") as f:
        requests.post(f"{public_url}/ocr", files={"file": ("f.png", f.read())})
elapsed = time.time() - t0
print(f"{elapsed/N:.2f} giây/công thức -> ~{N/elapsed*60:.0f} công thức/phút")
```

---

## Tính toán: Colab free T4 xử lý tối ưu bao nhiêu file 1 lần?

**Câu trả lời ngắn: KHÔNG bị giới hạn bởi VRAM/batch — VRAM dư dả cho khối lượng
công thức toán (ảnh nhỏ, đã crop sẵn). Giới hạn thực sự là thời lượng phiên
Colab free (session/idle timeout), không phải "bao nhiêu file 1 lần".**

**Cơ sở tính:**

| Yếu tố | Giá trị |
|---|---|
| VRAM T4 free tier | 16GB (không đảm bảo cấp, có thể bị chia sẻ/preempt) |
| Model DeepSeek-OCR-2 | ~3–3.4B tham số, bf16 ≈ 7GB VRAM cố định |
| VRAM còn lại cho suy luận | ~8–9GB |
| Vision token/ảnh (không tile, `crop_mode=False`) | 256 token cố định (ảnh công thức đã crop sẵn, KHÔNG phải trang tài liệu đầy đủ — không cần chế độ tile 0-6×768 làm tốn thêm token) |
| Output/công thức | thường 10–100 token LaTeX (rất ngắn so với 1 trang) |
| Tổng ngữ cảnh/request | ~300–400 token — nhẹ hơn nhiều so với benchmark OCR cả trang (800–1200+ token) |

→ Với ngữ cảnh nhỏ như vậy, **1 công thức tốn rất ít VRAM** (ước tính dưới 1GB/request kể cả có dư), nên **không có rủi ro OOM dù xử lý hàng trăm/nghìn công thức tuần tự trong 1 phiên** — miễn server xử lý **tuần tự từng ảnh một** (đã khóa bằng `_gpu_lock` trong `ocr_server.py`, vì `model.infer()` không phải batch API, chạy song song nhiều request cùng lúc trên 1 GPU dễ tranh chấp bộ nhớ).

**Vậy giới hạn thực tế nằm ở đâu?**
1. **Tốc độ tuần tự:** ước tính (chưa đo thật trên workload của bạn — dùng cell benchmark ở trên để có số chính xác) khoảng **1–3 giây/công thức** trên T4 cho ảnh nhỏ + output ngắn kiểu này. Với 16 công thức MathType/đề thi → **~20–50 giây/đề thi**.
2. **Thời lượng phiên Colab free:** tối đa 12 giờ, nhưng thực tế hay bị ngắt sau ~90 phút không tương tác, và GPU T4 không đảm bảo luôn cấp được (tùy demand). Đây mới là giới hạn số lượng file xử lý được trong "1 lần" — không phải VRAM.
3. Với tốc độ ước tính trên, **1 phiên Colab free (dùng hết ~1-2 tiếng thực tế trước khi có nguy cơ bị ngắt) có thể xử lý khoảng vài nghìn công thức, tức hàng trăm file đề thi (16 công thức/file)** — thừa sức cho nhu cầu OCR MathType của một bộ đề thi.

**Khuyến nghị thực dụng:**
- Không cần thiết kế giới hạn "N file/lần" ở phía client `docx-extract` — cứ để `mathocr.image_to_latex()` gọi tuần tự cho từng `mathtype_N`, endpoint sẽ tự xử lý tuần tự an toàn.
- Chạy cell benchmark ở trên với vài chục ảnh công thức thật của bạn để biết số giây/công thức chính xác, từ đó ước lượng cả bộ đề thi xử lý hết bao lâu trước khi phiên Colab bị ngắt (nên giữ notebook active — click/tương tác định kỳ, hoặc dùng Colab Pro để tránh preemption khi cần xử lý lô lớn).
- Nếu sau này khối lượng thật sự lớn (hàng chục nghìn công thức/lần) và muốn tăng thông lượng thật (xử lý nhiều request song song), cần chuyển sang serving bằng vLLM (batch/continuous batching) — phức tạp hơn nhiều so với script Colab đơn giản này, không cần thiết cho quy mô hiện tại.
