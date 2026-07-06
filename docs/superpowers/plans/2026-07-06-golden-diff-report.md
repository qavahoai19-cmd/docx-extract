# Task 7 / 7b — Golden diff report (khớp Azota)

**Ngày:** 2026-07-06 (Task 7), cập nhật cùng ngày (Task 7b — knob restriction lifted)
**File mẫu:** `ĐỀ VẬT LÍ LẦN 3_VER 2 (2).docx`
**Oracle:** `tests/fixtures/golden_azota.txt` (237 dòng có nghĩa sau khi bỏ dòng trắng)

## Kết quả cuối cùng (Task 7b)

| Bước | Tỉ lệ khớp dòng |
|---|---|
| Task 7 (3-knob, BLOCKED) | 160/237 = 67.5% |
| 7b Fix 1 — whitespace-only bold segment (`runs.wrap`) | 163/237 = 68.8% |
| 7b Fix 2 — strip bold trên label `Câu N`/`a)`..`d)` (`answer.is_paragraph_start_label` + `runs.emit`) | **184/237 = 77.6%** |
| 7b Fix 3 — layout table flatten (`tables._is_layout_table`) | 184/237 = 77.6% (không đổi số dòng khớp tuyệt đối vì số placeholder lệch, nhưng đúng cấu trúc — xem ghi chú) |
| 7b Fix 4 — block-equation newline grouping (Category 2) | **Không áp dụng** — không tìm được bằng chứng, xem bên dưới |
| **Ngưỡng khoá lại** | `>= 0.75` (floor(0.776, 0.05)) |

**Kết luận: DONE.** Toàn bộ 19 test đều PASS, bao gồm
`test_report_line_match_ratio` (77.6% ≥ 0.75) và
`test_key_anchors_present_in_order`.

## Các thay đổi Task 7b (không còn giới hạn 3 knob)

### Fix 1 — whitespace-only bold/italic segment (`runs.py::wrap`)

Một run chỉ chứa khoảng trắng/tab nhưng có `w:b`/`w:i` từng bị bọc thành
`[!b:$ $]` — rác không có trong golden. Sửa `wrap()`: nếu `text` rỗng hoặc
chỉ chứa whitespace, trả về nguyên văn (không bọc tag), bất kể `fmt`.
Ratio: 67.5% → 68.8%.

### Fix 2 — strip bold trên label câu hỏi / ý con (`answer.py`, `runs.py::emit`)

Kiểm tra thực tế cấu trúc run (dump XML) cho thấy:
- `"Câu 1"` + `":"` là 2 run bold riêng, coalesce thành 1 segment `"Câu 1:"`
  đứng ĐẦU đoạn (bold).
- `"Câu 2."` là 1 run bold duy nhất, cũng đứng đầu đoạn.
- Các label ý con `"a)"`..`"d)"` trong file mẫu này **đã sẵn plain** (không
  bold) — nên rule cho chúng chủ yếu mang tính phòng thủ/tổng quát hoá,
  không đổi hành vi trên file mẫu.
- `"Nhóm I."`, `"PHẦN I..."`, `"[GT]"`, `"Chọn D."` xác nhận KHÔNG khớp 2
  regex mới (`Câu\s+\d+\s*[.:]` và `[a-d]\)`) nên vẫn giữ bold — đã verify
  bằng diff.

Thêm `answer.is_paragraph_start_label(text)` (match TOÀN BỘ nội dung
segment, không chỉ prefix — vì bằng chứng cho thấy label luôn là segment
độc lập, không gộp thêm nội dung câu hỏi vào cùng format). Sửa `runs.emit`:
segment đầu tiên (`idx == 0`) của đoạn, nếu khớp label, xuất plain thay vì
`wrap()`. Ratio: 68.8% → **77.6%** (đóng góp lớn nhất, đúng như dự đoán
trong nhóm 1 của báo cáo Task 7 gốc).

### Fix 3 — layout table flatten (`tables.py`)

