import os
import base64
import pickle
import subprocess
import json
import time
import io
import random
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI SECRETS DINAMIS ---
TOKEN_DATA = os.environ.get('TOKEN_DATA')
# Folder ID sesuai permintaan user (Wajib diisi di GitHub Secrets)
INPUT_FOLDER_ID = os.environ.get('input_video_id')
OUTPUT_GABUNGAN_ID = os.environ.get('Gabungan_short_id')
DONE_ARCHIVE_ID = os.environ.get('Selesai_render_short_id')
# Folder musik untuk latar (opsional)
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')

def get_services():
    try:
        t_str = TOKEN_DATA.strip().replace('\xa0', '').replace(" ", "")
        pad = len(t_str) % 4
        if pad: t_str += '=' * (4 - pad)
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds), build('youtube', 'v3', credentials=creds)
    except Exception as e:
        print(f"⛔ Auth Error: {e}")
        return None, None

def get_video_duration(path):
    """Mendapatkan durasi video secara akurat."""
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', path]
        return float(subprocess.check_output(cmd).decode().strip())
    except: return 0

def standardize_clip(input_path, output_path):
    """Menyamakan resolusi 1080x1920 & fps agar transisi xfade stabil."""
    cmd = [
        'ffmpeg', '-y', '-i', input_path,
        '-vf', 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=24',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-an', output_path
    ]
    subprocess.run(cmd, capture_output=True)

def move_drive_file(service, file_id, old_parent, new_parent):
    """Memindahkan file antar folder di Google Drive."""
    try:
        service.files().update(fileId=file_id, addParents=new_parent, removeParents=old_parent).execute()
        return True
    except: return False

def main():
    print("=== ROBOT KOMPILASI MICRO WILD: CUSTOM FOLDER MODE ===")
    drive, youtube = get_services()
    if not drive: return

    # 1. AMBIL KLIP TERTUA DARI FOLDER INPUT (FIFO)
    print(f"[*] Mencari klip di folder input: {INPUT_FOLDER_ID}")
    query = f"'{INPUT_FOLDER_ID}' in parents and mimeType contains 'video' and trashed=false"
    # Mengambil 10 klip untuk video panjang yang berbobot
    res = drive.files().list(q=query, orderBy="createdTime", pageSize=10, fields="files(id, name)").execute()
    files = res.get('files', [])

    if len(files) < 2:
        print("[-] Bahan minimal 2 video. Antrean belum cukup.")
        return

    # 2. PROSES DOWNLOAD & STANDARISASI
    downloaded = []
    durations = []
    for i, f in enumerate(files):
        print(f"    -> Mendownload Klip {i+1}: {f['name']}")
        raw = f"raw_{i}.mp4"
        clean = f"clip_{i}.mp4"
        with open(raw, "wb") as fh:
            fh.write(drive.files().get_media(fileId=f['id']).execute())
        
        standardize_clip(raw, clean)
        durations.append(get_video_duration(clean))
        downloaded.append(clean)
        os.remove(raw)

    # 3. RAKIT FILTER TRANSISI (ANIMASI)
    transition = random.choice(['fade', 'wipeleft', 'circleopen', 'horzclose'])
    print(f"[*] Menggunakan Animasi: {transition}")

    filter_str = ""
    total_offset = 0
    for i in range(len(downloaded) - 1):
        if i == 0:
            total_offset = durations[0] - 1
            filter_str += f"[0:v][1:v]xfade=transition={transition}:duration=1:offset={total_offset}[v{i+1}];"
        else:
            total_offset += (durations[i] - 1)
            filter_str += f"[v{i}][{i+1}:v]xfade=transition={transition}:duration=1:offset={total_offset}[v{i+1}];"
    
    final_v_label = f"[v{len(downloaded)-1}]"
    out_name = f"Kompilasi_Mingguan_{int(time.time())}.mp4"

    # 4. EKSEKUSI RENDER
    inputs = []
    for d in downloaded: inputs.extend(['-i', d])
    
    cmd = inputs + [
        '-filter_complex', f"{filter_str}{final_v_label}format=yuv420p[vout]",
        '-map', '[vout]', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', out_name
    ]

    print("[🎬] Merender kompilasi artistik...")
    if subprocess.run(['ffmpeg', '-y'] + cmd).returncode == 0:
        print(f"✅ Render Berhasil: {out_name}")

        # 5. UPLOAD KE FOLDER GABUNGAN (Gudang Hasil)
        print("[*] Menyimpan ke folder Gabungan Shorts...")
        meta_gabungan = {'name': out_name, 'parents': [OUTPUT_GABUNGAN_ID]}
        media = MediaFileUpload(out_name, mimetype='video/mp4')
        drive.files().create(body=meta_gabungan, media_body=media, fields='id').execute()

        # 6. PINDAHKAN INPUT KE SELESAI_RENDER (Arsip Bahan)
        print("[*] Mengarsipkan bahan klip mentah ke folder Selesai...")
        for f_info in files:
            move_drive_file(drive, f_info['id'], INPUT_FOLDER_ID, DONE_ARCHIVE_ID)

        # 7. UPLOAD KE YOUTUBE
        print("[🚀] Memulai Upload ke YouTube...")
        judul_yt = f"Kompilasi Relaksasi Mingguan {datetime.now().strftime('%d/%m/%Y')} | #MicroWild"
        body_yt = {
            'snippet': {
                'title': judul_yt,
                'description': "Kumpulan momen terbaik minggu ini dengan transisi halus.\n#shorts #kompilasi #relaxing #microwild",
                'categoryId': '22'
            },
            'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
        }
        
        yt_media = MediaFileUpload(out_name, chunksize=-1, resumable=True)
        yt_res = youtube.videos().insert(part='snippet,status', body=body_yt, media_body=yt_media).execute()
        print(f"🎉 TAYANG DI YOUTUBE! ID: {yt_res['id']}")

    # Bersihkan file lokal
    for f in downloaded + [out_name]:
        if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
