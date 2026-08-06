# Structured export + LaTeX (v2) — Design Spec

- **Ngày:** 2026-07-06
- **Trạng thái:** Đã duyệt thiết kế, chờ review spec
- **Tiền đề:** Xây trên v1 (module làm sạch, nhánh `feat/docx-clean-module`). v1 xuất `markup.txt` phẳng giống Azota + `sidecar/` + `manifest.json`, dùng một bộ đếm placeholder toàn cục (`mathml_N` = OMML native, `mathtype_N` = OLE Equation, `img_N` = ảnh).
- **Phạm vi v2:** (a) chuyển 69 công thức OMML sang LaTeX; (b) bóc cây cấu trúc Phần→Nhóm→Câu với 3 loại câu; (c) xuất `structured.json`. KHÔNG phá đường phẳng v1.

---

## 1. Quyết định đã chốt (từ brainstorm)

1. **MathType OLE (`mathtype_N`, 16 cái): ~~giữ nguyên dạng ảnh~~ CẬP NHẬT 2026-08-06** — nay được OCR sang LaTeX qua DeepSeek-OCR-2 (xem `docs/superpowers/specs/2026-08-06-mathtype-ocr-latex-design.md`); asset ảnh WMF/EMF vẫn giữ làm backup/tham chiếu như cũ. Chỉ OMML dùng converter cây cấu trúc trực tiếp (không qua OCR).
2. **OMML → LaTeX bằng XSLT chạy qua `lxml`** (không thêm binary ngoài). Bundle 2 file `.xsl` mã nguồn mở. Fallback: converter đệ quy thuần Python.
3. **Output: giữ `markup.txt` như cũ + thêm `structured.json`.** LaTeX nằm trong JSON (và trong text field thay cho token `mathml_N`). `markup.txt` không đổi (vẫn tương thích Azota).
4. **Schema đầy đủ, phân loại theo từng loại câu** (`mcq` / `true_false` / `short_answer`).

## 2. Nguyên tắc kiến trúc

Cộng thêm 2 tầng hậu xử lý lên pipeline v1, không sửa hành vi phẳng:
- Tầng LaTeX: gắn vào `context.omml()` — convert khi gặp OMML, lưu `ctx.latex[oid]`.
- Tầng cấu trúc: `structure.build(markup, latex_map)` đọc lại markup phẳng (đã đủ marker xác định) → cây typed.

**Loại câu suy từ marker hiện diện, KHÔNG cứng theo số Phần** (bền hơn với đề khác bố cục).

## 3. Module — mới và thay đổi

| Module | Trạng thái | Nhiệm vụ | Interface | Phụ thuộc |
|---|---|---|---|---|
| `mathlatex.py` | MỚI | OMML element → LaTeX qua chuỗi XSLT `OMML2MML.xsl → mml2tex.xsl` chạy bằng `lxml.etree.XSLT`. Fallback converter đệ quy | `omml_to_latex(elem) -> str \| None` | lxml, `xslt/*.xsl` |
| `xslt/` (thư mục) | MỚI | Chứa 2 file XSLT mã nguồn mở | — | — |
| `context.py` | SỬA | Trong `omml()`: gọi `mathlatex.omml_to_latex`, lưu `self.latex[oid] = latex` (dict mới), thêm field `latex` vào manifest entry. Vẫn dump `.xml`. Lỗi convert → bỏ id khỏi `latex`, warning, giữ placeholder | thêm field `latex: dict` vào `Context` | mathlatex |
| `structure.py` | MỚI | Máy trạng thái theo dòng dựng cây Phần→Nhóm→Câu | `build(markup: str, latex_map: dict) -> dict` | — (regex thuần) |
| `assemble.py` | SỬA | Sau `clean_docx`, gọi `structure.build(markup, ctx.latex)`, ghi `structured.json`. CLI thêm cùng lúc | `write_outputs` ghi thêm `structured.json` | structure |

## 4. Luồng dữ liệu

