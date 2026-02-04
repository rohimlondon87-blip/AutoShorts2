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

# FAKTOR SLOW MOTION (Sesuaikan 1.2 - 1.5)
SLOW_MOTION_FACTOR = 1.3
LIVE_DURATION_SEC = random.randint(3300, 3600) 

def validate_environment():
    missing = []
    if not SOURCE_ID: missing.append("SOURCE_LIVE_ID")
    if not MUSIC_ID: missing.append("MUSIC_FOLDER_ID")
    if not STREAM_KEY: missing.append("YOUTUBE_STREAM_KEY")
    if not TOKEN_B64: missing.append("TOKEN_DATA")
    if missing:
        print(f"⛔ ERROR: Kunci rahasia belum lengkap: {', '.join(missing)}")
        sys.exit(1)
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
        while not done:
            _, done = downloader.next_chunk()

def get_multiple_random_files(service, folder_id, mime_type, limit=5):
    q = f"'{folder_id}' in parents and mimeType contains '{mime_type}' and trashed=false"
    results = service.files().list(q=q, fields="files(id, name)").execute()
    files = results.get('files', [])
    if not files: return []
    return random.sample(files, min(len(files), limit))

def get_ai_metadata(filenames):
    model = genai.GenerativeModel('gemini-1.5-flash')
    titles_str = ", ".join([f['name'] for f in filenames])
    prompt = (
        f"Video files: '{titles_str}'. Create an engaging international YouTube Live Title and Description. "
        "The content includes multiple office activities and relaxing slow-motion vibes. "
        "Return ONLY JSON: {'title': '...', 'description': '...'}"
    )
    try:
        res = model.generate_content(prompt)
        clean_text = res.text.replace('```json','').replace('```','').strip()
        return json.loads(clean_text)
    except:
        return {"title": "Focus Session: Office Ambience & Relaxing Music 💻", "description": "Productive work session live."}

def main():
    print(f"=== MULAI LIVE ANTI-MACET (OPTIMASI HEVC) ===")
    validate_environment()
    drive = get_drive_service()
    if not drive: return

    # 1. Pilih Bahan
    video_files = get_multiple_random_files(drive, SOURCE_ID, "video", limit=3)
    music_files = get_multiple_random_files(drive, MUSIC_ID, "audio", limit=10)

    if not video_files or not music_files:
        print("[-] Bahan tidak cukup di Drive.")
        return

    meta = get_ai_metadata(video_files)
    print(f"[*] Judul AI: {meta['title']}")

    # 2. Download
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

    # 3. Stream Command (Super Lightweight)
    print(f"[*] Menjalankan FFmpeg dengan optimasi CPU...")
    cmd = [
        'ffmpeg', '-re',
        '-fflags', '+genpts', 
        '-f', 'concat', '-safe', '0', '-i', 'video_playlist.txt',
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'music_playlist.txt',
        '-t', str(LIVE_DURATION_SEC),
        '-filter_complex', (
            f'[0:v]scale=1280:720,setpts={SLOW_MOTION_FACTOR}*PTS,fps=30[vout]; '
            f'[0:a]atempo={audio_speed},volume=0.3[a1]; '
            f'[1:a]volume=1.2[a2]; '
            f'[a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', 
        '-preset', 'ultrafast',         # Paling ringan untuk CPU
        '-tune', 'zerolatency', 
        '-threads', '0',                # Gunakan semua core CPU GitHub
        '-b:v', '2000k',                # Turunkan bitrate agar lebih stabil
        '-maxrate', '2500k', 
        '-bufsize', '5000k', 
        '-pix_fmt', 'yuv420p', 
        '-g', '60',
        '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
        '-max_muxing_queue_size', '1024', # Mencegah lag pada antrean buffer
        '-f', 'flv', f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    ]

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        for line in process.stdout:
            if "frame=" in line:
                print(line.strip(), end='\r')
            if "speed=" in line:
                # Memastikan Anda bisa memantau speed di log
                pass
        
        process.wait()
        print("\n[🚀] LIVE BERHASIL DISELESAIKAN!")

    except Exception as e:
        print(f"\n[-] Terjadi kesalahan fatal: {e}")
    finally:
        # Pembersihan file sampah
        all_temp = vid_list + mus_list + ["video_playlist.txt", "music_playlist.txt"]
        for temp in all_temp:
            if os.path.exists(temp): os.remove(temp)

if __name__ == "__main__":
    main()
