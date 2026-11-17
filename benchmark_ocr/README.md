# Notebook so sánh OCR riêng

Mở [docx_ocr_benchmark.ipynb](./docx_ocr_benchmark.ipynb) bằng **Kaggle → Code → New Notebook → File → Import Notebook**. Giữ Private, bật GPU và Internet, rồi **Run All**. Khi model sẵn sàng, chọn DOCX/ZIP và bấm **Chạy cả hai và so sánh**. Hai nút chạy riêng dùng để kiểm tra từng bản; chỉ nút chạy cả hai tạo kết luận so sánh.

- Đo nhanh: mỗi bản một lượt. Đo kỹ: mỗi bản ba lượt, đổi thứ tự ở lượt giữa và lấy trung vị.
- Cả hai phía luôn tắt cache **kết quả OCR**. Model và trọng số được nạp sẵn, warm-up cả hai đường xử lý trước phép đo. Khử ảnh trùng trong lô của bản mới vẫn được giữ.
- Đồng hồ từng bản gồm bóc Word, chuẩn bị ảnh, OCR thật, ghi kết quả và ZIP. Không gồm upload, nạp model, khởi động worker hoặc đóng gói báo cáo. Không cộng thời gian chạy cũ.
- Bản cũ là toàn bộ package client/parser và server convert/crop/infer ở Git `1d70099e4070ee0995c3d15cc47312152d4559d2`. **Ngoại lệ có chủ đích:** adapter thay loader cũ bằng loader chung đã khóa model revision, cùng dtype/attention/GPU lock, để chạy trên T4. Không phải khôi phục nguyên môi trường lịch sử; không nên so trực tiếp với số đo cũ trên máy khác.
- Bản mới là snapshot nguồn khi build. Báo cáo ghi Git revision và SHA-256 từng file để nhận diện cả thay đổi chưa commit.
- Hai bên chạy riêng tiến trình client, cùng server/model, không chiếm hai bản model trong VRAM. Bản mới kiểm tra GPU batch lúc khởi động và có thể tự về serial; giá trị thực tế nằm trong bảng health/báo cáo.
- Đối chiếu theo từng đề: hash đầu vào, markup, số lượng/loại/nguồn/hash asset và LaTeX theo ảnh tương ứng. Nếu lỗi hoặc khác biệt, tỉ lệ tốc độ chỉ mang tính tham khảo. Không dùng số công thức hoặc chuỗi LaTeX giống nhau để chứng minh OCR chính xác; lỗi chung của cả hai bản vẫn có thể tồn tại. Không so sánh được bố cục hiển thị hoàn chỉnh.
- ZIP tải về có báo cáo JSON, log worker và ZIP kết quả từng lượt. Không kèm Word gốc. Thời gian chuyển/crop và OCR tại server là các thành phần nằm trong tổng, không cộng lại vào tổng.
- Đây là bộ đo; không tự xác nhận mục tiêu 20 đề/phút. Thời gian còn phụ thuộc số ảnh công thức thực tế và độ phức tạp đầu ra.

## Build lại khi thay code tối ưu

Tại thư mục gốc repository, dùng Python của project:

```powershell
& '.\out\.venv-run\Scripts\python.exe' -X utf8 benchmark_ocr/build_notebook.py
```

Build không tải model, không cần GPU hoặc tài khoản Kaggle. Code hai bản được nhúng trong notebook, không phải clone repo private lúc chạy. Notebook không chứa đề thi, token hoặc kết quả chạy. Sau khi build lại, import lại notebook để dùng nguồn mới.

## Kiểm tra local

```powershell
& '.\out\.venv-run\Scripts\python.exe' -X utf8 -m pytest -q benchmark_ocr/test_benchmark.py
```

Kiểm tra HTTP/ánh xạ/cache/report ở local dùng server giả lập, **không phải số đo DeepSeek/GPU**. Để có tốc độ thật, chạy notebook trên GPU Kaggle và tải báo cáo.

## Xóa sau khi dùng

Toàn bộ công cụ và test mới nằm trong thư mục này. Xóa `benchmark_ocr/` và notebook tương ứng trên Kaggle khi không cần; không phải sửa code production hay notebook đọc đề chính. Bản cũ có thể lấy lại từ lịch sử Git. Giữ ZIP báo cáo nếu cần đối chứng.
