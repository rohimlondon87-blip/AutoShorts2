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
LIVE_FOLDER_ID = os.environ.get('SOURCE_LIVE_ID')      # Folder Bahan Live
MUSIC_FOLDER_ID = os.environ.get('MUSIC_FOLDER_ID')   # Folder Bahan Music
TARGET_FOLDER_ID = os.environ.get('UPLOTAN_FOLDER_ID') # Folder Hasil (Uplotan)

MAX_DURATION = 15 

# --- DAFTAR KATA-KATA OTOMATIS ---
LIST_TEXT_SHORTS = [
    "POV: Menemukan spot kerja paling tenang di kantor.",
    "POV: Kamu butuh 15 detik untuk bernapas.",
    "POV: Hujan, kopi, dan pekerjaan yang belum selesai.",
    "POV: Menghilang sejenak dari keramaian dunia.",
    "Perjuangan hari ini adalah kekuatan untuk hari esok.",
    "Hidup adalah tentang perjalanan, bukan hanya tujuan.",
    "Jangan biarkan hari yang buruk membuatmu merasa hidupmu buruk.",
    "Setiap tetes keringat adalah benih kesuksesan.",
    "Lelah itu manusiawi, menyerah itu pilihan. Pilih untuk bangkit!",
    "Tuhan tidak akan memberikan beban melebihi kemampuan hamba-Nya.",
    "Today's Mood: Relaxing.",
    "Office Therapy."
]

def validate_paths():
    print("[*] Mengecek Pengaturan Secret...")
    errors = []
    if not TOKEN_DATA: errors.append("TOKEN_DATA")
    if not LIVE_FOLDER_ID: errors.append("SOURCE_LIVE_ID")
    if not MUSIC_FOLDER_ID: errors.append("MUSIC_FOLDER_ID")
    if not TARGET_FOLDER_ID: errors.append("UPLOTAN_FOLDER_ID")
    if errors:
        print(f"⛔ ERROR: Secret berikut kosong: {', '.join(errors)}")
        sys.exit(1)

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
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return float(result.stdout.strip())
    except:
        return 0

def get_all_videos(service, folder_id):
    q = f"'{folder_id}' in parents and mimeType contains 'video' and trashed=false"
    res = service.files().list(q=q, fields="files(id, name)").execute()
    return res.get('files', [])

def get_random_music(service, folder_id):
    q = f"'{folder_id}' in parents and mimeType contains 'audio' and trashed=false"
    res = service.files().list(q=q, fields="files(id, name)").execute()
    files = res.get('files', [])
    return random.choice(files) if files else None

def render_with_ffmpeg(v_in, a_in, v_out, text_overlay, start_ss):
    # Logika Wrapping Teks
    lines = textwrap.wrap(text_overlay, width=20)
    # Gunakan karakter khusus untuk baris baru yang dipahami FFmpeg filter
    wrapped_text = "\\\n".join(lines)
    wrapped_text = wrapped_text.replace("'", "") # Hapus petik tunggal agar tidak merusak filter
    
    print(f"[*] Menyiapkan Render: {text_overlay} (Start: {start_ss:.2f}s)")
    
    # Perbaikan Filter: Menghapus align=center (tidak semua versi FFmpeg mendukung)
    # Sebagai gantinya x=(w-text_w)/2 sudah cukup untuk rata tengah horizontal
    text_filter = (
        f"drawtext=text='{wrapped_text}':fontcolor=white:fontsize=80:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:fontfile=/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf:"
        f"box=1:boxcolor=black@0.5:boxborderw=30:line_spacing=20:"
        f"shadowcolor=black@0.9:shadowx=5:shadowy=5"
    )

    cmd = [
        'ffmpeg', '-y',
        '-ss', str(start_ss), '-t', str(MAX_DURATION), '-i', v_in,
        '-stream_loop', '-1', '-i', a_in,
        '-filter_complex', (
            f'[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,{text_filter}[vout]; '
            f'[0:a]volume=0.2[a1]; [1:a]volume=1.0[a2]; [a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23', '-t', str(MAX_DURATION),
        '-c:a', 'aac', '-b:a', '128k', v_out
    ]
    
    try:
        # Gunakan capture_output untuk melihat pesan error detail jika gagal lagi
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[-] FFmpeg Fail Log: {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"[-] System Error: {e}")
        return False

def main():
    print("=== ROBOT RENDER SHORTS MASSAL (FIX EXIT STATUS 8) ===")
    validate_paths()
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
        duration = get_video_duration("temp_v.mp4")
        start_ss = random.uniform(0, max(0, duration - MAX_DURATION - 1))
        
        m_info = get_random_music(service, MUSIC_FOLDER_ID)
        if m_info: download_file(service, m_info['id'], "temp_a.mp3")
        else: continue

        selected_text = random.choice(LIST_TEXT_SHORTS)
        output_name = f"Shorts_{random.randint(100,999)}.mp4"
        
        if render_with_ffmpeg("temp_v.mp4", "temp_a.mp3", output_name, selected_text, start_ss):
            print(f"[*] Mengunggah ke Drive...")
            try:
                meta = {'name': output_name, 'parents': [TARGET_FOLDER_ID]}
                media = MediaFileUpload(output_name, mimetype='video/mp4', resumable=True)
                service.files().create(body=meta, media_body=media).execute()
                print(f"[✅] BERHASIL!")
            except Exception as e:
                print(f"⛔ GAGAL UPLOAD: {e}")

        for tmp in ["temp_v.mp4", "temp_a.mp3", output_name]:
            if os.path.exists(tmp): os.remove(tmp)

if __name__ == "__main__":
    main()
