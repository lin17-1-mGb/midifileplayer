#!/usr/bin/env python3
import st7789
from PIL import Image, ImageDraw, ImageFont

disp = st7789.ST7789(
    width=240,
    height=240,
    rotation=90,
    port=0,
    cs=st7789.BG_SPI_CS_FRONT,
    dc=9,
    backlight=13,
    spi_speed_hz=80_000_000,
)
disp.begin()

img = Image.new("RGB", (240, 240), (0, 0, 0))
draw = ImageDraw.Draw(img)

try:
    font_big = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34
    )
    font_small = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22
    )
except:
    font_big = font_small = ImageFont.load_default()

# ---- Line 1 ----
text1 = "ZOMPLER"
bbox1 = draw.textbbox((0, 0), text1, font=font_big)
w1, h1 = bbox1[2] - bbox1[0], bbox1[3] - bbox1[1]

# ---- Line 2 ----
text2 = "loading…"
bbox2 = draw.textbbox((0, 0), text2, font=font_small)
w2, h2 = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]

total_h = h1 + h2 + 6

x1 = max(6, (240 - w1) // 2)
x2 = max(6, (240 - w2) // 2)
y1 = (240 - total_h) // 2
y2 = y1 + h1 + 6

draw.text((x1, y1), text1, font=font_big, fill=(255, 255, 255))
draw.text((x2, y2), text2, font=font_small, fill=(180, 180, 180))

disp.display(img)
