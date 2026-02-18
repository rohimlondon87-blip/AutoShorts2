import os
import base64
import pickle
import subprocess
import random
import sys
import io
import time
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI SECRETS ---
TOKEN_B64 = os.environ.get('TOKEN_DATA_B') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

# Durasi live (45 - 60 menit)
LIVE_DURATION_SEC = random.randint(2700, 3600) 
# Jeda minimal untuk sinkronisasi awal
DELAY_MENIT = random.randint(0, 1)

def get_services():
    """Autentikasi dengan perbaikan padding otomatis."""
    try:
        if not TOKEN_B64:
            print("⛔ ERROR: Token tidak ditemukan!")
            return None, None
            
        t_str = TOKEN_B64.strip().replace('\xa0', '').replace(" ", "")
        missing_padding = len(t_str) % 4
        if missing_padding: t_str += '=' * (4 - missing_padding)

        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            print("[*] Menyegarkan token akses...")
            creds.refresh(Request())
        
        drive = build('drive', 'v3', credentials=creds)
        youtube = build('youtube', 'v3', credentials=creds)
        return drive, youtube
    except Exception as e:
        print(f"⛔ GAGAL AUTH: {e}")
        return None, None

def download_file(service, file_id, output_name):
    """Mengunduh file dari Drive ke server sementara."""
    try:
        print(f"    -> Mendownload {output_name}...", end="\r")
        request = service.files().get_media(fileId=file_id)
        with io.FileIO(output_name, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return True
    except Exception as e:
        print(f"\n    ❌ Gagal download {output_name}: {e}")
        return False

def main():
    print(f"=== ROBOT LIVE RAIN SYSTEM (FIXED PORTRAIT) ===")
    print(f"[*] Waktu Mulai: {datetime.now().strftime('%H:%M:%S')}")
    
    if DELAY_MENIT > 0:
        print(f"[⏳] Jeda natural: {DELAY_MENIT} menit...")
        time.sleep(DELAY_MENIT * 60)

    drive, youtube = get_services()
    if not drive: return

    try:
        # 1. Pindai Bahan
        v_res = drive.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false").execute()
        v_files = v_res.get('files', [])
        
        m_res = drive.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio' and trashed=false").execute()
        m_files = m_res.get('files', [])

        if not v_files or not m_files:
            print("⛔ ERROR: Bahan video atau musik tidak lengkap!")
            return

        # 2. Acak Urutan (FIFO & Random Mix)
        random.shuffle(v_files)
        random.shuffle(m_files)
        v_files = v_files[:5] # Batasi untuk efisiensi server
        m_files = m_files[:10]

        print(f"[*] Menyiapkan {len(v_files)} video dan {len(m_files)} lagu...")

        # 3. Proses Download Video
        v_list_content = ""
        for i, v in enumerate(v_files):
            fname = f"vid_{i}.mp4"
            if download_file(drive, v['id'], fname):
                v_list_content += f"file '{fname}'\n"
        with open("v_list.txt", "w") as f: f.write(v_list_content)

        # 4. Proses Download Musik
        m_list_content = ""
        for i, m in enumerate(m_files):
            mname = f"mus_{i}.mp3"
            if download_file(drive, m['id'], mname):
                m_list_content += f"file '{mname}'\n"
        with open("m_list.txt", "w") as f: f.write(m_list_content)

        # 5. Konfigurasi Streaming & Filter Paten
        rtmp = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
        
        # --- LOGIKA PATEN POSISI TEGAK (PORTRAIT) ---
        # 1. 'hflip,vflip' memutar video 180 derajat (Memperbaiki video terbalik)
        # 2. 'scale=720:1280' memastikan resolusi HD Portrait (9:16)
        # 3. 'setsar=1' memastikan aspek rasio pixel seimbang
        v_filter = "hflip,vflip,scale=720:1280,setsar=1"

        cmd = [
            'ffmpeg', '-y',
            # Input Video Loop
            '-f', 'concat', '-safe', '0', '-stream_loop', '-1', '-i', 'v_list.txt',
            # Input Musik Loop
            '-f', 'concat', '-safe', '0', '-stream_loop', '-1', '-i', 'm_list.txt',
            '-t', str(LIVE_DURATION_SEC),
            # Filter Gabungan
            '-filter_complex', f'[0:v]{v_filter}[vout]; [1:a]volume=1.0[aout]',
            '-map', '[vout]', '-map', '[aout]',
            # Setting Kualitas
            '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '2500k',
            '-c:a', 'aac', '-ar', '44100', '-b:a', '128k',
            '-pix_fmt', 'yuv420p', '-f', 'flv', rtmp
        ]

        print(f"\n[🚀] MEMULAI SIARAN (Standardized Orientation: ACTIVE)")
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        for line in process.stdout:
            if "frame=" in line:
                print(f"Streaming: {line.strip()}", end="\r")
        
        process.wait()
        print("\n[✨] Sesi Live Selesai.")

    except Exception as e:
        print(f"\n⛔ ERROR SISTEM: {e}")
    finally:
        # Bersihkan file temp
        print("[*] Membersihkan file sementara...")
        for f in os.listdir():
            if f.startswith("vid_") or f.startswith("mus_") or f in ["v_list.txt", "m_list.txt"]:
                try: os.remove(f)
                except: pass

if __name__ == "__main__":
    main()
