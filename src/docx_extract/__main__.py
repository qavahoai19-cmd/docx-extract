import argparse
from .assemble import clean_docx, write_outputs

def main():
    ap = argparse.ArgumentParser(prog="docx_extract")
    ap.add_argument("docx")
    ap.add_argument("-o", "--out", default="out")
    args = ap.parse_args()
    markup, ctx = clean_docx(args.docx)
    write_outputs(markup, ctx, args.out)
    print(f"Ghi {args.out}/markup.txt | assets: {len(ctx.written)} | warnings: {len(ctx.warnings)}")

if __name__ == "__main__":
    main()
