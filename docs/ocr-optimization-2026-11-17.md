# Tối ưu OCR hiện tại — 2026-11-17

Mục tiêu là xử lý khoảng 20 đề trong 60 giây, có chạy model OCR cho ảnh công thức MathType. Giữ DeepSeek-OCR-2, prompt, độ phân giải 1024 và dtype phù hợp GPU. Không dùng số đo giữ ảnh hoặc đọc dữ liệu MathType native để tuyên bố đạt tốc độ OCR.

## Thay đổi

- [Bộ xử lý nhiều đề](../src/docx_extract/batch.py) trích tất cả đề, cấp ID riêng cho request rồi khôi phục ID của từng đề. Code đọc MathType native bị tắt riêng trong đường này, kể cả khi biến môi trường bật.
- UI dùng chung một OCR client cho lô, gom tối đa 32 ảnh/request. Khử ảnh trùng diễn ra cả giữa các đề khi chưa có cache.
- CPU chuyển ảnh song song, mặc định 4 worker, giới hạn 8. Worker không dùng chung Session/SQLite.
- Server khử ảnh trùng và kiểm tra cache theo ảnh gốc trước khi gọi LibreOffice/crop. Cache thành công vẫn có giới hạn và khóa khi dùng nhiều request; lỗi và kết quả bị cắt không được lưu.
- [Transformers batch](../colab_ocr_server/transformers_batch.py) thử gom cả encoder và decoder, dùng cùng model. Forward adapter chỉ áp dụng cho instance trong một lần generate dưới khóa GPU, luôn được phục hồi khi thành công hoặc lỗi.
- Chế độ GPU batch chỉ hoạt động sau kiểm tra khởi động khớp đầu ra serial, có EOS đầy đủ và nhanh hơn trên ảnh thử. Khi không đạt, dùng lại serial. Mặc định server vẫn là 1; notebook mới yêu cầu kiểm tra 4.
- Nếu một lô đang suy luận hết VRAM, chia đôi lô và thử lại dưới cùng khóa GPU; giữ đúng thứ tự kết quả, không cắt công thức để giảm thời gian.
- ZIP có thêm `batch-metrics.json`. UI báo số ảnh/request chung và tổng thời gian đến khi đã tạo ZIP.

## Kiểm tra giao thức trên 20 đề thật

Chọn 20 DOCX nhiều tệp media nhất trong bộ đề local. Tắt cache và chuyển ảnh trong phép kiểm tra này; dùng transport/model giả trả chuỗi hash để kiểm tra ánh xạ và số request. **Không tải model, không suy luận GPU, không đo chất lượng LaTeX hoặc tốc độ OCR.**

| Chỉ số | Kiểu gọi từng đề, 8 ảnh/request | Gom cả lô, 32 ảnh/request |
| --- | ---: | ---: |
| Lượt ảnh công thức | 762 | 762 |
| Ảnh gửi đi sau khử trùng | 755 | 582 |
| POST OCR | 100 | 19 |
| Lượt lấy cache | 0 | 0 |

Không đổi markup, bytes sidecar gốc hoặc kết quả giả theo từng ID; không dùng MathType native. Bản gom lô khử tổng cộng 180 lượt ảnh lặp. Kết quả này chỉ xác nhận logic gom lô, không thể quy đổi thành số giây GPU.

[Dữ liệu kiểm tra giao thức](./benchmarks/2026-11-17-protocol.json).

## Đo chuyển ảnh thật trên CPU Windows

Chuyển 582 ảnh khác nhau theo các nhóm 32 ảnh, không dùng cache chuyển ảnh. Mỗi cấu hình chạy 3 lượt, lấy trung vị:

| Worker CPU | Thời gian chuyển ảnh |
| --- | ---: |
| 1 | 1,647 giây |
| 2 | 1,090 giây |
| 4 | 0,894 giây |

ID, phần mở rộng đầu ra và hash bytes của từng ảnh khớp giữa cả ba cấu hình. Có 1 vector không chuyển được bằng GDI+, vẫn được giữ nguyên để server thử LibreOffice; không thay bằng PNG trắng. Đây chỉ là thời gian chuyển ảnh, không bao gồm model OCR. [Dữ liệu CPU](./benchmarks/2026-11-17-cpu-conversion.json).

Nguồn cấu trúc model dùng cho adapter: [model revision được khóa](https://huggingface.co/deepseek-ai/DeepSeek-OCR-2/blob/aaa02f3811945a91062062994c5c4a3f4c0af2b0/modeling_deepseekocr2.py), [encoder cùng revision](https://huggingface.co/deepseek-ai/DeepSeek-OCR-2/blob/aaa02f3811945a91062062994c5c4a3f4c0af2b0/deepencoderv2.py).

## Cần đo tiếp

Chưa có phiên Kaggle đăng nhập/GPU sẵn sàng cho bản mới. Cần chạy notebook mới, kiểm tra `/health`, tải ZIP 20 đề rồi ghi tổng thời gian, số lỗi, số công thức trả đủ và đối chiếu LaTeX. Thời gian nạp model và upload/download phải ghi riêng. Mục tiêu 20 đề/phút hiện chưa được xác nhận.
