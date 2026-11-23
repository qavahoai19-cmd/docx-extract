import argparse
from .assemble import clean_docx, write_outputs
from .mathocr import OCRClient

def main():
    ap = argparse.ArgumentParser(prog="docx_extract")
    ap.add_argument("docx")
    ap.add_argument("-o", "--out", default="out")
    ap.add_argument("--keep-formulas", action="store_true",
                    help="Giữ XML/ảnh công thức gốc, không chuyển LaTeX hoặc gọi OCR")
    args = ap.parse_args()
    def progress(done, total, stats):
        print(f"OCR: {done}/{total} | cache: {stats['cache_hits']} | requests: {stats['http_requests']}", flush=True)
    if args.keep_formulas:
        markup, ctx = clean_docx(args.docx, preserve_formulas=True)
    else:
        with OCRClient(progress=progress) as client:
            markup, ctx = clean_docx(args.docx, ocr_client=client)
    write_outputs(markup, ctx, args.out)
    print(f"Ghi {args.out}/markup.txt | assets: {len(ctx.written)} | warnings: {len(ctx.warnings)}")
    print(f"Thời gian: {ctx.ocr_stats['document_s']:.2f}s | OCR: {ctx.ocr_stats.get('total_s', 0):.2f}s")
    print(f"OCR cache: {ctx.ocr_stats.get('cache_hits', 0)} | HTTP requests: {ctx.ocr_stats.get('http_requests', 0)}")
    print(f"MathType đọc trực tiếp: {ctx.ocr_stats.get('native_success', 0)} | chuyển OCR: {ctx.ocr_stats.get('ocr_total', 0)}")
    if args.keep_formulas:
        print(f"Giữ công thức gốc: {ctx.ocr_stats.get('preserved_formulas', 0)} | không chuyển LaTeX, không chạy model OCR")

if __name__ == "__main__":
    main()
