# Task 7 — Golden diff report (khớp Azota)

**Ngày:** 2026-07-06
**File mẫu:** `ĐỀ VẬT LÍ LẦN 3_VER 2 (2).docx`
**Oracle:** `tests/fixtures/golden_azota.txt` (237 dòng có nghĩa sau khi bỏ dòng trắng)

## Kết quả

| | Tỉ lệ khớp dòng (`test_report_line_match_ratio`) |
|---|---|
| Trước khi tinh chỉnh | 159/237 = **67.1%** |
| Sau khi tinh chỉnh   | 160/237 = **67.5%** |
| Ngưỡng yêu cầu       | 70.0% |

**Kết luận: BLOCKED.** Sau khi tinh chỉnh hết mức trong phạm vi 3 knob được phép
(`runs.TAB_SPACES`, bộ đếm placeholder trong `context.py`/`assemble.py`, và
strip option-marker trong `answer.py`), tỉ lệ khớp chỉ nhích từ 67.1% lên
67.5% — chưa đạt 70%. Ngưỡng `>= 0.70` trong `tests/test_golden.py` được
**giữ nguyên như plan yêu cầu** (không hạ thấp), nên
`test_report_line_match_ratio` hiện đang **FAIL** một cách có chủ đích (đúng
theo hướng dẫn "STOP and report BLOCKED rather than gaming the metric").
18/19 test khác (bao gồm `test_key_anchors_present_in_order`) đều PASS.

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

## Các nhóm khác biệt còn lại (không sửa — ngoài phạm vi 3 knob)

Phân tích 77 dòng golden còn thiếu sau khi áp dụng 3 thay đổi trên:

1. **Bold-label bị Azota strip nhưng không phải option-marker A–D (~30 dòng,
   nhóm lớn nhất).** Ký hiệu số câu `"Câu 1:"`, `"Câu 2."`... và ký hiệu ý
   `"a)"`, `"b)"`, `"c)"`, `"d)"` đều được tô đậm (`w:b`) trong docx, nhưng
   Azota xuất chúng dạng plain (không `[!b:]`) — trong khi `"Nhóm I."`,
   `"Nhóm II."`, `"PHẦN I."` thì **vẫn giữ bold**. Đây là một quy tắc
   whitelist khác (strip bold cho label câu/ý nhưng giữ cho label nhóm/phần),
   nằm ngoài 3 knob được phép chỉnh (`answer.py` chỉ được mở rộng cho option
   marker A–D theo đúng mô tả kế hoạch). Đã xác minh không có bằng chứng nào
   trong kế hoạch cho phép mở rộng `is_option_marker` sang `"Câu N"`/`"a)"`
   — để lại cho v2.

2. **Bộ đếm placeholder lệch thêm ở gần vị trí "44" và "60" (~38 dòng bị
   ảnh hưởng theo).** Sau khi sửa offset đầu file, 41 placeholder đầu tiên
   khớp tuyệt đối. Từ đó trở đi lệch thêm dần đúng như kế hoạch mô tả
   ("skip 44", "skip 60"). Đã điều tra sâu: không tìm thấy phần tử OOXML
   nào (oMath/drawing/object/AlternateContent) bị bỏ sót gần các mốc này.
   Bằng chứng thu thập được cho thấy nguyên nhân có thể nằm ở cách Azota xử
   lý các công thức **liên tiếp không có văn bản ngăn cách** trong cùng một
   đoạn (ví dụ `mathml_35`/`mathml_36` đứng cạnh nhau) — golden đặt mỗi công
   thức đó trên **một dòng riêng**, còn renderer hiện tại nối chúng trên
   cùng một dòng (vì cả hai đều là con trực tiếp của cùng `w:p`, không có
   `w:br` phân tách). Điều này gợi ý Azota có thể tách dòng theo từng
   `m:oMath`/`m:oMathPara` hiển thị dạng khối, một hành vi thuộc về
   `runs.py` (dựng đoạn văn) chứ không phải bộ đếm `context.py` — nằm ngoài
   phạm vi 3 knob. Không tìm được bằng chứng đủ chắc chắn để khẳng định
   chính xác vật thể nào bị "đếm nhưng không hiện" tại 44/60, nên **không
   thêm bất kỳ skip cứng nào** (tránh đoán mò theo đúng yêu cầu).

