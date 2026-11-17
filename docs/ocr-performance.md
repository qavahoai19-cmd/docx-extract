# Tối ưu và đo tốc độ OCR

## Mục tiêu 6–7 giây với OCR thật

Người dùng đã xác nhận thời gian phải gồm bóc Word, chuẩn bị ảnh, chạy model OCR và xuất kết quả cho đề mới. Khi đánh giá mục tiêu này, tắt cache thành công và đặt `DOCX_EXTRACT_NATIVE_MATH=0`. Bộ đọc MathType trực tiếp là tính năng thử nghiệm riêng, mặc định tắt; kết quả native không được dùng để tuyên bố đạt tốc độ OCR.

Hiện chưa xác nhận đạt 6–7 giây. Phép đo GPU thật trên T4 trước đó của đề 130 công thức: 149,014 giây, trong đó 36,615 giây chuẩn bị ảnh và 112,028 giây suy luận. Cần kiểm tra backend/model batch thực sự và độ đầy đủ của đầu ra, thay vì chỉ thay số ảnh trong một HTTP request. UI upload ghi thêm tổng thời gian gồm tạo ZIP. Khởi động model và tải file lên được ghi/đánh giá riêng.

Luồng xử lý mới: bóc DOCX và cấp ID theo thứ tự tài liệu → gom công thức MathType → loại ảnh trùng → đọc cache → chuẩn bị ảnh → gọi OCR theo lô → cập nhật LaTeX bằng ID. OMML tiếp tục được chuyển trực tiếp bằng bộ đọc hiện có.

Markup, thứ tự placeholder và sidecar gốc được giữ nguyên. Một ảnh lỗi không làm mất kết quả của các ảnh còn lại. Lỗi mạng dừng các request tiếp theo của lượt chạy, thay vì chờ timeout cho mọi công thức.

## Chạy thử

Trước tiên cập nhật hai file [ocr_server.py](../colab_ocr_server/ocr_server.py) và [ocr_logic.py](../colab_ocr_server/ocr_logic.py) lên thư mục server Colab, rồi khởi động lại tiến trình Uvicorn bằng notebook đang dùng. Cài thêm `Pillow` nếu môi trường server chưa có. Backend mặc định vẫn là Transformers.

Trong PowerShell tại thư mục dự án:

```powershell
$env:DOCX_EXTRACT_OCR_ENDPOINT = "https://domain-cua-ban.ngrok-free.app/ocr"
& ".\out\.venv-run\Scripts\python.exe" -m docx_extract "duong-dan-de.docx" -o "out/thu-ocr"
```

CLI hiển thị tiến độ, số lần lấy từ cache, số request và thời gian. Trong `manifest.json` của kết quả thử, mục `ocr` ghi:

- `parse_s`, `document_s`: thời gian bóc nội dung và toàn bộ lượt xử lý, chưa tính ghi file.
- `prepare_s`: thời gian chuẩn bị ảnh ở client.
- `http_s`: tổng thời gian chờ các POST OCR, bao gồm xử lý server; không cộng tiếp các số server vào nó.
- `server_prepare_s`, `server_queue_s`, `server_infer_s`: thời gian server trả về cho các request batch.
- `total`, `unique`, `deduplicated`, `cache_hits`, `remote_images`, `rasterized`, `failures`.
- `http_requests`: số POST OCR; không bao gồm GET health dùng để xác nhận phiên bản cache.

Server cũ vẫn nhận được ảnh riêng bằng `/ocr`; client chỉ thử batch một lần rồi tự chuyển cách gọi. Cache bền qua nhiều lượt chạy cần server mới trả `cache_namespace` qua `/health`.

## Cấu hình client

| Biến môi trường | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `DOCX_EXTRACT_OCR_BATCH_SIZE` | 8 | Số ảnh khác nhau mỗi request, tối đa 32 |
| `DOCX_EXTRACT_OCR_CACHE` | Cache người dùng, `docx-extract/ocr.sqlite3` | Đường dẫn SQLite; `off` để tắt cache bền |
| `DOCX_EXTRACT_OCR_CACHE_VERSION` | 1 | Đổi giá trị để vô hiệu hóa cache client khi cần |
| `DOCX_EXTRACT_OCR_PREPARE_IMAGES` | 1 | GDI+ chuyển WMF/EMF sang PNG trên Windows; `0` để gửi ảnh gốc |
| `DOCX_EXTRACT_OCR_RASTER_DPI` | 300 | Độ phân giải chuyển ảnh, khoảng 96–600; cạnh ảnh giới hạn 2400 px |
| `DOCX_EXTRACT_OCR_TIMEOUT` | 30 | Thời gian chờ request ảnh riêng |
| `DOCX_EXTRACT_OCR_BATCH_TIMEOUT` | Theo số ảnh, tối đa 120 giây với cấu hình mặc định | Thời gian chờ batch; có thể đặt riêng |

Cache chỉ lưu LaTeX thành công. Khóa gồm bytes ảnh gốc, định dạng, server, phạm vi khóa API, fingerprint model/prompt/tiền xử lý của server và cấu hình raster client. Không dùng hash gần giống để tránh nhầm hai công thức khác nhau. File cache lỗi/không ghi được không chặn OCR.

