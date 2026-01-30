import os
import base64
import pickle
import subprocess
import json
import random
import time
import sys
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import google.generativeai as genai

# --- CONFIGURATION (FLEKSIBEL: SATU AKUN ATAU BEDA AKUN) ---
# Mencari TOKEN_DATA_LIVE, jika tidak ada pakai TOKEN_DATA utama
TOKEN_LIVE_B64 = os.environ.get('TOKEN_DATA_LIVE') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID') 
API_KEY = os.environ.get('GEMINI_API_KEY')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

# Durasi acak antara 50 menit hingga 60 menit (3000 - 3600 detik)
LIVE_DURATION = random.randint(3000, 3600) 

def validate_config():
    """Memastikan semua kunci penting tersedia sebelum jalan"""
    missing = []
    if not SOURCE_ID or SOURCE_ID == "None": missing.append("SOURCE_LIVE_ID")
    if not STREAM_KEY: missing.append("YOUTUBE_STREAM_KEY")
    if not TOKEN_LIVE_B64: missing.append("TOKEN_DATA")
    
    if missing:
        print(f"⛔ ERROR: Kunci berikut belum ada di GitHub Secrets: {', '.join(missing)}")
        sys.exit(1)
    
    genai.configure(api_key=API_KEY)

def get_drive_service():
    """Membuka akses ke Google Drive"""
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_LIVE_B64))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error (Drive): {e}")
        return None

def get_ai_metadata():
    """Meminta Gemini membuat judul relaksasi yang bervariasi"""
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = (
        "Buat metadata LIVE YouTube suara hujan relaksasi untuk tidur atau belajar. "
        "Gunakan bahasa Indonesia yang estetik. "
        "Hasilkan HANYA JSON: {'title': '...', 'description': '...'}"
    )
    try:
        res = model.generate_content(prompt)
        text = res.text.replace('```json','').replace('```','').strip()
        return json.loads(text)
    except:
        return {
            "title": "Suara Hujan Menenangkan untuk Tidur & Relaksasi 🌧️",
            "description": "Dengarkan suara hujan alami untuk menemani tidur atau belajar Anda. #rain #sleep #meditation"
        }

def main():
    print(f"=== MULAI LIVE STREAM HUJAN ({LIVE_DURATION//60} MENIT) ===")
    validate_config()
    drive = get_drive_service()
    if not drive: return

    # 1. Ambil video hujan dari folder khusus
    results = drive.files().list(
        q=f"'{SOURCE_ID}' in parents and mimeType='video/mp4' and trashed=false", 
        fields="files(id, name)"
    ).execute()
    files = results.get('files', [])

    if not files:
        print("[-] Folder Drive kosong! Masukkan video hujan (.mp4) ke Drive.")
        return

    # Pilih satu video secara acak agar konten tidak monoton
    selected_file = random.choice(files)
    print(f"[*] Menggunakan file: {selected_file['name']}")

    # 2. Judul & Deskripsi AI
    meta = get_ai_metadata()
    print(f"[*] Judul Live AI: {meta['title']}")

    # 3. Download Video
    print("[*] Sedang mendownload dari Drive...")
    with open("live_input.mp4", "wb") as f:
        f.write(drive.files().get_media(fileId=selected_file['id']).execute())

    # 4. Proses Streaming (Looping dengan FFmpeg)
    # -stream_loop -1 membuat video berulang terus menerus secara halus
    print(f"[*] Menyiarkan ke YouTube selama {LIVE_DURATION} detik...")
    
    cmd = [
        'ffmpeg',
        '-re',                          # Kecepatan bit aslinya
        '-stream_loop', '-1',           # Loop selamanya (sampai durasi habis)
        '-i', 'live_input.mp4', 
        '-t', str(LIVE_DURATION),       # Berhenti setelah durasi tercapai
        '-c:v', 'libx264',              # Codec video standar YouTube
        '-preset', 'veryfast',          # Pengaturan ringan untuk server
        '-b:v', '3000k',                # Kualitas visual 1080p/720p
        '-maxrate', '3000k',
        '-bufsize', '6000k',
        '-pix_fmt', 'yuv420p',
        '-g', '60',                     # Interval keyframe 2 detik
        '-c:a', 'aac',                  # Codec audio
        '-b:a', '128k',                 # Kualitas suara jernih
        '-ar', '44100',
        '-f', 'flv',                    # Protokol siaran YouTube
        f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    ]

    try:
        subprocess.run(cmd, check=True)
        print("[🚀] LIVE STREAM BERHASIL DISELESAIKAN!")
    except Exception as e:
        print(f"[-] Terjadi kesalahan teknis streaming: {e}")
    finally:
        # Hapus file agar memori server tetap bersih
        if os.path.exists("live_input.mp4"): os.remove("live_input.mp4")

if __name__ == "__main__":
    main()
