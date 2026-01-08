#!/usr/bin/env python3
# Monkey MIDI Player - FULL VERSION + SAVE MIXER LOGIC ONLY

import sys, os, time, threading, smbus, datetime, json
import mido 

# --- 1. BOOT DELAY ---
time.sleep(0.5)

# --- 2. HARDCODED PATHS ---
BASE_DIR = "/home/pi"
soundfont_folder = os.path.join(BASE_DIR, "sf2")
midi_file_folder = os.path.join(BASE_DIR, "midifiles")
mixer_file = os.path.join(BASE_DIR, "mixer_settings.json")

# --- 3. CONFIGURATION & STATE ---
LED_NAME = "ACT"  
SHUTTING_DOWN = False  
LOW_POWER_MODE = False
MESSAGE = ""
msg_start_time = 0
volume_level = 0.5 

# --- NEW: MIXER SAVE/LOAD LOGIC ---
def save_mixer():
    try:
        with open(mixer_file, 'w') as f:
            json.dump(channel_volumes, f)
    except: pass

def load_mixer():
    global channel_volumes
    if os.path.exists(mixer_file):
        try:
            with open(mixer_file, 'r') as f:
                data = json.load(f)
                channel_volumes = {int(k): v for k, v in data.items()}
        except: pass

# ---------------------- RECORDING ENGINE ----------------------
class MidiRecorder:
    def __init__(self):
        self.recording = False
        self.mid = None
        self.track = None
        self.start_time = 0
        self.last_event_time = 0

    def start(self):
        self.mid = mido.MidiFile()
        self.track = mido.MidiTrack()
        self.mid.tracks.append(self.track)
        self.recording = True
        self.start_time = time.time()
        self.last_event_time = self.start_time

    def stop(self, filename):
        if not self.recording: return
        self.recording = False
        self.mid.save(filename)

    def add_event(self, msg):
        if self.recording:
            now = time.time()
            delta = int(mido.second2tick(now - self.last_event_time, self.mid.ticks_per_beat, 500000))
            msg.time = delta
            self.track.append(msg)
            self.last_event_time = now

recorder = MidiRecorder()

# ---------------------- METRONOME ENGINE ----------------------
metronome_on = False
bpm = 120
metro_vol = 80 
metro_adjusting = False

def metronome_worker():
    while True:
        if metronome_on and fs:
            try:
                fs.noteon(9, 76, 110) 
                time.sleep(0.05)
                fs.noteoff(9, 76)
                time.sleep((60.0 / bpm) - 0.05)
            except: 
                time.sleep(0.1)
        else:
            time.sleep(0.2)

threading.Thread(target=metronome_worker, daemon=True).start()

