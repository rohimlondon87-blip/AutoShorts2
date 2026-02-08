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

SLOW_MOTION_FACTOR = 1.2
LIVE_DURATION_SEC = random.randint(3300, 3600) 

def find_font():
    # Mencari font secara urut dari yang paling umum ada di Ubuntu
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
    print(f"[*] Downloading: {output_name}...")
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(output_name, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()

def main():
    print("=== MULAI LIVE CINEMA (VERSI DIAGNOSTIK) ===")
    
    # 1. Validasi Dasar
    if not all([TOKEN_B64, SOURCE_ID, MUSIC_ID, STREAM_KEY]):
        print("⛔ ERROR: Secret tidak lengkap. Cek GitHub Secrets Anda.")
        sys.exit(1)

    font_path = find_font()
    if not font_path:
        print("⛔ ERROR: Font tidak ditemukan di server.")
        sys.exit(1)
    
    drive = get_drive_service()
    if not drive: return

    # 2. Ambil Bahan
    v_res = drive.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video'").execute()
    m_res = drive.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio'").execute()
    
    v_files = random.sample(v_res.get('files', []), min(len(v_res.get('files', [])), 2))
    m_files = random.sample(m_res.get('files', []), min(len(m_res.get('files', [])), 5))

    if not v_files or not m_files:
        print("⛔ ERROR: Bahan video/musik tidak ditemukan di Drive.")
        return

    # 3. Proses Download & Playlist
    vid_paths, mus_paths = [], []
    for i, f in enumerate(v_files):
        name = f"v_{i}.mp4"
        download_file(drive, f['id'], name)
        vid_paths.append(name)
    
    for i, f in enumerate(m_files):
        name = f"m_{i}.mp3"
        download_file(drive, f['id'], name)
        mus_paths.append(name)

    # Buat file playlist dengan path absolut (lebih aman untuk FFmpeg)
    curr_dir = os.getcwd()
    with open("video_playlist.txt", "w") as f:
        for v in vid_paths:
            f.write(f"file '{os.path.join(curr_dir, v)}'\n")
    
    with open("music_playlist.txt", "w") as f:
        for m in mus_paths:
            f.write(f"file '{os.path.join(curr_dir, m)}'\n")

    # 4. Bangun Filter FFmpeg (Sangat Hati-hati dengan Karakter)
    # Gunakan format teks yang sangat dasar untuk menghindari Error Status 1
    t_speed = SLOW_MOTION_FACTOR
    a_speed = 1.0 / t_speed
    
    # Filter Teks: REC berkedip dan Timer sederhana
    # Menghindari penggunaan titik dua berlebih dalam drawtext
    text_filter = (
        f"drawtext=text='REC':fontcolor=red:fontsize=40:x=60:y=60:fontfile={font_path}:enable='lt(mod(t,2),1)',"
        f"drawtext=text='LIVE':fontcolor=white:fontsize=40:x=60:y=60:fontfile={font_path}:enable='gt(mod(t,2),1)',"
        f"drawtext=text='%{{pts\\:hms}}':fontcolor=white:fontsize=30:x=w-200:y=60:fontfile={font_path}"
    )

    # 5. Eksekusi Command
    print(f"[*] Menghubungkan ke RTMP YouTube...")
    rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"

    cmd = [
        'ffmpeg', '-y', '-re',
        '-f', 'concat', '-safe', '0', '-i', 'video_playlist.txt',
        '-stream_loop', '-1', '-i', 'music_playlist.txt',
        '-t', str(LIVE_DURATION_SEC),
        '-filter_complex', (
            f'[0:v]scale=1280:720,setpts={t_speed}*PTS,fps=30,{text_filter}[vout]; '
            f'[0:a]atempo={a_speed:.4f},volume=0.3[a1]; '
            f'[1:a]volume=1.0[a2]; [a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '128k', '-f', 'flv', rtmp_url
    ]

    try:
        # Jalankan dan tangkap pesan error jika gagal
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("\n⛔ FFmpeg Gagal!")
            print("--- LOG ERROR LENGKAP ---")
            print(result.stderr)
            print("-------------------------")
        else:
            print("\n[🚀] LIVE SELESAI DENGAN SUKSES!")
    except Exception as e:
        print(f"⛔ Terjadi kesalahan sistem: {e}")
    finally:
        # Pembersihan file
        for f in vid_paths + mus_paths + ["video_playlist.txt", "music_playlist.txt"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
