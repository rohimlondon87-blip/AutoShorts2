import os
import base64
import pickle
import subprocess
import random
import sys
import io
import json
import time
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI TUNGGAL (TOKEN A) ---
TOKEN_B64 = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')      # Folder Video Latar
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')    # Folder Musik MP3
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY') # Kunci Live YouTube

# Durasi live (45 - 60 menit)
LIVE_DURATION_SEC = random.randint(2700, 3600) 
# Jeda awal minimal
DELAY_MENIT = random.randint(0, 1)

def get_services():
    """Autentikasi Token A dengan pembersihan karakter."""
    try:
        if not TOKEN_B64:
            print("⛔ ERROR: TOKEN_DATA tidak ditemukan!")
            return None
            
        t_str = TOKEN_B64.strip().replace('\xa0', '').replace(" ", "")
        missing_padding = len(t_str) % 4
        if missing_padding: t_str += '=' * (4 - missing_padding)

        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"⛔ GAGAL LOGIN: {e}")
        return None

def download_file(service, file_id, output_name):
    """Download file dari Drive."""
    try:
        request = service.files().get_media(fileId=file_id)
        with io.FileIO(output_name, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return True
    except: return False

def get_video_rotation(path):
    """Membaca metadata rotasi asli video (0, 90, 180, 270)."""
    try:
        cmd = [
            'ffprobe', '-loglevel', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream_tags=rotate', '-of', 'json', path
        ]
        result = subprocess.check_output(cmd).decode('utf-8')
        data = json.loads(result)
        tags = data.get('streams', [{}])[0].get('tags', {})
        return int(tags.get('rotate', 0))
    except:
        return 0

def standardize_video(input_path, output_path):
    """
    PROSES KUNCI: Menormalkan setiap video satu per satu.
    Memperbaiki rotasi terbalik dan memaksa format Landscape 16:9.
    """
    rotation = get_video_rotation(input_path)
    print(f"    [*] Menormalkan Video. Deteksi Rotasi: {rotation}°")

    filters = []
    # Jika terdeteksi miring/terbalik, perbaiki secara permanen
    if rotation == 90:
        filters.append("transpose=1")
    elif rotation == 180:
        filters.append("hflip,vflip")
    elif rotation == 270:
        filters.append("transpose=2")
    
    # Paten 16:9 Landscape (1280x720)
    filters.append("scale=w=1280:h=720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1")
    
    v_filter = ",".join(filters)
    
    cmd = [
        'ffmpeg', '-y', '-i', input_path,
        '-vf', v_filter,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
        '-an', # Hapus suara asli (Mute)
        output_path
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0

def main():
    print(f"=== ROBOT LIVE: SISTEM LANDSCAPE 16:9 AUTO-FIX ===")
    
    if DELAY_MENIT > 0:
        print(f"[⏳] Jeda natural: {DELAY_MENIT} menit...")
        time.sleep(DELAY_MENIT * 60)

    drive = get_services()
    if not drive: return

    try:
        # 1. Pindai Bahan
        v_res = drive.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false").execute()
        v_files = v_res.get('files', [])
        
        m_res = drive.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio' and trashed=false").execute()
        m_files = m_res.get('files', [])

        if not v_files or not m_files:
            print("⛔ Bahan di Drive tidak lengkap!")
            return

        random.shuffle(v_files)
        random.shuffle(m_files)
        v_files = v_files[:8] # Ambil maksimal 8 video

        # 2. Proses Normalisasi Individu
        v_list_content = ""
        for i, v in enumerate(v_files):
            raw_name = f"raw_{i}.mp4"
            fixed_name = f"fixed_{i}.mp4"
            print(f"[*] Mendownload & Memperbaiki Video {i+1}: {v['name']}")
            
            if download_file(drive, v['id'], raw_name):
                if standardize_video(raw_name, fixed_name):
                    v_list_content += f"file '{fixed_name}'\n"
                if os.path.exists(raw_name): os.remove(raw_name)
        
        with open("v_list.txt", "w") as f: f.write(v_list_content)

        # 3. Siapkan Audio
        m_list_content = ""
        for i, m in enumerate(m_files[:15]): 
            mname = f"mus_{i}.mp3"
            if download_file(drive, m['id'], mname):
                m_list_content += f"file '{mname}'\n"
        with open("m_list.txt", "w") as f: f.write(m_list_content)

        # 4. Jalankan Live Streaming
        rtmp = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
        print(f"\n[🚀] LIVE DIMULAI (Format Landscape 16:9)")

        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-stream_loop', '-1', '-i', 'v_list.txt',
            '-f', 'concat', '-safe', '0', '-stream_loop', '-1', '-i', 'm_list.txt',
            '-t', str(LIVE_DURATION_SEC),
            '-map', '0:v', '-map', '1:a',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '2500k',
            '-c:a', 'aac', '-ar', '44100', '-b:a', '128k',
            '-pix_fmt', 'yuv420p', '-f', 'flv', rtmp
        ]

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            if "frame=" in line:
                print(f"Streaming: {line.strip()}", end="\r")
        process.wait()

    except Exception as e:
        print(f"\n⛔ ERROR: {e}")
    finally:
        print("\n[*] Pembersihan file sementara...")
        for f in os.listdir():
            if f.startswith("fixed_") or f.startswith("mus_") or f in ["v_list.txt", "m_list.txt"]:
                try:
                    os.remove(f)
                except:
                    pass

if __name__ == "__main__":
    main()
