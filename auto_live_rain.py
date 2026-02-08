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

# --- KONFIGURASI SESUAI FOTO GITHUB ---
TOKEN_B64 = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

SLOW_MOTION_FACTOR = 1.2
LIVE_DURATION_SEC = random.randint(3300, 3600) 

def find_font():
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
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
    print("=== MULAI LIVE CINEMA FINAL ROBUST ===")
    if not all([TOKEN_B64, SOURCE_ID, MUSIC_ID, STREAM_KEY]):
        print("⛔ ERROR: Secret tidak lengkap.")
        sys.exit(1)

    font_path = find_font()
    drive = get_drive_service()
    if not drive: return

    # Ambil Bahan
    v_files = drive.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video'").execute().get('files', [])
    m_files = drive.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio'").execute().get('files', [])

    v_samp = random.sample(v_files, min(len(v_files), 3))
    m_samp = random.sample(m_files, min(len(m_files), 10))

    # Download
    v_paths, m_paths = [], []
    for i, f in enumerate(v_samp):
        n = f"v_{i}.mp4"
        with open(n, "wb") as fh:
            d = MediaIoBaseDownload(fh, drive.files().get_media(fileId=f['id']))
            done = False
            while not done: _, done = d.next_chunk()
        v_paths.append(n)
    
    for i, f in enumerate(m_samp):
        n = f"m_{i}.mp3"
        with open(n, "wb") as fh:
            d = MediaIoBaseDownload(fh, drive.files().get_media(fileId=f['id']))
            done = False
            while not done: _, done = d.next_chunk()
        m_paths.append(n)

    # Playlist
    with open("v_list.txt", "w") as f:
        for p in v_paths: f.write(f"file '{os.path.abspath(p)}'\n")
    with open("m_list.txt", "w") as f:
        for p in m_paths: f.write(f"file '{os.path.abspath(p)}'\n")

    # Filter Teks (REC Berkedip & Jam)
    # Menggunakan metode join untuk menghindari masalah Status 183
    text_f = (
        f"drawtext=text='REC':fontcolor=red:fontsize=40:x=60:y=60:fontfile={font_path}:enable='lt(mod(t,2),1)',"
        f"drawtext=text='LIVE':fontcolor=white:fontsize=40:x=60:y=60:fontfile={font_path}:enable='gt(mod(t,2),1)',"
        f"drawtext=text='%{{pts\\:hms}}':fontcolor=white:fontsize=30:x=w-200:y=60:fontfile={font_path}"
    )

    t_sp = SLOW_MOTION_FACTOR
    a_sp = 1.0 / t_sp
    rtmp = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"

    cmd = [
        'ffmpeg', '-y', '-re',
        '-f', 'concat', '-safe', '0', '-i', 'v_list.txt',
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'm_list.txt',
        '-t', str(LIVE_DURATION_SEC),
        '-filter_complex', (
            f'[0:v]scale=1280:720,setpts={t_sp}*PTS,fps=30,{text_f}[vout]; '
            f'[0:a]atempo={a_sp:.4f},volume=0.3[a1]; '
            f'[1:a]volume=1.2[a2]; [a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '128k', '-f', 'flv', rtmp
    ]

    try:
        subprocess.run(cmd, check=True)
        print("\n[🚀] LIVE SELESAI!")
    except subprocess.CalledProcessError as e:
        print(f"\n[-] FFmpeg Fail. Log: {e.output}")
    finally:
        for f in v_paths + m_paths + ["v_list.txt", "m_list.txt"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
