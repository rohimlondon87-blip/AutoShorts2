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
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')    # Folder Musik MP3
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

def get_multiple_random_music(service, folder_id, limit=8):
    """Mengambil beberapa file musik acak untuk dijadikan playlist"""
    q = f"'{folder_id}' in parents and mimeType contains 'audio' and trashed=false"
    results = service.files().list(q=q, fields="files(id, name)").execute()
    files = results.get('files', [])
    if not files:
        return []
    
    # Ambil maksimal 'limit' lagu secara acak
    sample_size = min(len(files), limit)
    return random.sample(files, sample_size)

def get_ai_metadata():
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = (
        "Buatkan metadata LIVE YouTube tentang perpaduan suara hujan alami dan playlist musik relaksasi (lofi/piano). "
        "Target: tidur, belajar, atau meditasi. "
        "Gunakan bahasa Indonesia yang estetik. "
        "Hasilkan HANYA JSON: {'title': '...', 'description': '...'}"
    )
    try:
        res = model.generate_content(prompt)
        clean_text = res.text.replace('```json','').replace('```','').strip()
        return json.loads(clean_text)
    except:
        return {
            "title": "Playlist Hujan & Musik Relaksasi Malam 🌧️🎹 Tidur & Fokus",
            "description": "Nikmati playlist musik pilihan dipadukan dengan suara hujan alami. #rain #lofi #relax"
        }

def main():
    print(f"=== MULAI LIVE STREAM PLAYLIST HUJAN + MUSIK ({LIVE_DURATION_SEC//60} MENIT) ===")
    validate_environment()
    drive = get_drive_service()
    if not drive: return

    # 1. Pilih 1 Video Hujan dan Beberapa Musik (Playlist)
    video_q = f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false"
    video_files = drive.files().list(q=video_q, fields="files(id, name)").execute().get('files', [])
    
    music_files = get_multiple_random_music(drive, MUSIC_ID, limit=8)

    if not video_files or not music_files:
        print("[-] Gagal mengambil bahan. Pastikan folder Video dan Musik tidak kosong.")
        return

    selected_video = random.choice(video_files)
    print(f"[*] Video Latar: {selected_video['name']}")
    print(f"[*] Membuat Playlist dengan {len(music_files)} lagu acak.")

    # 2. Metadata AI
    meta = get_ai_metadata()
    print(f"[*] Judul: {meta['title']}")

    # 3. Download Bahan
    print("[*] Mendownload video...")
    with open("vid.mp4", "wb") as f:
        f.write(drive.files().get_media(fileId=selected_video['id']).execute())
    
    # Download semua lagu dalam playlist
    playlist_files = []
    for i, m in enumerate(music_files):
        filename = f"music_{i}.mp3"
        print(f"    -> Mendownload lagu {i+1}: {m['name']}")
        with open(filename, "wb") as f:
            f.write(drive.files().get_media(fileId=m['id']).execute())
        playlist_files.append(filename)

    # Buat file daftar putar untuk FFmpeg
    with open("playlist.txt", "w") as f:
        for pf in playlist_files:
            f.write(f"file '{pf}'\n")

    # 4. Stream HD dengan Playlist Musik
    print(f"[*] Memulai siaran dengan playlist musik yang berganti-ganti...")
    
    cmd = [
        'ffmpeg',
        '-re',                          
        '-stream_loop', '-1', '-i', 'vid.mp4', # Input 0: Video Hujan (Loop)
        # Input 1: Gunakan concat demuxer untuk memutar playlist lagu
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'playlist.txt',
        
        '-t', str(LIVE_DURATION_SEC),   
        
        # Mixing Audio: Hujan (0.3), Musik Playlist (1.2)
        '-filter_complex', '[0:a]volume=0.3[a1];[1:a]volume=1.2[a2];[a1][a2]amix=inputs=2:duration=first[aout]',
        
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
        print("[🚀] LIVE STREAM BERHASIL SELESAI!")
    except Exception as e:
        print(f"[-] Terjadi kesalahan stream: {e}")
    finally:
        # Pembersihan total
        files_to_delete = ["vid.mp4", "playlist.txt"] + playlist_files
        for f in files_to_delete:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
