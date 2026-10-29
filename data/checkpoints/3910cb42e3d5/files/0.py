from PIL import Image, ImageDraw, ImageFont
import textwrap

font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 34)
small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 26)
pages = []
for p in range(3):
    img = Image.new('RGB', (1240, 1754), 'white')
    d = ImageDraw.Draw(img)
    d.text((80, 60), f'ANSWER SHEET  -  Page {p+1}', fill='black', font=font)
    q = f'Question {p+1}. Explain the concept of machine learning in your own words.'
    for j, line in enumerate(textwrap.wrap(q, width=60)):
        d.text((80, 150 + j * 45), line, fill='black', font=small)
    ans = ('Machine learning is a branch of artificial intelligence where computers '
           'learn patterns from data instead of being programmed with explicit rules. '
           'The model improves its predictions over time as it sees more examples.')
    for j, line in enumerate(textwrap.wrap(ans, width=55)):
        d.text((80, 320 + j * 40), line, fill='black', font=small)
    pages.append(img)

# Greyscale pages -> PIL writes PDFs with ZIP encoding (no JPEG plugin needed)
grey = [p.convert('L') for p in pages]
try:
    grey[0].save('sample_booklet.pdf', save_all=True, append_images=grey[1:])
    print('sample_booklet.pdf created,', len(grey), 'pages')
except Exception as e:
    print('ERROR:', type(e).__name__, e)
