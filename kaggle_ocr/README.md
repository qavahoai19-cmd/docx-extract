# Chạy DOCX OCR trên Kaggle

## Notebook xem câu hỏi, không cần OCR

[docx_questions_kaggle.ipynb](./docx_questions_kaggle.ipynb) là notebook riêng cho chế độ giữ công thức gốc: Accelerator **None (CPU)**, bật Internet lần đầu rồi **Run All**. Đề mẫu đầu tiên tự hiển thị; menu **Đề mẫu → Chạy đề mẫu** cho phép chọn đề tiếng Anh tô vàng hoặc đề Toán. Chọn DOCX/ZIP khác và bấm **Bóc câu hỏi** để xem ngay dưới giao diện. Nội dung gồm câu hỏi, phương án, công thức và hình.

Mặc định hiển thị **Đề thi A4**, ẩn dấu đáp án. Mở **Thông tin bản in** trước khi bóc để điền trường/đơn vị, tên kỳ thi, môn, thời gian và mã đề. Bản in có thông tin thí sinh, ngữ liệu, câu hỏi và dòng HẾT; không tự thêm tên cơ quan hay thời gian thi nếu chưa được nhập. Bấm **Tải bản đề thi A4**, mở HTML đã tải rồi **In / lưu PDF**. ZIP có `de-thi.html` cho học sinh và `de-thi-co-dap-an.html` để đối chiếu. Chế độ **Xem câu hỏi** vẫn có sẵn.

Chỉ điền **Bắt đầu từ** khi muốn bỏ phần ôn tập trước một mục xác định. Mặc định toàn bộ nội dung nguồn được giữ. Đề mẫu tiếng Anh đóng gói sẵn được chọn rõ từ mục PRACTICE; việc chọn này không áp dụng cho file tải lên. Dữ liệu gốc vẫn nằm trong markup và sidecar. Notebook này vẫn nhận DOCX/ZIP, chưa nhận ảnh chụp để OCR toàn trang.

Word Equation hiển thị từ XML OMML gốc. MathType giữ ảnh gốc và chỉ chuyển WMF/EMF sang PNG để xem, không OCR hay sinh LaTeX. ZIP kết quả có `questions.html`, markup, manifest và sidecar. Nếu chuyển ảnh lỗi, giao diện báo và vẫn giữ dữ liệu gốc. Giữ notebook Private vì có đề mẫu/đề tải lên. Bản xem không bảo đảm khôi phục mọi bố cục hoặc nhận đủ ký hiệu phông cũ; chế độ này không dùng để tuyên bố tốc độ OCR.

Với bảng LMS, bản xem đọc riêng loại câu và cột đáp án: câu lựa chọn A–D, nhiều lựa chọn, các ý Đúng/Sai thuộc câu dẫn, và đáp án điền khuyết. Nhãn A–D là danh sách `upperLetter` được đánh số trực tiếp trong Word được giữ trong chế độ này. Dữ liệu cấu trúc nằm ở `questions.json`; `questions-answers.html` là bản có đáp án, `questions.html` là bản câu hỏi. Ô **Hiện đáp án đúng trong file** đổi giữa hai cách xem. Khi cột Đáp án đúng và dấu `*` không khớp, giao diện báo mâu thuẫn; câu thiếu dữ liệu được báo để kiểm tra, không tự giải hoặc đoán đáp án. Các dạng kéo thả/tự luận chỉ giữ nội dung và khóa đáp án nguồn, chưa kiểm định ngữ nghĩa chấm bài.

Build lại với Python của project: `python kaggle_ocr/build_preserve_notebook.py --sample "duong-dan-de.docx"`. Có thể lặp `--sample` để đóng gói nhiều đề mẫu. Bản đã import trên Kaggle không tự cập nhật khi sửa nguồn hoặc push GitHub.

Nếu phiên cũ báo `spec not found for the module 'docx_extract.numbering'`, import lại notebook mới rồi **Run All**. Bộ nạp mới giải nén mỗi bundle vào thư mục phiên bản riêng và nhập lại cả package của bộ đọc, tránh dùng `__path__` hoặc bytecode từ lần chạy trước. Mã phiên bản hiện ở ô cuối để đối chiếu.

Bộ đọc giữ toàn bộ phần đầu tài liệu, gồm ngữ liệu đọc hiểu, dòng “Cho biết…” và bảng dữ kiện trước câu 1. Kết quả field và các ký hiệu Symbol như →, Ω, Δ, √ cũng được giữ. Sau khi thay notebook, cần import bản mới và chạy lại để nhận bản sửa; các file kết quả đã xuất trước đó không tự cập nhật.

