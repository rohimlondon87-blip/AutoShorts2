import os
import base64
import pickle
import random
import io
import time
import subprocess
import textwrap
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.auth.transport.requests import Request

# --- KONFIGURASI ENV (GITHUB SECRETS) ---
TOKEN_DATA = os.environ.get('TOKEN_DATA_B') or os.environ.get('TOKEN_DATA')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')    # Folder berisi file audio
UPLOTAN_ID = os.environ.get('UPLOTAN_FOLDER_ID') # Folder tujuan upload video
QUOTES_ID = os.environ.get('QUOTES_FILE_ID')    # ID file teks quotes di Drive

# Kita set BATCH_LIMIT menjadi 1 sesuai permintaan (hanya ambil 1 audio)
BATCH_LIMIT = 1 

INTERNAL_BACKUP_QUOTES = [
    "Perjuangan hari ini adalah kekuatan esok.",
    "Jangan menyerah, bangkitlah!",
    "Sukses butuh proses.",
    "Lakukan yang terbaik hari ini."
]

def get_drive_service():
    try:
        if not TOKEN_DATA:
            print("⛔ ERROR: Token tidak ditemukan!")
            return None
        
        t_str = TOKEN_DATA.strip()
        pad = len(t_str) % 4
        if pad: t_str += '=' * (4 - pad)
        
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error: {e}")
        return None

def get_available_fonts():
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
    ]
    available = [p for p in paths if os.path.exists(p)]
    return available if available else ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]

def get_quotes(service):
    if not QUOTES_ID: return INTERNAL_BACKUP_QUOTES
    try:
        file_meta = service.files().get(fileId=QUOTES_ID).execute()
        mime_type = file_meta.get('mimeType', '')
        fh = io.BytesIO()
        if 'application/vnd.google-apps' in mime_type:
            request = service.files().export_media(fileId=QUOTES_ID, mimeType='text/plain')
        else:
            request = service.files().get_media(fileId=QUOTES_ID)
        
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        content = fh.getvalue().decode('utf-8-sig')
        lines = [l.strip() for l in content.splitlines() if len(l.strip()) > 5]
        return lines if lines else INTERNAL_BACKUP_QUOTES
    except:
        return INTERNAL_BACKUP_QUOTES

def get_media_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        return float(subprocess.check_output(cmd).decode().strip())
    except: return 0

def generate_random_color():
    return "#{:06x}".format(random.randint(0, 0xFFFFFF))

def render_video(audio_path, video_output, text, font_path):
    duration = get_media_duration(audio_path)
    if duration <= 0: return False

    # Warna acak untuk gradasi
    c1 = generate_random_color()
    c2 = generate_random_color()
    text_color = "white"
    
    # Bungkus teks untuk landscape (lebih lebar)
    wrapped_text = "\n".join(textwrap.wrap(text, width=50))
    safe_text = wrapped_text.replace("'", "").replace(":", "\\:")

    # Filter Complex FFmpeg:
    # 1. [0:v] Buat background hitam 1920x1080 (Landscape)
    # 2. Drawgradient: Tambahkan gradasi warna acak
    # 3. [1:a] Showwaves: Buat visualizer audio berbentuk gelombang
    # 4. Overlay: Gabungkan visualizer di atas background
    # 5. Drawtext: Tempelkan teks di tengah
    v_filter = (
        f"[0:v]drawgradient=c1={c1}:c2={c2}:shape=linear:x1=0:y1=0:x2=1920:y2=1080[bg];"
        f"[1:a]showwaves=s=1920x300:mode=line:colors=white@0.6:scale=log[waves];"
        f"[bg][waves]overlay=0:H-350[tmp];"
        f"[tmp]drawtext=text='{safe_text}':fontfile={font_path}:fontcolor={text_color}:fontsize=50:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-100:box=1:boxcolor=black@0.4:boxborderw=30:line_spacing=15[vout]"
    )

    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', f'color=c=black:s=1920x1080:d={duration}', # Source video 16:9
        '-i', audio_path, # Source audio
        '-filter_complex', v_filter,
        '-map', '[vout]',
        '-map', '1:a',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '25',
        '-c:a', 'aac', '-b:a', '192k',
        '-shortest', video_output
    ]

    print(f"[*] Rendering Landscape: {c1} -> {c2} | Visualizer Aktif")
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        print(f"[-] Error: {res.stderr.decode()[-500:]}")
        return False
    return True

def main():
    service = get_drive_service()
    if not service: return

    print("=== STARTING LANDSCAPE RENDER WITH VISUALIZER ===")
    
    m_res = service.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio'").execute()
    m_files = m_res.get('files', [])
    quotes_pool = get_quotes(service)
    fonts = get_available_fonts()

    if not m_files:
        print("⛔ Tidak ada audio di Drive.")
        return

    # Sesuai permintaan: Hanya ambil 1 audio saja (acak dari folder)
    random.shuffle(m_files)
    f_audio = m_files[0] 
    
    quote = random.choice(quotes_pool)
    font = random.choice(fonts)
    
    audio_local = "input_audio.mp3"
    video_local = f"Landscape_Render_{int(time.time())}.mp4"

    try:
        print(f"[*] Mengambil audio: {f_audio['name']}")
        with open(audio_local, "wb") as f:
            f.write(service.files().get_media(fileId=f_audio['id']).execute())
        
        if render_video(audio_local, video_local, quote, font):
            print(f"[+] Mengunggah hasil render landscape...")
            meta = {'name': video_local, 'parents': [UPLOTAN_ID]}
            media = MediaFileUpload(video_local, mimetype='video/mp4')
            service.files().create(body=meta, media_body=media).execute()
            print(f"✅ SUKSES!")
        else:
            print(f"❌ Gagal render.")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        for f in [audio_local, video_local]:
            if os.path.exists(f): os.remove(f)

    print("\n[✨] Selesai.")

if __name__ == "__main__":
    main()
