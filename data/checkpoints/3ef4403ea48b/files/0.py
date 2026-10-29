"""Generate sample_booklet.pdf (3 greyscale pages) without needing a PDF library."""
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 34)
small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 26)
W, H = 1240, 1754

pages_gray = []  # bytes of raw greyscale pixel data per page
for p in range(3):
    img = Image.new('L', (W, H), 255)
    d = ImageDraw.Draw(img)
    d.text((80, 60), f'ANSWER SHEET  -  Page {p+1}', fill=0, font=font)
    q = f'Question {p+1}. Explain the concept of machine learning in your own words.'
    for j, line in enumerate(__import__('textwrap').wrap(q, width=60)):
        d.text((80, 150 + j * 45), line, fill=0, font=small)
    ans = ('Machine learning is a branch of artificial intelligence where computers '
           'learn patterns from data instead of being programmed with explicit rules. '
           'The model improves its predictions over time as it sees more examples.')
    for j, line in enumerate(__import__('textwrap').wrap(ans, width=55)):
        d.text((80, 320 + j * 40), line, fill=0, font=small)
    pages_gray.append(img.tobytes())
    img.save(f'sample_pngs/page_{p+1}.png')
    print(f'page_{p+1}.png drawn')

# --- assemble a minimal PDF: 3 pages, each an embedded greyscale (Flate) image ---
def pdf_obj(n, body):
    return f'{n} 0 obj\n{body}\nendobj\n'.encode()

objects = []
objects.append(pdf_obj(1, '<< /Type /Catalog /Pages 2 0 R >>'))
kids = ' '.join(f'{3 + i*3} 0 R' for i in range(3))
objects.append(pdf_obj(2, f'<< /Type /Pages /Kids [{kids}] /Count {len(pages_gray)} >>'))

out = b'%PDF-1.4\n'
offsets = []
for i, raw in enumerate(pages_gray):
    page_n, img_n, content_n = 3 + i * 3, 4 + i * 3, 5 + i * 3
    stream = zlib.compress(raw)
    objects.append(pdf_obj(page_n, (
        f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] '
        f'/Resources << /XObject << /Im0 {img_n} 0 R >> >> '
        f'/Contents {content_n} 0 R >>'))
    objects.append(pdf_obj(img_n, (
        f'<< /Type /XObject /Subtype /Image /Width {W} /Height {H} '
        f'/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode '
        f'/Length {len(stream)} >>\nstream\n'.encode() + stream + b'\nendstream'))
    draw = f'q {W} 0 0 {H} 0 0 cm /Im0 Do Q'.encode()
    objects.append(pdf_obj(content_n, (
        f'<< /Length {len(draw)} >>\nstream\n'.encode() + draw + b'\nendstream'))

for obj in objects:
    offsets.append(len(out))
    out += obj
xref_pos = len(out)
out += f'xref\n0 {len(objects)+1}\n'.encode()
out += b'0000000000 65535 f \n'
for off in offsets:
    out += f'{off:010d} 00000 n \n'.encode()
out += (f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\n'
        f'startxref\n{xref_pos}\n%%EOF\n').encode()

Path('sample_booklet.pdf').write_bytes(out)
print('sample_booklet.pdf written,', len(pages_gray), 'pages,', len(out), 'bytes')
