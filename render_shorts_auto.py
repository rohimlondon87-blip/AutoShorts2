import os
import base64
import pickle
import random
import io
import sys
import subprocess
import textwrap
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.auth.transport.requests import Request

# --- KONFIGURASI DARI GITHUB SECRETS ---
TOKEN_DATA = os.environ.get('TOKEN_DATA')
LIVE_FOLDER_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_FOLDER_ID = os.environ.get('MUSIC_FOLDER_ID')
TARGET_FOLDER_ID = os.environ.get('UPLOTAN_FOLDER_ID')

MAX_DURATION = 15 # Detik

# --- DAFTAR KATA-KATA OTOMATIS ---
LIST_TEXT_SHORTS = [
   # Kategori POV & Relaksasi
    "POV: Menemukan spot kerja paling tenang di kantor.",
    "POV: Kamu butuh 15 detik untuk bernapas.",
    "POV: Hujan, kopi, dan pekerjaan yang belum selesai.",
    "POV: Menghilang sejenak dari keramaian dunia.",
    "Today's Mood: Relaxing.",
    "Office Therapy.",
    
    # Kategori Kehidupan & Perjuangan (BARU)
    "Perjuangan hari ini adalah kekuatan untuk hari esok.",
    "Hidup adalah tentang perjalanan, bukan hanya tujuan.",
    "Jangan biarkan hari yang buruk membuatmu merasa hidupmu buruk.",
    "Setiap tetes keringat adalah benih kesuksesan.",
    "Tetaplah berjuang meskipun dunia sedang tidak berpihak padamu.",
    "Bukan seberapa cepat kamu sampai, tapi seberapa tangguh kamu bertahan.",
    "Lelah itu manusiawi, menyerah itu pilihan. Pilih untuk bangkit!",
    "Tuhan tidak akan memberikan beban melebihi kemampuan hamba-Nya.",
    "Masa depan yang cerah dibangun dari kerja keras hari ini.",
    "Jadilah versi terbaik dari dirimu sendiri setiap harinya.",
    "Proses tidak akan pernah mengkhianati hasil.",
    "Satu langkah kecil hari ini adalah awal dari lompatan besar.",
    "Jangan bandingkan prosesmu dengan orang lain.",
    "Kerja keras dalam diam, biarkan suksesmu yang bersuara.",
    
    # Kategori Hook & Interaksi
    "Tonton sampai akhir: Ada yang tenang di menit terakhir.",
    "Coba dengerin pakai earphone... 🎧",
    "Rahasia tetap tenang di bawah tekanan.",
    "Definisi 'Healing' yang sebenarnya.",
    "Istirahatlah, kamu sudah melakukan yang terbaik hari ini.",
    "Absen yuk! Kota mana yang lagi hujan sekarang? 🌧️"
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

def download_file(service, file_id, out_name):
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(out_name, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

def get_video_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return float(result.stdout)
    except: return 0

def get_all_files(service, folder_id, mime_type):
    q = f"'{folder_id}' in parents and mimeType contains '{mime_type}' and trashed=false"
    res = service.files().list(q=q, fields="files(id, name)").execute()
    return res.get('files', [])

def render_with_ffmpeg(v_in, a_in, v_out, text_overlay, start_time):
    # Auto-wrap teks (memotong baris agar tidak melebar keluar layar)
    wrapped_text = "\n".join(textwrap.wrap(text_overlay, width=18))
    wrapped_text = wrapped_text.replace("'", "'\\\\\\''") # Escape untuk FFmpeg
    
    print(f"[*] Merender dari detik ke-{start_time:.2f} dengan teks: {text_overlay}")
    
    # Filter Teks: Perbaikan (Menghapus 'align=center' yang menyebabkan error)
    # x=(w-text_w)/2:y=(h-text_h)/2 tetap membuat teks berada di tengah video
    text_filter = (
        f"drawtext=text='{wrapped_text}':fontcolor=white:fontsize=80:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:fontfile=/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf:"
        f"box=1:boxcolor=black@0.5:boxborderw=30:line_spacing=15:"
        f"shadowcolor=black@0.9:shadowx=5:shadowy=5"
    )

    cmd = [
        'ffmpeg', '-y',
        '-ss', f'{start_time}', '-t', str(MAX_DURATION), '-i', v_in,
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
        print(f"[-] FFmpeg Error: {e}")
        return False

def main():
    print("=== ROBOT RENDER SHORTS (FULL RANDOMIZED - FIXED) ===")
    service = get_drive_service()
    if not service: return

    videos = get_all_files(service, LIVE_FOLDER_ID, "video")
    music_files = get_all_files(service, MUSIC_FOLDER_ID, "audio")

    if not videos or not music_files:
        print("[-] Bahan video atau musik tidak ditemukan.")
        return

    print(f"[*] Ditemukan {len(videos)} video dan {len(music_files)} musik.")

    for f_info in videos:
        v_id, v_name = f_info['id'], f_info['name']
        print(f"\n[▶] MEMPROSES: {v_name}")

        download_file(service, v_id, "temp_v.mp4")
        duration = get_video_duration("temp_v.mp4")
        
        # Tentukan titik potong acak
        start_t = 0
        if duration > MAX_DURATION:
            start_t = random.uniform(0, duration - MAX_DURATION)

        # Ambil musik acak
        m_info = random.choice(music_files)
        download_file(service, m_info['id'], "temp_a.mp3")

        # Pilih Teks Acak & Render
        selected_text = random.choice(LIST_TEXT_SHORTS)
        output_name = f"Shorts_{v_name.replace(' ', '_')}_{random.randint(100,999)}.mp4"
        
        if render_with_ffmpeg("temp_v.mp4", "temp_a.mp3", output_name, selected_text, start_t):
            print(f"[*] Mengunggah hasil ke Drive (Folder ID: {TARGET_FOLDER_ID})...")
            try:
                meta = {'name': output_name, 'parents': [TARGET_FOLDER_ID.strip()]}
                media = MediaFileUpload(output_name, mimetype='video/mp4', resumable=True)
                service.files().create(body=meta, media_body=media).execute()
                print(f"[✅] BERHASIL!")
            except Exception as e:
                print(f"⛔ GAGAL UPLOAD: {e}")

        # Bersihkan file sampah
        for tmp in ["temp_v.mp4", "temp_a.mp3", output_name]:
            if os.path.exists(tmp): os.remove(tmp)

    print("\n[🚀] SEMUA PROSES SELESAI!")

if __name__ == "__main__":
    main()
