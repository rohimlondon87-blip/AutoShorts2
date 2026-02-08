import os
import base64
import pickle
import subprocess
import random
import sys
import io
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI ---
TOKEN_B64 = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

# Faktor slow motion (1.2 berarti 20% lebih lambat)
SLOW_MOTION_FACTOR = 1.2
# Durasi Live: 60 Menit (3600 detik)
LIVE_DURATION_SEC = 3600 

def find_font():
    """Mencari font yang tersedia di server Ubuntu"""
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
    ]
    for p in paths:
        if os.path.exists(p): return p
    return None

def get_drive_service():
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_B64))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except: return None

def main():
    print("=== MULAI LIVE CINEMA (FIX DURATION LOOP) ===")
    if not all([TOKEN_B64, SOURCE_ID, MUSIC_ID, STREAM_KEY]):
        print("⛔ ERROR: Secret tidak lengkap di GitHub Settings.")
        sys.exit(1)

    font_path = find_font()
    drive = get_drive_service()
    if not drive: 
        print("⛔ ERROR: Gagal akses Google Drive.")
        sys.exit(1)

    # 1. Ambil Bahan (Ambil 3 video agar variatif)
    v_res = drive.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video'").execute()
    m_res = drive.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio'").execute()
    
    v_files = random.sample(v_res.get('files', []), min(len(v_res.get('files', [])), 3))
    m_files = random.sample(m_res.get('files', []), min(len(m_res.get('files', [])), 10))

    if not v_files:
        print("⛔ ERROR: Video tidak ditemukan.")
        return

    # 2. Download Bahan
    v_paths, m_paths = [], []
    for i, f in enumerate(v_files):
        name = f"v_{i}.mp4"
        print(f"[*] Menyiapkan Video: {f['name']}")
        with open(name, "wb") as fh:
            d = MediaIoBaseDownload(fh, drive.files().get_media(fileId=f['id']))
            done = False
            while not done: _, done = d.next_chunk()
        v_paths.append(name)
    
    for i, f in enumerate(m_files):
        name = f"m_{i}.mp3"
        with open(name, "wb") as fh:
            d = MediaIoBaseDownload(fh, drive.files().get_media(fileId=f['id']))
            done = False
            while not done: _, done = d.next_chunk()
        m_paths.append(name)

    # 3. Buat Playlist Path Absolut
    curr_dir = os.path.abspath(os.getcwd())
    with open("v_list.txt", "w") as f:
        for p in v_paths: f.write(f"file '{os.path.join(curr_dir, p)}'\n")
    with open("m_list.txt", "w") as f:
        for p in m_paths: f.write(f"file '{os.path.join(curr_dir, p)}'\n")

    # 4. Filter Teks & Sinkronisasi Kecepatan
    t_sp = SLOW_MOTION_FACTOR
    a_sp = 1.0 / t_sp
    
    text_f = (
        f"drawtext=text='REC':fontcolor=red:fontsize=40:x=60:y=60:fontfile={font_path}:enable='lt(mod(t,2),1)',"
        f"drawtext=text='LIVE':fontcolor=white:fontsize=40:x=60:y=60:fontfile={font_path}:enable='gt(mod(t,2),1)',"
        f"drawtext=text='%{{pts\\:hms}}':fontcolor=white:fontsize=30:x=w-200:y=60:fontfile={font_path}"
    )

    rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"

    # 5. Command FFmpeg dengan Loop Video & Audio
    cmd = [
        'ffmpeg', '-y', '-re',
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'v_list.txt', # Video Loop
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'm_list.txt', # Audio Loop
        '-t', str(LIVE_DURATION_SEC), # Batasi durasi total (1 Jam)
        '-filter_complex', (
            f'[0:v]scale=1280:720,setpts={t_sp}*PTS,fps=30,{text_f}[vout]; '
            f'[0:a]atempo={a_sp:.4f},volume=0.3[a1]; '
            f'[1:a]volume=1.0[a2]; [a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-pix_fmt', 'yuv420p',
        '-g', '60', '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
        '-f', 'flv', rtmp_url
    ]

    try:
        print(f"[*] Memulai siaran langsung ke YouTube (Target: 60 Menit)...")
        # Menggunakan shell=False untuk keamanan dan capture_output=True untuk debug jika gagal
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("\n⛔ FFmpeg Terhenti Pre-mature!")
            print(result.stderr)
        else:
            print("\n[🚀] LIVE SELESAI SESUAI JADWAL!")
    except Exception as e:
        print(f"\n⛔ Terjadi kesalahan: {e}")
    finally:
        # Bersihkan file
        print("[*] Membersihkan file sementara...")
        for f in v_paths + m_paths + ["v_list.txt", "m_list.txt"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
