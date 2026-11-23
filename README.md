# docx-extract

Bóc nội dung đề thi Word DOCX thành markup có thứ tự, kèm công thức, ảnh và thông tin nhận dạng OCR.

## Chức năng

- Giữ thứ tự đoạn văn, bảng, phương án và các dấu đáp án có trong tài liệu.
- Giữ cả ngữ liệu, dữ kiện và bảng trước câu hỏi đầu tiên; không cắt nội dung dựa trên tiêu đề PHẦN/Nhóm/Câu.
- Đọc kết quả field, nội dung lồng trong run và ký hiệu font Symbol thông dụng; giữ ký tự gốc kèm cảnh báo nếu chưa giải mã được font cũ.
- Nhận dấu đáp án tô nền ở nhãn hoặc nội dung A–D, kể cả nhãn đánh số tự động; giữ gạch chân phát âm và hỗ trợ câu “Question” trong đề tiếng Anh.
- Đọc công thức Word Equation (OMML) bằng code và chuyển sang LaTeX khi hỗ trợ.
- Bộ chuyển phân biệt mũi tên vector với dấu mũ, giữ dấu gạch trên/dưới và mũi tên phản ứng. Cấu trúc chưa hỗ trợ không xuất LaTeX thiếu ký hiệu: giữ XML gốc, ghi lỗi cụ thể và đánh dấu cần kiểm tra. Số công thức tính cả Word Equation và MathType; `ok` không chứng nhận tính đúng ngữ nghĩa của kết quả model OCR.
- Trích ảnh MathType/OLE, ảnh DrawingML/VML, nhóm hình và nội dung trong textbox, bảng lồng nhau.
- Gửi ảnh công thức MathType/OLE đến server OCR theo lô; giữ ảnh gốc khi nhận dạng lỗi.
- Cache theo nội dung ảnh và cấu hình model, kèm thời gian từng công đoạn.
- Có server Colab và notebook Kaggle dùng GPU, cùng công cụ xem kết quả offline.
- [Notebook OCR Kaggle](./kaggle_ocr/docx_ocr_kaggle.ipynb) hiển thị kết quả ngay sau khi đọc: chọn đề trong menu để xem nội dung, công thức và hình; tải ZIP là tùy chọn lưu thêm. Thêm DOCX/ZIP bằng Input → Upload rồi cập nhật danh sách trong ô đọc.
- Có chế độ `--keep-formulas`: giữ XML Word Equation và ảnh MathType gốc, không cần LaTeX hoặc model OCR.

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

### Bóc và xem đề trước khi chuyển LaTeX

```powershell
python -m docx_extract "de-thi.docx" --keep-formulas -o "out/de-thi-goc"
```

Hoặc gọi `clean_docx(path, preserve_formulas=True)` từ Python. Văn bản, bảng và placeholder vẫn được bóc theo thứ tự; công thức Word Equation được lưu thành XML OMML trong `sidecar/`, công thức MathType được lưu bằng ảnh gốc. Chế độ này không gọi bộ chuyển OMML/MTEF sang LaTeX, không gửi request OCR, kể cả khi endpoint hay biến bật MathType native đã được cấu hình. Manifest ghi `preserved: true` và `ocr.mode: preserve_formulas`; việc chưa có LaTeX ở các mục này là chủ đích, không bị tính thành lỗi OCR.

Trang xem offline có thể hiển thị Word Equation từ XML gốc, không cần LaTeX. Với ảnh vector WMF/EMF, cần chuyển sang PNG để trình duyệt hiển thị; đó là bước chuyển định dạng ảnh, không phải OCR. Bản markup văn bản chỉ chứa placeholder; cần giữ kèm manifest và sidecar để xem đủ công thức/hình. Chế độ này không suy đoán công thức đã bị mất khi copy/paste hoặc tự hiểu ngữ nghĩa của công thức. Ký hiệu Symbol thông dụng được chuyển sang Unicode; ký hiệu font cũ chưa giải mã được vẫn giữ ký tự gốc và có cảnh báo để đối chiếu. Đây là tùy chọn CLI/Python; notebook Kaggle đã import trước đó không tự thay đổi.

### Xuất đề thi để in

```powershell
python scripts/build_exam.py "de-thi.docx" -o "out/ban-in" --pdf
```

Tạo bản học sinh `de-thi.pdf` khổ A4, bản HTML có nút in và bản HTML riêng có đáp án để đối chiếu. Xuất PDF cần Chrome, Edge hoặc Chromium. Mặc định giữ toàn bộ nội dung tài liệu; với tài liệu ôn tập có phần bài tập riêng, dùng `--start-heading PRACTICE` để chọn rõ mục bắt đầu. Các dòng trống gạch chân và nhãn a–h trong câu sắp xếp được giữ trong bản in.

Điền đầu đề bằng các tùy chọn `--school`, `--title`, `--subject`, `--duration "90 phút"`, `--code`. Notebook Kaggle cũng có mục **Thông tin bản in** và xuất bản đề A4 để tải về, mở và in/lưu PDF từ trình duyệt.

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