Dấu gạch chân đánh dấu đáp án được đọc cả khi chữ A–D và dấu chấm nằm ở các run khác nhau; không suy ra đáp án từ chữ in đậm. Bảng LMS được đọc theo hàng đầy đủ dù ô có xuống dòng hoặc bảng lồng; hỗ trợ cả tên cột “Đáp án” và “Đáp án đúng”. Công thức dài cuộn ngang trong khung riêng để không đẩy chữ ra ngoài bản xem. Ô cuối notebook hiện mã phiên bản bộ đọc và kiểm tra bundle, tránh chạy nhầm nguồn còn lưu từ phiên cũ.

Với đề tô nền, bộ đọc nhận highlight hoặc shading trên nhãn A–D hay phần nội dung phương án; không dùng màu chữ xanh của nhãn để suy ra đáp án. Gạch chân trong từ ở bài phát âm được giữ trong bản xem và không tự đánh dấu đúng. Câu mang nhãn “Question” được tách cả khi nằm trong bảng bốn cột hoặc nhiều câu chung một đoạn Word. ZIP có dữ liệu câu và dấu đáp án ở `questions.json` cho cả đề thông thường. Khi có cột đáp án LMS, cột này vẫn được đối chiếu với dấu định dạng và báo nếu mâu thuẫn.

## Notebook chạy model OCR

GPU chỉ cần cho phần **DeepSeek-OCR-2**. Đây là model duy nhất được hỗ trợ trong luồng đọc đề; pipeline DeepSeek-OCR cũ đã loại bỏ để tránh dùng nhầm model chưa được benchmark. Bóc DOCX, cache và chuyển định dạng chạy trên CPU. Bộ đọc MathType trực tiếp đã có ở chế độ thử nghiệm nhưng **mặc định tắt**: mục tiêu người dùng là **code + model OCR thực sự chạy trong 6–7 giây cho đề mới**, không được dùng kết quả đọc native hoặc cache thay cho phép đo này.

[Notebook tự chứa](./docx_ocr_kaggle.ipynb) đã kèm code client/server, ô chọn đề trong Kaggle Input, ảnh PNG kiểm tra GPU và đề mẫu 16 công thức. Bạn cũng có thể tải đề trực tiếp từ máy. Giữ notebook **Private** vì bundle chứa dữ liệu đề. Kaggle giới hạn mã nguồn notebook dưới 1 MB.

## Đưa đề mới vào đọc

