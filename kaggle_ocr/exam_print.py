"""Lay out extracted content as a self-contained A4 exam for browser printing."""
import html

from question_extract import plain


PRINT_CSS = '''
@page{size:A4;margin:15mm}
.exam-heading,.exam-ending{box-sizing:border-box;max-width:210mm;margin:22px auto 0;padding:0 20px;font:12pt/1.45 "Times New Roman",serif;color:#000}
.exam-heading-grid{display:grid;grid-template-columns:1fr 2fr;gap:18px;text-align:center;align-items:start}
.exam-school{font-weight:bold;white-space:pre-line;text-transform:uppercase}
.exam-school:after{content:"";display:block;width:50%;border-bottom:1px solid;margin:6pt auto}
.exam-kind{margin-top:6pt}.exam-heading h1{font:700 15pt/1.3 "Times New Roman",serif;text-transform:uppercase;max-width:none;margin:0 0 5pt}
.exam-heading .exam-meta{margin:3pt 0;font-size:12pt;color:#000}
.exam-fields{display:flex;justify-content:space-between;flex-wrap:wrap;gap:6pt;margin:16pt 0 8pt;font-size:12pt}
.exam-ending{text-align:center;font-weight:bold;margin:14pt auto 20pt}
.print-actions{text-align:center;margin:12px}.print-actions button{padding:8px 18px;cursor:pointer}
.question{margin-bottom:8pt!important;break-inside:avoid}
.question p{margin:4pt 0 6pt}
.options{grid-template-columns:repeat(2,minmax(0,1fr));gap:2pt 10pt;margin:4pt 0}
.options.long{grid-template-columns:1fr}
.option{padding:1pt 0!important;gap:5pt;line-height:1.4;font-size:1em}
.option-letter{display:inline!important;min-width:1.2em;width:auto;height:auto;margin:0!important;
 padding:0;border:0!important;border-radius:0;background:transparent!important;font:700 12pt/1.4 "Times New Roman",serif}
.option-letter:after{content:"."}
.paragraph u{white-space:pre-wrap;text-decoration-skip-ink:none}
.exam-blank{display:inline-block;min-width:4em;border-bottom:1px solid currentColor;text-decoration:none;white-space:pre}
.exam-instruction{font-weight:bold;break-after:avoid;margin:10pt 0 6pt}
body:not(.show-correct-answers) .option{color:black!important;font-weight:normal}
body:not(.show-correct-answers) .option b,body:not(.show-correct-answers) .option strong{font-weight:inherit}
body:not(.show-correct-answers) .option .option-letter{color:black!important}
body:not(.show-correct-answers) .explanation{display:none!important}
@media screen{
 .workspace{box-sizing:border-box;max-width:210mm!important;margin:0 auto!important}
 .paper{font-size:12pt!important;line-height:1.45!important}
}
@media print{
 .exam-heading{padding:0;margin:0 0 8mm;max-width:none}
 .exam-ending{padding:0;max-width:none}
 .print-actions{display:none!important}
 .paper{font-size:12pt!important;line-height:1.45!important}
 .paragraph{orphans:3;widows:3}
 .section-heading{background:transparent!important;border:0;border-radius:0;padding:0;margin:12pt 0 8pt}
 .section-heading h2{color:black;font-weight:bold}
}
'''


def select_markup(markup, start_heading=None):
    """Keep all source content unless the user explicitly selects a start."""
    if not start_heading:
        return markup
    lines = markup.splitlines()
    for index, line in enumerate(lines):
        if plain(line).casefold() == start_heading.strip().casefold():
            return '\n'.join(lines[index + 1:]).strip()
    raise ValueError(f'Không tìm thấy mục bắt đầu: {start_heading}')


def print_page(page, title, question_count, *, school='', subject='', duration='', code=''):
    esc = lambda value: html.escape(str(value))
    meta = []
    for label, value in (('Môn', subject), ('Thời gian làm bài', duration), ('Mã đề', code)):
        if str(value).strip():
            meta.append('<div class="exam-meta">' + label + ': ' + esc(value) + '</div>')
    header = ('<header class="exam-heading"><div class="exam-heading-grid"><div>'
              '<div class="exam-school">' + esc(school or 'ĐỀ THI') + '</div>'
              '<div class="exam-kind">' + str(question_count) + ' câu hỏi</div></div>'
              '<div><h1>' + esc(title) + '</h1>' + ''.join(meta) + '</div></div>'
              '<div class="exam-fields"><span>Họ và tên: ............................................</span>'
              '<span>Lớp: ............</span><span>SBD: ................</span></div>'
              '<div class="print-actions"><button onclick="window.print()">In / lưu PDF</button></div></header>')
    page = page.replace('</head>', '<style>' + PRINT_CSS + '</style></head>')
    page = page.replace('<body class="answers-hidden">', '<body class="answers-hidden">' + header, 1)
    compact = '''<div class="exam-ending">— HẾT —</div><script>
for(const body of document.querySelectorAll('.question-body')){
 for(const box of body.querySelectorAll(':scope > .options')){
  while(box.nextElementSibling?.classList.contains('options')){
   const next=box.nextElementSibling;box.append(...next.children);next.remove();
  }
  if([...box.querySelectorAll('.option')].some(e=>e.textContent.length>80))box.classList.add('long');
 }
 body.querySelectorAll('p:empty').forEach(e=>e.remove());
}
document.querySelectorAll('img').forEach(e=>e.loading='eager');
document.querySelectorAll('.paper u').forEach(e=>{
 if(!e.textContent.trim())e.classList.add('exam-blank');
});
</script>'''
    return page.replace('</body>', compact + '</body>')
