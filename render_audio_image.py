import os
import base64
import pickle
import subprocess
import random
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# --- KONFIGURASI FOLDER ---
TOKEN_DATA = os.environ.get('TOKEN_DATA')

# Gembok Folder di GitHub Secrets
IMAGE_FOLDER_ID = os.environ.get('IMAGE_FOLDER_ID') # Folder berisi bahan gambar (.jpg / .png)
AUDIO_FOLDER_ID = os.environ.get('MUSIC_FOLDER_ID') # Menggunakan folder musik yang sudah ada
RENDER_OUTPUT_ID = os.environ.get('UPLOTAN_FOLDER_ID') # Folder untuk menyimpan hasil render
PROCESSED_ID = os.environ.get('PROCESSED_FOLDER_ID') # Folder pembuangan bahan yang sudah dipakai

def get_services():
    try:
        t_str = TOKEN_DATA.strip().replace('\xa0', '').replace(" ", "").replace("\n", "")
        t_str += '=' * (4 - (len(t_str) % 4))
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"⛔ Auth Error: {e}")
        return None

def get_media_duration(file_path):
    """Mendapatkan durasi audio menggunakan FFprobe"""
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        return float(subprocess.check_output(cmd).decode().strip())
    except: 
        return 0

def move_file_to_processed(service, file_id, old_parent):
    """Memindahkan bahan yang sudah dipakai ke folder Arsip/Processed"""
    if PROCESSED_ID and PROCESSED_ID != "***":
        try:
            service.files().update(fileId=file_id, addParents=PROCESSED_ID, removeParents=old_parent).execute()
            print(f"    -> Berkas dipindahkan ke folder Arsip.")
        except Exception as e:
            print(f"    -> Gagal memindahkan berkas: {e}")

def main():
    print("=== ROBOT RENDER AUDIO VISUALIZER (HD 16:9 + NAMA FILE OTOMATIS) ===")
    drive = get_services()
    if not drive: return

    # 1. CARI BAHAN GAMBAR & AUDIO
    print("[*] Mencari bahan di Google Drive...")
    
    img_query = f"'{IMAGE_FOLDER_ID}' in parents and mimeType contains 'image/' and trashed=false"
    img_results = drive.files().list(q=img_query, fields="files(id, name)").execute()
    img_files = img_results.get('files', [])
    
    aud_query = f"'{AUDIO_FOLDER_ID}' in parents and mimeType contains 'audio/' and trashed=false"
    aud_results = drive.files().list(q=aud_query, fields="files(id, name)").execute()
    aud_files = aud_results.get('files', [])

    if not img_files or not aud_files:
        print("⛔ Kekurangan Bahan! Pastikan ada minimal 1 Gambar dan 1 Audio di folder masing-masing.")
        return

    selected_img = random.choice(img_files)
    selected_aud = random.choice(aud_files)

    print(f"[*] Bahan Terpilih:")
    print(f"    - Gambar : {selected_img['name']}")
    print(f"    - Audio  : {selected_aud['name']}")

    # 2. DOWNLOAD BAHAN & SIAPKAN NAMA FILE OUTPUT
    img_ext = os.path.splitext(selected_img['name'])[1] or '.jpg'
    aud_ext = os.path.splitext(selected_aud['name'])[1] or '.mp3'
    
    # MENGAMBIL NAMA FILE AUDIO UNTUK HASIL AKHIR (Tanpa ekstensi .mp3)
    nama_audio_asli = os.path.splitext(selected_aud['name'])[0]
    # Membersihkan nama file dari karakter yang mungkin dilarang oleh sistem
    nama_bersih = "".join([c for c in nama_audio_asli if c.isalpha() or c.isdigit() or c in " _-"]).strip()
    
    local_img = f"bahan_gambar{img_ext}"
    local_aud = f"bahan_audio{aud_ext}"
    
    # NAMA FILE HASIL RENDER AKAN MENGIKUTI NAMA AUDIO
    output_file = f"{nama_bersih}.mp4"

    with open(local_img, "wb") as f:
        f.write(drive.files().get_media(fileId=selected_img['id']).execute())
    with open(local_aud, "wb") as f:
        f.write(drive.files().get_media(fileId=selected_aud['id']).execute())

    # 3. PROSES RENDER (FFMPEG) DENGAN EFEK VISUALIZER
    durasi_audio = get_media_duration(local_aud)
    print(f"[*] Durasi Audio Terdeteksi: {durasi_audio:.2f} Detik")

    warna_visual = random.choice(["cyan", "yellow", "red", "00FF00", "magenta", "orange", "white"])
    print(f"[*] Warna Audio Visualizer: {warna_visual.upper()}")
    print(f"[*] Nama File Target: {output_file}")

    v_filter = (
        f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080[bg];"
        f"[1:a]showfreqs=s=1920x300:mode=bar:colors={warna_visual}[wave];"
        f"[bg][wave]overlay=0:H-h"
    )

    cmd = [
        'ffmpeg', '-y', 
        '-loop', '1', '-i', local_img,
        '-i', local_aud,
        '-filter_complex', v_filter,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', 
        '-c:a', 'aac', '-b:a', '128k', 
        '-t', str(durasi_audio),
        output_file
    ]

    print("\n[🎬] Mulai Merender Video Landscape HD...")
    res = subprocess.run(cmd, capture_output=True)

    if res.returncode != 0:
        print("⛔ FFmpeg Error saat merender video.")
    else:
        print(f"✅ Render Berhasil! Menyimpan ke Google Drive...")
        
        # 4. UPLOAD HASIL RENDER KE FOLDER 'UPLOTAN'
        file_metadata = {
            'name': output_file,
            'parents': [RENDER_OUTPUT_ID]
        }
        drive.files().create(
            body=file_metadata,
            media_body=MediaFileUpload(output_file, mimetype='video/mp4', resumable=True)
        ).execute()
        
        print(f"🎉 Video '{output_file}' berhasil disimpan ke folder Siap Upload!")

        # 5. PINDAHKAN BAHAN YANG SUDAH DIPAKAI
        print("[*] Merapikan file bahan...")
        move_file_to_processed(drive, selected_img['id'], IMAGE_FOLDER_ID)
        move_file_to_processed(drive, selected_aud['id'], AUDIO_FOLDER_ID)

    # 6. BERSIH-BERSIH SERVER
    for f in [local_img, local_aud, output_file]:
        if os.path.exists(f):
            try: os.remove(f)
            except: pass

if __name__ == "__main__":
    main()