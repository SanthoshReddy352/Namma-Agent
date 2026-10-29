from PIL import Image, ImageDraw, ImageFont
import textwrap

font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 34)
small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 26)

for p in range(3):
    img = Image.new('L', (1240, 1754), 255)
    d = ImageDraw.Draw(img)
    d.text((80, 60), f'ANSWER SHEET  -  Page {p+1}', fill=0, font=font)
    q = f'Question {p+1}. Explain the concept of machine learning in your own words.'
    for j, line in enumerate(textwrap.wrap(q, width=60)):
        d.text((80, 150 + j * 45), line, fill=0, font=small)
    ans = ('Machine learning is a branch of artificial intelligence where computers '
           'learn patterns from data instead of being programmed with explicit rules. '
           'The model improves its predictions over time as it sees more examples.')
    for j, line in enumerate(textwrap.wrap(ans, width=55)):
        d.text((80, 320 + j * 40), line, fill=0, font=small)
    img.save(f'sample_pngs/page_{p+1}.png')
    print(f'page_{p+1}.png saved')
