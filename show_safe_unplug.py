#!/usr/bin/env python3
import time
from PIL import Image, ImageDraw, ImageFont
import st7789
from gpiozero import LED

WIDTH = HEIGHT = 240
BACKLIGHT_PIN = 13

backlight = LED(BACKLIGHT_PIN)
backlight.on()

def make_frame(brightness):
    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), TEXT, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((WIDTH - w) // 2, (HEIGHT - h) // 2),
        TEXT,
        font=font,
        fill=(0, brightness, 0),
    )
    return img

# --- display init ---
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

try:
    disp.begin()
except Exception:
    # SPI already gone — nothing we can do
    while True:
        time.sleep(1)

try:
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22
    )
except:
    font = ImageFont.load_default()

TEXT = "Safe to unplug"

# --- guaranteed first frame ---
frame = make_frame(255)
shown = False

for _ in range(3):  # retry window (~150ms)
    try:
        disp.display(frame)
        shown = True
        break
    except:
        time.sleep(0.05)

if not shown:
    # display unreachable — freeze silently
    while True:
        time.sleep(1)

# --- optional fade (only if SPI still alive) ---
steps = 18
for i in range(steps - 1, -1, -1):
    try:
        disp.display(make_frame(int(255 * i / steps)))
        time.sleep(0.04)
    except:
        break  # SPI died mid-fade → keep last frame

# --- freeze cleanly ---
try:
    disp._spi.close()
except:
    pass

backlight.off()

while True:
    time.sleep(1)

