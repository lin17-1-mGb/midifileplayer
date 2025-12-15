#!/usr/bin/env python3
# Fast‑boot Monkey MIDI Player – FULL FEATURE VERSION (No Bluetooth Menu)
# Pimoroni Pirate Audio ST7789 240×240
# Raspberry Pi Zero 2 W

import sys, os, time, threading

# ---------------------- PATHS ----------------------
directory = os.path.expanduser("~")
if directory == "/root":
    directory = "/home/pi"

soundfont_folder = os.path.join(directory, "sf2")
midi_file_folder = os.path.join(directory, "midifiles")

# ---------------------- UI STATE ----------------------
MESSAGE = ""
pathes = ["MIDI KEYBOARD", "SOUND FONT", "MIDI FILE", "SHUTDOWN"]
files = pathes.copy()
selectedindex = 0
operation_mode = "main screen"
shutting_down = False

# ---------------------- HARDWARE GLOBALS ----------------------
rtmidi = fluidsynth = st7789 = None
Image = ImageDraw = ImageFont = None
fs = None
sfid = None
loaded_sf2_path = None

button_up = button_down = button_select = button_back = None

disp = None
WIDTH = HEIGHT = 240
img = draw = font = None

DISPLAY_MIN_INTERVAL = 0.06
_last_display_time = 0.0

# ---------------------- MIDI / DISPLAY STATE ----------------------
channel_presets = {}
current_midi_channel = None
current_program_change = None
state_lock = threading.Lock()

# Overlay states
drum_overlay_shown = False
drum_overlay_start_time = 0.0

keyboard_overlay_channel = None
keyboard_overlay_start_time = 0.0

# ---------------------- CACHED FILE LISTS ----------------------
soundfont_paths, soundfont_names = [], []
midi_paths, midi_names = [], []

# ---------------------- LAZY IMPORTS ----------------------
def lazy_imports():
    global rtmidi, fluidsynth, st7789
    global Image, ImageDraw, ImageFont

    import rtmidi as _rtmidi
    import fluidsynth as _fluidsynth
    import st7789 as _st7789
    from PIL import Image as _Image, ImageDraw as _ImageDraw, ImageFont as _ImageFont

    rtmidi = _rtmidi
    fluidsynth = _fluidsynth
    st7789 = _st7789
    Image = _Image
    ImageDraw = _ImageDraw
    ImageFont = _ImageFont

# ---------------------- GPIO ----------------------
def init_buttons():
    global button_up, button_down, button_select, button_back
    from gpiozero import Button

    button_up = Button(16)
    button_down = Button(24)
    button_select = Button(5)
    button_back = Button(6)

# ---------------------- DISPLAY ----------------------
def init_display():
    global disp, img, draw, font

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

    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18
        )
    except:
        font = ImageFont.load_default()

# ---------------------- AUDIO ----------------------
def init_fluidsynth_lazy():
    global fs
    if fs is None:
        fs = fluidsynth.Synth()
        fs.start(driver="alsa")

# ---------------------- SF2 PRESET SUPPORT ----------------------
try:
    from sf2utils.sf2parse import Sf2File
except Exception:
    Sf2File = None

def _safe_attr(obj, names, default=None):
    for n in names:
        if hasattr(obj, n):
            v = getattr(obj, n)
            if v is not None:
                return v
    return default

def build_sf2_preset_map(path):
    mapping = {}
    if not Sf2File or not path:
        return mapping, False
    try:
        with open(path, "rb") as f:
            sf2 = Sf2File(f)
            for p in sf2.presets:
                bank = int(_safe_attr(p, ["bank", "bank_number"], 0) or 0)
                prog = _safe_attr(p, ["preset", "preset_number", "program"], None)
                if prog is None:
                    continue
                name = _safe_attr(p, ["name"], f"Preset {prog}")
                mapping[(bank, int(prog))] = str(name)
        return mapping, True
    except Exception as e:
        print("SF2 parse error:", e)
        return {}, False

def get_internal_channel(monkey_ch):
    return 9 if monkey_ch == 0 else monkey_ch - 1

def get_display_channel(fs_ch):
    return 10 if fs_ch == 9 else fs_ch + 1

def select_first_presets_for_monkey():
    if sfid is None:
        return
    mapping, ok = build_sf2_preset_map(loaded_sf2_path)

    fs_ch = get_internal_channel(0)
    try:
        fs.program_select(fs_ch, sfid, 128, 0)
    except:
        fs.program_select(fs_ch, sfid, 0, 0)
    channel_presets[fs_ch] = mapping.get((128, 0), "Drums") if ok else "Drums"

    for monkey_ch in range(1, 10):
        fs_ch = get_internal_channel(monkey_ch)
        prog = monkey_ch - 1
        try:
            fs.program_select(fs_ch, sfid, 0, prog)
        except:
            fs.program_select(fs_ch, sfid, 0, 0)
        channel_presets[fs_ch] = mapping.get((0, prog), f"Preset {prog}") if ok else f"Preset {prog}"

