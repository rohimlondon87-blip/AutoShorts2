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

# Waktu Live Random antara 45 Menit (2700 detik) sampai 65 Menit (3900 detik)
LIVE_DURATION = random.randint(2700, 3900)

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
    if not drive: return
    
    # Jeda acak biar natural (1 - 5 menit)
    delay = random.randint(1, 5)
    print(f"[⏳] Menunggu {delay} menit sebelum memulai...")
    time.sleep(delay * 60)

    # Ambil bahan dari Drive
    v_files = drive.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false").execute().get('files', [])
    m_files = drive.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio' and trashed=false").execute().get('files', [])

    if not v_files or not m_files:
        print("⛔ Bahan Video/Musik Kosong!")
        return

    # Ambil 1 video dan 1 musik acak
    vid = random.choice(v_files)
    mus = random.choice(m_files)

    print(f"[*] Mendownload Video: {vid['name']}")
    with open("v.mp4", "wb") as f: f.write(drive.files().get_media(fileId=vid['id']).execute())
    
    print(f"[*] Mendownload Musik: {mus['name']}")
    with open("m.mp3", "wb") as f: f.write(drive.files().get_media(fileId=mus['id']).execute())

    rtmp = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    
    durasi_menit = LIVE_DURATION // 60
    durasi_detik = LIVE_DURATION % 60
    print(f"[🚀] SIARAN DIMULAI! Durasi diatur selama: {durasi_menit} menit {durasi_detik} detik.")

    # FFmpeg Command (Looping Terpisah & Anti-Buffering)
    cmd = [
        'ffmpeg', '-y', 
        '-re', 
        '-stream_loop', '-1', '-i', 'v.mp4', 
        '-stream_loop', '-1', '-i', 'm.mp3',
        '-t', str(LIVE_DURATION), 
        '-map', '0:v:0', '-map', '1:a:0', 
        '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '3000k', '-g', '48',
        '-c:a', 'aac', '-b:a', '128k', 
        '-pix_fmt', 'yuv420p', # Format warna standar YouTube
        '-f', 'flv', rtmp
    ]

    subprocess.run(cmd)
    
    print("[✅] Live Selesai dengan sukses.")
    
    # Bersihkan file
    if os.path.exists("v.mp4"): os.remove("v.mp4")
    if os.path.exists("m.mp3"): os.remove("m.mp3")

if __name__ == "__main__":
    main()
