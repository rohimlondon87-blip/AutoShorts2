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

# --- KONFIGURASI GITHUB SECRETS ---
TOKEN_DATA = os.environ.get('TOKEN_DATA')
SOURCE_LIVE_ID = os.environ.get('SOURCE_LIVE_ID')      
MUSIC_FOLDER_ID = os.environ.get('MUSIC_FOLDER_ID')   
UPLOTAN_FOLDER_ID = os.environ.get('UPLOTAN_FOLDER_ID') 
QUOTES_FILE_ID = os.environ.get('QUOTES_FILE_ID') 

MAX_DURATION = 15 

def find_font():
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
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

def get_quotes_from_drive(service):
    """Mengambil teks dari Google Doc atau File TXT"""
    if not QUOTES_FILE_ID:
        return ["Tetap semangat hari ini!", "Perjuangan adalah kunci."]
    
    try:
        print(f"[*] Menghubungkan ke Drive untuk mengambil kutipan...")
        # Cek tipe file (Google Doc atau File Biasa)
        file_metadata = service.files().get(fileId=QUOTES_FILE_ID).execute()
        mime_type = file_metadata.get('mimeType')

        fh = io.BytesIO()
        if 'google-apps.document' in mime_type:
            # Jika Google Doc, ekspor sebagai plain text
            request = service.files().export_media(fileId=QUOTES_FILE_ID, mimeType='text/plain')
        else:
            # Jika file .txt biasa
            request = service.files().get_media(fileId=QUOTES_FILE_ID)
        
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        
        content = fh.getvalue().decode('utf-8')
        # Bersihkan baris kosong
        quotes = [line.strip() for line in content.split('\n') if line.strip()]
        print(f"✅ Berhasil memuat {len(quotes)} kutipan dari Drive.")
        return quotes
    except Exception as e:
        print(f"⚠️ Gagal mengambil quotes (Gunakan default): {e}")
        return ["Teruslah melangkah.", "Hari ini harus lebih baik."]

def get_video_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        return float(subprocess.check_output(cmd).decode().strip())
    except: return 0

def render_with_ffmpeg(v_in, a_in, v_out, text_overlay, start_ss, font_p):
    wrapped = "\n".join(textwrap.wrap(text_overlay, width=20))
    # Escape karakter spesial
    safe_text = wrapped.replace("'", "").replace(":", "\\:")
    
    # Filter Teks: Ukuran 85, Center, Box Hitam
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
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except:
        return False

def main():
    print("=== ROBOT RENDER SHORTS (SISTEM DRIVE EXTERNAL) ===")
    service = get_drive_service()
    font_path = find_font()
    if not service or not font_path: return

    # Ambil quotes dari Drive Anda
    quotes_list = get_quotes_from_drive(service)

    v_files = service.files().list(q=f"'{SOURCE_LIVE_ID}' in parents and mimeType contains 'video' and trashed=false").execute().get('files', [])
    m_files = service.files().list(q=f"'{MUSIC_FOLDER_ID}' in parents and mimeType contains 'audio' and trashed=false").execute().get('files', [])

    if not v_files: return

    for f in v_files:
        print(f"\n[▶] Memproses: {f['name']}")
        
        # Download Video
        with open("temp_v.mp4", "wb") as fh:
            fh.write(service.files().get_media(fileId=f['id']).execute())
        
        # Download Musik
        ms = random.choice(m_files)
        with open("temp_a.mp3", "wb") as fh:
            fh.write(service.files().get_media(fileId=ms['id']).execute())

        # Logika Randomisasi
        dur = get_video_duration("temp_v.mp4")
        start = random.uniform(0, max(0, dur - MAX_DURATION - 2))
        selected_text = random.choice(quotes_list)
        out = f"Shorts_{random.randint(100,999)}.mp4"

        if render_with_ffmpeg("temp_v.mp4", "temp_a.mp3", out, selected_text, start, font_path):
            print(f"[*] Render Berhasil: {selected_text}")
            meta = {
                'name': out, 
                'parents': [UPLOTAN_FOLDER_ID],
                'description': selected_text
            }
            media = MediaFileUpload(out, mimetype='video/mp4')
            service.files().create(body=meta, media_body=media).execute()
            print("[✅] Terunggah ke Drive.")
        
        for tmp in ["temp_v.mp4", "temp_a.mp3", out]:
            if os.path.exists(tmp): os.remove(tmp)

if __name__ == "__main__":
    main()
