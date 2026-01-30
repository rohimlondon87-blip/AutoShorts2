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
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')    # Folder Video Utama (Kegiatan/Hujan)
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')    # Folder Musik Latar MP3
API_KEY = os.environ.get('GEMINI_API_KEY')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

# Durasi live diacak antara 50 - 65 menit (3000 - 3900 detik)
LIVE_DURATION_SEC = random.randint(3000, 3900) 

def validate_environment():
    """Memastikan rahasia GitHub sudah terisi"""
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
    """Membuka akses ke Google Drive"""
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_B64))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error: {e}")
        return None

def get_multiple_random_music(service, folder_id, limit=10):
    """Mengambil playlist musik acak dari Drive"""
    q = f"'{folder_id}' in parents and mimeType contains 'audio' and trashed=false"
    results = service.files().list(q=q, fields="files(id, name)").execute()
    files = results.get('files', [])
    if not files:
        return []
    sample_size = min(len(files), limit)
    return random.sample(files, sample_size)

def get_ai_metadata(filename):
    """Gemini membuat Judul & Deskripsi Live berdasarkan nama file video"""
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = (
        f"Saya akan Live Streaming YouTube dengan video: '{filename}'. "
        "Buatkan Judul dan Deskripsi Live yang sangat menarik dalam Bahasa Indonesia. "
        "Hasilkan HANYA JSON: {'title': '...', 'description': '...'}"
    )
    try:
        res = model.generate_content(prompt)
        clean_text = res.text.replace('```json','').replace('```','').strip()
        return json.loads(clean_text)
    except:
        return {
            "title": f"LIVE: {filename.split('.')[0]} 🔴 Santai Sejenak",
            "description": "Selamat datang di live streaming kami. Selamat menikmati tayangan ini!"
        }

def main():
    print(f"=== MULAI LIVE STREAM UNIVERSAL ({LIVE_DURATION_SEC//60} MENIT) ===")
    validate_environment()
    drive = get_drive_service()
    if not drive: return

    # 1. Pilih 1 Video Utama dan Playlist Musik
    video_q = f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false"
    video_files = drive.files().list(q=video_q, fields="files(id, name)").execute().get('files', [])
    
    music_files = get_multiple_random_music(drive, MUSIC_ID, limit=10)

    if not video_files or not music_files:
        print("[-] Gagal mengambil bahan. Cek folder Drive Anda.")
        return

    selected_video = random.choice(video_files)
    print(f"[*] Video Terpilih: {selected_video['name']}")

    # 2. Metadata AI
    meta = get_ai_metadata(selected_video['name'])
    print(f"[*] Judul Live: {meta['title']}")

    # 3. Download Bahan ke Server GitHub
    print("[*] Mendownload video...")
    with open("main_vid.mp4", "wb") as f:
        f.write(drive.files().get_media(fileId=selected_video['id']).execute())
    
    playlist_files = []
    for i, m in enumerate(music_files):
        fname = f"track_{i}.mp3"
        print(f"    -> Mendownload musik: {m['name']}")
        with open(fname, "wb") as f:
            f.write(drive.files().get_media(fileId=m['id']).execute())
        playlist_files.append(fname)

    # Buat file daftar putar untuk FFmpeg
    with open("playlist.txt", "w") as f:
        for pf in playlist_files:
            f.write(f"file '{pf}'\n")

    # 4. Eksekusi Streaming dengan FFmpeg
    print(f"[*] Memulai siaran HD (1080p)...")
    
    cmd = [
        'ffmpeg',
        '-re',                          
        '-stream_loop', '-1', '-i', 'main_vid.mp4', # Input 0: Video (Loop)
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'playlist.txt', # Input 1: Musik (Loop)
        
        '-t', str(LIVE_DURATION_SEC),   
        
        # MIXING AUDIO: Suara video (0.3), Musik (1.2)
        '-filter_complex', '[0:a]volume=0.3[a1];[1:a]volume=1.2[a2];[a1][a2]amix=inputs=2:duration=first[aout]',
        
        # Visual 1080p
        '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2',
        '-map', '0:v',                  
        '-map', '[aout]',               
        
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
        print("[🚀] LIVE BERHASIL SELESAI!")
    except Exception as e:
        print(f"[-] Terjadi kesalahan stream: {e}")
    finally:
        # Pembersihan file sampah di server
        all_temp = ["main_vid.mp4", "playlist.txt"] + playlist_files
        for temp in all_temp:
            if os.path.exists(temp): os.remove(temp)

if __name__ == "__main__":
    main()
