# Chạy DOCX OCR trên Kaggle

GPU chỉ cần cho phần DeepSeek-OCR-2 trong cấu hình hiện tại. Bóc DOCX, cache và chuyển định dạng chạy trên CPU. Bộ đọc MathType trực tiếp đã có ở chế độ thử nghiệm nhưng **mặc định tắt**: mục tiêu người dùng là **code + model OCR thực sự chạy trong 6–7 giây cho đề mới**, không được dùng kết quả đọc native hoặc cache thay cho phép đo này.

[Notebook tự chứa](./docx_ocr_kaggle.ipynb) đã kèm code client/server, ô chọn file, ảnh PNG kiểm tra GPU và đề mẫu 16 công thức. Đọc đề mới không cần tạo Kaggle Dataset. Giữ notebook **Private** vì bundle chứa dữ liệu đề. Kaggle giới hạn mã nguồn notebook dưới 1 MB; đề mới đi qua nút chọn file hoặc Input riêng.

## Đưa đề mới vào đọc

1. Mở [notebook](https://www.kaggle.com/code/quanganh2005/docx-ocr-kaggle-gpu/edit). Lần đầu của phiên, bấm **Run All** và chờ model sẵn sàng.
2. Ở cuối notebook, ô **Đọc đề mới**, bấm **Chọn file đề**. Chọn một/nhiều DOCX hoặc một ZIP chứa DOCX từ máy.
3. Bấm **Đọc đề**. Chờ thanh tiến độ và thông báo hoàn tất.
4. Bấm **Tải kết quả ZIP**. Mỗi đề có một thư mục riêng gồm `markup.txt`, `manifest.json`, `sidecar/`; `summary.json` ghi thời gian, cache và lỗi từng đề.

Ngay dưới nút **Đọc đề** có thời gian từng file và dòng **Tổng thời gian xử lý (đọc Word + OCR + tạo ZIP)**. Tổng này gồm xử lý ở kernel và chuẩn bị ZIP; không gồm tải file từ máy lên hoặc tải/khởi động model. Mốc 6–7 giây với OCR thật hiện **chưa đạt/chưa được xác nhận**; số đo DeepSeek gần nhất của đề 130 công thức vẫn là 149,014 giây.

Đề tiếp theo dùng lại ô này; không cần sửa đường dẫn, tạo Dataset hoặc Run All lại. Cache công thức dùng chung giữa các lượt trong phiên. File ZIP kết quả cũng được ghi ở Output. Nếu session đã tắt/khởi động lại, chạy Run All trước. Mặc định **không chạy benchmark**, không xuất lại đề mẫu. File `.doc` hoặc `.rar` cần chuyển sang DOCX/ZIP trước.

Code giao diện và xử lý upload: [notebook_upload.py](./notebook_upload.py). Bộ sinh notebook đưa sẵn module này vào bundle. Các file trùng tên được giữ riêng; OCR thiếu kết quả được đánh dấu cần kiểm tra, vẫn cho tải phần dữ liệu đã xử lý.

## Chạy bằng giao diện Kaggle

Notebook trên tài khoản `quanganh2005`: [DOCX OCR Kaggle GPU](https://www.kaggle.com/code/quanganh2005/docx-ocr-kaggle-gpu/edit), chế độ **Private**. Ngày 2026-11-16 đã xác minh tài khoản, bật GPU T4 ×2 và Internet, chạy thành công model trên GPU 0 (14,6 GiB, FP16, Torch 2.11.0+cu130). Tải model và warm-up mất 79,2 giây; smoke test OCR thật mất 0,492 giây. Benchmark đề 16 công thức: 33,337 → 13,992 giây (2,38×); lượt có cache 0,0449 giây; 0 lỗi và không đổi LaTeX so với baseline. Đây là một lượt đo, server/client cùng chạy trên Kaggle, chưa gồm mạng từ Windows.

Đã tự tải và gắn [đề 130 công thức (Private)](https://www.kaggle.com/datasets/quanganh2005/docx-ocr-private-benchmark-130) vào notebook online. Bản đo tốc độ được lưu ở phiên bản #2. Bản có ô chọn file dùng để đọc đề mới; không tự chạy lại đề benchmark trong Input.

Đề 130 đo thực tế: **305,302 → 149,014 giây (2,05×)**; có cache: **0,0469 giây**. Không lỗi OCR, không đổi LaTeX so với baseline. Xem [báo cáo và số liệu gốc](../docs/ocr-benchmark-2026-11-16.md). Đã lưu notebook online phiên bản #2 và tải số liệu cùng ZIP kết quả OCR mẫu về máy; bản metadata local cũng gắn sẵn Input Private.

1. Đăng nhập [Kaggle Code](https://www.kaggle.com/code), tạo notebook và nhập file `docx_ocr_kaggle.ipynb`.
2. Chọn GPU T4 ×2 hoặc L4 nếu tài khoản được cấp; bật Internet trong Session options. Notebook chỉ dùng GPU 0, không tự gộp VRAM hai GPU.
3. Bấm Run All. Lần đầu có cài dependencies, tải model và warm-up; sau đó ô chọn đề mới xuất hiện. Mặc định bỏ qua benchmark và export đề mẫu.
4. Cell smoke test phải trả LaTeX từ một công thức trên GPU thật. Chỉ sau bước này mới chạy benchmark.
5. Nếu cần đo tốc độ lại, đặt `RUN_BENCHMARK=True` để đo đề mẫu 16 công thức. Muốn đo thêm đề 130 công thức, dùng Input Private đã gắn, đặt `HEAVY_DOCX_PATH` bằng đường dẫn trong `/kaggle/input`, rồi đặt `RUN_HEAVY_BENCHMARK=True` ở cell cấu hình. Việc đọc đề mới qua nút chọn file không cần các bước này.
6. Lấy `ocr-live-benchmark.json`, `gpu-smoke.json`, `ocr-result.zip` trong Output. Khi lưu phiên bản bằng Save & Run All, output được lưu khi job kết thúc.

Notebook kiểm tra CUDA trước khi tải model, giữ nguyên Torch/Torchvision đi kèm Kaggle, chọn FP16 cho T4/P100 và BF16 cho GPU có hỗ trợ native. Code model chính thức cố định BF16 ở bước chuẩn bị ảnh/autocast; adapter chỉ thay dtype trong phương thức `infer` của instance đang chạy, không sửa Torch toàn cục hoặc file model dùng chung. Phiên bản model được khóa ở revision `aaa02f3811945a91062062994c5c4a3f4c0af2b0`.

P100 cần CUDA wheel còn hỗ trợ kiến trúc sm_60. T4/L4 là lựa chọn ưu tiên khi có. Không cài vLLM mặc định cho bản chạy thử này; backend Transformers giữ khóa GPU, HTTP vẫn gửi theo lô.

## Nối với chương trình trên máy

Trong phiên tương tác Kaggle, tạo và bật các Secrets:

- `NGROK_AUTHTOKEN`: token ngrok.
- `DOCX_OCR_API_KEY`: API key riêng cho endpoint OCR.
- `NGROK_DOMAIN`: tùy chọn domain ngrok đã đăng ký.

Đặt `ENABLE_TUNNEL=True` rồi chạy cell tunnel sau khi server sẵn sàng. Cell chỉ in URL endpoint, không in token/API key. Dùng cùng giá trị API key tại máy Windows:

```powershell
$env:DOCX_EXTRACT_OCR_ENDPOINT = "https://domain-cua-ban.ngrok-free.app/ocr"
$env:DOCX_EXTRACT_OCR_API_KEY = "gia-tri-giong-Kaggle-Secret"
& ".\out\.venv-run\Scripts\python.exe" -m docx_extract "duong-dan-de.docx" -o out/kaggle-test
```

Nếu chỉ benchmark batch ngay trong Kaggle, không cần ngrok hoặc các Secrets này. Tunnel cần phiên tương tác còn hoạt động; phiên chạy nền đã kết thúc không tiếp tục phục vụ HTTP. Không dùng cơ chế chống idle. Tắt session GPU khi xong.

## Triển khai bằng CLI

CLI cần tài khoản Kaggle đã được xác thực. Đăng nhập trên trình duyệt ngoài không tự tạo phiên đăng nhập trong trình duyệt tích hợp hoặc CLI.

```powershell
& ".\out\.venv-run\Scripts\kaggle.exe" auth login
& ".\out\.venv-run\Scripts\python.exe" kaggle_ocr/build_notebook.py --owner TEN_KAGGLE --revision aaa02f3811945a91062062994c5c4a3f4c0af2b0
& ".\out\.venv-run\Scripts\kaggle.exe" kernels push -p kaggle_ocr --accelerator NvidiaTeslaT4
& ".\out\.venv-run\Scripts\kaggle.exe" kernels status TEN_KAGGLE/docx-ocr-kaggle-gpu
```

[Metadata CLI](./kernel-metadata.json) đặt Private, GPU và Internet. Thay owner bằng username thật qua builder trước khi push. Dùng `kernels output` để tải output sau khi job hoàn thành. Secret của notebook cần được gắn trong giao diện Kaggle nếu bật tunnel.

## Kiểm tra local và giới hạn xác nhận

Notebook được sinh từ source hiện tại bởi [builder](./build_notebook.py), có kiểm tra SHA-256 của bundle trước khi giải nén. Code cell có thể kiểm tra cú pháp và format notebook ở máy local; kết quả GPU chỉ được công nhận khi có output smoke test và benchmark từ Kaggle. Không dùng số liệu mock trước đó để khẳng định tốc độ Kaggle.

Các kiểm thử local xác nhận: lựa chọn dtype theo GPU, adapter không đổi Torch/global hoặc instance khác, warm-up/readiness, xác thực endpoint, batch/cache và toàn bộ luồng xử lý trước đó.

Nguồn: [Kaggle Notebooks](https://www.kaggle.com/docs/notebooks), [metadata notebook](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels_metadata.md), [Kaggle CLI authentication](https://github.com/Kaggle/kaggle-cli/blob/main/skills/references/auth.md), [DeepSeek-OCR-2](https://github.com/deepseek-ai/DeepSeek-OCR-2).
