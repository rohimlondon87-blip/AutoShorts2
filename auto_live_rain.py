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
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')
API_KEY = os.environ.get('GEMINI_API_KEY')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

LIVE_DURATION_SEC = random.randint(3000, 3900) 

def validate_environment():
    missing = []
    if not SOURCE_ID: missing.append("SOURCE_LIVE_ID")
    if not MUSIC_ID: missing.append("MUSIC_FOLDER_ID")
    if not STREAM_KEY: missing.append("YOUTUBE_STREAM_KEY")
    if not TOKEN_B64: missing.append("TOKEN_DATA")
    if missing:
        sys.exit(1)
    genai.configure(api_key=API_KEY)

def get_drive_service():
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_B64))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except:
        return None

def download_file(service, file_id, output_name):
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(output_name, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

def get_multiple_random_music(service, folder_id, limit=10):
    q = f"'{folder_id}' in parents and mimeType contains 'audio' and trashed=false"
    results = service.files().list(q=q, fields="files(id, name)").execute()
    files = results.get('files', [])
    if not files: return []
    return random.sample(files, min(len(files), limit))

def get_ai_metadata(filename):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"Video: '{filename}'. Buat Judul & Deskripsi Live YouTube Inggris (International) menarik. Hasilkan JSON: {{'title': '...', 'description': '...'}}"
    try:
        res = model.generate_content(prompt)
        clean_text = res.text.replace('```json','').replace('```','').strip()
        return json.loads(clean_text)
    except:
        return {"title": "Productive Session: Stay Focused", "description": "Work with me live!"}

def main():
    print(f"=== MULAI LIVE STREAM OPTIMIZED ({LIVE_DURATION_SEC//60} MENIT) ===")
    validate_environment()
    drive = get_drive_service()
    if not drive: return

    video_q = f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false"
    video_files = drive.files().list(q=video_q, fields="files(id, name)").execute().get('files', [])
    music_files = get_multiple_random_music(drive, MUSIC_ID, limit=10)

    if not video_files or not music_files: return

    selected_video = random.choice(video_files)
    meta = get_ai_metadata(selected_video['name'])

    download_file(drive, selected_video['id'], "main_vid.mp4")
    playlist_files = []
    for i, m in enumerate(music_files):
        fname = f"track_{i}.mp3"
        download_file(drive, m['id'], fname)
        playlist_files.append(fname)

    with open("playlist.txt", "w") as f:
        for pf in playlist_files: f.write(f"file '{pf}'\n")

    # --- OPTIMASI FFmpeg UNTUK GITHUB ACTIONS ---
    cmd = [
        'ffmpeg', '-re',
        '-stream_loop', '-1', '-i', 'main_vid.mp4',
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'playlist.txt',
        '-t', str(LIVE_DURATION_SEC),
        '-filter_complex', '[0:a]volume=0.3[a1];[1:a]volume=1.2[a2];[a1][a2]amix=inputs=2:duration=first[aout]',
        
        # Gunakan resolusi 720p jika 1080p terlalu berat (opsional, tapi saya coba optimasi preset dulu)
        '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2',
        '-map', '0:v', '-map', '[aout]',
        
        '-c:v', 'libx264', 
        '-preset', 'ultrafast',         # Paling ringan, memastikan speed >= 1.0x
        '-tune', 'zerolatency',         # Cocok untuk Live Streaming
        '-b:v', '3000k',                # Bitrate yang lebih stabil untuk 720p/1080p
        '-maxrate', '3500k', 
        '-bufsize', '7000k', 
        '-pix_fmt', 'yuv420p', 
        '-g', '60',
        
        '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
        '-f', 'flv', f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    ]

    try:
        subprocess.run(cmd, check=True)
    except:
        pass
    finally:
        for f in ["main_vid.mp4", "playlist.txt"] + playlist_files:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()

