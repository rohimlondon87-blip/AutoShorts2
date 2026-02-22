import os
import base64
import pickle
import random
import io
import sys
import subprocess
import textwrap
import time
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.auth.transport.requests import Request

# --- KONFIGURASI BRANDING: MICRO WILD ---
# Hanya menggunakan satu Token (A)
TOKEN_DATA = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')      
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')   
UPLOTAN_ID = os.environ.get('UPLOTAN_FOLDER_ID') 
QUOTES_ID = os.environ.get('QUOTES_FILE_ID') 

MAX_DURATION = 30 
BATCH_LIMIT = 5 

# Cadangan jika Drive Gagal Total
INTERNAL_BACKUP = [
    "Perjuangan hari ini adalah kekuatan esok.",
    "Konsistensi adalah kunci keberhasilan.",
    "Jangan berhenti saat lelah, berhentilah saat selesai.",
    "MICRO WILD: Menjelajah tanpa batas."
]

def get_drive_service():
    """Autentikasi murni menggunakan TOKEN_DATA (Token A)."""
    try:
        if not TOKEN_DATA:
            print("⛔ ERROR: TOKEN_DATA (Token A) tidak ditemukan di Secrets!")
            return None
        
        t_str = TOKEN_DATA.strip().replace('\xa0', '').replace(" ", "")
        pad = len(t_str) % 4
        if pad: t_str += '=' * (4 - pad)
        
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            print("[*] Menyegarkan akses token...")
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"⛔ Auth Error: {e}")
        return None

def find_font():
    """Mencari font sistem untuk Linux (GitHub Actions)."""
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
    ]
    for p in paths:
        if os.path.exists(p): return p
    return None

def get_video_rotation(path):
    """Mendeteksi rotasi video (Paten Anti-Terbalik)."""
    try:
        cmd = [
            'ffprobe', '-loglevel', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream_tags=rotate', '-of', 'json', path
        ]
        result = subprocess.check_output(cmd).decode('utf-8')
        data = json.loads(result)
        tags = data.get('streams', [{}])[0].get('tags', {})
        return int(tags.get('rotate', 0))
    except: return 0

def get_quotes_robust(service):
    """Mengambil quotes dari Drive secara acak."""
    if not QUOTES_ID: return INTERNAL_BACKUP
    print(f"[*] Mengambil Quotes dari Drive...")
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
        return lines if lines else INTERNAL_BACKUP
    except: return INTERNAL_BACKUP

def render_shorts(v_in, a_in, v_out, text, v_start, a_start, font_p):
    """Rendering Shorts dengan Paten Portrait 9:16 & Fix Rotation."""
    wrapped = "\n".join(textwrap.wrap(text, width=20))
    safe_txt = wrapped.replace("'", "").replace(":", "\\:")
    
    rotation = get_video_rotation(v_in)
    rot_filter = ""
    if rotation == 90: rot_filter = "transpose=1,"
    elif rotation == 180: rot_filter = "hflip,vflip,"
    elif rotation == 270: rot_filter = "transpose=2,"

    # Filter: Rotasi -> Portrait 9:16 -> DrawText Tengah
    v_filter = (
        f"{rot_filter}scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=text='{safe_txt}':fontcolor=white:fontsize=75:fontfile={font_p}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.6:boxborderw=40:line_spacing=20"
    )

    cmd = [
        'ffmpeg', '-y',
        '-ss', str(round(v_start, 2)), '-t', str(MAX_DURATION), '-i', v_in,
        '-ss', str(round(a_start, 2)), '-t', str(MAX_DURATION), '-i', a_in,
        '-filter_complex', f'[0:v]{v_filter}[vout]; [0:a]volume=0.3[a1]; [1:a]volume=1.2[a2]; [a1][a2]amix=inputs=2:duration=first[aout]',
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', '-t', str(MAX_DURATION), v_out 
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0

def main():
    print("=== ROBOT SHORTS: MICRO WILD (FIXED PORTRAIT) ===")
    service = get_drive_service()
    font_path = find_font()
    if not service or not font_path: return

    try:
        quotes_pool = get_quotes_robust(service) 
        v_res = service.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video'").execute()
        m_res = service.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio'").execute()
        
        v_files = v_res.get('files', [])
        m_files = m_res.get('files', [])
        
        if not v_files or not m_files:
            print("⛔ Bahan Video/Musik tidak ditemukan.")
            return
            
        random.shuffle(v_files)
        random.shuffle(m_files)
    except Exception as e:
        print(f"⛔ Drive Error: {e}")
        return

    limit = min(BATCH_LIMIT, len(v_files))
    for i in range(limit):
        f_vid = v_files[i]
        f_mus = m_files[i % len(m_files)]
        txt = random.choice(quotes_pool)
        
        print(f"\n[🚀] Memulai Render {i+1}/{limit}")
        print(f"    🎬 Video : {f_vid['name']}")
        print(f"    📝 Quotes: {txt[:30]}...")

        t_v, t_a = f"v{i}.mp4", f"a{i}.mp3"
        out_name = f"Shorts_{int(time.time())}_{i}.mp4"

        try:
            # Download bahan
            with open(t_v, "wb") as f: f.write(service.files().get_media(fileId=f_vid['id']).execute())
            with open(t_a, "wb") as f: f.write(service.files().get_media(fileId=f_mus['id']).execute())
            
            # Ambil potongan acak
            dv = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', t_v]).decode().strip())
            vs = random.uniform(0, max(0, dv - MAX_DURATION - 2))
            
            if render_shorts(t_v, t_a, out_name, txt, vs, 0, font_path):
                meta = {'name': out_name, 'parents': [UPLOTAN_ID]}
                media = MediaFileUpload(out_name, mimetype='video/mp4')
                service.files().create(body=meta, media_body=media).execute()
                print(f"    ✅ BERHASIL UPLOAD KE DRIVE")
            else:
                print("    ❌ Gagal Rendering")

        except Exception as e:
            print(f"    ❌ Error: {e}")
        finally:
            for f in [t_v, t_a, out_name]:
                if os.path.exists(f): os.remove(f)

    print("\n[✨] Semua tugas MICRO WILD Selesai.")

if __name__ == "__main__":
    main()