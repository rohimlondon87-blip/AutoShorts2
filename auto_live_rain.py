import os
import base64
import pickle
import subprocess
import json
import random
import sys
import io
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request
import google.generativeai as genai

# --- KONFIGURASI SECRETS ---
TOKEN_B64 = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID') 
API_KEY = os.environ.get('GEMINI_API_KEY')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

SLOW_MOTION_FACTOR = 1.2
LIVE_DURATION_SEC = random.randint(3300, 3600) 

def find_font():
    """Mencari lokasi font di server Ubuntu secara otomatis"""
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

def validate_environment():
    missing = []
    if not SOURCE_ID: missing.append("SOURCE_LIVE_ID")
    if not MUSIC_ID: missing.append("MUSIC_FOLDER_ID")
    if not STREAM_KEY: missing.append("YOUTUBE_STREAM_KEY")
    if not TOKEN_B64: missing.append("TOKEN_DATA")
    if missing:
        print(f"⛔ ERROR: Secret belum lengkap: {', '.join(missing)}")
        sys.exit(1)
    if API_KEY:
        genai.configure(api_key=API_KEY)

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
    q = f"'{folder_id}' in parents and mimeType contains '{mime_type}' and trashed=false"
    res = service.files().list(q=q, fields="files(id, name)").execute()
    files = res.get('files', [])
    if not files: return []
    return random.sample(files, min(len(files), limit))

def main():
    print("=== MULAI LIVE CINEMA ROBUST ===")
    validate_environment()
    
    font_path = find_font()
    if not font_path:
        print("⛔ ERROR: Font tidak ditemukan!")
        sys.exit(1)
    print(f"✅ Menggunakan Font: {font_path}")

    drive = get_drive_service()
    if not drive: return

    # 1. Pilih Bahan
    video_files = get_multiple_random_files(drive, SOURCE_ID, "video", limit=3)
    music_files = get_multiple_random_files(drive, MUSIC_ID, "audio", limit=10)
    
    if not video_files or not music_files:
        print("[-] Bahan tidak lengkap di Drive.")
        return

    # 2. Download & Buat Playlist
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

    # 3. Filter Overlay Cinema (REC & Frame)
    # - box border diperbaiki agar tidak error sintaks
    overlay_filter = (
        f"drawtext=text='● REC':fontcolor=red:fontsize=40:x=60:y=60:fontfile={font_path}:enable='lt(mod(t,2),1)', "
        f"drawtext=text='REC':fontcolor=white:fontsize=40:x=110:y=60:fontfile={font_path}:enable='gt(mod(t,2),1)', "
        "drawbox=x=40:y=40:w=100:h=4:color=white@0.8:t=fill, "
        "drawbox=x=40:y=40:w=4:h=100:color=white@0.8:t=fill, "
        "drawbox=x=w-140:y=40:w=100:h=4:color=white@0.8:t=fill, "
        "drawbox=x=w-44:y=40:w=4:h=100:color=white@0.8:t=fill, "
        "drawbox=x=40:y=h-44:w=100:h=4:color=white@0.8:t=fill, "
        "drawbox=x=40:y=h-140:w=4:h=100:color=white@0.8:t=fill, "
        "drawbox=x=w-140:y=h-44:w=100:h=4:color=white@0.8:t=fill, "
        "drawbox=x=w-44:y=h-140:w=4:h=100:color=white@0.8:t=fill, "
        f"drawtext=text='%{{pts\\:hms}}':fontcolor=white:fontsize=35:x=w-230:y=60:fontfile={font_path}"
    )

    # 4. Stream Command
    print(f"[*] Mengirim siaran ke YouTube... (Durasi: {LIVE_DURATION_SEC//60} Menit)")
    cmd = [
        'ffmpeg', '-re', '-fflags', '+genpts+igndts',
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'video_playlist.txt',
        '-stream_loop', '-1', '-i', 'music_playlist.txt',
        '-t', str(LIVE_DURATION_SEC),
        '-filter_complex', (
            f'[0:v]scale=1280:720,setpts={SLOW_MOTION_FACTOR}*PTS,fps=30,{overlay_filter}[vout]; '
            f'[0:a]atempo={audio_speed},volume=0.3[a1]; '
            f'[1:a]volume=1.2[a2]; '
            f'[a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
        '-b:v', '2500k', '-maxrate', '2500k', '-bufsize', '5000k',
        '-pix_fmt', 'yuv420p', '-g', '60', '-r', '30',
        '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
        '-f', 'flv', f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    ]

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        for line in process.stdout:
            if "frame=" in line: 
                print(line.strip(), end='\r')
            elif "Error" in line:
                print(f"\n[!] Log: {line.strip()}")
        process.wait()
        print("\n[🚀] LIVE SELESAI!")
    except Exception as e:
        print(f"\n[-] Fatal Error: {e}")
    finally:
        # Bersihkan file sampah
        files_to_clean = vid_list + mus_list + ["video_playlist.txt", "music_playlist.txt"]
        for f in files_to_clean:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()

