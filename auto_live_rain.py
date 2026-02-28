import os
import base64
import pickle
import subprocess
import random
import io
import json
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI ---
TOKEN_B64 = os.environ.get('TOKEN_DATA_B') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')
QUOTES_ID = os.environ.get('QUOTES_FILE_ID')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

# Kunci Durasi menjadi 1 Jam (3600 Detik)
LIVE_DURATION_SEC = random.randint(3500, 3700) 

def get_services():
    try:
        t_str = TOKEN_B64.strip().replace('\xa0', '').replace(" ", "").replace("\n", "")
        t_str += '=' * (4 - (len(t_str) % 4))
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token: creds.refresh(Request())
        return build('drive', 'v3', credentials=creds), build('youtube', 'v3', credentials=creds)
    except Exception as e:
        print(f"⛔ GAGAL AUTH: {e}")
        return None, None

def get_quotes(service):
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

def update_live_title(youtube, quote):
    try:
        print("[*] Mencoba mengubah judul Live YouTube...")
        request = youtube.liveBroadcasts().list(part="snippet", broadcastType="persistent", mine=True)
        response = request.execute()
        if not response.get('items'):
            print("    ⚠️ Tidak ditemukan Broadcast default.")
            return
        broadcast = response['items'][0]
        suffix = " | MICRO WILD Live"
        max_len = 100 - len(suffix)
        safe_quote = quote if len(quote) <= max_len else quote[:max_len-3] + "..."
        new_title = safe_quote + suffix
        broadcast['snippet']['title'] = new_title
        youtube.liveBroadcasts().update(part="snippet", body=broadcast).execute()
        print(f"    ✅ Judul Live diubah: '{new_title}'")
    except Exception as e:
        print(f"    ❌ Gagal mengubah judul Live: {e}")

def find_font():
    paths = [
        "/usr/share/fonts/truetype/msttcorefonts/comic.ttf", 
        "/usr/share/fonts/truetype/msttcorefonts/Comic_Sans_MS.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ]
    for p in paths:
        if os.path.exists(p): return p
    return None

def standardize_video(input_path, output_path, quote, font_path):
    try:
        cmd = ['ffprobe', '-loglevel', 'error', '-select_streams', 'v:0', '-show_entries', 'stream_tags=rotate', '-of', 'json', input_path]
        rotation = int(json.loads(subprocess.check_output(cmd).decode('utf-8')).get('streams', [{}])[0].get('tags', {}).get('rotate', 0))
    except: rotation = 0

    filters = []
    if rotation == 90: filters.append("transpose=1")
    elif rotation == 180: filters.append("hflip,vflip")
    elif rotation == 270: filters.append("transpose=2")
    filters.append("scale=w=1280:h=720:force_original_aspect_ratio=increase,crop=1280:720")

    words = quote.split()
    chunks = [" ".join(words[i:i+4]) for i in range(0, len(words), 4)]
    safe_txt = "\\n".join(chunks).replace("'", "").replace(":", "\\:")
    
    t_start = random.randint(3, 10)
    t_end = t_start + random.randint(10, 20)
    
    if font_path:
        dt = (f"drawtext=text='{safe_txt}':fontfile={font_path}:fontcolor=red:"
              f"bordercolor=black:borderw=4:"
              f"shadowcolor=white:shadowx=2:shadowy=2:"
              f"fontsize=50:line_spacing=15:"
              f"x=(w-text_w)/2:y='(h-text_h)/2 + 15*sin(t*2)':"
              f"enable='between(t,{t_start},{t_end})'")
        filters.append(dt)

    v_filter = ",".join(filters)
    cmd = [
        'ffmpeg', '-y', '-i', input_path, '-vf', v_filter,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
        '-c:a', 'aac', '-ar', '44100', '-ac', '2', output_path
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0

def main():
    print(f"=== ROBOT LIVE NATURAL & 3D TEXT ===")
    
    if not STREAM_KEY or len(STREAM_KEY) < 10:
        print("⛔ FATAL ERROR: YOUTUBE_STREAM_KEY KOSONG ATAU SALAH FORMAT!")
        return

    drive, youtube = get_services()
    font_path = find_font()
    if not drive or not youtube: return

    try:
        quotes_pool = get_quotes(drive)
        update_live_title(youtube, random.choice(quotes_pool))
        
        v_files = drive.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false").execute().get('files', [])
        m_files = drive.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio' and trashed=false").execute().get('files', [])

        if not v_files or not m_files:
            print("⛔ Bahan Kosong!")
            return

        random.shuffle(v_files)
        random.shuffle(m_files)

        v_list = ""
        for i, v in enumerate(v_files[:8]):
            raw, fixed = f"raw_{i}.mp4", f"fixed_{i}.mp4"
            print(f"[*] Menyiapkan Video {i+1}...")
            with open(raw, "wb") as f: f.write(drive.files().get_media(fileId=v['id']).execute())
            if standardize_video(raw, fixed, quotes_pool[i % len(quotes_pool)], font_path):
                v_list += f"file '{fixed}'\n"
            if os.path.exists(raw): os.remove(raw)
        with open("v_list.txt", "w") as f: f.write(v_list)

        m_list = ""
        for i, m in enumerate(m_files[:15]): 
            mname = f"mus_{i}.mp3"
            with open(mname, "wb") as f: f.write(drive.files().get_media(fileId=m['id']).execute())
            m_list += f"file '{mname}'\n"
        with open("m_list.txt", "w") as f: f.write(m_list)

        rtmp = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY.strip()}"
        print(f"\n[🚀] MEMULAI STREAMING KE YOUTUBE ({LIVE_DURATION_SEC} Detik)...")

        # PERBAIKAN: Mengubah amix duration dari first menjadi longest, dan mengandalkan parameter -t
        cmd = [
            'ffmpeg', '-y', '-re',
            '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'v_list.txt',
            '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'm_list.txt',
            '-filter_complex', '[0:a]volume=0.3[va];[1:a]volume=1.0[ma];[va][ma]amix=inputs=2:duration=longest[aout]',
            '-t', str(LIVE_DURATION_SEC), # Kunci durasi mati di sini
            '-map', '0:v', '-map', '[aout]',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '2500k', 
            '-g', '48', '-keyint_min', '48', 
            '-c:a', 'aac', '-b:a', '128k',
            '-f', 'flv', rtmp
        ]

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        berhasil_konek = False
        for line in process.stdout:
            if "frame=" in line:
                berhasil_konek = True
                print(f"Streaming: {line.strip()[:80]}", end="\r", flush=True)
            elif "Connection refused" in line or "I/O error" in line or "Server error" in line:
                print(f"\n[⛔ ERROR YOUTUBE]: {line.strip()}")
            elif not berhasil_konek and ("rtmp" in line.lower() or "error" in line.lower()):
                print(f"[INFO]: {line.strip()}")
                
        process.wait()

        if process.returncode != 0:
            print(f"\n❌ STREAMING TERPUTUS! (Kode Error FFmpeg: {process.returncode})")
        else:
            print(f"\n✅ STREAMING SELESAI DENGAN SUKSES (Tercapai Target 1 Jam).")

    except Exception as e:
        print(f"\n⛔ ERROR SISTEM: {e}")
    finally:
        for f in os.listdir():
            if f.startswith("fixed_") or f.startswith("mus_") or f in ["v_list.txt", "m_list.txt"]:
                try: os.remove(f)
                except: pass

if __name__ == "__main__":
    main()