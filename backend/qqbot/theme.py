"""Local vector treatment for the game's music/stage themed image panels."""
from PIL import Image, ImageDraw, ImageFilter

INK = '#202D4B'
MUTED = '#65728A'
PAPER = '#EDF2FA'
PINK = '#F15C95'
NAVY = '#192744'


def mix(a, b, weight):
    def rgb(value):
        return tuple(int(value[i:i+2], 16) for i in (1, 3, 5))
    return tuple(round(x*(1-weight)+y*weight) for x, y in zip(rgb(a), rgb(b)))


def stage(size, accent):
    """Quiet lighting and score lines; no remote texture or new asset request."""
    w, h = size
    image = Image.new('RGB', size)
    draw = ImageDraw.Draw(image)
    for y in range(h):
        draw.line((0, y, w, y), fill=mix('#D9E6F5', '#F3F5FC', min(1, y/900)))
    draw.polygon([(0, 0), (w, 0), (0, min(h, 720))], fill=mix(accent, '#FFFFFF', .91))
    for x in range(-h, w, 120):
        draw.line((x, 0, x+h, h), fill='#E2EAF4', width=1)
    for x in (14, w-17):
        for y in range(160, h-70, 30):
            draw.ellipse((x, y, x+3, y+3), fill='#BDCCDF')
    return image


def spotlight(image, box, accent):
    """Framed performance stage under art, preserving the full visible subject."""
    x, y, w, h = map(int, box)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((x, y, x+w, y+h), radius=20, fill=mix(accent, '#FFFFFF', .86))
    draw.polygon([(x+6, y+h-28), (x+w-8, y+45), (x+w-8, y+h-10)], fill=mix(accent, '#FFFFFF', .77))
    for offset in range(0, 4):
        draw.line((x+18, y+h-65+offset*10, x+w-18, y+h-65+offset*10), fill=mix(accent, '#FFFFFF', .67), width=1)
    draw.rounded_rectangle((x, y, x+w, y+h), radius=20, outline=mix(accent, '#FFFFFF', .62), width=2)
    draw.line((x+17, y+14, x+65, y+14), fill='white', width=3)
    draw.line((x+14, y+17, x+14, y+65), fill='white', width=3)


def floating_panel(canvas, panel, xy):
    x, y = xy
    w, h = panel.size
    # Local shadow buffers keep memory bounded on the 384 MiB deployment.
    shadow = Image.new('RGBA', (w+24, h+24))
    ImageDraw.Draw(shadow).rounded_rectangle((12, 12, w+12, h+12), radius=18, fill=(32, 54, 92, 30))
    shadow = shadow.filter(ImageFilter.GaussianBlur(5))
    canvas.paste(shadow, (x-12, y-7), shadow)
    mask = Image.new('L', panel.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w-1, h-1), radius=16, fill=255)
    canvas.paste(panel, xy, mask)
    ImageDraw.Draw(canvas).rounded_rectangle((x, y, x+w-1, y+h-1), radius=16, outline='#D8E2EF', width=1)


def masthead(image, accent):
    w = image.width
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, w, 114), fill=NAVY)
    draw.polygon([(w-335, 0), (w, 0), (w, 114), (w-460, 114)], fill=mix(accent, NAVY, .45))
    for offset in range(5):
        draw.line((w-350, 26+offset*13, w-20, 26+offset*13), fill=mix(accent, NAVY, .62), width=2)
    draw.polygon([(0, 111), (360, 111), (341, 119), (0, 119)], fill=PINK)
    draw.polygon([(367, 111), (w, 111), (w, 119), (348, 119)], fill=accent)


def heading(image, height, accent):
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, image.width, height), fill=mix(accent, '#FFFFFF', .92))
    draw.rectangle((0, height-2, image.width, height), fill=mix(accent, '#FFFFFF', .75))
    draw.polygon([(0, 0), (7, 0), (7, height-18), (0, height)], fill=accent)

