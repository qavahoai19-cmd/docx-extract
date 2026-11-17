# Kết quả thử tối ưu OCR — 2026-11-16

Đã triển khai gom công thức sau khi bóc DOCX, HTTP theo lô, Session dùng lại, cache SQLite có phiên bản, raster GDI+ và sửa crop ở server. Có backend vLLM tùy chọn cho GPU batch thật.

## Kết quả GPU thật trên Kaggle

Đã chạy [notebook Private](https://www.kaggle.com/code/quanganh2005/docx-ocr-kaggle-gpu/edit) trên Tesla T4 14,6 GiB, FP16, Torch 2.11.0+cu130; backend Transformers, eager attention, một GPU. Model revision `aaa02f3811945a91062062994c5c4a3f4c0af2b0`. Tải model và warm-up: 79,2 giây; tách khỏi thời gian xử lý đề. Smoke test ảnh PNG trả LaTeX sau 0,492 giây.

| Đề | Công thức | Bản cũ | Bản mới chưa cache | Đã cache | Tăng tốc chưa cache | POST cũ → mới → cache |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| sample | 16 | 33,337 s | 13,992 s | 0,0449 s | 2,38× | 16 → 2 → 0 |
| đề mẫu online cấp lớp số 3 | 130 | 305,302 s | 149,014 s | 0,0469 s | 2,05× | 130 → 17 → 0 |

Mỗi đề chạy một lượt so sánh trên cùng model đã warm-up. Tắt cache RAM server khi đo baseline/cold; lượt warm dùng cache SQLite client. Cả hai đề có **0 lỗi OCR, 0 thay đổi LaTeX** so với baseline. Benchmark cũng kiểm tra markup, thứ tự placeholder và sidecar không đổi. Điều này xác nhận tính nhất quán trước/sau, chưa xác nhận độ chính xác so với đáp án người kiểm duyệt.

Đề 130 có 130 hash ảnh khác nhau nên lượt đầu không được lợi từ khử ảnh trùng. 149,014 giây gồm 36,615 giây chuẩn bị ảnh ở server và 112,028 giây suy luận. Phần suy luận vẫn tuần tự; HTTP batch giảm chi phí chuyển ảnh và request. Trên Linux, client giữ WMF/EMF cho LibreOffice phía server; lượt đo này chưa dùng raster GDI+ Windows và chưa gồm mạng từ Windows tới Kaggle.

Số liệu gốc: [16 công thức](../out/kaggle-live/ocr-live-benchmark.json), [130 công thức](../out/kaggle-live/ocr-heavy-benchmark.json). [ZIP kết quả OCR mẫu](../out/kaggle-live/ocr-result.zip) hợp lệ, đủ LaTeX cho 16 công thức. Đề 130 đã được tải và gắn vào notebook dưới dạng [Input Private](https://www.kaggle.com/datasets/quanganh2005/docx-ocr-private-benchmark-130).

## Phép đo giả lập trước khi có GPU

**Các thời gian trong bảng dùng endpoint giả lập trên localhost, không chạy model OCR hoặc GPU. Không suy ra mức giảm của đề 5 phút từ các con số này.**

Đầu vào là đề thật. Giả lập đặt thời gian chờ mỗi POST là 15 ms và suy luận tuần tự mỗi ảnh là 3 ms. Thời gian đo còn gồm lập lịch hệ điều hành, xử lý DOCX, multipart, raster và SQLite. Cả bản cũ và mới đều giả lập suy luận tuần tự, không giả lập lợi ích GPU batch.

Baseline Git: `1d70099e4070ee0995c3d15cc47312152d4559d2`. Mỗi trường hợp chạy 3 lần, lấy trung vị. Cột request đếm POST OCR, không gồm GET health xác nhận phiên bản cache.

| Đề | Công thức | Bản cũ | Bản mới, chưa cache | Bản mới, đã cache | Tăng tốc chưa cache | POST cũ → mới → cache |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| đề mẫu online cấp lớp số 3 | 130 | 4,294 s | 1,191 s | 0,063 s | 3,60× | 130 → 17 → 0 |
| khang2 | 116 | 3,985 s | 1,037 s | 0,054 s | 3,84× | 116 → 15 → 0 |
| sample | 16 | 0,567 s | 0,195 s | 0,048 s | 2,91× | 16 → 2 → 0 |

## Kiểm tra trên dữ liệu thật

- 81 tài liệu: markup, bộ đếm placeholder và bytes sidecar giống baseline. Hai file khóa tạm của Word được bỏ qua.
- 654 ảnh MathType khác nhau được chuyển và kiểm tra bằng GDI+/Pillow trong 2,174 giây. Có 653 PNG có nội dung; 1 ảnh native ra trắng được trả về dạng vector gốc để server thử chuyển đổi. Không gửi PNG trắng.
- 66 kiểm thử đạt, gồm unit test và endpoint FastAPI với model giả.
- Lỗi crop được kiểm chứng với ảnh 1000×800 chứa nét chữ 100×50: ảnh sau crop là 140×90, tính cả lề 20 px.

## Giới hạn và bước đo GPU

- Phép đo giả lập bên trên thực hiện trước khi có endpoint thật. Kết quả DeepSeek thực tế trên Kaggle đã được bổ sung ở đầu báo cáo; chương trình Windows chưa được nối endpoint từ xa.
- Chưa kiểm chứng tốc độ, VRAM và chất lượng của backend vLLM trên GPU người dùng. Mặc định vẫn dùng Transformers tuần tự.
- Mock trả LaTeX giả để đo luồng dữ liệu, không xác nhận độ chính xác nhận dạng. Benchmark live lưu các LaTeX thay đổi so với baseline để đối chiếu.
- Crop đúng giúp ảnh đầu vào đúng vùng; không quy đổi tỷ lệ giảm pixel thành tốc độ GPU khi encoder vẫn có kích thước cấu hình cố định.
- PNG native có thể lớn hơn WMF. Lợi ích chính là giảm khởi chạy LibreOffice phía server; ảnh gốc vẫn được giữ làm sidecar.

## Chạy tiếp với server thật

1. Cập nhật [ocr_server.py](../colab_ocr_server/ocr_server.py) và [ocr_logic.py](../colab_ocr_server/ocr_logic.py) trên Colab; khởi động lại Uvicorn.
2. Đặt `DOCX_EXTRACT_OCR_ENDPOINT` thành URL `/ocr` của server đang chạy.
3. Chạy [script benchmark](../scripts/benchmark_ocr.py) với revision cũ. Header `X-OCR-Cache: off` ngăn cache RAM server làm sai số baseline; cache client được đo ở lượt riêng.

```powershell
& ".\out\.venv-run\Scripts\python.exe" scripts/benchmark_ocr.py "duong-dan-de.docx" --baseline 1d70099e4070ee0995c3d15cc47312152d4559d2 --repeat 3 --output out/ocr-live-benchmark.json
```

Xem [hướng dẫn cấu hình và đo tốc độ](./ocr-performance.md), [số liệu JSON](../out/ocr-benchmark.json) và [kiểm tra raster](../out/ocr-raster-check.json).
