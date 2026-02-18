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

# --- KONFIGURASI SECRETS ---
TOKEN_B64 = os.environ.get('TOKEN_DATA_B') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

# Durasi live (45 - 65 menit)
LIVE_DURATION_SEC = random.randint(2700, 3900) 
# Jeda awal agar natural (0-5 menit)
DELAY_MENIT = random.randint(0, 5)

def get_services():
    try:
        if not TOKEN_B64:
            print("⛔ ERROR: Token tidak ditemukan!")
            return None, None
            
        # Fix padding base64
        t_str = TOKEN_B64.strip().replace('\xa0', '').replace(" ", "")
        missing_padding = len(t_str) % 4
        if missing_padding: t_str += '=' * (4 - missing_padding)

        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        
        drive = build('drive', 'v3', credentials=creds)
        youtube = build('youtube', 'v3', credentials=creds)
        return drive, youtube
    except Exception as e:
        print(f"⛔ GAGAL AUTH: {e}")
        return None, None

def download_file(service, file_id, output_name):
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
    print(f"=== ROBOT LIVE: KONSEP MULTI-ASSET ===")
    
    if DELAY_MENIT > 0:
        print(f"[⏳] Jeda natural: {DELAY_MENIT} menit...")
        time.sleep(DELAY_MENIT * 60)

    drive, youtube = get_services()
    if not drive: sys.exit(1)

    try:
        # 1. Ambil SEMUA Video dari Folder
        v_res = drive.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false").execute()
        v_files = v_res.get('files', [])
        
        # 2. Ambil Musik dari Folder
        m_res = drive.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio' and trashed=false").execute()
        m_files = m_res.get('files', [])

        if not v_files or not m_files:
            print("⛔ Bahan video atau musik kosong!")
            return

        # 3. Pengacakan Urutan
        random.shuffle(v_files)
        random.shuffle(m_files)
        # Batasi musik agar tidak terlalu banyak didownload (misal 10 lagu cukup untuk 1 jam)
        selected_m = m_files[:10]

        print(f"[*] Mengunduh {len(v_files)} video & {len(selected_m)} musik...")

        # 4. Proses Download Video
        v_list_content = ""
        for i, v in enumerate(v_files):
            fname = f"vid_{i}.mp4"
            if download_file(drive, v['id'], fname):
                v_list_content += f"file '{fname}'\n"
        
        with open("v_list.txt", "w") as f: f.write(v_list_content)

        # 5. Proses Download Musik
        m_list_content = ""
        for i, m in enumerate(selected_m):
            mname = f"mus_{i}.mp3"
            if download_file(drive, m['id'], mname):
                m_list_content += f"file '{mname}'\n"
        
        with open("m_list.txt", "w") as f: f.write(m_list_content)

        # 6. Jalankan Streaming FFmpeg
        # Konsep: 
        # - Input 0: Concat video (loop)
        # - Input 1: Concat musik (loop)
        # - Map 0:v: Ambil video saja (Mute suara asli video)
        # - Map 1:a: Ambil audio dari musik saja
        
        rtmp = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
        print(f"[🚀] LIVE DIMULAI (Target: {LIVE_DURATION_SEC/60:.1f} Menit)")

        cmd = [
            'ffmpeg', '-y',
            # Input Video List (Looping)
            '-f', 'concat', '-safe', '0', '-stream_loop', '-1', '-i', 'v_list.txt',
            # Input Music List (Looping)
            '-f', 'concat', '-safe', '0', '-stream_loop', '-1', '-i', 'm_list.txt',
            # Batasi durasi total
            '-t', str(LIVE_DURATION_SEC),
            # Pemetaan: Ambil video dari input 0, Ambil audio dari input 1
            '-map', '0:v', 
            '-map', '1:a',
            # Encoding settings
            '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '2500k',
            '-c:a', 'aac', '-ar', '44100', '-b:a', '128k',
            '-pix_fmt', 'yuv420p', '-f', 'flv', rtmp
        ]

        subprocess.run(cmd, check=True)
        print("[✨] Live selesai dengan sukses.")

    except Exception as e:
        print(f"⛔ ERROR RUNTIME: {e}")
    finally:
        # Bersihkan file
        print("[*] Membersihkan file sementara...")
        for f in os.listdir():
            if f.startswith("vid_") or f.startswith("mus_") or f in ["v_list.txt", "m_list.txt"]:
                os.remove(f)

if __name__ == "__main__":
    main()
