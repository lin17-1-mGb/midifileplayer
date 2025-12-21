#!/usr/bin/env python3
import time
from PIL import Image, ImageDraw, ImageFont
import st7789
from gpiozero import LED

WIDTH = HEIGHT = 240
BACKLIGHT_PIN = 13

backlight = LED(BACKLIGHT_PIN)
backlight.on()

disp = st7789.ST7789(
    width=240,
    height=240,
    rotation=90,
    port=0,
    cs=st7789.BG_SPI_CS_FRONT,
    dc=9,
    backlight=None,
    spi_speed_hz=80_000_000,
)

disp.begin()

try:
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22
    )
except:
    font = ImageFont.load_default()

text = "Safe to unplug"

# --- visible fade using redraw ---
steps = 20
for i in range(steps, -1, -1):
    brightness = int(255 * (i / steps))
    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    draw.text(
        ((WIDTH - w) // 2, (HEIGHT - h) // 2),
        text,
        font=font,
        fill=(0, brightness, 0),
    )

    disp.display(img)
    time.sleep(0.04)

# --- freeze last frame ---
try:
    disp._spi.close()
except:
    pass

# optional: backlight fully off after fade
backlight.off()

while True:
    time.sleep(1)
