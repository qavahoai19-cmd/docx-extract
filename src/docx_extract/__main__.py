import argparse
from .assemble import clean_docx, write_outputs
from .mathocr import OCRClient

def main():
    ap = argparse.ArgumentParser(prog="docx_extract")
    ap.add_argument("docx")
    ap.add_argument("-o", "--out", default="out")
    args = ap.parse_args()
    def progress(done, total, stats):
        print(f"OCR: {done}/{total} | cache: {stats['cache_hits']} | requests: {stats['http_requests']}", flush=True)
    with OCRClient(progress=progress) as client:
        markup, ctx = clean_docx(args.docx, ocr_client=client)
    write_outputs(markup, ctx, args.out)
    print(f"Ghi {args.out}/markup.txt | assets: {len(ctx.written)} | warnings: {len(ctx.warnings)}")
    print(f"Thời gian: {ctx.ocr_stats['document_s']:.2f}s | OCR: {ctx.ocr_stats.get('total_s', 0):.2f}s")
    print(f"OCR cache: {ctx.ocr_stats.get('cache_hits', 0)} | HTTP requests: {ctx.ocr_stats.get('http_requests', 0)}")
    print(f"MathType đọc trực tiếp: {ctx.ocr_stats.get('native_success', 0)} | chuyển OCR: {ctx.ocr_stats.get('ocr_total', 0)}")

if __name__ == "__main__":
    main()