Dump `w:tblPr/w:tblBorders` của 2 bảng trong file mẫu:
- Bảng layout (`img_43`/`img_44`, 1 dòng 2 cột, mỗi cell chỉ chứa ảnh):
  `tblBorders` với **tất cả 6 cạnh** (`top/left/bottom/right/insideH/insideV`)
  đều `w:val="none"`.
- Bảng dữ liệu thật (k / t°C / áp kế): **không có** `w:tblBorders` override
  (dùng viền mặc định của table style) → tín hiệu phân biệt rõ ràng.

Thêm `tables._is_layout_table(tbl)`: `True` khi có `tblBorders` VÀ tất cả 6
cạnh đều `none`/`nil`. `render_table` khi layout → nối nội dung cell không
rỗng bằng khoảng trắng (không bọc `[* | *]`), mỗi `w:tr` một dòng; bảng dữ
liệu vẫn dùng `[* c1 | c2 *]` như cũ. Đã verify bảng `[* 0 | 27 | 0 *]` không
đổi hành vi (anchor test vẫn pass).

Ratio đo được không đổi (vẫn 77.6%) vì số placeholder `img_43`/`img_44` lệch
so với `img_45`/`img_46` trong golden (do offset đếm còn tồn đọng — xem mục
"còn lại" bên dưới) nên dòng vẫn không khớp tuyệt đối theo string — nhưng
thay đổi này ĐÚNG về cấu trúc (không còn `[* | *]` bọc quanh 2 ảnh dàn cạnh
nhau) và là fix bắt buộc theo yêu cầu task, giữ lại.

### Fix 4 (Category 2) — GUARDED, KHÔNG ÁP DỤNG

Giả thuyết: các công thức hiển thị liên tiếp (`m:oMathPara` hoặc `m:oMath`
không có văn bản ngăn cách) trong cùng đoạn nên được tách dòng riêng.

Đã điều tra lại bằng script dump trực tiếp cây `w:p`:
- Không có đoạn nào trong file mẫu chứa ≥2 `m:oMathPara` là con trực tiếp.
- Không có đoạn nào chứa 2 `m:oMath` là con trực tiếp LIÊN TIẾP nhau (không
  có `w:r` xen giữa).
- Không có đoạn nào chứa `m:oMath` — `w:r` (chỉ whitespace) — `m:oMath`
  liên tiếp.
- Các đoạn có ≥2 phần tử `m:oMath` trực tiếp đều có text ngăn cách rõ ràng
  (vd `"A. <math> B. <math> C. <math> D. <math>"` — các marker phương án
  A/B/C/D, không phải công thức "trần trụi" liên tiếp).