# ---------------------- SAFE MIDI ----------------------
class SafeMidiIn:
    def __init__(self):
        self.midiin = rtmidi.MidiIn()
        self.port_name = None
        self.callback = None
        self.lock = threading.Lock()

    def set_callback(self, cb):
        self.callback = cb
        if self.midiin.is_port_open():
            self.midiin.set_callback(self._cb)

    def _cb(self, msg, ts):
        if self.callback:
            self.callback(msg, ts)

    def open_port_by_name_async(self, name):
        def t():
            with self.lock:
                ports = self.midiin.get_ports()
                if name in ports:
                    if self.midiin.is_port_open():
                        self.midiin.close_port()
                    self.midiin.open_port(ports.index(name))
                    self.midiin.set_callback(self._cb)
                    self.port_name = name
                    global MESSAGE
                    MESSAGE = "Connected MIDI"
        threading.Thread(target=t, daemon=True).start()

    def list_ports(self):
        return self.midiin.get_ports()

# ---------------------- MIDI CALLBACK ----------------------
def midi_callback(message_data, timestamp):
    message, _ = message_data
    status = message[0] & 0xF0
    ch = message[0] & 0x0F
    n1 = message[1] if len(message) > 1 else 0
    n2 = message[2] if len(message) > 2 else 0

    global current_midi_channel, current_program_change
    global drum_overlay_shown, drum_overlay_start_time
    global keyboard_overlay_channel, keyboard_overlay_start_time

    with state_lock:
        current_midi_channel = ch
        if status == 0xC0:
            current_program_change = n1

    # --- Note On / Off handling ---
    if status == 0x90:
        if n2 > 0:
            fs.noteon(ch, n1, n2)
            # Show overlay only on first note press per channel
            if ch == 9:  # drum
                if not drum_overlay_shown:
                    drum_overlay_shown = True
                    drum_overlay_start_time = time.time()
            else:
                if keyboard_overlay_channel != ch:
                    keyboard_overlay_channel = ch
                    keyboard_overlay_start_time = time.time()
        else:
            fs.noteoff(ch, n1)
    elif status == 0x80:
        fs.noteoff(ch, n1)
    elif status == 0xB0:
        fs.cc(ch, n1, n2)
    elif status == 0xE0:
        fs.pitch_bend(ch, (n2 << 7) + n1 - 8192)
    elif status == 0xC0:
        fs.program_change(ch, n1)
        channel_presets[ch] = f"Prog {n1}"

# ---------------------- FILE SCANS ----------------------
def scan_soundfonts():
    global soundfont_paths, soundfont_names
    p, l = [], []
    if os.path.isdir(soundfont_folder):
        for f in os.listdir(soundfont_folder):
            if f.endswith('.sf2'):
                p.append(os.path.join(soundfont_folder, f))
                l.append(f.replace('.sf2', ''))
    soundfont_paths, soundfont_names = p, l

def scan_midifiles():
    global midi_paths, midi_names
    p, l = [], []
    if os.path.isdir(midi_file_folder):
        for f in os.listdir(midi_file_folder):
            if f.endswith('.mid'):
                p.append(os.path.join(midi_file_folder, f))
                l.append(f.replace('.mid', ''))
    midi_paths, midi_names = p, l