GDI+ không yêu cầu GPU hoặc Python package bổ sung. PNG có thể lớn hơn WMF; lợi ích chính là bỏ bước khởi chạy LibreOffice trên server. Nếu chuyển ảnh native lỗi, cho ảnh trắng hoặc client chạy trên hệ điều hành khác, server vẫn nhận ảnh gốc.

## Hai backend server

- **Transformers, mặc định:** model chạy từng công thức dưới một khóa GPU. Vẫn hưởng lợi từ kết nối dùng lại, cache, crop đúng và chuyển ảnh theo lô. HTTP batch không đồng nghĩa với GPU batch.
- **vLLM, tùy chọn:** đặt `DOCX_OCR_BACKEND=vllm` trước khi khởi động server. Cần môi trường vLLM/CUDA/GPU tương thích; chưa được benchmark trên GPU của người dùng. Backend này đưa nhiều ảnh vào một lần `LLM.generate`. `DOCX_OCR_MAX_TOKENS` mặc định 1024; kết quả chạm giới hạn token được đánh dấu lỗi và không cache, không coi công thức bị cắt là hợp lệ.

`DOCX_OCR_MODEL_REVISION` chọn revision model. `DOCX_OCR_IMAGE_SIZE` nhận 768 hoặc 1024, mặc định 1024, áp dụng cho backend Transformers. Giữ 1024 đến khi đã đối chiếu chất lượng công thức trên mẫu thật.

`DOCX_OCR_DTYPE=auto` chọn FP16 cho T4/P100, BF16 cho GPU có hỗ trợ native; `DOCX_OCR_ATTENTION=eager` dùng attention tương thích với các GPU này. `DOCX_OCR_WARMUP=1` chạy thử một công thức trước khi server nhận request. `/health` có `warmed_up` và `dtype`. Đặt `DOCX_OCR_API_KEY` trên server để yêu cầu Bearer key cho endpoint OCR; giá trị phía client là `DOCX_EXTRACT_OCR_API_KEY`.

Có [bản triển khai Kaggle](../kaggle_ocr/README.md) tự chứa code và dữ liệu thử, với kiểm tra GPU, warm-up và benchmark thật trong notebook.

Server crop đúng vùng nét chữ, ghép nền trong suốt lên nền trắng, bỏ ảnh trắng trước khi gọi model. Khi cần LibreOffice, cả nhóm ảnh vector được chuyển trong một lần chạy với profile tạm riêng. Công việc blocking chạy ngoài event loop để health và các request khác vẫn phản hồi được.

## Đo trước/sau

[Script benchmark](../scripts/benchmark_ocr.py) so sánh pipeline tại một Git revision cũ với pipeline mới. Mỗi phép đo gồm bản cũ, bản mới chưa có cache và bản mới đã có cache. Kết quả lấy trung vị, kiểm tra markup, ID và sidecar; LaTeX khác bản cũ được ghi lại để đối chiếu. Thời gian tải model không nằm trong phép đo vì server được khởi tạo trước khi nhận request.

Đo GPU thật sau khi cập nhật server:

```powershell
& ".\out\.venv-run\Scripts\python.exe" scripts/benchmark_ocr.py "duong-dan-de.docx" --baseline 1d70099e4070ee0995c3d15cc47312152d4559d2 --repeat 3 --output out/ocr-live-benchmark.json
```

Endpoint lấy từ biến môi trường. Header `X-OCR-Cache: off` tắt cache RAM server trong benchmark để tránh làm sai phép so sánh; lượt cache client vẫn được đo riêng. Sau khi commit thay đổi, cần tiếp tục truyền revision cũ bằng `--baseline`.

Đo phần client/HTTP khi chưa có server GPU:

```powershell
& ".\out\.venv-run\Scripts\python.exe" scripts/benchmark_ocr.py --mock --corpus-check --baseline 1d70099e4070ee0995c3d15cc47312152d4559d2
```

Chế độ này dùng dữ liệu đề thật và HTTP thật trên localhost, nhưng cố ý giả lập độ trễ mạng và suy luận tuần tự. **Không dùng số đo mock để khẳng định tốc độ GPU, chất lượng OCR hoặc suy ra đề 5 phút còn bao nhiêu giây.** Crop ít pixel hơn cũng không tự chứng minh model nhanh hơn khi kích thước encoder vẫn là 1024.

Cell notebook lặp lại cùng một ảnh chỉ đo đường cache sau request đầu; dùng nhiều ảnh khác nhau hoặc benchmark đầy đủ đề để đánh giá thông lượng suy luận.

## Kiểm thử

Môi trường kiểm thử đầy đủ cần `pytest`, `Pillow`, `fastapi`, `httpx` và `python-multipart`. Các kiểm thử server dùng model giả, không tải trọng số hoặc chạy GPU.

```powershell
& ".\out\.venv-run\Scripts\python.exe" -m pytest -q tests colab_ocr_server/test_ocr_logic.py
```

Các trường hợp được kiểm tra gồm: ánh xạ ID khi kết quả trả khác thứ tự; cache thành công và đổi phiên bản model; không cache lỗi; lỗi một ảnh không làm hỏng cả lô; tương thích server cũ; dừng request khi server mất kết nối; crop nền trắng/trong suốt; một lần gọi LibreOffice cho cả nhóm; health vẫn phản hồi khi GPU bận; lỗi giới hạn token không được coi là LaTeX hợp lệ.
