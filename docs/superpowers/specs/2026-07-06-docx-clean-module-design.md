# Module làm sạch DOCX → markup Azota — Design Spec

- **Ngày:** 2026-07-06
- **Trạng thái:** Đã duyệt thiết kế, chờ review spec
- **Phạm vi:** Tái tạo "Tầng A" của Azota — biến file `.docx` đề thi thành markup phẳng giống panel phải của Azota, kèm trích xuất asset (toán/ảnh) ra sidecar. KHÔNG bao gồm convert công thức, KHÔNG build cây câu hỏi JSON.

---

## 1. Mục tiêu & tiêu chí thành công

Đầu vào: một file `.docx` (mẫu chuẩn: `ĐỀ VẬT LÍ LẦN 3_VER 2 (2).docx`).

Đầu ra:
- `markup.txt` — văn bản phẳng theo dòng, **y hệt cú pháp Azota**: `[!b:$...$]`, `[!i:$...$]`, `[!sup:$...$]`, `[!sub:$...$]`, `[!b!i:$...$]`, `[!m:$mathml_N$]`, `[!m:$mathtype_N$]`, `[img:$img_N$]`, bảng `[* c1 | c2 *]`, và dấu `*` trước chữ cái đáp án đúng.
- `sidecar/` — asset thô: `mathml_N.xml` (OMML fragment), `mathtype_N.wmf|emf` (render MathType OLE), `img_N.png|jpeg|wmf` (ảnh hình vẽ).
- `manifest.json` — map mỗi id placeholder → nguồn (rId, tên file media/embedding, vị trí trong document order).

**Tiêu chí thành công (thước đo chính):** golden diff giữa `markup.txt` và đoạn markup Azota đã có sẵn cho đúng file này (do người dùng cung cấp). Càng ít khác biệt càng tốt; mọi khác biệt còn lại phải giải thích được.

## 2. Nguyên tắc cốt lõi

Markup Azota là **văn bản phẳng theo dòng**, KHÔNG phải cây JSON lồng nhau. Các mỏ neo cấu trúc (`Câu N`, `PHẦN I/II/III`, `Nhóm I..IV`, `[GT]`, `[/]`, `Chọn X.`, `Đáp án là {a}`) **đã là text sẵn trong file docx** (do giáo viên gõ). Vì vậy module là một **pipeline tuyến tính**, không cần nhận diện ngữ nghĩa câu hỏi.

Module chỉ **thêm hoặc biến đổi** đúng 5 nhóm việc:
1. Inline-tag định dạng (đậm/nghiêng/sup/sub) theo whitelist.
2. Placeholder cho toán/ảnh + trích asset.
3. Dấu `*` trước chữ cái đáp án đúng.
4. Cú pháp bảng `[* | *]`.
5. Gộp run liền kề cùng định dạng.

**Làm sạch = VỨT ĐI, không phải SỬA.** Chỉ giữ lại whitelist (b/i/sup/sub/math/img/table); mọi thuộc tính khác (màu, cỡ chữ, font, highlight, tab thừa, đoạn rỗng, run bị Word xé vụn) bị loại bỏ. Đây là lý do nguồn bẩn tới đâu cũng ra sạch.

## 3. Kiến trúc — 6 unit tách biệt

Mỗi unit một nhiệm vụ, giao tiếp qua interface rõ ràng, test độc lập.

| Unit | Nhiệm vụ | Interface (đầu vào → đầu ra) | Phụ thuộc |
|---|---|---|---|
| `loader.py` | Unzip in-memory; parse `document.xml`; đọc `word/_rels/document.xml.rels` để map `rId → media/embedding path`; nạp bytes asset | `load(path) → Document(body_tree, rels: dict, assets: dict[name,bytes])` | `zipfile`, `lxml` |
| `runs.py` | `w:p` → duyệt run, đọc `w:rPr`, phát whitelist tag; gộp run liền kề cùng định dạng; `w:tab`→space, `w:br`→`\n`; vứt phần còn lại | `render_paragraph(p_elem, ctx) → str` | — |
| `math_assets.py` | Phát placeholder + trích asset. `m:oMath`→`mathml_N` (+dump OMML). `w:object` OLE DSMT4→`mathtype_N` (+copy WMF/EMF). `w:drawing/a:blip`→`img_N` (+copy ảnh). Giữ **một bộ đếm N toàn cục**, prefix theo loại | `emit(elem, ctx) → placeholder_str` (ghi asset qua ctx) | `loader` |
| `answer.py` | Trong đoạn, nhận run chữ cái `^[A-D][.)]`; đánh `*` theo đa tín hiệu ưu tiên | `mark_correct(runs) → runs'` | `runs` |
| `tables.py` | `w:tbl` → `[* cell1 | cell2 | cell3 *]` mỗi hàng; cell render qua `runs` | `render_table(tbl_elem, ctx) → str` | `runs` |
| `assemble.py` / `__main__.py` | Duyệt `w:body` theo thứ tự, gọi unit phù hợp cho từng `w:p`/`w:tbl`; nối bằng `\n`; ghi `markup.txt` + `sidecar/` + `manifest.json`; CLI | `clean_docx(path, out_dir) → (markup, manifest)` | tất cả |

### Data flow
```
docx ──loader──> Document{body, rels, assets}
                      │
              assemble: for child in body:
                 ├── w:p  ──runs(+math_assets+answer)──> dòng markup
                 └── w:tbl ──tables(runs+math_assets)───> dòng bảng
                      │
                 join "\n" ──> markup.txt
                 ctx.assets_written ──> sidecar/  + manifest.json
```

