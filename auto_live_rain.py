import os
import base64
import pickle
import subprocess
import json
import random
import sys
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import google.generativeai as genai

# --- KONFIGURASI ---
TOKEN_B64 = os.environ.get('TOKEN_DATA_LIVE') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')    # Folder Video Hujan
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')    # Folder Musik MP3 (Baru)
API_KEY = os.environ.get('GEMINI_API_KEY')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

# Durasi live diacak antara 50 - 60 menit
LIVE_DURATION_SEC = random.randint(3000, 3600) 

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

def get_random_file(service, folder_id, mime_prefix):
    """Mengambil satu file acak berdasarkan tipe (video atau audio)"""
    q = f"'{folder_id}' in parents and mimeType contains '{mime_prefix}' and trashed=false"
    results = service.files().list(q=q, fields="files(id, name)").execute()
    files = results.get('files', [])
    if not files:
        return None
    return random.choice(files)

def get_ai_metadata():
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = (
        "Buatkan metadata LIVE YouTube tentang suara hujan menenangkan yang dipadukan dengan musik piano/lofi. "
        "Target: tidur, belajar, atau meditasi. "
        "Hasilkan HANYA JSON: {'title': '...', 'description': '...'}"
    )
    try:
        res = model.generate_content(prompt)
        clean_text = res.text.replace('```json','').replace('```','').strip()
        return json.loads(clean_text)
    except:
        return {
            "title": "Hujan Alami & Musik Relaksasi 🌧️🎹 Tidur Nyenyak & Fokus Belajar",
            "description": "Perpaduan suara hujan dan musik untuk ketenangan Anda. #rain #lofi #meditation"
        }

def main():
    print(f"=== MULAI LIVE STREAM HUJAN + MUSIK ({LIVE_DURATION_SEC//60} MENIT) ===")
    validate_environment()
    drive = get_drive_service()
    if not drive: return

    # 1. Pilih Video dan Musik secara acak
    video_file = get_random_file(drive, SOURCE_ID, "video")
    music_file = get_random_file(drive, MUSIC_ID, "audio")

    if not video_file or not music_file:
        print("[-] Gagal mengambil video atau musik dari Drive. Pastikan folder tidak kosong.")
        return

    print(f"[*] Video: {video_file['name']}")
    print(f"[*] Musik: {music_file['name']}")

    # 2. Ambil Metadata AI
    meta = get_ai_metadata()
    print(f"[*] Judul: {meta['title']}")

    # 3. Download Bahan
    print("[*] Mengunduh bahan...")
    with open("vid.mp4", "wb") as f:
        f.write(drive.files().get_media(fileId=video_file['id']).execute())
    with open("mus.mp3", "wb") as f:
        f.write(drive.files().get_media(fileId=music_file['id']).execute())

    # 4. Stream HD dengan Mixing Audio (FFmpeg)
    # amix=inputs=2 menggabungkan suara hujan (dari video) dan musik
    print(f"[*] Memulai siaran HD dengan mixing audio...")
    
    cmd = [
        'ffmpeg',
        '-re',                          
        '-stream_loop', '-1', '-i', 'vid.mp4', # Input 0: Video (Loop)
        '-stream_loop', '-1', '-i', 'mus.mp3', # Input 1: Musik (Loop)
        '-t', str(LIVE_DURATION_SEC),   
        
        # Filter Complex: Gabungkan suara video dan musik
        # volume=0.8 untuk musik agar tidak menutupi suara hujan
        '-filter_complex', '[0:a]volume=1.0[a1];[1:a]volume=0.6[a2];[a1][a2]amix=inputs=2:duration=first[aout]',
        
        # Pengaturan Video (1080p)
        '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2',
        '-map', '0:v',                  # Ambil gambar dari video
        '-map', '[aout]',               # Ambil suara hasil gabungan
        
        '-c:v', 'libx264',              
        '-preset', 'faster',            
        '-b:v', '4500k',                
        '-maxrate', '5000k',
        '-bufsize', '9000k',
        '-pix_fmt', 'yuv420p',
        '-g', '60',                     
        
        '-c:a', 'aac',                  
        '-b:a', '192k',                 
        '-ar', '44100',
        
        '-f', 'flv',                    
        f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    ]

    try:
        subprocess.run(cmd, check=True)
        print("[🚀] LIVE SELESAI!")
    except Exception as e:
        print(f"[-] Terjadi kesalahan stream: {e}")
    finally:
        # Bersihkan file
        for f in ["vid.mp4", "mus.mp3"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