3. **Bảng chỉ dùng để dàn ảnh (layout table) bị Azota "làm phẳng".** Đoạn
   `img_45`/`img_46` nằm trong một `w:tbl` 1 dòng 2 cột, nhưng golden xuất
   ra `"[img:$img_45$]      [img:$img_46$]"` — KHÔNG bọc `[* | *]` như một
   bảng dữ liệu thật. `tables.py` hiện áp dụng `[* | *]` cho mọi `w:tbl` vô
   điều kiện. Sửa đúng cần thêm logic phân biệt "bảng layout" (toàn ảnh,
   không viền/border none) — nằm trong `tables.py`, không phải 1 trong 3
   knob được phép.

4. **Segment khoảng trắng/tab bọc bold render thành tag rác
   (`"[!b:$ $]"`, `"[!b:$\t$]"`).** Khi một run chỉ chứa khoảng trắng/tab
   nhưng có định dạng bold, `wrap()` trong `runs.py` vẫn bọc nó thành
   `[!b:$...$]` dù nội dung chỉ là whitespace — Azota rõ ràng bỏ qua định
   dạng cho các đoạn thuần khoảng trắng. Phát hiện ở ~5 dòng (vd dòng chứa
   `mathml_18`, đoạn "Do... khả năng đâm xuyên..."). Sửa đúng cần thêm điều
   kiện trong `wrap()`/`emit()` của `runs.py` (không phải `answer.py`) —
   nằm ngoài 3 knob.

5. **HTML-entity hoá dấu ngoặc kép (`&quot;`) trong golden.** Ở câu 10, golden
   chứa literal chuỗi `&quot;` thay vì ký tự `"` thật — nhiều khả năng là
   một hiện tượng phụ của cách Azota xuất panel dạng HTML rồi copy ra text,
   không phải quy tắc làm sạch theo spec (`§ Global Constraints` không nhắc
   HTML-escape). Không sửa vì spec không yêu cầu mô phỏng hiện tượng export
   này của Azota.

6. **Tab/khoảng cách thiếu ngay trong nguồn docx** (vd giữa `"Tia X."` và
   `"B."` ở câu 11 — không có `<w:tab/>` hay khoảng trắng nào giữa 2 run
   trong XML gốc). Đây là sự không nhất quán của chính tác giả đề, không
   phải lỗi renderer — giữ nguyên trung thực với nguồn theo đúng nguyên tắc
   "làm sạch = whitelist", không tự thêm nội dung không có trong docx.

## Đề xuất cho v2

- Mở rộng whitelist bold-stripping sang label câu hỏi (`"Câu N[.:]"`) và ý
  đúng/sai (`"a)"`.."d)"`) — cần một hàm mới song song với
  `answer.is_option_marker`, không lẫn với marker A–D (khác ngữ cảnh:
  marker câu luôn đứng đầu đoạn).
- Thêm điều kiện "whitespace-only segment → không bọc format" vào
  `runs.wrap`/`emit`.
- `tables.py`: phát hiện bảng "toàn ảnh, không viền" → render phẳng thay vì
  `[* | *]`.
- Điều tra tiếp cơ chế "đếm nhưng không hiện" ở các mốc 44/60 bằng cách so
  sánh với các đề khác (để tách quy luật chung, tránh overfit 1 file mẫu) —
  ưu tiên giả thuyết "công thức liên tiếp không phân tách" ở trên.
- Xử lý `&quot;`/HTML-entity nếu xác nhận đây là hành vi ổn định của Azota
  (cần thêm mẫu để kiểm chứng, không suy diễn từ 1 câu hỏi).

## Cách tái tạo

```
uv run pytest tests/test_golden.py -v -s
uv run pytest -q
```
