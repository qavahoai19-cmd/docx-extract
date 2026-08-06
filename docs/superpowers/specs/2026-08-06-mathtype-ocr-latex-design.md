# MathType OLE → LaTeX qua DeepSeek-OCR-2 — Design Spec

**Ngày:** 2026-08-06
**Trạng thái:** Chờ duyệt thiết kế

**Goal:** Chuyển 16 công thức MathType OLE (`mathtype_N`, hiện giữ dạng ảnh WMF/EMF) sang LaTeX bằng OCR (DeepSeek-OCR-2 chạy local), để đạt mục tiêu "tất cả công thức đều về LaTeX".

**Architecture:** Thêm module `mathocr.py` (lazy-load model DeepSeek-OCR-2 + convert WMF/EMF→PNG qua GDI+ Windows) được gọi từ `Context.ole()` ngay sau khi render asset được resolve; kết quả LaTeX lưu vào `ctx.latex[oid]` giống hệt cơ chế OMML hiện có. Không đổi hành vi v1 (markup.txt phẳng, manifest, warnings-never-crash).

**Tech Stack:** `transformers` + `torch` (model `deepseek-ai/DeepSeek-OCR-2`), GDI+ Windows (qua `pythonnet`/`ctypes`+`gdiplus.dll`) để rasterize WMF/EMF → PNG.

---

## 1. Quyết định đã chốt (qua trao đổi)

1. **Phạm vi:** chỉ OCR cho `mathtype_N` (MathType OLE). OMML native (`mathml_N`) **giữ nguyên** converter cây cấu trúc hiện có trong `mathlatex.py` — không đụng vào. Điều này **đảo ngược** quyết định cũ trong spec v2 ("MathType OLE giữ ảnh, KHÔNG convert LaTeX") — sẽ cập nhật lại decision #1 trong spec đó sau khi duyệt.
2. **Tích hợp:** gọi thẳng `deepseek-ai/DeepSeek-OCR-2` qua `transformers` trong tiến trình Python của `docx-extract` (không qua app GUI `local_ai_ocr`, không qua subprocess/service riêng).
3. **Convert ảnh:** WMF/EMF → PNG bằng GDI+ Windows (native, không cài phần mềm ngoài như LibreOffice/ImageMagick).
4. **Model weight:** tải mới hoàn toàn qua `transformers` cache (~6.67GB), không tái dùng thư mục của `local_ai_ocr`.
5. **Luôn bật** — không có flag `--ocr-mathtype`, mọi file có `mathtype_N` sẽ tự động chạy OCR.

## 2. Luồng dữ liệu

```
w:object (OLE Equation) ─ context.ole() ─┬─> ghi asset mathtype_N.wmf (như cũ, không đổi)
                                          └─> mathocr.image_to_latex(png_bytes)
                                                  │
                                        wmf/emf bytes ──gdi+──> png bytes ──DeepSeek-OCR-2──> latex str | None
                                          │
                                   latex is not None?
                                     ├─ có: ctx.latex["mathtype_N"] = latex; manifest entry thêm "latex"
                                     └─ không (lỗi/torch thiếu/model lỗi): ctx.warnings.append(...), giữ placeholder
                                                                            ảnh-only như hiện tại (KHÔNG crash)
```

`ctx.latex` giờ chứa cả `mathml_*` (từ OMML) lẫn `mathtype_*` (từ OCR) — cùng một dict, cùng cơ chế tra cứu cho `structure.py` sau này (module đó chưa được code, sẽ tự động hưởng lợi khi build).

## 3. Module mới / thay đổi

| Module | Trạng thái | Nhiệm vụ | Interface |
|---|---|---|---|
| `mathocr.py` | MỚI | (a) lazy-singleton load tokenizer+model DeepSeek-OCR-2 (import `torch`/`transformers` **bên trong hàm**, không ở top-level, để không bắt buộc mọi import của package phải có torch); (b) `wmf_to_png(data: bytes, ext: str) -> bytes \| None` convert qua GDI+; (c) `image_to_latex(png_bytes: bytes) -> str \| None` chạy `model.infer(...)` với prompt `"<image>\nFree OCR."`, trả LaTeX hoặc `None` nếu lỗi | `image_to_latex(png_bytes) -> str \| None`, `wmf_to_png(data, ext) -> bytes \| None` |
| `context.py` | SỬA | `ole()`: sau khi resolve `path, data` thành công cho OLE Equation, gọi `mathocr.wmf_to_png` rồi `mathocr.image_to_latex`; ghi `self.latex[oid]`; thêm field `latex` vào manifest entry (đồng bộ format với `omml()`). Lỗi ở bất kỳ bước nào → `warnings.append(...)`, không set `ctx.latex[oid]`, vẫn trả `[!m:$oid$]` như cũ | không đổi chữ ký `ole()` |

**Điểm mở cho test (không cần torch khi test):** `Context` nhận thêm tham số optional `ocr_fn: Callable[[bytes], str \| None] \| None = None` (mặc định `None` → dùng `mathocr.image_to_latex` thật). Test tiêm fake `ocr_fn` để verify wiring mà không cần cài torch/tải model.

## 4. Xử lý lỗi (giữ nguyên convention "never crash")

- Thiếu `torch`/`transformers` chưa cài, model chưa tải được, GDI+ convert lỗi, hoặc OCR trả rác → tất cả bắt exception, log vào `ctx.warnings`, **không** set `ctx.latex[oid]`, placeholder ảnh vẫn xuất ra bình thường (hành vi fallback y hệt hôm nay).
- Model chỉ load một lần cho cả tiến trình (lazy singleton trong `mathocr.py`), tránh việc mỗi công thức tải lại 6.67GB.

## 5. Testing

- `tests/test_mathocr.py`: test `wmf_to_png` với input WMF/EMF giả (bytes cố định, mock GDI+ call hoặc dùng sample thật nếu có trong `tests/fixtures`); test `image_to_latex` bằng cách mock `transformers`/model load (không gọi model thật trong CI).
- `tests/test_math_assets.py` (đã có): thêm case gọi `Context(..., ocr_fn=fake_ocr)` → xác nhận `ctx.latex["mathtype_1"]` được set đúng, manifest có field `latex`; case `ocr_fn` raise exception → xác nhận fallback (warning, không crash, không set latex).
- Không cần torch cài trong máy dev/CI để chạy suite chính — chỉ cần khi thực sự chạy pipeline thật với OLE equation.

## 6. Dependency footprint (đã chốt)

Thêm `torch`, `transformers` thẳng vào `[project.dependencies]` chính trong `pyproject.toml` — bắt buộc cài cho mọi người dùng `docx-extract` (không tách optional group). Package nặng (~2GB+ khi cài, cộng 6.67GB weight tải lần đầu khi chạy lần đầu qua `transformers` cache) là đánh đổi chấp nhận được để tính năng luôn sẵn sàng, không cần flag bật/tắt.

## 7. Rủi ro / lưu ý

- Máy dev hiện tại **không có GPU** → OCR CPU sẽ rất chậm (có thể vài chục giây/công thức). Chấp nhận được cho chạy offline, nhưng cần biết trước.
- Cách chính xác convert WMF/EMF→PNG qua GDI+ (ctypes gọi `gdiplus.dll` trực tiếp, hay qua `pythonnet`) sẽ chốt lúc code — cả hai đều không cần cài phần mềm ngoài, chỉ khác cách gọi API .NET/Win32.
- Chưa có sample WMF/EMF thật trong `tests/fixtures` để test convert — cần kiểm tra `tests/fixtures/` hoặc dùng fixture docx thật có OLE Equation.
