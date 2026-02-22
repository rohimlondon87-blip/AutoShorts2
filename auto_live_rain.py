import os
import base64
import pickle
import subprocess
import random
import time
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# --- KONFIGURASI MICRO WILD ---
TOKEN_DATA = os.environ.get('TOKEN_DATA_B') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')
LIVE_DURATION = 3600 # 1 Jam

def get_services():
    t_str = TOKEN_DATA.strip().replace('\xa0', '').replace(" ", "")
    pad = len(t_str) % 4
    if pad: t_str += '=' * (4 - pad)
    creds = pickle.loads(base64.b64decode(t_str))
    if creds.expired: creds.refresh(Request())
    return build('drive', 'v3', credentials=creds)

def main():
    print("=== MICRO WILD: LIVE STREAM ENGINE ACTIVE ===")
    drive = get_services()
    
    # Jeda acak biar natural
    delay = random.randint(1, 5)
    print(f"[⏳] Menunggu {delay} menit...")
    time.sleep(delay * 60)

    v_files = drive.files().list(q=f"'{SOURCE_ID}' in parents").execute().get('files', [])
    m_files = drive.files().list(q=f"'{MUSIC_ID}' in parents").execute().get('files', [])

    # Ambil 1 video dan 1 musik acak
    vid = random.choice(v_files)
    mus = random.choice(m_files)

    with open("v.mp4", "wb") as f: f.write(drive.files().get_media(fileId=vid['id']).execute())
    with open("m.mp3", "wb") as f: f.write(drive.files().get_media(fileId=mus['id']).execute())

    rtmp = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    
    # FFmpeg Command (Looping & Anti-Buffering)
    cmd = [
        'ffmpeg', '-re', '-stream_loop', '-1', '-i', 'v.mp4', '-stream_loop', '-1', '-i', 'm.mp3',
        '-t', str(LIVE_DURATION), '-map', '0:v', '-map', '1:a',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '3000k', '-g', '48',
        '-c:a', 'aac', '-b:a', '128k', '-f', 'flv', rtmp
    ]

    print("[🚀] SIARAN DIMULAI...")
    subprocess.run(cmd)
    print("[✅] Live Selesai.")

if __name__ == "__main__":
    main()