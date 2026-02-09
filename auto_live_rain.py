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

# --- KONFIGURASI SESUAI GITHUB SECRETS ---
TOKEN_B64 = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

# Faktor slow motion (1.2 = 20% lebih lambat)
SLOW_MOTION_FACTOR = 1.2
# Durasi Live: 60 Menit (3600 detik)
LIVE_DURATION_SEC = 3600 

def find_font():
    """Mencari font yang tersedia di server Ubuntu secara otomatis"""
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
    except Exception as e:
        print(f"Auth Error: {e}")
        return None

def download_file(service, file_id, output_name):
    print(f"[*] Mengunduh: {output_name}...")
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(output_name, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()

def get_multiple_random_files(service, folder_id, mime_type, limit=3):
    try:
        q = f"'{folder_id}' in parents and mimeType contains '{mime_type}' and trashed=false"
        res = service.files().list(q=q, fields="files(id, name)").execute()
        files = res.get('files', [])
        if not files: return []
        return random.sample(files, min(len(files), limit))
    except Exception as e:
        print(f"[-] Drive List Error: {e}")
        return []

def main():
    print("=== MULAI LIVE CINEMA FINAL (DOUBLE LOOP) ===")
    
    if not all([TOKEN_B64, SOURCE_ID, MUSIC_ID, STREAM_KEY]):
        print("⛔ ERROR: Secret tidak lengkap di GitHub!")
        sys.exit(1)

    font_path = find_font()
    drive = get_drive_service()
    if not drive: return

    # 1. Pilih Bahan (Ambil beberapa untuk variasi)
    video_files = get_multiple_random_files(drive, SOURCE_ID, "video", limit=3)
    music_files = get_multiple_random_files(drive, MUSIC_ID, "audio", limit=10)
    
    if not video_files or not music_files:
        print("[-] Bahan tidak ditemukan di folder Drive.")
        return

    # 2. Download & Buat Playlist
    vid_paths, mus_paths = [], []
    for i, v in enumerate(video_files):
        vname = f"v_{i}.mp4"
        download_file(drive, v['id'], vname)
        vid_paths.append(vname)
    
    for i, m in enumerate(music_files):
        mname = f"m_{i}.mp3"
        download_file(drive, m['id'], mname)
        mus_paths.append(mname)

    curr_dir = os.path.abspath(os.getcwd())
    with open("v_list.txt", "w") as f:
        for p in vid_paths: f.write(f"file '{os.path.join(curr_dir, p)}'\n")
    with open("m_list.txt", "w") as f:
        for p in mus_paths: f.write(f"file '{os.path.join(curr_dir, p)}'\n")

    # 3. Konfigurasi Filter (REC berkedip & Jam)
    # Filter Teks: REC merah dan Jam (timecode)
    text_f = (
        f"drawtext=text='REC':fontcolor=red:fontsize=40:x=60:y=60:fontfile={font_path}:enable='lt(mod(t,2),1)',"
        f"drawtext=text='LIVE':fontcolor=white:fontsize=40:x=60:y=60:fontfile={font_path}:enable='gt(mod(t,2),1)',"
        f"drawtext=text='%{{pts\\:hms}}':fontcolor=white:fontsize=30:x=w-200:y=60:fontfile={font_path}"
    )

    t_sp = SLOW_MOTION_FACTOR
    a_sp = 1.0 / t_sp
    rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"

    # 4. Command FFmpeg dengan Loop Video & Music
    cmd = [
        'ffmpeg', '-y', '-re',
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'v_list.txt', # VIDEO LOOP
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'm_list.txt', # MUSIC LOOP
        '-t', str(LIVE_DURATION_SEC),
        '-filter_complex', (
            f'[0:v]scale=1280:720,setpts={t_sp}*PTS,fps=30,{text_f}[vout]; '
            f'[0:a]atempo={a_sp:.4f},volume=0.3[a1]; '
            f'[1:a]volume=1.0[a2]; [a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
        '-f', 'flv', rtmp_url
    ]

    try:
        print(f"[*] Mengirim siaran... Target durasi: {LIVE_DURATION_SEC//60} menit.")
        # Menggunakan capture_output=True agar jika gagal kita bisa melihat log error-nya
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("\n⛔ FFmpeg Gagal!")
            print(result.stderr)
        else:
            print("\n[🚀] LIVE SELESAI DENGAN SUKSES!")
    except Exception as e:
        print(f"\n[-] Error Sistem: {e}")
    finally:
        # Pembersihan file sampah
        for f in vid_paths + mus_paths + ["v_list.txt", "m_list.txt"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()