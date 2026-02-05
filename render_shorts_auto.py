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
LIVE_FOLDER_ID = os.environ.get('SOURCE_LIVE_ID')      # Folder Bahan Live
MUSIC_FOLDER_ID = os.environ.get('MUSIC_FOLDER_ID')   # Folder Bahan Music
TARGET_FOLDER_ID = os.environ.get('UPLOTAN_FOLDER_ID') # Folder Hasil (Uplotan)
ARCHIVE_FOLDER_ID = os.environ.get('PROCESSED_FOLDER_ID') # Folder Arsip Selesai

MAX_DURATION = 15 

# --- DAFTAR KATA-KATA OTOMATIS ---
LIST_TEXT_SHORTS = [
    "POV: Menemukan spot kerja paling tenang di kantor.",
    "POV: Kamu butuh 15 detik untuk bernapas.",
    "POV: Hujan, kopi, dan pekerjaan yang belum selesai.",
    "POV: Menghilang sejenak dari keramaian dunia.",
    "Tonton sampai akhir: Ada yang tenang di menit terakhir.",
    "Coba dengerin pakai earphone... 🎧",
    "Rahasia tetap tenang di bawah tekanan.",
    "Definisi 'Healing' yang sebenarnya.",
    "Istirahatlah, kamu sudah melakukan yang terbaik hari ini.",
    "Pelan-pelan saja, semua akan selesai pada waktunya.",
    "Jangan lupa bahagia di sela-sela sibukmu.",
    "Today's Mood: Relaxing.",
    "Office Therapy."
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

def get_all_videos(service, folder_id):
    q = f"'{folder_id}' in parents and mimeType contains 'video' and trashed=false"
    res = service.files().list(q=q, fields="files(id, name)").execute()
    return res.get('files', [])

def get_random_music(service, folder_id):
    q = f"'{folder_id}' in parents and mimeType contains 'audio' and trashed=false"
    res = service.files().list(q=q, fields="files(id, name)").execute()
    files = res.get('files', [])
    return random.choice(files) if files else None

def move_to_archive(service, file_id, source_folder, target_folder):
    if not target_folder: return
    service.files().update(
        fileId=file_id,
        addParents=target_folder,
        removeParents=source_folder,
        fields='id, parents'
    ).execute()

def render_with_ffmpeg(v_in, a_in, v_out, text_overlay):
    print(f"[*] Rendering Teks Besar: {text_overlay}")
    
    # Perbaikan Filter Teks:
    # fontsize=90 (Sangat besar)
    # box=1 (Menambahkan kotak latar belakang agar teks tajam)
    # y=h/2 (Tepat di tengah vertikal)
    text_filter = (
        f"drawtext=text='{text_overlay}':fontcolor=white:fontsize=90:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:fontfile=/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf:"
        f"box=1:boxcolor=black@0.4:boxborderw=20:" # Kotak hitam transparan agar tulisan tajam
        f"shadowcolor=black@0.9:shadowx=5:shadowy=5"
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
    print("=== ROBOT RENDER SHORTS MASSAL (TEKS BESAR & TAJAM) ===")
    service = get_drive_service()
    if not service: return

    videos = get_all_videos(service, LIVE_FOLDER_ID)
    if not videos:
        print("[-] Folder sumber kosong.")
        return

    for f_info in videos:
        v_id, v_name = f_info['id'], f_info['name']
        print(f"\n[▶] Memproses: {v_name}")

        download_file(service, v_id, "temp_v.mp4")
        m_info = get_random_music(service, MUSIC_FOLDER_ID)
        if m_info: download_file(service, m_info['id'], "temp_a.mp3")
        else: continue

        selected_text = random.choice(LIST_TEXT_SHORTS)
        output_name = f"Shorts_HD_{random.randint(100,999)}.mp4"
        
        if render_with_ffmpeg("temp_v.mp4", "temp_a.mp3", output_name, selected_text):
            # Upload
            meta = {'name': output_name, 'parents': [TARGET_FOLDER_ID]}
            media = MediaFileUpload(output_name, mimetype='video/mp4', resumable=True)
            service.files().create(body=meta, media_body=media).execute()

            # Arsip
            move_to_archive(service, v_id, LIVE_FOLDER_ID, ARCHIVE_FOLDER_ID)
            print(f"[✅] Selesai: {v_name}")
        
        for tmp in ["temp_v.mp4", "temp_a.mp3", output_name]:
            if os.path.exists(tmp): os.remove(tmp)

if __name__ == "__main__":
    main()
