import os
import base64
import pickle
import subprocess
import json
import random
import sys
import io
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request
import google.generativeai as genai

# --- KONFIGURASI ---
TOKEN_B64 = os.environ.get('TOKEN_DATA_LIVE') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')    # Folder Video Utama
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')    # Folder Musik MP3
API_KEY = os.environ.get('GEMINI_API_KEY')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

# FAKTOR SLOW MOTION (Contoh: 1.5 berarti 1.5x lebih lambat, 2.0 berarti setengah kecepatan)
# Jangan disetel di bawah 1.0. Rekomendasi: 1.2 hingga 1.5 untuk hasil halus.
SLOW_MOTION_FACTOR = 1.3

# Durasi live diacak antara 50 - 65 menit
LIVE_DURATION_SEC = random.randint(3000, 3900) 

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
        return {"title": "Slow & Productive Day: Office Work Ambience 💻", "description": "Relaxing multi-video session for deep focus."}

def main():
    print(f"=== MULAI LIVE SLOW-MOTION ({LIVE_DURATION_SEC//60} MENIT) ===")
    validate_environment()
    drive = get_drive_service()
    if not drive: return

    # 1. Pilih Bahan (3 Video dan 10 Musik)
    video_files = get_multiple_random_files(drive, SOURCE_ID, "video", limit=3)
    music_files = get_multiple_random_files(drive, MUSIC_ID, "audio", limit=10)

    if not video_files or not music_files:
        print("[-] Bahan video atau musik tidak ditemukan.")
        return

    meta = get_ai_metadata(video_files)
    print(f"[*] Judul: {meta['title']}")

    # 2. Download Video & Musik
    print("[*] Mendownload video-video utama...")
    vid_list = []
    for i, v in enumerate(video_files):
        vname = f"video_{i}.mp4"
        download_file(drive, v['id'], vname)
        vid_list.append(vname)
    
    with open("video_playlist.txt", "w") as f:
        for vn in vid_list: f.write(f"file '{vn}'\n")

    print("[*] Mendownload playlist musik...")
    mus_list = []
    for i, m in enumerate(music_files):
        mname = f"track_{i}.mp3"
        download_file(drive, m['id'], mname)
        mus_list.append(mname)

    with open("music_playlist.txt", "w") as f:
        for mn in mus_list: f.write(f"file '{mn}'\n")

    # Hitung kecepatan audio (kebalikan dari faktor slow motion)
    # FFmpeg atempo mendukung range 0.5 - 2.0
    audio_speed = max(0.5, 1.0 / SLOW_MOTION_FACTOR)

    # 3. Stream HD 720p (Gabungan Multi-Video + Slow Motion)
    print(f"[*] Mengirim siaran slow-motion (Faktor: {SLOW_MOTION_FACTOR}x) ke YouTube...")
    cmd = [
        'ffmpeg', '-re',
        # Input 0: Playlist Video (Loop)
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'video_playlist.txt',
        # Input 1: Playlist Musik (Loop)
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'music_playlist.txt',
        
        '-t', str(LIVE_DURATION_SEC),
        
        # FILTER COMPLEX:
        # [0:v]setpts=... memperlambat visual video
        # [0:a]atempo=... memperlambat suara asli video agar tetap sinkron
        '-filter_complex', (
            f'[0:v]setpts={SLOW_MOTION_FACTOR}*PTS,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2[vout]; '
            f'[0:a]atempo={audio_speed},volume=0.3[a1]; '
            f'[1:a]volume=1.2[a2]; '
            f'[a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        
        '-map', '[vout]', 
        '-map', '[aout]',
        
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-b:v', '2500k',
        '-maxrate', '3000k', '-bufsize', '6000k', '-pix_fmt', 'yuv420p', '-g', '60',
        '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
        '-f', 'flv', f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    ]

    try:
        subprocess.run(cmd, check=True)
        print("[🚀] LIVE BERHASIL!")
    except Exception as e:
        print(f"[-] Terjadi kesalahan: {e}")
    finally:
        # Pembersihan file sampah
        all_temp = vid_list + mus_list + ["video_playlist.txt", "music_playlist.txt"]
        for temp in all_temp:
            if os.path.exists(temp): os.remove(temp)

if __name__ == "__main__":
    main()