```
docx ─loader─> assemble.clean_docx ─> (markup, ctx)   # markup.txt như cũ
                                        │  ctx.latex{oid->latex}  (mới, do context.omml điền)
                       structure.build(markup, ctx.latex) ─> tree(dict)
                       write_outputs: markup.txt + sidecar/ + manifest.json + structured.json
```

`structure.build` thay token `[!m:$mathml_N$]` trong mọi text field bằng `$<latex>$` tra từ `latex_map`; `[!m:$mathtype_N$]` và `[img:$img_N$]` giữ nguyên làm tham chiếu (đồng thời gom vào field `assets`).

## 5. Marker mà `structure.py` dựa vào (đều xác định trong markup phẳng)

- Phần: dòng bắt đầu `[!b:$PHẦN <số La Mã>` → phần mới. `title` = nội dung đậm; `instruction` = phần `[!i:$…$]` cùng dòng nếu có.
- Nhóm: dòng bắt đầu `[!b:$Nhóm <số La Mã>` → group; `context` = phần text còn lại của dòng + các dòng tới marker con đầu tiên.
- Câu: `^Câu\s+(\d+)\s*[.:]` → question.
- Phương án (mcq): `^\*?([A-D])[.)]\s*(.*)` → option; có `*` → `answer`. Nhiều phương án có thể cùng dòng (tách theo pattern).
- Ý đúng/sai (true_false): dòng bắt đầu `[S]` hoặc `[D]` → item; thứ tự → key `a,b,c,d`; `answer` = `"S"`/`"D"`.
- Đáp án ngắn (short_answer): `Đáp án là {a}` rồi dòng kế `^([A-D]?\.?)\s*(.+)` → `answer` = giá trị (vd `69,6`).
- Giải thích: từ `[!b:$[GT]...$]` (hoặc `[GT]`) tới `[!b:$[/]$]` (hoặc `[/]`) → `explanation`, gắn vào question/group đang mở.

## 6. Schema `structured.json`

```jsonc
{
  "source": "sample.docx",
  "parts": [
    {
      "no": "I",
      "type": "mcq",
      "title": "PHẦN I. Câu trắc nghiệm nhiều phương án lựa chọn (4,5 điểm).",
      "instruction": "Thí sinh trả lời từ câu 1 đến câu 18…",
      "content": [
        {
          "kind": "question",
          "no": 1,
          "stem": "Vào mùa đông… sự",
          "options": [
            {"key": "A", "text": "nóng chảy."},
            {"key": "B", "text": "bay hơi."},
            {"key": "C", "text": "ngưng kết."},
            {"key": "D", "text": "ngưng tụ."}
          ],
          "answer": "D",
          "explanation": "Hơi thở… Chọn D.",
          "assets": []
        }
      ]
    },
    {
      "no": "II",
      "type": "true_false",
      "title": "PHẦN II. Câu trắc nghiệm đúng sai (4,0 điểm).",
      "content": [
        {
          "kind": "group",
          "label": "Nhóm I.",
          "context": "Để hàn các linh kiện…",
          "assets": ["img_34"],
          "items": [
            {"key": "a", "stem": "Khi hàn, mỏ hàn sẽ phóng ra tia lửa điện…", "answer": "S"},
            {"key": "b", "stem": "…", "answer": "S"},
            {"key": "c", "stem": "…", "answer": "D"},
            {"key": "d", "stem": "…", "answer": "D"}
          ],
          "explanation": "a)… b)… c)… d)…"
        }
      ]
    },
    {
      "no": "III",
      "type": "short_answer",
      "title": "PHẦN III. Thí sinh trả lời từ câu 1 đến câu 6.",
      "content": [
        {"kind": "question", "no": 1, "stem": "Phanh xe tải…", "answer": "69,6", "explanation": "…", "assets": []},
        {
          "kind": "group",
          "label": "Nhóm II.",
          "context": "…máy đo huyết áp…",
          "assets": ["img_82"],
          "questions": [
            {"kind": "question", "no": 2, "stem": "…", "answer": "3,1", "explanation": null},
            {"kind": "question", "no": 3, "stem": "…", "answer": "70", "explanation": null}
          ],
          "explanation": "Câu 2:… Câu 3:…"
        }
      ]
    }
  ]
}
```

