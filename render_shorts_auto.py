import os
import base64
import pickle
import random
import io
import sys
import subprocess
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.auth.transport.requests import Request

# --- KONFIGURASI DARI GITHUB SECRETS ---
TOKEN_DATA = os.environ.get('TOKEN_DATA')
LIVE_FOLDER_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_FOLDER_ID = os.environ.get('MUSIC_FOLDER_ID')
TARGET_FOLDER_ID = os.environ.get('UPLOTAN_FOLDER_ID')

MAX_DURATION = 15 

# --- DAFTAR KATA-KATA OTOMATIS (Sesuai ide_tulisan_shorts.md) ---
LIST_TEXT_SHORTS = [
    # Kategori POV
    "POV: Menemukan spot kerja paling tenang di kantor.",
    "POV: Kamu butuh 15 detik untuk bernapas.",
    "POV: Hujan, kopi, dan pekerjaan yang belum selesai.",
    "POV: Menghilang sejenak dari keramaian dunia.",
    "POV: Menikmati kesendirian di tengah hiruk pikuk.",
    
    # Kategori Hook (Pancingan)
    "Tonton sampai akhir: Ada yang tenang di menit terakhir.",
    "Coba dengerin pakai earphone... 🎧",
    "Rahasia tetap tenang di bawah tekanan.",
    "Definisi 'Healing' yang sebenarnya.",
    "Pernah gak ngerasa se-damai ini?",
    
    # Kategori Quotes & Afirmasi
    "Istirahatlah, kamu sudah melakukan yang terbaik hari ini.",
    "Pelan-pelan saja, semua akan selesai pada waktunya.",
    "Jangan lupa bahagia di sela-sela sibukmu.",
    "Fokus pada proses, bukan hanya hasil.",
    "Satu langkah kecil lebih baik daripada diam.",
    
    # Kategori Interaksi
    "Absen yuk! Kota mana yang lagi hujan sekarang? 🌧️",
    "Pilih mana: Kerja di kantor atau WFH?",
    "Skala 1-10, seberapa capek kamu hari ini?",
    "Tulis 1 keinginanmu yang ingin dicapai bulan ini.",
    
    # Kategori Estetik
    "Today's Mood: Relaxing.",
    "Current State: Focusing.",
    "Digital Detox: 15 Seconds.",
    "Office Therapy.",
    "Quiet Mind, Busy Hands."
]

def get_drive_service():
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_DATA))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error: {e}")
        return None

def download_random_file(service, folder_id, mime_filter, out_name):
    q = f"'{folder_id}' in parents and mimeType contains '{mime_filter}' and trashed=false"
    res = service.files().list(q=q, fields="files(id, name)").execute()
    files = res.get('files', [])
    if not files: return None
    
    selected = random.choice(files)
    print(f"[*] Terpilih dari Drive: {selected['name']}")
    
    request = service.files().get_media(fileId=selected['id'])
    with io.FileIO(out_name, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return selected['name']

def render_with_ffmpeg(v_in, a_in, v_out, text_overlay):
    print(f"[*] Memproses Video dengan Teks: '{text_overlay}'")
    
    # Desain Teks: 
    # Font Putih, Ukuran 45, Di tengah layar, Dengan bayangan hitam (Shadow)
    text_filter = (
        f"drawtext=text='{text_overlay}':fontcolor=white:fontsize=45:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-100:fontfile=/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf:"
        f"shadowcolor=black@0.7:shadowx=3:shadowy=3"
    )

    cmd = [
        'ffmpeg', '-y',
        '-ss', '0', '-t', str(MAX_DURATION), '-i', v_in,
        '-stream_loop', '-1', '-i', a_in,
        '-filter_complex', (
            f'[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,{text_filter}[vout]; '
            f'[0:a]volume=0.2[a1]; [1:a]volume=1.0[a2]; [a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-t', str(MAX_DURATION),
        '-c:a', 'aac', '-b:a', '128k', v_out
    ]
    
    try:
        subprocess.run(cmd, check=True)
        return True
    except Exception as e:
        print(f"[-] Gagal Render: {e}")
        return False

def main():
    print("=== ROBOT RENDER SHORTS OTOMATIS (VERSI TEKS BERAGAM) ===")
    service = get_drive_service()
    if not service: return

    # 1. Ambil Bahan Acak
    v_name = download_random_file(service, LIVE_FOLDER_ID, "video", "raw_v.mp4")
    download_random_file(service, MUSIC_FOLDER_ID, "audio", "raw_a.mp3")

    if not v_name:
        print("[-] Bahan tidak ditemukan di folder Drive.")
        return

    # 2. Pilih Teks Acak dari Daftar yang Sudah Diperluas
    selected_text = random.choice(LIST_TEXT_SHORTS)
    
    # 3. Render
    output_filename = f"Shorts_Ready_{random.randint(1000,9999)}.mp4"
    if render_with_ffmpeg("raw_v.mp4", "raw_a.mp3", output_filename, selected_text):
        print(f"[*] Mengunggah hasil ke Drive: {output_filename}")
        
        file_metadata = {
            'name': output_filename,
            'parents': [TARGET_FOLDER_ID]
        }
        media = MediaFileUpload(output_filename, mimetype='video/mp4', resumable=True)
        service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        print("[🚀] SELESAI!")
    
    # Bersihkan file sampah di server GitHub
    for f in ["raw_v.mp4", "raw_a.mp3", output_filename]:
        if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
