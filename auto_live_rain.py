import os
import base64
import pickle
import subprocess
import json
import random
import time
import sys
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request
import google.generativeai as genai

# --- KONFIGURASI ---
# Robot akan mencoba TOKEN_DATA_LIVE dulu, jika kosong pakai TOKEN_DATA utama
TOKEN_B64 = os.environ.get('TOKEN_DATA_LIVE') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID') 
API_KEY = os.environ.get('GEMINI_API_KEY')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

# Durasi Live diacak antara 50 menit (3000 detik) - 60 menit (3600 detik)
LIVE_DURATION = random.randint(3000, 3600) 

def validate_config():
    """Memastikan semua Secret di GitHub sudah diisi"""
    missing = []
    if not TOKEN_B64: missing.append("TOKEN_DATA")
    if not SOURCE_ID: missing.append("SOURCE_LIVE_ID")
    if not API_KEY: missing.append("GEMINI_API_KEY")
    if not STREAM_KEY: missing.append("YOUTUBE_STREAM_KEY")
    
    if missing:
        print(f"⛔ ERROR: Secret berikut belum diisi: {', '.join(missing)}")
        sys.exit(1)
    
    genai.configure(api_key=API_KEY)

def get_drive_service():
    """Login ke Google Drive"""
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_B64))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error: {e}")
        return None

def get_ai_metadata():
    """Gemini membuat judul yang menarik untuk audiens relaksasi"""
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = (
        "Buatkan Judul dan Deskripsi LIVE YouTube tentang suara hujan menenangkan. "
        "Target audiens: orang insomnia, belajar, atau meditasi. "
        "Gunakan bahasa Indonesia yang estetik. "
        "Hasilkan HANYA JSON: {'title': '...', 'description': '...'}"
    )
    try:
        res = model.generate_content(prompt)
        clean_json = res.text.replace('```json','').replace('```','').strip()
        return json.loads(clean_json)
    except:
        return {
            "title": "Suara Hujan Alami untuk Tidur Nyenyak 🌧️ Relaksasi & Meditasi",
            "description": "Nikmati suasana hujan untuk ketenangan pikiran. #rain #sleep"
        }

def main():
    print(f"=== MULAI LIVE STREAM ({LIVE_DURATION//60} MENIT) ===")
    validate_config()
    drive = get_drive_service()
    if not drive: return

    # 1. Cari video di folder khusus Live Hujan
    q = f"'{SOURCE_ID}' in parents and mimeType='video/mp4' and trashed=false"
    files = drive.files().list(q=q, fields="files(id, name)").execute().get('files', [])

    if not files:
        print("[-] Folder Drive kosong. Masukkan video hujan Anda!")
        return

    # Pilih video acak dari Drive
    selected_file = random.choice(files)
    print(f"[*] Menggunakan file: {selected_file['name']}")

    # 2. Metadata AI
    meta = get_ai_metadata()
    print(f"[*] Judul: {meta['title']}")

    # 3. Download Video
    print("[*] Mengunduh video...")
    request = drive.files().get_media(fileId=selected_file['id'])
    with open("live_input.mp4", "wb") as f:
        f.write(request.execute())

    # 4. Stream ke YouTube menggunakan FFmpeg
    # -stream_loop -1 sangat penting untuk mengulang video < 3 menit menjadi 1 jam
    print(f"[*] Memulai siaran ke YouTube...")
    
    cmd = [
        'ffmpeg',
        '-re',                          # Kecepatan asli
        '-stream_loop', '-1',           # LOOP TANPA BATAS
        '-i', 'live_input.mp4',         # File input
        '-t', str(LIVE_DURATION),       # Berhenti setelah X detik
        '-c:v', 'libx264',              # Video codec
        '-preset', 'veryfast',          # Ringan untuk server
        '-b:v', '3000k',                # Bitrate stabil
        '-maxrate', '3000k',
        '-bufsize', '6000k',
        '-pix_fmt', 'yuv420p',
        '-g', '60',                     # Keyframe (Wajib YouTube)
        '-c:a', 'aac',                  # Audio codec
        '-b:a', '128k',                 # Audio bitrate
        '-ar', '44100',
        '-f', 'flv',                    # Format RTMP
        f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    ]

    try:
        subprocess.run(cmd, check=True)
        print("[🚀] LIVE SELESAI DENGAN SUKSES!")
    except Exception as e:
        print(f"[-] Kesalahan Streaming: {e}")
    finally:
        if os.path.exists("live_input.mp4"): os.remove("live_input.mp4")

if __name__ == "__main__":
    main()
