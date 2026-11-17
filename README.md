# docx-extract

Bóc nội dung đề thi Word DOCX thành markup có thứ tự, kèm công thức, ảnh và thông tin nhận dạng OCR.

## Chức năng

- Giữ thứ tự đoạn văn, bảng, phương án và các dấu đáp án có trong tài liệu.
- Đọc công thức Word Equation (OMML) bằng code và chuyển sang LaTeX khi hỗ trợ.
- Trích ảnh MathType/OLE, ảnh DrawingML/VML, nhóm hình và nội dung trong textbox, bảng lồng nhau.
- Gửi ảnh công thức MathType/OLE đến server OCR theo lô; giữ ảnh gốc khi nhận dạng lỗi.
- Cache theo nội dung ảnh và cấu hình model, kèm thời gian từng công đoạn.
- Có server Colab và notebook Kaggle dùng GPU, cùng công cụ xem kết quả offline.

Ảnh thường được trích và giữ nguyên; hiện chưa tự phân loại mọi ảnh thường thành công thức để OCR. Bộ đọc dữ liệu MathType gốc là tính năng thử nghiệm, mặc định tắt.

## Cài đặt và chạy

Client cần Python 3.13 trở lên. Ví dụ với PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .

# Khi cần OCR, đặt endpoint của server đã khởi động model:
$env:DOCX_EXTRACT_OCR_ENDPOINT = "https://your-server/ocr"
python -m docx_extract "de-thi.docx" -o "out/de-thi"
```

Kết quả gồm:

- `markup.txt`: nội dung đề và placeholder ảnh/công thức.
- `manifest.json`: ánh xạ asset, LaTeX, cảnh báo và số đo OCR.
- `sidecar/`: ảnh gốc và các đoạn XML công thức.

OCR cần server riêng; GPU dành cho model trên server. Client bóc Word và xử lý ảnh trên CPU. Khi endpoint chưa được cấu hình, ảnh vẫn được giữ nhưng các công thức cần OCR sẽ có cảnh báo chưa nhận dạng được.

## Server, notebook và xem kết quả

- [Server OCR Colab](./colab_ocr_server/README.md).
- [Notebook và hướng dẫn Kaggle](./kaggle_ocr/README.md).
- [Cấu hình và cách đo tốc độ](./docs/ocr-performance.md).
- [Kết quả benchmark GPU đã đo](./docs/ocr-benchmark-2026-11-16.md).
- [Công cụ tạo trang xem offline](./scripts/build_preview.py) và [mẫu giao diện](./scripts/preview-template.html).

Luồng OCR hiện tại chưa được xác nhận đạt 20 đề/phút. Server mặc định suy luận từng ảnh; notebook mới thử batch 4 và chỉ dùng khi kiểm tra khởi động khớp kết quả, nhanh hơn. UI gom ảnh cần OCR giữa nhiều đề và khử trùng trước khi gửi. Xem [bản tối ưu OCR hiện tại](./docs/ocr-optimization-2026-11-17.md); số đo giữ ảnh không được dùng làm số đo OCR.

Các thư mục kết quả, cache, môi trường Python và thông tin xác thực được bỏ qua bởi Git. Fixture trong bộ kiểm thử và notebook tự chứa vẫn được lưu cùng mã nguồn.

## Kiểm thử

```powershell
python -m pip install pytest Pillow fastapi httpx python-multipart numpy
python -m pytest -q tests colab_ocr_server/test_ocr_logic.py
```

Các kiểm thử server dùng model giả để kiểm tra giao thức và xử lý lỗi; không phải phép đo chất lượng hoặc tốc độ OCR thật.
