import os
import base64
import pickle
import subprocess
import random
import io
import json
import time
import textwrap
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI ---
TOKEN_B64 = os.environ.get('TOKEN_DATA_B') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')
QUOTES_ID = os.environ.get('QUOTES_FILE_ID')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

LIVE_DURATION_SEC = random.randint(2700, 3900) # 45-65 Menit
DELAY_MENIT = random.randint(0, 1)

def get_services():
    try:
        t_str = TOKEN_B64.strip().replace('\xa0', '').replace(" ", "").replace("\n", "")
        t_str += '=' * (4 - (len(t_str) % 4))
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token: creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"⛔ GAGAL AUTH: {e}")
        return None

def get_quotes(service):
    """Mengambil kutipan acak dari Drive."""
    backup_quotes = ["Tetap Semangat!", "Fokus pada tujuanmu.", "Kerja keras tak mengkhianati hasil."]
    if not QUOTES_ID: return backup_quotes
    try:
        file_meta = service.files().get(fileId=QUOTES_ID).execute()
        mime_type = file_meta.get('mimeType', '')
        fh = io.BytesIO()
        if 'application/vnd.google-apps' in mime_type:
            req = service.files().export_media(fileId=QUOTES_ID, mimeType='text/plain')
        else:
            req = service.files().get_media(fileId=QUOTES_ID)
            
        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while not done: _, done = downloader.next_chunk()
        lines = [l.strip() for l in fh.getvalue().decode('utf-8-sig').splitlines() if len(l.strip()) > 5]
        random.shuffle(lines)
        return lines if lines else backup_quotes
    except: return backup_quotes

def find_font():
    """Mencari Comic Sans, jika tidak ada pakai font default."""
    paths = [
        "/usr/share/fonts/truetype/msttcorefonts/comic.ttf",  # Comic Sans
        "/usr/share/fonts/truetype/msttcorefonts/Comic_Sans_MS.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" # Fallback
    ]
    for p in paths:
        if os.path.exists(p): return p
    return None

def standardize_video(input_path, output_path, quote, font_path):
    """
    Memproses rotasi, crop, menambah audio channel, dan MEMASUKKAN TEKS 3D.
    Audio ASLI TIDAK DIMUTE, melainkan distandarisasi formatnya.
    """
    # Deteksi rotasi
    try:
        cmd = ['ffprobe', '-loglevel', 'error', '-select_streams', 'v:0', '-show_entries', 'stream_tags=rotate', '-of', 'json', input_path]
        rotation = int(json.loads(subprocess.check_output(cmd).decode('utf-8')).get('streams', [{}])[0].get('tags', {}).get('rotate', 0))
    except: rotation = 0

    filters = []
    if rotation == 90: filters.append("transpose=1")
    elif rotation == 180: filters.append("hflip,vflip")
    elif rotation == 270: filters.append("transpose=2")
    filters.append("scale=w=1280:h=720:force_original_aspect_ratio=increase,crop=1280:720")

    # LOGIKA YANG SUDAH DIPERBAIKI (safe_txt)
    safe_txt = "\\n".join(textwrap.wrap(quote, width=30)).replace("'", "").replace(":", "\\:")
    
    # Waktu muncul acak (Misal: Muncul di detik 5 sampai detik 25)
    t_start = random.randint(3, 10)
    t_duration = random.randint(10, 20)
    t_end = t_start + t_duration
    
    if font_path:
        # Teks 3D: Warna Merah, Border Hitam (3px), Shadow Putih (2px)
        # Animasi: y='(h-text_h)/2 + 15*sin(t)' -> Teks akan melayang naik turun secara halus
        dt = (f"drawtext=text='{safe_txt}':fontfile={font_path}:fontcolor=red:"
              f"bordercolor=black:borderw=4:"
              f"shadowcolor=white:shadowx=2:shadowy=2:"
              f"fontsize=50:line_spacing=15:"
              f"x=(w-text_w)/2:y='(h-text_h)/2 + 15*sin(t*2)':"
              f"enable='between(t,{t_start},{t_end})'")
        filters.append(dt)

    v_filter = ",".join(filters)
    
    # Perintah FFmpeg (Menyertakan audio asli dengan format standar agar bisa digabung nanti)
    cmd = [
        'ffmpeg', '-y', '-i', input_path,
        '-vf', v_filter,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
        '-c:a', 'aac', '-ar', '44100', '-ac', '2', # Standarisasi Audio Asli
        output_path
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0

def main():
    print(f"=== ROBOT LIVE NATURAL & 3D TEXT ===")
    if DELAY_MENIT > 0:
        time.sleep(DELAY_MENIT * 60)

    drive = get_services()
    font_path = find_font()
    if not drive: return

    try:
        quotes_pool = get_quotes(drive)
        # Tambahkan trashed=false agar tidak mengambil video di keranjang sampah
        v_files = drive.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false").execute().get('files', [])
        m_files = drive.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio' and trashed=false").execute().get('files', [])

        if not v_files or not m_files:
            print("⛔ Bahan Kosong!")
            return

        # ACAK TOTAL
        random.shuffle(v_files)
        random.shuffle(m_files)
        v_files = v_files[:8] # Ambil maksimal 8 video acak

        v_list = ""
        for i, v in enumerate(v_files):
            raw = f"raw_{i}.mp4"
            fixed = f"fixed_{i}.mp4"
            quote = quotes_pool[i % len(quotes_pool)]
            
            print(f"[*] Menyiapkan Video {i+1} (Teks: {quote[:20]}...)")
            with open(raw, "wb") as f:
                f.write(drive.files().get_media(fileId=v['id']).execute())
            
            if standardize_video(raw, fixed, quote, font_path):
                v_list += f"file '{fixed}'\n"
            if os.path.exists(raw): os.remove(raw)
        
        with open("v_list.txt", "w") as f: f.write(v_list)

        m_list = ""
        for i, m in enumerate(m_files[:15]): 
            mname = f"mus_{i}.mp3"
            with open(mname, "wb") as f:
                f.write(drive.files().get_media(fileId=m['id']).execute())
            m_list += f"file '{mname}'\n"
        with open("m_list.txt", "w") as f: f.write(m_list)

        rtmp = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
        print(f"\n[🚀] MEMULAI STREAMING (AUDIO MIXING & 3D TEXT)")

        # Perintah Streaming dengan Audio Mixing (Video Asli 30%, Musik 100%)
        cmd = [
            'ffmpeg', '-y', '-re',
            '-f', 'concat', '-safe', '0', '-stream_loop', '-1', '-i', 'v_list.txt',
            '-f', 'concat', '-safe', '0', '-stream_loop', '-1', '-i', 'm_list.txt',
            '-filter_complex', '[0:a]volume=0.3[va];[1:a]volume=1.0[ma];[va][ma]amix=inputs=2:duration=first[aout]',
            '-t', str(LIVE_DURATION_SEC),
            '-map', '0:v', '-map', '[aout]',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '2500k', 
            '-g', '48', '-keyint_min', '48', 
            '-c:a', 'aac', '-b:a', '128k',
            '-f', 'flv', rtmp
        ]

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            if "frame=" in line: print(f"Streaming: {line.strip()}", end="\r")
        process.wait()

    except Exception as e:
        print(f"\n⛔ ERROR: {e}")
    finally:
        for f in os.listdir():
            if f.startswith("fixed_") or f.startswith("mus_") or f in ["v_list.txt", "m_list.txt"]:
                try: os.remove(f)
                except: pass

if __name__ == "__main__":
    main()