Không tìm được bằng chứng cụ thể nào trong file mẫu để implement rule tách
dòng mà không đoán mò. Theo đúng guard trong hướng dẫn ("REVERT nếu không
có bằng chứng chắc chắn / không cải thiện") — **không thêm code cho
Category 2**. Để lại v2, ưu tiên so sánh với đề khác để tìm quy luật thật.

## Các thay đổi đã áp dụng (trong phạm vi 3 knob)

### 1. Bộ đếm placeholder — bỏ qua 2 đoạn "metadata" đầu file (`assemble.py`)

File mẫu có 2 đoạn mở đầu không xuất hiện trong panel Azota:
`"---NTP"` và `"Cho biết: ... hạt/mol; ...J."` (đoạn thứ hai chứa đúng 2 công
thức inline). Bằng chứng: golden bắt đầu bằng `mathtype_3` (không phải
`mathtype_1`) — nghĩa là 2 số đầu tiên (1, 2) đã bị "tiêu" bởi 2 công thức
trong 2 đoạn mở đầu này, dù chúng không hiện ra trong output.

Đã sửa `clean_docx()`: vẫn gọi `render_paragraph(child, ctx)` cho MỌI đoạn
(để bộ đếm `ctx.counter` tăng đúng), nhưng chỉ **append vào `lines`** kể từ
đoạn đầu tiên có text bắt đầu bằng `"PHẦN"` (heading section đầu tiên).
Kết quả: từ vị trí này trở đi, số thứ tự của TẤT CẢ placeholder cho tới
`mathml_43` khớp **chính xác 1:1** với golden (xem so sánh ID trong quá
trình test — 41/41 mục đầu tiên khớp tuyệt đối cả loại lẫn số).

### 2. Marker bị gộp với khoảng trắng cùng định dạng (`answer.py`)

Phát hiện: option-marker như `"B."` đôi khi có run khoảng trắng theo sau
**cùng định dạng bold** (`w:b` trên cả `"B."` và `" "`), khiến bước
`_coalesce` trong `runs.py` gộp chúng thành một segment `"B. "`. Hàm
`render_marker` cũ dùng `.strip()` nên xoá luôn dấu cách cần giữ trước nội
dung kế tiếp (vd công thức toán ngay sau marker), tạo ra
`"B.[!m:$mathml_..$]"` thay vì `"B. [!m:$mathml_..$]"`.

Sửa `answer.py`: regex marker giữ lại `trail` (khoảng trắng đuôi) và chỉ
thay phần `[A-D][.)]` bằng `"*"+letter` hoặc `letter`, nối lại `trail`
nguyên vẹn. Đây đúng là biến thể "marker fused... in a single run" mà kế
hoạch dự đoán — nhưng khi rà toàn bộ tài liệu, **không tìm thấy** trường hợp
"chữ cái + nội dung đáp án" cùng một `<w:t>` (vd `"A. nóng chảy"` một run
duy nhất) như ví dụ minh hoạ trong kế hoạch — mọi marker A–D trong file mẫu
đều là run riêng biệt. Vì vậy phần mở rộng duy nhất thực sự cần là xử lý
việc gộp với khoảng trắng nói trên.

### 3. `runs.TAB_SPACES`

Golden cho thấy Azota căn cột theo tab-stop thực của Word (số dấu cách quan
sát được dao động 4, 8, 12, 13, 20... tuỳ vị trí — không phải hằng số), nên
không có giá trị đơn lẻ nào tái tạo đúng mọi trường hợp. Vì
`tests/test_golden.py::_norm` chuẩn hoá mọi chuỗi khoảng trắng liên tiếp về
1 dấu cách trước khi so khớp, **giá trị của `TAB_SPACES` không ảnh hưởng tới
tỉ lệ khớp** đo được. Đã đổi từ `"\t"` sang 4 dấu cách (`"    "`) làm giá trị
mặc định hợp lý hơn cho `markup.txt` "thô" (không chuẩn hoá) — tài liệu hoá
rõ lý do trong comment của `runs.py`, không cố mô phỏng tab-stop chính xác
(việc đó cần model font-metric, ngoài phạm vi task).

## Trạng thái các nhóm khác biệt sau Task 7b

Nhóm 1 (bold-label), 3 (layout table), 4 (whitespace-bold rác) đã **sửa** ở
Task 7b (xem phần "Các thay đổi Task 7b" phía trên). Nhóm 2 đã điều tra lại
nhưng **không tìm được bằng chứng** để implement an toàn. Nhóm 5, 6 **vẫn
ngoài phạm vi** như kết luận gốc của Task 7. Chi tiết:

1. ~~Bold-label bị Azota strip~~ — **ĐÃ SỬA** (Fix 2, xem trên). Đóng góp lớn
   nhất vào ratio (68.8% → 77.6%).

2. **Bộ đếm placeholder lệch dần (còn tồn đọng, để lại v2).** Sau Fix 1–3,
   ảnh layout hiện đúng vị trí cấu trúc (`img_43`/`img_44` không còn bọc
   `[* | *]`) nhưng SỐ vẫn lệch so với golden (`img_45`/`img_46`) — nghĩa là
   đâu đó trước điểm này bộ đếm toàn cục đã đi lệch 1-2 đơn vị so với Azota.
   Điều tra lại giả thuyết "công thức khối liên tiếp không phân tách"
   (Category 2 gốc) bằng cách dump trực tiếp cây `w:p`:
   - Không có đoạn nào chứa ≥2 `m:oMathPara` là con trực tiếp.
   - Không có đoạn nào chứa 2 `m:oMath` liên tiếp (không có `w:r` xen giữa)
     là con trực tiếp của cùng `w:p`.
   - Không có mẫu `oMath — whitespace-run — oMath` liên tiếp.
   - Mọi đoạn có ≥2 `m:oMath` trực tiếp đều có text ngăn cách rõ ràng (marker
     phương án `"A."`, `"B."`...), không phải công thức "trần" liên tiếp.

   Không tìm được bằng chứng đủ chắc chắn → **không implement** rule tách
   dòng cho Category 2 (đúng theo guard "REVERT/không thêm nếu không chắc
   chắn"). Nguyên nhân lệch đếm thực sự vẫn chưa xác định — để lại v2, ưu
   tiên so sánh nhiều đề khác để tách quy luật chung thay vì suy diễn từ 1
   file mẫu.

3. ~~Layout table bị làm phẳng~~ — **ĐÃ SỬA** (Fix 3, xem trên).

4. ~~Whitespace-bold render rác~~ — **ĐÃ SỬA** (Fix 1, xem trên).

5. **HTML-entity hoá dấu ngoặc kép (`&quot;`) trong golden — vẫn ngoài phạm
   vi.** Ở câu 10, golden chứa literal chuỗi `&quot;` thay vì ký tự `"` thật
   — nhiều khả năng là hiện tượng phụ của cách Azota xuất panel dạng HTML
   rồi copy ra text, không phải quy tắc làm sạch theo spec (`§ Global
   Constraints` không nhắc HTML-escape). Không sửa theo đúng chỉ định của
   Task 7b (out of scope, để v2).

6. **Tab/khoảng cách thiếu ngay trong nguồn docx — vẫn ngoài phạm vi** (vd
   giữa `"Tia X."` và `"B."` ở câu 11 — không có `<w:tab/>` hay khoảng trắng
   nào giữa 2 run trong XML gốc). Sự không nhất quán của chính tác giả đề,
   không phải lỗi renderer — giữ nguyên trung thực với nguồn theo đúng
   nguyên tắc "làm sạch = whitelist". Không sửa theo đúng chỉ định của Task
   7b (out of scope, để v2).

## Giới hạn v1 được chấp nhận (theo spec §8)

- **Nhận đáp án đúng chỉ dùng tín hiệu gạch chân (tier-1).** `answer.py` v1 chỉ
  đánh `*` khi chữ cái phương án được gạch chân — đúng với file mẫu. Bốn tầng
  fallback trong spec §4.3 (đậm khác biệt → màu/highlight → suy từ "Chọn X."
  trong `[GT]`) cùng cảnh báo khi không có tín hiệu nào được **hoãn sang v2** có
  chủ đích. Hệ quả: đề đánh dấu đáp án bằng đậm/màu thay vì gạch chân sẽ không
  được gắn `*` ở v1 (không crash, chỉ thiếu dấu). Phạm vi đã chốt, không phải lỗi.

## Đề xuất cho v2

- Điều tra tiếp cơ chế "bộ đếm placeholder lệch dần" (nhóm 2) bằng cách so
  sánh với các đề khác (để tách quy luật chung, tránh overfit 1 file mẫu).
  Task 7b đã loại trừ giả thuyết "công thức khối liên tiếp không phân
  tách" (không tìm thấy mẫu OOXML tương ứng trong file này) — cần thu thập
  thêm mẫu đề để tìm giả thuyết khác.
- Xử lý `&quot;`/HTML-entity (nhóm 5) nếu xác nhận đây là hành vi ổn định
  của Azota (cần thêm mẫu để kiểm chứng, không suy diễn từ 1 câu hỏi).
- Nhóm 6 (khoảng trắng thiếu trong nguồn docx) — giữ nguyên triết lý "làm
  sạch = whitelist, không tự thêm nội dung", không có kế hoạch sửa.
- Cân nhắc tổng quát hoá `answer.is_paragraph_start_label` nếu phát hiện đề
  khác dùng biến thể khác của label câu/ý (vd `"Câu 1)"`, `"1."` không có
  chữ "Câu", ý con dạng `"A)"` viết hoa).

## Cách tái tạo

```
uv run pytest tests/test_golden.py -v -s
uv run pytest -q
```