# ---------------------- DISPLAY UPDATE ----------------------
def update_display():
    global _last_display_time, draw, img
    global drum_overlay_shown, drum_overlay_start_time
    global keyboard_overlay_channel, keyboard_overlay_start_time

    if draw is None or img is None:
        return

    now = time.time()
    if now - _last_display_time < DISPLAY_MIN_INTERVAL:
        return
    _last_display_time = now

    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=(0, 0, 0))

    if shutting_down:
        draw.text((10, HEIGHT//2 - 10), MESSAGE, font=font, fill=(0, 255, 0))
        try:
            disp.display(img)
        except Exception as e:
            print("disp.display failed:", e)
        return

    # --- Draw menu ---
    if operation_mode == "main screen":
        start_index = 0
        end_index = len(files)
    else:
        start_index = max(0, selectedindex - 6)
        end_index = min(len(files), start_index + 7)

    for i, line in enumerate(files[start_index:end_index], start=start_index):
        y = 30 + (i - start_index) * 30
        if i == selectedindex:
            draw.rectangle([10, y, WIDTH - 10, y + 30], fill=(255, 255, 255))
            draw.text((10, y), line, font=font, fill=(0, 0, 0))
        else:
            draw.text((10, y), line, font=font, fill=(255, 255, 255))

    draw.text((10, 0), MESSAGE, font=font, fill=(255, 0, 0))
    overlay_y = HEIGHT - 30

    # --- DRUM OVERLAY WITH SMOOTH FADE ---
    if drum_overlay_shown:
        elapsed = now - drum_overlay_start_time
        if elapsed < 4.0:
            alpha = int(255 * (1 - elapsed / 4.0))
            disp_ch = get_display_channel(9)
            preset_name = channel_presets.get(9, "Drums")
            color = (0, alpha, 0)
            draw.rectangle((0, overlay_y, WIDTH, HEIGHT), fill=(0, 0, 0))
            draw.text((10, overlay_y + 4), f"CH {disp_ch} : {preset_name}", font=font, fill=color)
        else:
            drum_overlay_shown = False

    # --- KEYBOARD OVERLAY WITH SMOOTH FADE ---
    if keyboard_overlay_channel is not None:
        elapsed = now - keyboard_overlay_start_time
        if elapsed < 4.0:
            alpha = int(255 * (1 - elapsed / 4.0))
            disp_ch = get_display_channel(keyboard_overlay_channel)
            preset_name = channel_presets.get(keyboard_overlay_channel, f"Prog {current_program_change}")
            color = (0, alpha, 0)
            draw.rectangle((0, overlay_y, WIDTH, HEIGHT), fill=(0, 0, 0))
            draw.text((10, overlay_y + 4), f"CH {disp_ch} : {preset_name}", font=font, fill=color)
        else:
            keyboard_overlay_channel = None

    # --- MIDI connection status ---
    if 'midi_manager' in globals() and midi_manager is not None:
        if operation_mode in ["main screen", "MIDI KEYBOARD"]:
            status_text = f"MIDI: {midi_manager.port_name}" if midi_manager.port_name else "MIDI: Connecting..."
            draw.text((10, HEIGHT - 55), status_text, font=font, fill=(255, 255, 0))

    try:
        disp.display(img)
    except Exception as e:
        print("disp.display failed:", e)

# ---------------------- BUTTON HANDLERS ----------------------
def handle_up():
    global selectedindex
    selectedindex = max(0, selectedindex - 1)
    update_display()

def handle_down():
    global selectedindex
    selectedindex = min(len(files) - 1, selectedindex + 1)
    update_display()

def handle_back():
    global operation_mode, files, pathes, selectedindex
    operation_mode = "main screen"
    files = pathes = ["MIDI KEYBOARD", "SOUND FONT", "MIDI FILE", "SHUTDOWN"]
    selectedindex = 0
    update_display()

def handle_select():
    global operation_mode, files, pathes, selectedindex, MESSAGE
    global sfid, loaded_sf2_path, fs, shutting_down

    sel = files[selectedindex]
    MESSAGE = ""

    if operation_mode == "main screen":
        operation_mode = sel
        if sel == "SOUND FONT":
            files = soundfont_names.copy()
            pathes = soundfont_paths.copy()
            if not files:
                MESSAGE = "No SF2 files"
        elif sel == "MIDI FILE":
            files = midi_names.copy()
            pathes = midi_paths.copy()
            if not files:
                MESSAGE = "No MIDI files"
        elif sel == "MIDI KEYBOARD":
            if 'midi_manager' in globals() and midi_manager is not None:
                pathes = files = midi_manager.list_ports()
            else:
                pathes = files = []
            if not files:
                MESSAGE = "No MIDI ports"
        elif sel == "SHUTDOWN":
            shutting_down = True
            MESSAGE = "Shutting down..."
            update_display()
            time.sleep(4)
            os.system("sudo /bin/systemctl poweroff")
            return
        selectedindex = 0
    else:
        if operation_mode == "SOUND FONT" and files:
            loaded_sf2_path = pathes[selectedindex]
            init_fluidsynth_lazy()
            sfid = fs.sfload(loaded_sf2_path, True)
            select_first_presets_for_monkey()
            MESSAGE = "SoundFont loaded"
        elif operation_mode == "MIDI FILE" and files:
            init_fluidsynth_lazy()
            try:
                fs.play_midi_file(pathes[selectedindex])
                MESSAGE = "Playing MIDI"
            except Exception as e:
                MESSAGE = str(e)
        elif operation_mode == "MIDI KEYBOARD" and files:
            MESSAGE = "Connecting MIDI"
            if 'midi_manager' in globals() and midi_manager is not None:
                midi_manager.open_port_by_name_async(pathes[selectedindex])
        handle_back()

# ---------------------- BACKGROUND INIT ----------------------
def background_init():
    lazy_imports()
    init_buttons()
    init_display()

    threading.Thread(target=scan_soundfonts, daemon=True).start()
    threading.Thread(target=scan_midifiles, daemon=True).start()

    button_up.when_pressed = handle_up
    button_down.when_pressed = handle_down
    button_select.when_pressed = handle_select
    button_back.when_pressed = handle_back

    global midi_manager
    midi_manager = SafeMidiIn()
    midi_manager.set_callback(midi_callback)

    update_display()

# ---------------------- MAIN ----------------------
def main():
    threading.Thread(target=background_init, daemon=True).start()
    while True:
        time.sleep(0.05)  # faster updates for smoother fade
        update_display()

if __name__ == '__main__':
    main()
