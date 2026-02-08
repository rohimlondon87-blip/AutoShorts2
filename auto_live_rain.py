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
import google.generativeai as genai

# --- KONFIGURASI SINKRON DENGAN .YML & FOTO GITHUB ---
TOKEN_B64 = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID') # Sudah disamakan dengan foto
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')
API_KEY = os.environ.get('GEMINI_API_KEY')

SLOW_MOTION_FACTOR = 1.2
LIVE_DURATION_SEC = random.randint(3300, 3600) 

def find_font():
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
    ]
    for p in paths:
        if os.path.exists(p): return p
    return None

def validate_environment():
    print("[*] Memeriksa Kesiapan Live...")
    missing = []
    if not TOKEN_B64: missing.append("TOKEN_DATA")
    if not SOURCE_ID: missing.append("SOURCE_LIVE_ID")
    if not MUSIC_ID: missing.append("MUSIC_FOLDER_ID")
    if not STREAM_KEY: missing.append("YOUTUBE_STREAM_KEY")
    
    if missing:
        print(f"⛔ ERROR: Data berikut tidak terkirim dari GitHub Actions ke Skrip:")
        for m in missing:
            print(f"   - {m}")
        print("\nPastikan nama di file .yml bagian 'env:' sama dengan nama di GitHub Secrets.")
        sys.exit(1)
    
    print("✅ Semua kunci Secret terdeteksi.")
    if API_KEY:
        genai.configure(api_key=API_KEY)
        print("✅ Gemini AI: Aktif")

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
    print("=== MULAI LIVE CINEMA ROBUST (FIX NAMES) ===")
    validate_environment()
    
    font_path = find_font()
    drive = get_drive_service()
    if not drive: return

    # 1. Ambil Bahan
    video_files = get_multiple_random_files(drive, SOURCE_ID, "video", limit=3)
    music_files = get_multiple_random_files(drive, MUSIC_ID, "audio", limit=10)
    
    if not video_files:
        print(f"[-] Folder Video (ID: {SOURCE_ID}) kosong atau tidak bisa diakses.")
        return
    if not music_files:
        print(f"[-] Folder Musik (ID: {MUSIC_ID}) kosong atau tidak bisa diakses.")
        return

    # 2. Persiapan Playlist
    vid_list, mus_list = [], []
    for i, v in enumerate(video_files):
        vname = f"v_{i}.mp4"
        download_file(drive, v['id'], vname)
        vid_list.append(vname)
    with open("video_playlist.txt", "w") as f:
        for vn in vid_list: f.write(f"file '{vn}'\n")

    for i, m in enumerate(music_files):
        mname = f"m_{i}.mp3"
        download_file(drive, m['id'], mname)
        mus_list.append(mname)
    with open("music_playlist.txt", "w") as f:
        for mn in mus_list: f.write(f"file '{mn}'\n")

    audio_speed = max(0.5, 1.0 / SLOW_MOTION_FACTOR)
    overlay_filter = (
        f"drawtext=text='● REC':fontcolor=red:fontsize=40:x=60:y=60:fontfile={font_path}:enable='lt(mod(t,2),1)', "
        f"drawtext=text='REC':fontcolor=white:fontsize=40:x=110:y=60:fontfile={font_path}:enable='gt(mod(t,2),1)', "
        f"drawtext=text='%{{pts\\:hms}}':fontcolor=white:fontsize=35:x=w-230:y=60:fontfile={font_path}"
    )

    # 3. Jalankan Streaming
    print(f"[*] Mengirim siaran... Durasi: {LIVE_DURATION_SEC//60} Menit")
    cmd = [
        'ffmpeg', '-re', '-f', 'concat', '-safe', '0', '-i', 'video_playlist.txt',
        '-stream_loop', '-1', '-i', 'music_playlist.txt',
        '-t', str(LIVE_DURATION_SEC),
        '-filter_complex', (
            f'[0:v]scale=1280:720,setpts={SLOW_MOTION_FACTOR}*PTS,fps=30,{overlay_filter}[vout]; '
            f'[0:a]atempo={audio_speed},volume=0.3[a1]; '
            f'[1:a]volume=1.2[a2]; [a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
        '-pix_fmt', 'yuv420p', '-g', '60', '-c:a', 'aac', '-ar', '44100',
        '-f', 'flv', f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    ]

    try:
        subprocess.run(cmd, check=True)
        print("\n[🚀] LIVE SELESAI!")
    except Exception as e:
        print(f"\n[-] Error Streaming: {e}")
    finally:
        for f in vid_list + mus_list + ["video_playlist.txt", "music_playlist.txt"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()

