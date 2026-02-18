import os
import base64
import pickle
import subprocess
import random
import sys
import io
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI TOKEN A ---
TOKEN_B64 = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')      # ID Folder Video
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')    # ID Folder Musik
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY') # Kunci Live YouTube

# Durasi live (detik)
LIVE_DURATION_SEC = random.randint(2700, 3600) 

def get_services():
    """Login menggunakan Token A saja."""
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
        print(f"⛔ Gagal Login: {e}")
        return None

def download_file(service, file_id, output_name):
    """Fungsi download standar."""
    try:
        request = service.files().get_media(fileId=file_id)
        with io.FileIO(output_name, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return True
    except: return False

def main():
    print(f"=== ROBOT LIVE: VERSI ARSIP (TOKEN A) ===")
    
    drive = get_services()
    if not drive: return

    try:
        # 1. Ambil Daftar File
        v_res = drive.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false").execute()
        v_files = v_res.get('files', [])
        
        m_res = drive.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio' and trashed=false").execute()
        m_files = m_res.get('files', [])

        if not v_files or not m_files:
            print("⛔ Bahan tidak ditemukan!")
            return

        # 2. Acak Urutan
        random.shuffle(v_files)
        random.shuffle(m_files)
        v_files = v_files[:5]  # Batasi download

        # 3. Proses Download
        v_list = ""
        for i, v in enumerate(v_files):
            fname = f"vid_{i}.mp4"
            if download_file(drive, v['id'], fname):
                v_list += f"file '{fname}'\n"
        
        with open("v_list.txt", "w") as f: f.write(v_list)

        m_list = ""
        for i, m in enumerate(m_files[:10]):
            mname = f"mus_{i}.mp3"
            if download_file(drive, m['id'], mname):
                m_list += f"file '{mname}'\n"
        
        with open("m_list.txt", "w") as f: f.write(m_list)

        # 4. Jalankan Live Streaming (Mute Video, Play Musik, Format 16:9)
        rtmp = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
        print(f"[🚀] LIVE DIMULAI")

        cmd = [
            'ffmpeg', '-y',
            # Input Video (Loop)
            '-f', 'concat', '-safe', '0', '-stream_loop', '-1', '-i', 'v_list.txt',
            # Input Musik (Loop)
            '-f', 'concat', '-safe', '0', '-stream_loop', '-1', '-i', 'm_list.txt',
            '-t', str(LIVE_DURATION_SEC),
            # Filter: Mute audio video, Scale ke 16:9 (1280x720)
            '-vf', 'scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1',
            '-map', '0:v', '-map', '1:a',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '2500k',
            '-c:a', 'aac', '-ar', '44100', '-b:a', '128k',
            '-pix_fmt', 'yuv420p', '-f', 'flv', rtmp
        ]

        subprocess.run(cmd)

    except Exception as e:
        print(f"⛔ ERROR: {e}")
    finally:
        # Bersihkan file sementara
        for f in os.listdir():
            if f.startswith("vid_") or f.startswith("mus_") or f in ["v_list.txt", "m_list.txt"]:
                try: os.remove(f)
                except: pass

if __name__ == "__main__":
    main()