**Quy tắc model:**
- `part.content` giữ **đúng thứ tự tài liệu**; mỗi phần tử là `kind:"question"` (đứng lẻ) hoặc `kind:"group"`.
- `group` mang `context` chung + `items` (true_false) HOẶC `questions` (short_answer có nhóm). Không có cả hai cùng lúc.
- `explanation` có thể ở cấp `question`, `item`-chung-group, hoặc `group`. Nếu một `[GT]` chung cho cả nhóm → đặt ở `group.explanation`.
- `answer`: `mcq` = `"A".."D"`; `true_false` item = `"D"`/`"S"`; `short_answer` = chuỗi giá trị. Không tách được → `null` + warning.
- `assets`: danh sách id (`img_*`, `mathtype_*`) xuất hiện trong stem/context của node đó.

## 7. Xử lý lỗi

- Dòng không khớp marker nào → nối vào `stem`/`explanation`/`context` đang mở (không mất chữ).
- Không tách được đáp án → `answer: null` + warning, không bịa.
- Thiếu LaTeX cho một id → giữ token `[!m:$mathml_N$]` nguyên trong text field.
- OMML→LaTeX lỗi trên 1 công thức → id đó không vào `latex_map`, giữ placeholder, warning; không chặn file.
- Không nhận diện được loại phần (không marker nào) → `type: "unknown"`, dồn toàn bộ dòng vào `content` dạng `question` thô + warning.

## 8. Kiểm thử (TDD)

- `mathlatex`: fragment OMML (phân số `m:f`, mũ `m:sSup`, căn `m:rad`, `m:nary`, `m:d`) → LaTeX kỳ vọng. Test cả nhánh fallback đệ quy nếu XSLT vắng.
- `structure`: unit test từng luật — suy type từ marker; mcq option+answer; true_false 4 items D/S + key a-d; short_answer value; group context; gắn `[GT]`; dòng lạ nối vào node mở.
- Golden tích hợp từ `sample.docx`: assert 3 parts; Phần I `type=mcq` 18 questions; Phần II 4 groups mỗi group 4 items; Phần III 6 câu (gồm 1 group Nhóm II chứa câu 2,3); spot-check `parts[0].content[0].answer=="D"`, `Nhóm I items[0].answer=="S"`, `Phần III câu 1 answer=="69,6"`.

## 9. Rủi ro

1. **Sourcing XSLT.** `OMML2MML.xsl` bản Microsoft vướng bản quyền phân phối. Plan dùng bản **mã nguồn mở** (OMML→MathML open + `mml2tex` giấy phép MIT). Nếu chất lượng/độ phủ không đạt trên tập công thức thật → **fallback converter đệ quy thuần Python** phủ các tag OMML phổ biến (`m:f, m:sSup, m:sSub, m:rad, m:nary, m:d, m:r, m:acc`), vẫn hợp kiến trúc, không binary ngoài. Plan phải chứa CẢ hai đường và tiêu chí chọn.
2. `structure.py` phụ thuộc chất lượng markup phẳng. Các lệch placeholder đã biết (nhóm 44/60 ở golden v1) KHÔNG ảnh hưởng cấu trúc Phần/Nhóm/Câu/đáp án (các marker đó độc lập với số placeholder).

## 10. Ngoài phạm vi (YAGNI)

- MathType OLE → LaTeX (giữ ảnh).
- Sửa các lệch placeholder v1 (nhóm 44/60).
- Đa tín hiệu nhận đáp án (vẫn kế thừa v1: gạch chân cho mcq; `[S]/[D]` cho true_false; `Đáp án là {a}` cho short).
- Render LaTeX, sinh HTML, hay tích hợp LMS cụ thể.