1. Mở [notebook](https://www.kaggle.com/code/quanganh2005/docx-ocr-kaggle-gpu/edit). Lần đầu của phiên, bấm **Run All** và chờ model sẵn sàng.
2. Tải DOCX/ZIP bằng **Input → Upload** ở cột phải Kaggle. Trong ô **Đọc đề mới**, bấm **Cập nhật danh sách**, chọn file (Ctrl/Shift hoặc **Chọn tất cả**).
3. Bấm **Đọc đề**. Chờ thanh tiến độ và thông báo hoàn tất.
4. Kết quả tự hiện ngay trong khung **Kết quả đọc đề**. Chọn **Xem đề** để đổi tài liệu; không chạy lại model và không cần tải ZIP. Word Equation hiển thị từ XML gốc, MathType/hình giữ ảnh để đối chiếu; ảnh WMF/EMF chuyển sang PNG chỉ để xem. Cảnh báo dựng ảnh được hiện rõ.

Mở **Lưu kết quả ZIP (tùy chọn)** khi cần lưu markup, manifest, sidecar và số liệu. Khung xem nằm riêng ngoài vùng log của callback. Thời gian dựng bản xem/chuyển ảnh là bước riêng sau đọc Word + OCR + tạo ZIP. Bản xem không sửa LaTeX OCR hay bảo đảm nội dung/đáp án hoàn toàn đúng.

Nhãn A/B/C/D do Word tự đánh số được giữ cả trong luồng OCR; đáp án tô màu vẫn được đánh dấu `*`. Bật **Đọc lại không dùng cache** trước khi bấm **Đọc đề** để bỏ qua cả cache SQLite của client và cache RAM trên server. Bình thường cache vẫn hoạt động. Bản mới đổi khóa cache để không dùng lại kết quả từ trước khi có kiểm tra cấu trúc. Kết quả có lỗi server, thiếu ngoặc hoặc phân số/căn thiếu đối số được báo cần kiểm tra và giữ ảnh gốc, không lưu cache. Kiểm tra này không phát hiện được mọi lỗi nhận dạng có LaTeX hợp lệ, chẳng hạn đảo dấu `≤` thành `≥`.

Bản sửa OMML phân biệt vector/dấu mũ, giữ dấu gạch trên/dưới, mũi tên phản ứng và ngoặc vô hình; hỗ trợ hệ phương trình, ma trận và nhiều dòng. Cấu trúc chưa hỗ trợ giữ XML, ghi `error`/`review_required` trong manifest và đưa tài liệu sang `needs_review`. Thống kê `total` gồm Word Equation và MathType; `ocr_total` là số công thức thực sự thuộc luồng OCR. Không coi LaTeX khác rỗng là bằng chứng model đọc đúng ngữ nghĩa.

Notebook được sinh từ code hiện có trong project, kèm bộ xem hiện tại; ô giải nén và giao diện in **mã phiên bản nguồn**. Mỗi bundle dùng thư mục nguồn riêng và nhập lại package, tránh module cũ trong kernel. Chỉ import lại file notebook đã sinh mới cập nhật code trên Kaggle; bản đã import không tự theo GitHub.

Ngay dưới nút **Đọc đề** có kết quả từng file, số ảnh/request OCR chung của lô và dòng **Tổng thời gian xử lý (đọc Word + OCR + tạo ZIP)**. Tổng này gồm xử lý ở kernel và chuẩn bị ZIP; không gồm tải file từ máy lên hoặc tải/khởi động model. Mốc 6–7 giây với OCR thật và mục tiêu 20 đề/phút hiện **chưa được xác nhận**; số đo GPU DeepSeek gần nhất của đề 130 công thức vẫn là 149,014 giây.

Bản mới gom ảnh của cả lô trước khi OCR, nên loại ảnh trùng giữa các đề ngay cả khi tắt cache. `batch-metrics.json` trong ZIP ghi số ảnh khác nhau, lượt cache, request và thời gian OCR của cả lô. Số liệu mỗi đề có `timing_scope=shared_batch`, không cộng số giây OCR chung nhiều lần. Bộ giải mã MathType MTEF vẫn tắt; riêng số WMF đơn giản, cùng cỡ chữ và cùng dòng được đọc trực tiếp, ghi `method=wmf-number` và thống kê `wmf_direct`. Phân số, chỉ số và cấu trúc phức tạp vẫn qua OCR.

Cell cấu hình dùng ảnh 1024 và batch 2 để ưu tiên chất lượng, có thể tăng thời gian và bộ nhớ GPU so với ảnh 768. Server thử encoder/decoder theo lô với cùng model, so đầu ra và thời gian với serial trước khi phục vụ đề. Chỉ giữ chế độ batch khi phép kiểm tra thành công và nhanh hơn; nếu không sẽ dùng lại batch size 1. Xem `batch_verified`, `inference_batch_size`, `batch_validation_timings` trong dòng **Model ready**. Chưa có phép đo GPU cho cấu hình chất lượng mới.

Trước khi dựng ảnh, bộ xử lý sửa font Euclid và charset Symbol đã xác minh để tránh đổi ∞ thành ¥. Ký hiệu ℝ độc lập của Euclid Extra được dựng bằng font Unicode; mã Euclid Extra chưa hỗ trợ được báo lỗi để kiểm tra, vẫn giữ vector gốc. Notebook cài thêm các font thay thế và xuất ảnh LibreOffice ở chiều rộng 1600. Các thay đổi này xử lý lỗi ảnh đầu vào, không bảo đảm model đọc đúng mọi công thức.

ZIP lưu thêm ảnh `*.ocr-input.png` trong sidecar khi server thực sự chuẩn bị ảnh để suy luận; manifest ghi `ocr_input` và cấu hình. Đây là PNG gửi vào hàm inference, trước bước xử lý tensor của model. Công thức lấy từ cache hoặc đọc số trực tiếp không có ảnh này. Khóa cache đã đổi cho phiên bản tiền xử lý mới để tránh dùng kết quả cũ. Để đối chiếu chất lượng, import lại notebook mới, khởi động phiên rồi đọc một vài đề với **Đọc lại không dùng cache**.

Đề tiếp theo chỉ cần chọn file khác trong danh sách rồi bấm **Đọc đề**; không cần sửa đường dẫn hoặc Run All lại. Cache công thức dùng chung giữa các lượt trong phiên. File ZIP kết quả cũng được ghi ở Output. Nếu session đã tắt/khởi động lại, chạy Run All trước. Mặc định **không chạy benchmark**, không xuất lại đề mẫu. File `.doc` hoặc `.rar` cần chuyển sang DOCX/ZIP trước.

Code giao diện và xử lý upload: [notebook_upload.py](./notebook_upload.py). Bộ sinh notebook đưa sẵn module này vào bundle. Các file trùng tên được giữ riêng; OCR thiếu kết quả được đánh dấu cần kiểm tra, vẫn cho tải phần dữ liệu đã xử lý.

## Chạy bằng giao diện Kaggle

Notebook trên tài khoản `quanganh2005`: [DOCX OCR Kaggle GPU](https://www.kaggle.com/code/quanganh2005/docx-ocr-kaggle-gpu/edit), chế độ **Private**. Ngày 2026-11-16 đã xác minh tài khoản, bật GPU T4 ×2 và Internet, chạy thành công **DeepSeek-OCR-2** trên GPU 0 (14,6 GiB, FP16, Torch 2.11.0+cu130). Tải model và warm-up mất 79,2 giây; smoke test OCR thật mất 0,492 giây. Benchmark đề 16 công thức: 33,337 → 13,992 giây (2,38×); lượt có cache 0,0449 giây; 0 lỗi và không đổi LaTeX so với baseline. Đây là một lượt đo, server/client cùng chạy trên Kaggle, chưa gồm mạng từ Windows.

Đã tự tải và gắn [đề 130 công thức (Private)](https://www.kaggle.com/datasets/quanganh2005/docx-ocr-private-benchmark-130) vào notebook online. Bản đo tốc độ được lưu ở phiên bản #2. Bản có ô chọn file dùng để đọc đề mới; không tự chạy lại đề benchmark trong Input.

Đề 130 đo thực tế: **305,302 → 149,014 giây (2,05×)**; có cache: **0,0469 giây**. Không lỗi OCR, không đổi LaTeX so với baseline. Xem [báo cáo và số liệu gốc](../docs/ocr-benchmark-2026-11-16.md). Đã lưu notebook online phiên bản #2 và tải số liệu cùng ZIP kết quả OCR mẫu về máy; bản metadata local cũng gắn sẵn Input Private.

1. Đăng nhập [Kaggle Code](https://www.kaggle.com/code), tạo notebook và nhập file `docx_ocr_kaggle.ipynb`.
2. Chọn GPU T4 ×2 hoặc L4 nếu tài khoản được cấp; bật Internet trong Session options. Notebook chỉ dùng GPU 0, không tự gộp VRAM hai GPU.
3. Bấm Run All. Lần đầu có cài dependencies, tải model và warm-up; sau đó ô chọn đề mới xuất hiện. Mặc định bỏ qua benchmark và export đề mẫu.
4. Cell smoke test phải trả LaTeX từ một công thức trên GPU thật. Chỉ sau bước này mới chạy benchmark.
5. Nếu cần đo tốc độ lại, đặt `RUN_BENCHMARK=True` để đo đề mẫu 16 công thức. Muốn đo thêm đề 130 công thức, dùng Input Private đã gắn, đặt `HEAVY_DOCX_PATH` bằng đường dẫn trong `/kaggle/input`, rồi đặt `RUN_HEAVY_BENCHMARK=True` ở cell cấu hình. Việc đọc đề mới qua nút chọn file không cần các bước này.
6. Lấy `ocr-live-benchmark.json`, `gpu-smoke.json`, `ocr-result.zip` trong Output. Khi lưu phiên bản bằng Save & Run All, output được lưu khi job kết thúc.

Notebook kiểm tra CUDA trước khi tải model, giữ nguyên Torch/Torchvision đi kèm Kaggle, chọn FP16 cho T4/P100 và BF16 cho GPU có hỗ trợ native. Code model chính thức cố định BF16 ở bước chuẩn bị ảnh/autocast; adapter chỉ thay dtype trong phương thức `infer` của instance đang chạy, không sửa Torch toàn cục hoặc file model dùng chung. Phiên bản model được khóa ở revision `aaa02f3811945a91062062994c5c4a3f4c0af2b0`.

P100 cần CUDA wheel còn hỗ trợ kiến trúc sm_60. T4/L4 là lựa chọn ưu tiên khi có. Không cài vLLM mặc định; backend Transformers giữ khóa GPU và chỉ bật suy luận batch sau kiểm tra khởi động.

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