`ctx` (context) là object dùng chung mang: bộ đếm N toàn cục, `rels`, `assets`, danh sách asset đã ghi. Truyền xuyên suốt để giữ đánh số nhất quán theo document order.

## 4. Quy tắc chi tiết

### 4.1 Whitelist inline tag (runs.py)
- `w:b`/`w:bCs` → `[!b:$...$]`; `w:i`/`w:iCs` → `[!i:$...$]`; đậm+nghiêng → `[!b!i:$...$]`.
- `w:vertAlign val="superscript"` → `[!sup:$...$]`; `"subscript"` → `[!sub:$...$]`.
- **Gộp run:** trước khi bọc tag, coalesce các run liền kề có cùng bộ (b,i,sup,sub) để tránh `[!b:$a$][!b:$b$]` → `[!b:$ab$]`.
- `w:tab` → khoảng trắng (số lượng theo quan sát golden, mặc định giữ như text gốc); `w:br` → newline.
- Bỏ qua: `w:color`, `w:sz`, `w:rFonts`, `w:highlight`, `w:u` (trừ vai trò tín hiệu đáp án ở answer.py), `w:spacing`, rsid…

### 4.2 Placeholder & đánh số (math_assets.py)
- **Một bộ đếm toàn cục** tăng dần theo document order; prefix chọn theo loại object: `mathml_`, `mathtype_`, `img_`.
- `m:oMath` (OMML native) → `[!m:$mathml_N$]`; dump XML fragment `sidecar/mathml_N.xml`.
- `w:object` chứa OLE `Equation.DSMT4` → `[!m:$mathtype_N$]`; theo `v:imagedata`/`o:OLEObject r:id` → copy render WMF/EMF → `sidecar/mathtype_N.<ext>`.
- `w:drawing` → `a:blip @r:embed` → `[img:$img_N$]`; copy media → `sidecar/img_N.<ext>`.
- **Nuance đã biết:** đánh số Azota có khoảng trống (thiếu 44, 60; bắt đầu ở 3, không phải 1). Giả thuyết: vài object tiêu tốn số nhưng không xuất (vd equation trong header/ảnh lồng). Chiến lược: đếm mọi object gặp trong body theo thứ tự; đối chiếu golden để tinh chỉnh xem object nào Azota bỏ. Ghi lệch vào manifest để debug.

### 4.3 Đáp án đúng (answer.py)
Đa tín hiệu, ưu tiên có fallback (dừng ở tín hiệu đầu tiên khớp):
1. Chữ cái phương án có **gạch chân** (`w:u`) → đúng. *(file mẫu dùng cách này)*
2. Chữ cái phương án **đậm khác biệt** so với các phương án khác.
3. Chữ cái/phương án có **màu** hoặc **highlight** khác biệt.
4. Không tín hiệu định dạng → (v1) không đánh `*`; ghi cảnh báo. *(Tương lai: đọc "Chọn X." trong block `[GT]` để suy ra.)*
Khi khớp → chèn `*` ngay trước chữ cái: `*D.`.

### 4.4 Bảng (tables.py)
- `w:tbl` → mỗi `w:tr` thành một dòng `[* <cell1> | <cell2> | <cell3> *]`.
- Nội dung cell render qua `runs.render_paragraph` (cell có thể chứa tag/placeholder).
- Lưu ý: có đề vừa nhúng bảng dưới dạng ảnh (`img_59`) VỪA có markup bảng `[* *]` — cả hai cùng xuất, giữ đúng thứ tự document.

## 5. Xử lý lỗi
- Element không nhận diện → bỏ qua + log DEBUG. Không crash.
- Thiếu `rId`/asset không tìm thấy → vẫn phát placeholder, log WARNING, ghi `manifest` là `missing`.
- OMML/OLE hỏng → vẫn phát placeholder, dump bytes raw ra sidecar để soi tay.
- Mục tiêu: chạy hết file bất kể lỗi cục bộ; gom cảnh báo cuối run.

## 6. Kiểm thử (TDD)
- **Unit test** từng unit với fixture XML nhỏ tự dựng: bold, italic, bold+italic, sup, sub, gộp run, tab/br, placeholder từng loại + đánh số toàn cục, underline→`*`, một hàng bảng.
- **Integration/golden:** chạy trên file mẫu, diff `markup.txt` với markup Azota người dùng cung cấp. Ghi lại % khớp và danh sách khác biệt còn lại kèm lý do.
- Viết test TRƯỚC implementation từng unit.

## 7. Bố cục thư mục
```
docx-extract/
  src/docx_extract/
    __init__.py        # export clean_docx
    __main__.py        # CLI
    loader.py
    runs.py
    math_assets.py
    answer.py
    tables.py
    assemble.py
  tests/
    fixtures/
    test_runs.py test_math_assets.py test_answer.py test_tables.py
    test_golden.py
  docs/superpowers/specs/2026-07-06-docx-clean-module-design.md
```

## 8. Ngoài phạm vi (YAGNI cho v1)
- Convert OMML→MathML, WMF→PNG/SVG.
- Build cây JSON câu hỏi.
- Suy luận đáp án từ text "Chọn X." khi không có tín hiệu định dạng.
- UI sửa tay.
- Xử lý định dạng file khác `.docx` (doc, pdf).
