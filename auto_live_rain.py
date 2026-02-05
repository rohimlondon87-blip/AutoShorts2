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

# --- KONFIGURASI ---
TOKEN_B64 = os.environ.get('TOKEN_DATA_LIVE') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID') 
API_KEY = os.environ.get('GEMINI_API_KEY')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

SLOW_MOTION_FACTOR = 1.2
LIVE_DURATION_SEC = random.randint(3300, 3600) 

def validate_environment():
    missing = []
    if not SOURCE_ID: missing.append("SOURCE_LIVE_ID")
    if not MUSIC_ID: missing.append("MUSIC_FOLDER_ID")
    if not STREAM_KEY: missing.append("YOUTUBE_STREAM_KEY")
    if not TOKEN_B64: missing.append("TOKEN_DATA")
    if missing:
        print(f"⛔ ERROR: Secret belum lengkap: {', '.join(missing)}")
        sys.exit(1)
    genai.configure(api_key=API_KEY)

def get_drive_service():
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_B64))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except: return None

def download_file(service, file_id, output_name):
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(output_name, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()

def get_multiple_random_files(service, folder_id, mime_type, limit=5):
    q = f"'{folder_id}' in parents and mimeType contains '{mime_type}' and trashed=false"
    res = service.files().list(q=q, fields="files(id, name)").execute()
    files = res.get('files', [])
    if not files: return []
    return random.sample(files, min(len(files), limit))

def main():
    print(f"=== MULAI LIVE SYNC ({LIVE_DURATION_SEC//60} MENIT) ===")
    validate_environment()
    drive = get_drive_service()
    if not drive: return

    # 1. Pilih Bahan
    video_files = get_multiple_random_files(drive, SOURCE_ID, "video", limit=3)
    music_files = get_multiple_random_files(drive, MUSIC_ID, "audio", limit=10)
    if not video_files or not music_files: return

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

    # 3. Stream Command (Fokus pada Sinkronisasi Timestamp)
    print(f"[*] Mengirim siaran... (Memaksa sinkronisasi gambar)")
    cmd = [
        'ffmpeg', 
        '-re',                          # Baca input sesuai durasi asli
        '-fflags', '+genpts+igndts',    # Paksa buat ulang timestamp agar tidak macet
        '-avoid_negative_ts', 'make_zero',
        
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'video_playlist.txt',
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'music_playlist.txt',
        
        '-t', str(LIVE_DURATION_SEC),
        
        '-filter_complex', (
            f'[0:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setpts={SLOW_MOTION_FACTOR}*PTS,fps=30[vout]; '
            f'[0:a]atempo={audio_speed},volume=0.3[a1]; '
            f'[1:a]volume=1.2[a2]; '
            f'[a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        
        '-map', '[vout]', '-map', '[aout]',
        
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
        '-b:v', '2000k', '-maxrate', '2000k', '-bufsize', '4000k',
        '-pix_fmt', 'yuv420p', 
        '-g', '60',                     # Keyframe setiap 2 detik (Wajib YouTube)
        '-r', '30',                     # Paksa frame rate output konstan
        
        '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
        '-f', 'flv', f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    ]

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        for line in process.stdout:
            if "frame=" in line: print(line.strip(), end='\r')
        process.wait()
        print("\n[🚀] LIVE SELESAI!")
    except Exception as e:
        print(f"\n[-] Error: {e}")
    finally:
        for f in vid_list + mus_list + ["video_playlist.txt", "music_playlist.txt"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
