#!/usr/bin/env python3
import time
from PIL import Image, ImageDraw, ImageFont
import st7789
from gpiozero import LED

WIDTH = HEIGHT = 240
BACKLIGHT_PIN = 13

# Backlight (digital, reliable)
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

img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
draw = ImageDraw.Draw(img)

try:
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22
    )
except:
    font = ImageFont.load_default()

text = "Safe to unplug"
bbox = draw.textbbox((0, 0), text, font=font)
w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]

draw.text(
    ((WIDTH - w) // 2, (HEIGHT - h) // 2),
    text,
    font=font,
    fill=(0, 255, 0),
)

disp.display(img)

# Let user read it
time.sleep(3)

# Clean backlight off
backlight.off()

# Freeze forever
while True:
    time.sleep(1)
