import os
import base64
import pickle
import subprocess
import random
import io
import json
import time
import textwrap
import math
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI MICRO WILD ---
TOKEN_B64 = os.environ.get('TOKEN_DATA_B') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
QUOTES_ID = os.environ.get('QUOTES_FILE_ID')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

# Durasi Live stabil 1 jam (3600 detik)
LIVE_TARGET_DURATION = 3600 

def get_services():
    try:
        t_str = TOKEN_B64.strip().replace('\xa0', '').replace(" ", "").replace("\n", "")
        t_str += '=' * (4 - (len(t_str) % 4))
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token: creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"⛔ GAGAL AUTH: {e}")
        return None

def get_quotes(service):
    backup = ["Stay Wild with MICRO WILD", "Menemukan ketenangan dalam alam.", "Fokus dan Produktif."]
    try:
        file_meta = service.files().get(fileId=QUOTES_ID).execute()
        fh = io.BytesIO()
        if 'application/vnd.google-apps' in file_meta.get('mimeType', ''):
            req = service.files().export_media(fileId=QUOTES_ID, mimeType='text/plain')
        else:
            req = service.files().get_media(fileId=QUOTES_ID)
        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while not done: _, done = downloader.next_chunk()
        lines = [l.strip() for l in fh.getvalue().decode('utf-8-sig').splitlines() if len(l.strip()) > 5]
        return lines if lines else backup
    except: return backup

def get_duration(input_p):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', input_p]
        return float(subprocess.check_output(cmd).decode().strip())
    except: return 0

def standardize_video(input_p, output_p, quotes_pool, font_p):
    """
    Memastikan video 720p HD dan memasang teks berbeda setiap 3 menit.
    Menggunakan audio asli dari video.
    """
    duration = get_duration(input_p)
    
    # 1. Cek Rotasi
    try:
        cmd_rot = ['ffprobe', '-loglevel', 'error', '-select_streams', 'v:0', '-show_entries', 'stream_tags=rotate', '-of', 'json', input_p]
        res = subprocess.check_output(cmd_rot).decode('utf-8')
        rot = int(json.loads(res).get('streams', [{}])[0].get('tags', {}).get('rotate', 0))
    except: rot = 0

    vf = []
    if rot == 90: vf.append("transpose=1")
    elif rot == 180: vf.append("hflip,vflip")
    elif rot == 270: vf.append("transpose=2")
    
    # Resolusi Standar Landscape 16:9
    vf.append("scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1")

    # 2. Overlay Teks Dinamis (Muncul setiap 180 detik / 3 menit)
    if font_p and duration > 0:
        # Tentukan berapa kali teks harus muncul
        instances = math.ceil(duration / 180)
        for i in range(instances):
            start_t = (i * 180) + 10 # Mulai di detik ke-10, 190, 370...
            end_t = start_t + 30     # Muncul selama 30 detik
            
            if start_t < duration:
                txt = random.choice(quotes_pool)
                # Bungkus teks agar tidak melebar keluar layar
                wrapped_txt = "\\n".join(textwrap.wrap(txt, width=35))
                safe_txt = wrapped_txt.replace("'", "").replace(":", "\\:")
                
                dt = (f"drawtext=text='{safe_txt}':fontfile='{font_p}':fontcolor=white:fontsize=40:"
                      f"box=1:boxcolor=black@0.4:boxborderw=20:x=(w-text_w)/2:y='h-text_h-100 + 10*sin(t*1.5)':"
                      f"enable='between(t,{start_t},{end_t})'")
                vf.append(dt)

    # 3. Indikator "REC" Berkedip (Efek Seni Kamera)
    vf.append("drawtext=text='● REC':fontcolor=red:fontsize=30:x=50:y=50:alpha='if(lt(mod(t,2),1),1,0.2)'")
    
    # 4. Jam Digital Pojok Kanan
    vf.append(f"drawtext=text='%{{localtime\\:%H\\\\:%M\\\\:%S}}':fontcolor=white:fontsize=25:x=w-text_w-50:y=50:box=1:boxcolor=black@0.5")

    cmd = [
        'ffmpeg', '-y', '-i', input_p, '-vf', ",".join(vf),
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
        '-c:a', 'aac', '-ar', '44100', '-ac', '2', output_p
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0

def main():
    print(f"=== MICRO WILD: LIVE STREAM ENGINE (ORIGINAL AUDIO + DYNAMIC OVERLAY) ===")
    drive = get_services()
    if not drive: return

    # 1. Ambil List File
    v_files = drive.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false").execute().get('files', [])
    quotes = get_quotes(drive)
    
    # Font standar di Linux
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    if not v_files:
        print("⛔ Folder Video Sumber Kosong!")
        return
    
    random.shuffle(v_files)

    # 2. Persiapan Video (Standardisasi & Baking)
    v_list = ""
    # Maksimal 10 video untuk menjaga stabilitas server
    for i, v_info in enumerate(v_files[:10]):
        raw, fixed = f"raw_{i}.mp4", f"vid_{i}.mp4"
        print(f"[*] Mengolah Video {i+1}: {v_info['name']}")
        
        try:
            with open(raw, "wb") as f:
                f.write(drive.files().get_media(fileId=v_info['id']).execute())
            
            if standardize_video(raw, fixed, quotes, font_path):
                v_list += f"file '{fixed}'\n"
            
            if os.path.exists(raw): os.remove(raw)
        except Exception as e:
            print(f"   ⚠️ Lewati file {v_info['name']} karena error: {e}")

    if not v_list:
        print("⛔ Tidak ada video yang berhasil diolah.")
        return

    with open("v_list.txt", "w") as f: f.write(v_list)

    # 3. Jalankan Streaming
    rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    print(f"\n[🚀] MEMULAI SIARAN LANGSUNG DENGAN AUDIO ASLI...")
    
    # FFmpeg Command: 
    # - concat: menyambung video-video hasil olahan
    # - stream_loop -1: mengulang terus jika durasi total kurang dari target
    cmd = [
        'ffmpeg', '-y', '-re',
        '-f', 'concat', '-safe', '0', '-stream_loop', '-1', '-i', 'v_list.txt',
        '-t', str(LIVE_TARGET_DURATION),
        '-c:v', 'copy',  # Copy codec dari hasil baking agar CPU hemat
        '-c:a', 'copy',  # Menggunakan audio asli sepenuhnya
        '-f', 'flv', rtmp_url
    ]

    # Jalankan proses siaran
    subprocess.run(cmd)
    print("\n✅ SIARAN SELESAI.")

    # Bersih-bersih file lokal
    for f in os.listdir():
        if f.startswith("vid_") or f == "v_list.txt":
            try: os.remove(f)
            except: pass

if __name__ == "__main__":
    main()
