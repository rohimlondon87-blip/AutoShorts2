import os
import base64
import pickle
import random
import io
import subprocess
import textwrap
import time
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.auth.transport.requests import Request

# --- KONFIGURASI MICRO WILD ---
TOKEN_DATA = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')      
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')   
UPLOTAN_ID = os.environ.get('UPLOTAN_FOLDER_ID') 
QUOTES_ID = os.environ.get('QUOTES_FILE_ID') 

# Durasi ditetapkan 35 detik sesuai permintaan
MAX_DURATION = 35 
BATCH_LIMIT = 5 

# Cadangan kalimat jika gagal baca dari Drive
INTERNAL_BACKUP = [
    "Perjuangan hari ini adalah kekuatan esok.",
    "Lelah itu manusiawi, menyerah itu pilihan.",
    "Bekerja keraslah dalam diam, biarkan suksesmu bersuara."
]

def get_drive_service():
    try:
        if not TOKEN_DATA: return None
        t_str = TOKEN_DATA.strip().replace('\xa0', '').replace(" ", "")
        pad = len(t_str) % 4
        if pad: t_str += '=' * (4 - pad)
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error: {e}")
        return None

def get_quotes_robust(service):
    """Mengambil teks/quotes acak dari Google Drive."""
    if not QUOTES_ID: return INTERNAL_BACKUP
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
        # Filter baris kosong
        lines = [l.strip() for l in content.splitlines() if len(l.strip()) > 5]
        if not lines: return INTERNAL_BACKUP
        
        random.shuffle(lines)
        return lines
    except Exception:
        return INTERNAL_BACKUP

def get_video_rotation(path):
    """Mendeteksi rotasi video (Paten Anti-Terbalik)."""
    try:
        cmd = ['ffprobe', '-loglevel', 'error', '-select_streams', 'v:0', '-show_entries', 'stream_tags=rotate', '-of', 'json', path]
        result = subprocess.check_output(cmd).decode('utf-8')
        tags = json.loads(result).get('streams', [{}])[0].get('tags', {})
        return int(tags.get('rotate', 0))
    except: return 0

def get_media_duration(file_path):
    """Mendapatkan total durasi media untuk perhitungan acak."""
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        return float(subprocess.check_output(cmd).decode().strip())
    except: return 0

def render_shorts(v_in, a_in, v_out, text, v_start, a_start, font_p):
    wrapped = "\n".join(textwrap.wrap(text, width=20))
    safe_txt = wrapped.replace("'", "").replace(":", "\\:")
    rotation = get_video_rotation(v_in)
    
    # Perbaikan posisi otomatis
    rot_filter = ""
    if rotation == 90: rot_filter = "transpose=1,"
    elif rotation == 180: rot_filter = "hflip,vflip,"
    elif rotation == 270: rot_filter = "transpose=2,"

    # Filter Teks Besar & Posisi Crop 9:16
    v_filter = (
        f"{rot_filter}scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=text='{safe_txt}':fontcolor=white:fontsize=85:fontfile={font_p}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.6:boxborderw=40:line_spacing=20"
    )

    cmd = [
        'ffmpeg', '-y', 
        '-ss', str(round(v_start, 2)), '-t', str(MAX_DURATION), '-i', v_in,
        '-stream_loop', '-1', '-ss', str(round(a_start, 2)), '-t', str(MAX_DURATION), '-i', a_in,
        '-filter_complex', f'[0:v]{v_filter}[vout]; [0:a]volume=0.3[a1]; [1:a]volume=1.2[a2]; [a1][a2]amix=inputs=2:duration=first[aout]',
        '-map', '[vout]', '-map', '[aout]', 
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', v_out 
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0

def main():
    print("=== MICRO WILD: AUTO RENDER SUPER ENGINE ===")
    service = get_drive_service()
    if not service: return

    try:
        quotes_pool = get_quotes_robust(service)
        
        v_res = service.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false").execute().get('files', [])
        m_res = service.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio' and trashed=false").execute().get('files', [])
        
        if not v_res or not m_res:
            print("⛔ Bahan di Drive tidak lengkap (Video/Musik kosong).")
            return

        random.shuffle(v_res)
        random.shuffle(m_res)
        
        for i in range(min(BATCH_LIMIT, len(v_res))):
            f_vid = v_res[i]
            f_mus = m_res[i % len(m_res)]
            txt = random.choice(quotes_pool) # Ambil teks acak dari pool
            out_name = f"MICRO_WILD_{int(time.time())}_{i}.mp4"
            
            print(f"\n[▶] Memproses Video {i+1}/{BATCH_LIMIT}")
            print(f"    🎥 File: {f_vid['name']}")
            print(f"    🎵 Lagu: {f_mus['name']}")
            
            # Download bahan
            with open("temp_v.mp4", "wb") as f: f.write(service.files().get_media(fileId=f_vid['id']).execute())
            with open("temp_a.mp3", "wb") as f: f.write(service.files().get_media(fileId=f_mus['id']).execute())
            
            # Hitung Random Start
            dur_v = get_media_duration("temp_v.mp4")
            dur_a = get_media_duration("temp_a.mp3")
            
            vs = random.uniform(0, max(0, dur_v - MAX_DURATION - 2))
            as_ = random.uniform(0, max(0, dur_a - MAX_DURATION - 2))
            
            # Keterangan Log Laporan
            print(f"    ⏱️  Video dimulai dari : {vs:.2f} detik")
            print(f"    ⏱️  Audio dimulai dari : {as_:.2f} detik")
            print(f"    📝 Teks / Deskripsi   : \"{txt}\"")
            
            # Render
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if render_shorts("temp_v.mp4", "temp_a.mp3", out_name, txt, vs, as_, font_path):
                # Upload ke folder UPLOTAN dengan "description" sesuai teks
                file_metadata = {
                    'name': out_name,
                    'parents': [UPLOTAN_ID],
                    'description': txt  # <-- Robot Uploader akan baca ini jadi judul!
                }
                media = MediaFileUpload(out_name, mimetype='video/mp4')
                service.files().create(body=file_metadata, media_body=media).execute()
                print(f"    ✅ Sukses Upload ke Drive.")
            else:
                print("    ❌ Gagal Render Video.")
            
            # Bersihkan file sampah
            for f in ["temp_v.mp4", "temp_a.mp3", out_name]:
                if os.path.exists(f): os.remove(f)

    except Exception as e:
        print(f"⛔ Error Utama: {e}")

if __name__ == "__main__":
    main()