# ---------------------- WAVESHARE UPS (C) ----------------------
class UPS_C:
    def __init__(self, addr=0x43):
        self.bus = None; self.addr = addr; self.readings = []
        try: self.bus = smbus.SMBus(1)
        except: pass
    def get_voltage(self):
        if not self.bus: return 0.0
        try:
            read = self.bus.read_word_data(self.addr, 0x02)
            swapped = ((read << 8) & 0xFF00) | ((read >> 8) & 0x00FF)
            v = (swapped >> 3) * 0.004
            self.readings.append(v)
            if len(self.readings) > 20: self.readings.pop(0)
            return sorted(self.readings)[len(self.readings)//2]
        except: return 0.0
    def get_time_left(self):
        v = self.get_voltage()
        p = max(0, min(1, (v - 3.4) / (4.15 - 3.4)))
        total_minutes = p * (450 if LOW_POWER_MODE else 240)
        return f"{int(total_minutes // 60)}:{int(total_minutes % 60):02d}"

ups = UPS_C()

# ---------------------- UI MENU CONFIG ----------------------
MAIN_MENU = ["MIDI KEYBOARD", "SOUND FONT", "MIDI FILE", "MIXER", "RECORD", "METRONOME", "VOLUME", "POWER", "SHUTDOWN"]
files = MAIN_MENU.copy()
pathes = MAIN_MENU.copy()
selectedindex = 0
operation_mode = "main screen"
selected_file_path = ""
rename_string = ""

rename_chars = [" ", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", 
                "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z", 
                "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "_", "-", "OK"]

rename_char_idx = 0
channel_volumes = {i: 100 for i in range(16)}
load_mixer() # Load settings on start
mixer_selected_ch = 0
mixer_adjusting = False
channel_presets = {}

# ---------------------- HARDWARE INITIALIZATION ----------------------
rtmidi = fluidsynth = st7789 = None
Image = ImageDraw = ImageFont = None
fs = None; sfid = None; loaded_sf2_path = None; disp = None
img = draw = font = font_tiny = None
_last_display_time = 0.0
soundfont_paths, soundfont_names = [], []; midi_paths, midi_names = [], []

def lazy_imports():
    global rtmidi, fluidsynth, st7789, Image, ImageDraw, ImageFont
    import rtmidi, fluidsynth, st7789
    from PIL import Image, ImageDraw, ImageFont

def init_buttons():
    global button_up, button_down, button_select, button_back
    from gpiozero import Button
    button_up, button_down = Button(16), Button(24)
    button_select, button_back = Button(5), Button(6)

def init_display():
    global disp, img, draw, font, font_tiny
    try:
        import st7789 as st_lib
        disp = st_lib.ST7789(width=240, height=240, rotation=90, port=0, cs=st_lib.BG_SPI_CS_FRONT, dc=9, backlight=13, spi_speed_hz=40_000_000)
        disp.begin()
        img = Image.new("RGB", (240, 240), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        try: 
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
            font_tiny = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        except: 
            font = ImageFont.load_default(); font_tiny = ImageFont.load_default()
    except: pass

def init_fluidsynth_lazy():
    global fs
    if fs is None:
        try:
            import fluidsynth as fs_lib
            fs = fs_lib.Synth()
            fs.setting('synth.gain', volume_level)
            fs.setting('synth.polyphony', 48 if LOW_POWER_MODE else 96)
            fs.start(driver="alsa")
        except: pass

# ---------------------- POWER MANAGEMENT ----------------------
def toggle_power_mode():
    global LOW_POWER_MODE, MESSAGE, msg_start_time
    LOW_POWER_MODE = not LOW_POWER_MODE
    if LOW_POWER_MODE:
        os.system("sudo tvservice -o > /dev/null 2>&1")
        os.system("sudo rfkill block wifi")
        os.system("echo powersave | sudo tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor > /dev/null")
        os.system(f"echo none | sudo tee /sys/class/leds/{LED_NAME}/trigger > /dev/null")
        os.system(f"echo 0 | sudo tee /sys/class/leds/{LED_NAME}/brightness > /dev/null")
        if fs: fs.setting('synth.polyphony', 48)
        MESSAGE = "Lean: ON (ECO)"
    else:
        os.system("sudo tvservice -p > /dev/null 2>&1")
        os.system("sudo rfkill unblock wifi")
        os.system("echo ondemand | sudo tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor > /dev/null")
        os.system(f"echo mmc0 | sudo tee /sys/class/leds/{LED_NAME}/trigger > /dev/null")
        os.system(f"echo 1 | sudo tee /sys/class/leds/{LED_NAME}/brightness > /dev/null")
        if fs: fs.setting('synth.polyphony', 96)
        MESSAGE = "Lean: OFF (MAX)"
    msg_start_time = time.time()

# ---------------------- MIDI ENGINE LOGIC ----------------------
def build_sf2_preset_map(path):
    mapping = {}
    try:
        from sf2utils.sf2parse import Sf2File
        with open(path, "rb") as f:
            sf2 = Sf2File(f)
            for p in sf2.presets:
                b = getattr(p, 'bank', 0); pr = getattr(p, 'preset', None)
                if pr is not None: mapping[(int(b), int(pr))] = str(getattr(p, 'name', f"P{pr}"))
        return mapping, True
    except: return {}, False

def get_internal_channel(monkey_ch): return 9 if monkey_ch == 0 else monkey_ch - 1

def select_first_presets_for_monkey():
    global channel_presets
    if sfid is None or fs is None: return
    mapping, ok = build_sf2_preset_map(loaded_sf2_path)
    for i in range(16): fs.cc(i, 7, channel_volumes.get(i, 100))
    fs.cc(9, 7, metro_vol)
    
    d_ch = get_internal_channel(0)
    try: fs.program_select(d_ch, sfid, 128, 0)
    except: fs.program_select(d_ch, sfid, 0, 0)
    fs.program_change(d_ch, 0)
    channel_presets[d_ch] = mapping.get((128, 0), "Drums") if ok else "Drums"
    for m_ch in range(1, 10):
        f_ch = get_internal_channel(m_ch); prog = m_ch - 1
        fs.program_select(f_ch, sfid, 0, prog)
        fs.program_change(f_ch, prog)
        channel_presets[f_ch] = mapping.get((0, prog), f"Preset {prog}") if ok else f"Preset {prog}"

class SafeMidiIn:
    def __init__(self):
        import rtmidi as rt_lib
        self.midiin = rt_lib.MidiIn(); self.port_name = None; self.callback = None
    def set_callback(self, cb):
        self.callback = cb
        if self.midiin.is_port_open(): self.midiin.set_callback(self._cb)
    def _cb(self, msg, ts):
        if self.callback: self.callback(msg, ts)
    def open_port_by_name_async(self, name):
        def t():
            ports = self.midiin.get_ports()
            if name in ports:
                if self.midiin.is_port_open(): self.midiin.close_port()
                self.midiin.open_port(ports.index(name))
                self.midiin.set_callback(self._cb); self.port_name = name
                global MESSAGE, msg_start_time; MESSAGE = "Connected MIDI"; msg_start_time = time.time()
        threading.Thread(target=t, daemon=True).start()
    def list_ports(self): return self.midiin.get_ports()

def midi_callback(message_data, timestamp):
    message, _ = message_data; status, ch = message[0] & 0xF0, message[0] & 0x0F
    n1, n2 = message[1] if len(message) > 1 else 0, message[2] if len(message) > 2 else 0
    if recorder.recording:
        if status == 0x90: recorder.add_event(mido.Message('note_on', channel=ch, note=n1, velocity=n2))
        elif status == 0x80: recorder.add_event(mido.Message('note_off', channel=ch, note=n1, velocity=n2))
        elif status == 0xB0: recorder.add_event(mido.Message('control_change', channel=ch, control=n1, value=n2))
    if status == 0x90 and n2 > 0:
        if fs: fs.noteon(ch, n1, n2)
    elif status == 0x90 or status == 0x80: 
        if fs: fs.noteoff(ch, n1)
    elif status == 0xB0 and fs: fs.cc(ch, n1, n2)
    elif status == 0xE0 and fs: fs.pitch_bend(ch, (n2 << 7) + n1 - 8192)
    elif status == 0xC0 and fs: 
        fs.program_change(ch, n1); channel_presets[ch] = f"Prog {n1}"

def scan_soundfonts():
    global soundfont_paths, soundfont_names
    p, l = [], []
    if os.path.isdir(soundfont_folder):
        for f in os.listdir(soundfont_folder):
            if f.endswith('.sf2'): p.append(os.path.join(soundfont_folder, f)); l.append(f.replace('.sf2', ''))
    soundfont_paths, soundfont_names = p, l

def scan_midifiles():
    global midi_paths, midi_names
    p, l = [], []
    if os.path.isdir(midi_file_folder):
        m_files = sorted(os.listdir(midi_file_folder))
        for f in m_files:
            if f.endswith('.mid'): p.append(os.path.join(midi_file_folder, f)); l.append(f.replace('.mid', ''))
    midi_paths, midi_names = p, l

# ---------------------- BUTTON HANDLERS ----------------------
def handle_up():
    global selectedindex, volume_level, rename_char_idx, channel_volumes, mixer_selected_ch, bpm, metro_vol, metro_adjusting
    if operation_mode == "VOLUME":
        volume_level = min(1.0, volume_level + 0.05)
        if fs: fs.setting('synth.gain', volume_level)
    elif operation_mode == "RENAME":
        rename_char_idx = (rename_char_idx - 1) % len(rename_chars)
    elif operation_mode == "MIXER":
        if mixer_adjusting:
            f_ch = get_internal_channel(mixer_selected_ch)
            channel_volumes[f_ch] = min(127, channel_volumes[f_ch] + 5)
            if fs: fs.cc(f_ch, 7, channel_volumes[f_ch])
        else: mixer_selected_ch = max(0, mixer_selected_ch - 1)
    elif operation_mode == "METRONOME":
        if metro_adjusting:
            if selectedindex == 1: bpm = min(240, bpm + 5)
            elif selectedindex == 2: 
                metro_vol = min(127, metro_vol + 5)
                if fs: fs.cc(9, 7, metro_vol)
        else: selectedindex = max(0, selectedindex - 1)
    else: selectedindex = max(0, selectedindex - 1)

def handle_down():
    global selectedindex, volume_level, rename_char_idx, channel_volumes, mixer_selected_ch, bpm, metro_vol, metro_adjusting
    if operation_mode == "VOLUME":
        volume_level = max(0.0, volume_level - 0.05)
        if fs: fs.setting('synth.gain', volume_level)
    elif operation_mode == "RENAME":
        rename_char_idx = (rename_char_idx + 1) % len(rename_chars)
    elif operation_mode == "MIXER":
        if mixer_adjusting:
            f_ch = get_internal_channel(mixer_selected_ch)
            channel_volumes[f_ch] = max(0, channel_volumes[f_ch] - 5)
            if fs: fs.cc(f_ch, 7, channel_volumes[f_ch])
        else: mixer_selected_ch = min(9, mixer_selected_ch + 1)
    elif operation_mode == "METRONOME":
        if metro_adjusting:
            if selectedindex == 1: bpm = max(40, bpm - 5)
            elif selectedindex == 2: 
                metro_vol = max(0, metro_vol - 5)
                if fs: fs.cc(9, 7, metro_vol)
        else: selectedindex = min(2, selectedindex + 1)
    else: selectedindex = min(len(files) - 1, selectedindex + 1)

def handle_back():
    global operation_mode, files, pathes, selectedindex, rename_string, mixer_adjusting, metro_adjusting
    # --- NEW: Save when leaving Mixer ---
    if operation_mode == "MIXER":
        if mixer_adjusting: mixer_adjusting = False; return
        else: save_mixer() 
    if operation_mode == "METRONOME" and metro_adjusting: metro_adjusting = False; return
    if operation_mode == "RENAME":
        if len(rename_string) > 0: rename_string = rename_string[:-1]
        else: operation_mode = "FILE ACTION"; files = ["PLAY", "STOP", "RENAME", "DELETE", "BACK"]
    elif operation_mode == "FILE ACTION":
        operation_mode = "MIDI FILE"; scan_midifiles(); files, pathes = midi_names.copy(), midi_paths.copy()
    else:
        operation_mode = "main screen"; files = MAIN_MENU.copy()
    selectedindex = 0

def handle_select():
    global operation_mode, files, pathes, selectedindex, MESSAGE, msg_start_time, fs, sfid, SHUTTING_DOWN
    global rename_string, rename_char_idx, mixer_adjusting, metronome_on, selected_file_path, loaded_sf2_path, metro_adjusting
    
    if operation_mode == "MIXER": mixer_adjusting = not mixer_adjusting; return
    if operation_mode == "METRONOME":
        if selectedindex == 0: metronome_on = not metronome_on
        else: metro_adjusting = not metro_adjusting
        return
        
    if not files and operation_mode != "RENAME": return
    if operation_mode != "RENAME": sel = files[selectedindex]
    
    if operation_mode == "main screen":
        if sel == "MIXER": operation_mode = "MIXER"; return
        if sel == "METRONOME": operation_mode = "METRONOME"; selectedindex = 0; return
        if sel == "RECORD":
            if not recorder.recording: recorder.start(); MESSAGE = "Recording..."
            else:
                ts = datetime.datetime.now().strftime("%H%M%S")
                path = os.path.join(midi_file_folder, f"rec_{ts}.mid")
                recorder.stop(path); MESSAGE = "Saved Rec"; scan_midifiles()
            msg_start_time = time.time(); return
        if sel == "VOLUME": operation_mode = "VOLUME"; return
        if sel == "POWER": toggle_power_mode(); return
        
        if sel == "SHUTDOWN":
            SHUTTING_DOWN = True 
            time.sleep(0.1)
            draw.rectangle((0, 0, 240, 240), fill=(0, 0, 0))
            draw.text((45, 100), "SYSTEM HALT", font=font, fill=(255, 0, 0))
            draw.text((35, 140), "SAFE TO UNPLUG", font=font_tiny, fill=(255, 255, 255))
            disp.display(img)
            if fs: fs.delete()
            time.sleep(1.0)
            os.system("sudo /sbin/poweroff")
            return

        operation_mode = sel
        if sel == "SOUND FONT": scan_soundfonts(); files, pathes = soundfont_names.copy(), soundfont_paths.copy()
        elif sel == "MIDI FILE": scan_midifiles(); files, pathes = midi_names.copy(), midi_paths.copy()
        elif sel == "MIDI KEYBOARD": files = pathes = midi_manager.list_ports()
        selectedindex = 0
    elif operation_mode == "MIDI FILE":
        selected_file_path = pathes[selectedindex]; operation_mode = "FILE ACTION"
        files = ["PLAY", "STOP", "RENAME", "DELETE", "BACK"]; selectedindex = 0
    elif operation_mode == "FILE ACTION":
        if sel == "PLAY": 
            if sfid is None: MESSAGE = "LOAD SF2 FIRST"
            else: init_fluidsynth_lazy(); fs.play_midi_file(selected_file_path); MESSAGE = "Playing"
            msg_start_time = time.time()
        elif sel == "STOP":
            if fs: fs.delete(); fs = None; init_fluidsynth_lazy()
            if loaded_sf2_path: sfid = fs.sfload(loaded_sf2_path, True); select_first_presets_for_monkey()
            MESSAGE = "Stopped"; msg_start_time = time.time()
        elif sel == "RENAME": operation_mode = "RENAME"; rename_string = os.path.basename(selected_file_path).replace(".mid", ""); rename_char_idx = 0
        elif sel == "DELETE":
            try: os.remove(selected_file_path); MESSAGE = "Deleted"; scan_midifiles(); handle_back()
            except: MESSAGE = "Error"
            msg_start_time = time.time()
        elif sel == "BACK": handle_back()
    elif operation_mode == "RENAME":
        char = rename_chars[rename_char_idx]
        if char == "OK":
            new_path = os.path.join(midi_file_folder, rename_string.strip() + ".mid")
            try: os.rename(selected_file_path, new_path); MESSAGE = "Renamed"
            except: MESSAGE = "Error"
            operation_mode = "FILE ACTION"; files = ["PLAY", "STOP", "RENAME", "DELETE", "BACK"]
        else: rename_string += char
    else:
        if operation_mode == "SOUND FONT":
            loaded_sf2_path = pathes[selectedindex]; init_fluidsynth_lazy()
            sfid = fs.sfload(loaded_sf2_path, True); select_first_presets_for_monkey(); MESSAGE = "SF2 Loaded"
        elif operation_mode == "MIDI KEYBOARD": midi_manager.open_port_by_name_async(pathes[selectedindex])
        msg_start_time = time.time(); handle_back()

# ---------------------- DISPLAY ENGINE ----------------------
def update_display():
    global _last_display_time, draw, img, MESSAGE, operation_mode, SHUTTING_DOWN
    if SHUTTING_DOWN or draw is None: return 
    now = time.time()
    if now - _last_display_time < (0.15 if LOW_POWER_MODE else 0.06): return
    _last_display_time = now
    
    accent = (255, 255, 0) if LOW_POWER_MODE else (255, 255, 255)
    draw.rectangle((0, 0, 240, 240), fill=(0, 0, 0))
    draw.rectangle((0, 0, 240, 26), fill=(30, 30, 30))
    draw.text((10, 4), f"TIME: {ups.get_time_left()}", font=font_tiny, fill=accent)
    draw.rectangle((0, 26, 240, 56), fill=(50, 50, 50))
    draw.text((10, 31), operation_mode.upper(), font=font, fill=accent)

    if operation_mode == "VOLUME":
        draw.text((30, 90), "MASTER GAIN", font=font, fill=accent)
        draw.rectangle((20, 120, 220, 150), outline=accent, width=2)
        fill_w = int(196 * volume_level)
        draw.rectangle((22, 122, 22 + fill_w, 148), fill=(0, 255, 0))
        draw.text((100, 160), f"{int(volume_level * 100)}%", font=font, fill=accent)
    elif operation_mode == "RENAME":
        draw.text((10, 100), rename_string + "_", font=font, fill=(0, 255, 0))
        char_curr = rename_chars[rename_char_idx]
        draw.rectangle((105, 145, 145, 180), fill=accent)
        draw.text((118, 150), char_curr, font=font, fill=(0,0,0))
    elif operation_mode == "MIXER":
        for i in range(10):
            y = 60 + (i * 18); f_ch = get_internal_channel(i)
            color = accent if i == mixer_selected_ch else (200, 200, 200)
            if i == mixer_selected_ch and mixer_adjusting: draw.rectangle((5, y, 235, y+16), outline=(0, 255, 0))
            draw.text((10, y), f"{i}: {channel_presets.get(f_ch, f'CH {i+1}')[:12]}", font=font_tiny, fill=color)
            draw.rectangle((150, y+4, 150 + int(channel_volumes.get(f_ch, 100)/1.6), y+12), fill=color)
    elif operation_mode == "METRONOME":
        opts = [f"STATUS: {'ON' if metronome_on else 'OFF'}", f"SPEED: {bpm} BPM", f"VOL: {metro_vol}"]
        for i, opt in enumerate(opts):
            y = 80 + (i * 40); color = accent if i == selectedindex else (200, 200, 200)
            if i == selectedindex: draw.rectangle([10, y-5, 230, y+25], outline=(0, 255, 0) if metro_adjusting else color)
            draw.text((20, y), opt, font=font, fill=color)
    else:
        view_size = 5; start_idx = max(0, min(selectedindex - 2, len(files) - view_size))
        for i, line in enumerate(files[start_idx:start_idx+view_size], start=start_idx):
            y = 62 + (i - start_idx) * 28; color = (0,0,0) if i == selectedindex else accent
            if i == selectedindex: draw.rectangle([10, y, 230, y+26], fill=accent)
            draw.text((15, y+2), line[:22], font=font, fill=color)

    if MESSAGE and now - msg_start_time < 2.0:
        draw.rectangle((20, 100, 220, 140), fill=(200, 0, 0)); draw.text((35, 110), MESSAGE, font=font, fill=(255, 255, 255))
    disp.display(img)

# ---------------------- MAIN BOOT ----------------------
def background_init():
    try:
        lazy_imports(); init_buttons(); init_display()
        threading.Thread(target=scan_soundfonts, daemon=True).start()
        threading.Thread(target=scan_midifiles, daemon=True).start()
        button_up.when_pressed, button_down.when_pressed = handle_up, handle_down
        button_select.when_pressed, button_back.when_pressed = handle_select, handle_back
        global midi_manager; midi_manager = SafeMidiIn(); midi_manager.set_callback(midi_callback)
    except: pass

def main():
    threading.Thread(target=background_init, daemon=True).start()
    while True:
        if not SHUTTING_DOWN:
            update_display()
        time.sleep(0.05)

if __name__ == '__main__':
    main()