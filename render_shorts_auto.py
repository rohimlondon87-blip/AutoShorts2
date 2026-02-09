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

# --- KONFIGURASI SESUAI GITHUB SECRETS ---
TOKEN_DATA = os.environ.get('TOKEN_DATA')
SOURCE_LIVE_ID = os.environ.get('SOURCE_LIVE_ID')      
MUSIC_FOLDER_ID = os.environ.get('MUSIC_FOLDER_ID')   
UPLOTAN_FOLDER_ID = os.environ.get('UPLOTAN_FOLDER_ID') 

MAX_DURATION = 15 

LIST_TEXT_SHORTS = [
   # Tema Perjuangan
    "Perjuangan hari ini adalah kekuatan untuk hari esok.",
    "Lelah itu manusiawi, menyerah itu pilihan. Bangkit!",
    "Hasil tidak akan pernah mengkhianati proses yang jujur.",
    "Jangan berhenti saat lelah, berhentilah saat selesai.",
    "Masa sulit akan membentuk pribadi yang jauh lebih kuat.",
    "Kemenangan terbesar adalah saat kita mampu mengalahkan diri sendiri.",
    "Bekerja keraslah dalam diam, biarkan suksesmu yang bersuara.",
    "Setiap tetes keringat adalah investasi untuk masa depanmu.",
    "Rasa sakit yang kamu rasakan hari ini akan jadi kekuatanmu besok.",
    "Disiplin adalah jembatan antara cita-cita dan pencapaian.",
    
    # Tema Kehidupan
    "Hidup adalah tentang perjalanan, bukan hanya tentang tujuan.",
    "Jangan biarkan hari yang buruk membuatmu merasa hidupmu buruk.",
    "Setiap hari adalah kesempatan baru untuk memperbaiki diri.",
    "Fokuslah pada apa yang bisa kamu kendalikan hari ini.",
    "Masa depan adalah milik mereka yang percaya pada mimpi mereka.",
    "Hidup bukan tentang menemukan diri, tapi menciptakan diri sendiri.",
    "Pelan-pelan saja, semua akan sampai pada waktunya.",
    "Hargai setiap proses kecil yang sedang kamu lalui.",
    "Jangan bandingkan bab pertama hidupmu dengan bab ke-20 orang lain.",
    "Jadilah versi terbaik dari dirimu sendiri, bukan salinan orang lain.",
    
    # Tema Relaksasi & POV
    "POV: Menemukan ketenangan di tengah hiruk pikuk dunia.",
    "POV: Kamu hanya butuh 15 detik untuk kembali bernapas.",
    "Istirahat sejenak, kamu sudah melakukan yang terbaik hari ini.",
    "Today's Mood: Tenang, Fokus, dan Tetap Berjuang.",
    "Jangan lupa bahagia di sela-sela perjuanganmu."
]

def find_font():
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
    ]
    for p in paths:
        if os.path.exists(p): return p
    return None

def get_drive_service():
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_DATA))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error: {e}")
        return None

def get_video_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        return float(subprocess.check_output(cmd).decode().strip())
    except: return 0

def render_with_ffmpeg(v_in, a_in, v_out, text_overlay, start_ss, font_p):
    wrapped = "\n".join(textwrap.wrap(text_overlay, width=20))
    safe_text = wrapped.replace("'", "").replace(":", "\\:")
    
    text_filter = (
        f"drawtext=text='{safe_text}':fontcolor=white:fontsize=85:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:fontfile={font_p}:"
        f"box=1:boxcolor=black@0.5:boxborderw=35:line_spacing=20:"
        f"shadowcolor=black@0.9:shadowx=5:shadowy=5"
    )

    cmd = [
        'ffmpeg', '-y',
        '-ss', str(round(start_ss, 2)), '-t', str(MAX_DURATION), '-i', v_in,
        '-stream_loop', '-1', '-i', a_in,
        '-filter_complex', (
            f'[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,{text_filter}[vout]; '
            f'[0:a]volume=0.2[a1]; [1:a]volume=1.0[a2]; [a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26', '-t', str(MAX_DURATION),
        '-c:a', 'aac', '-b:a', '128k', v_out
    ]
    
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.returncode == 0
    except:
        return False

def main():
    print("=== ROBOT SHORTS (SISTEM CATATAN TEKS) ===")
    service = get_drive_service()
    font_path = find_font()
    if not service or not font_path: return

    v_files = service.files().list(q=f"'{SOURCE_LIVE_ID}' in parents and mimeType contains 'video' and trashed=false").execute().get('files', [])
    m_files = service.files().list(q=f"'{MUSIC_FOLDER_ID}' in parents and mimeType contains 'audio' and trashed=false").execute().get('files', [])

    if not v_files: return

    for f in v_files:
        print(f"\n[▶] Memproses: {f['name']}")
        
        # Download Video & Music
        download_req = service.files().get_media(fileId=f['id'])
        with open("temp_v.mp4", "wb") as fh:
            downloader = MediaIoBaseDownload(fh, download_req)
            done = False
            while not done: _, done = downloader.next_chunk()
            
        ms = random.choice(m_files)
        with open("temp_a.mp3", "wb") as fh:
            downloader = MediaIoBaseDownload(fh, service.files().get_media(fileId=ms['id']))
            done = False
            while not done: _, done = downloader.next_chunk()

        # Logika Render
        dur = get_video_duration("temp_v.mp4")
        start = random.uniform(0, max(0, dur - MAX_DURATION - 2))
        selected_text = random.choice(LIST_TEXT_SHORTS)
        out = f"Shorts_{random.randint(1000,9999)}.mp4"

        if render_with_ffmpeg("temp_v.mp4", "temp_a.mp3", out, selected_text, start, font_path):
            print("[*] Mengunggah ke Folder Uplotan dengan Metadata Teks...")
            # Kita simpan selected_text di properti 'description' file Drive
            meta = {
                'name': out, 
                'parents': [UPLOTAN_FOLDER_ID],
                'description': selected_text # <--- INI KUNCI UNTUK JUDUL NANTI
            }
            media = MediaFileUpload(out, mimetype='video/mp4')
            service.files().create(body=meta, media_body=media).execute()
            print("[✅] BERHASIL!")
        
        for tmp in ["temp_v.mp4", "temp_a.mp3", out]:
            if os.path.exists(tmp): os.remove(tmp)

if __name__ == "__main__":
    main()
