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

## 4. Phiên bản tối ưu: batch, cache và đo từng công đoạn

Cập nhật cả [ocr_server.py](./ocr_server.py) và [ocr_logic.py](./ocr_logic.py) trên Colab, rồi khởi động lại Uvicorn. Bản mới giữ `/ocr`, thêm `/ocr/batch` nhận tối đa 32 ảnh cùng danh sách ID. Kết quả theo ID, lỗi riêng từng ảnh, kèm thời gian chuẩn bị/chờ GPU/suy luận.

Client mới mặc định gom 8 ảnh/request, dùng lại HTTP Session, loại ảnh trùng và cache SQLite các kết quả thành công. Trên Windows, client chuyển WMF/EMF bằng GDI+ trước khi gửi để giảm số lần gọi LibreOffice phía server. Phần fallback LibreOffice cũng chuyển cả nhóm ảnh trong một lần chạy. `/health` trả fingerprint để cache tự thay đổi theo model và cấu hình.

Backend mặc định `transformers` vẫn suy luận từng ảnh. Đặt `DOCX_OCR_BACKEND=vllm` trong môi trường GPU/CUDA/vLLM tương thích để dùng GPU batch thật. Tùy chọn này cần được đo trên phần cứng thực tế; không suy ra VRAM hoặc tốc độ chỉ từ kích thước file ảnh. Không thay đổi mặc định chất lượng ảnh 1024.

**Cell lặp lại cùng một ảnh ở mục 3 sẽ dùng cache sau lần đầu.** Để đo thông lượng OCR, sử dụng các công thức khác nhau và phép đo trước/sau toàn bộ đề.

Xem [hướng dẫn chạy và benchmark](../docs/ocr-performance.md) để đo bản cũ, bản mới chưa cache và bản mới có cache. Số đo mock chỉ kiểm tra client/HTTP, không phải benchmark GPU.

## 5. Gom nhiều đề và thử batch với chính DeepSeek hiện tại

UI Kaggle gom tất cả ảnh MathType của lô DOCX trước khi OCR, loại ảnh trùng giữa các đề rồi gửi tối đa 32 ảnh/request. Luồng này bắt buộc OCR ảnh, không dùng bộ đọc MathType native. Ảnh trên Windows được chuyển song song bằng tối đa 4 worker CPU; đổi bằng `DOCX_EXTRACT_OCR_PREPARE_WORKERS=1..8`. Server cũng loại ảnh trùng và đọc cache trước khi chuyển WMF/EMF.

Server giữ mặc định suy luận từng ảnh. Để thử encoder và decoder theo lô với cùng model, đặt `DOCX_OCR_INFERENCE_BATCH_SIZE=4` trước khi khởi động Uvicorn. Cần có thêm [transformers_batch.py](./transformers_batch.py) cạnh server. Chế độ này chỉ dành cho ảnh cố định 768/1024, không crop; không thay weights, prompt hoặc dtype của model. `DOCX_OCR_BATCH_MAX_TOKENS` mặc định 8192; đầu ra thiếu EOS bị đánh dấu lỗi, không cache.

Lúc khởi động, server so đầu ra serial và batch trên ảnh thử, đo thời gian sau lượt warm-up đầu tiên. Nếu kết quả khác, chạy chậm hơn hoặc phát sinh lỗi, server tự dùng batch size 1. `/health` ghi `inference_batch_size`, `batch_verified`, `batch_validation_error`, `batch_validation_timings`. Đây là kiểm tra khởi động, chưa thay cho benchmark độ đúng và thời gian trên đề thật.

Notebook Kaggle mới đặt `OCR_GPU_BATCH_SIZE=4` để thực hiện kiểm tra trên; có thể đặt 1 để dùng hẳn đường serial. Mục tiêu 20 đề/phút chưa được xác nhận trên GPU. Xem [kết quả kiểm tra tối ưu](../docs/ocr-optimization-2026-11-17.md).
