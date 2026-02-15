import os
import base64
import pickle
import random
import io
import subprocess
import textwrap
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.auth.transport.requests import Request

# --- KONFIGURASI ---
TOKEN_DATA = os.environ.get('TOKEN_DATA_B') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')      
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')   
UPLOTAN_ID = os.environ.get('UPLOTAN_FOLDER_ID') 
QUOTES_ID = os.environ.get('QUOTES_FILE_ID') 

MAX_DURATION = 15 
BATCH_LIMIT = 5 # Membuat 5 video unik per jalan

def get_drive_service():
    try:
        # Perbaikan otomatis padding Base64
        t_str = TOKEN_DATA.strip()
        pad = len(t_str) % 4
        if pad: t_str += '=' * (4 - pad)
        
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error: {e}")
        return None

def get_clean_quotes(service):
    """Membaca quotes dan membuang baris kosong (Solusi Gambar 5)"""
    if not QUOTES_ID: return ["Tetap Semangat!"]
    try:
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, service.files().get_media(fileId=QUOTES_ID))
        done = False
        while not done: _, done = downloader.next_chunk()
        content = fh.getvalue().decode('utf-8')
        # Hanya ambil baris yang ada teksnya (minimal 5 karakter)
        lines = [l.strip() for l in content.splitlines() if len(l.strip()) > 5]
        random.shuffle(lines)
        return lines
    except: return ["Lakukan yang terbaik!"]

def render_video(v_in, a_in, v_out, text, v_start, a_start):
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    wrapped = "\n".join(textwrap.wrap(text, width=20))
    safe_txt = wrapped.replace("'", "").replace(":", "\\:")
    
    # Filter 9:16, Teks di tengah dengan background hitam transparan
    v_filter = (
        f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=text='{safe_txt}':fontcolor=white:fontsize=80:fontfile={font}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.6:boxborderw=40"
    )

    cmd = [
        'ffmpeg', '-y',
        '-ss', str(round(v_start, 2)), '-t', str(MAX_DURATION), '-i', v_in,
        '-ss', str(round(a_start, 2)), '-t', str(MAX_DURATION), '-i', a_in,
        '-filter_complex', f'[0:v]{v_filter}[vout]; [0:a]volume=0.3[a1]; [1:a]volume=1.2[a2]; [a1][a2]amix=inputs=2:duration=first[aout]',
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', '-t', str(MAX_DURATION), out
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0

def main():
    print("=== ROBOT RENDER MUCRO WILD (MULTI-VARIAN) ===")
    service = get_drive_service()
    if not service: return

    # Ambil dan acak semua bahan
    quotes = get_clean_quotes(service)
    v_files = service.files().list(q=f"'{SOURCE_ID}' in parents and trashed=false").execute().get('files', [])
    m_files = service.files().list(q=f"'{MUSIC_ID}' in parents and trashed=false").execute().get('files', [])

    random.shuffle(v_files)
    random.shuffle(m_files)

    for i in range(min(BATCH_LIMIT, len(v_files))):
        f_vid = v_files[i]
        f_mus = m_files[i % len(m_files)]
        txt = quotes[i % len(quotes)]
        
        print(f"[*] Membuat Video {i+1}: {txt[:30]}...")
        
        t_v, t_a = f"v{i}.mp4", f"a{i}.mp3"
        out = f"Shorts_{int(time.time())}_{i}.mp4"

        try:
            with open(t_v, "wb") as f: f.write(service.files().get_media(fileId=f_vid['id']).execute())
            with open(t_a, "wb") as f: f.write(service.files().get_media(fileId=f_mus['id']).execute())
            
            # Titik potong acak
            vs = random.uniform(0, 10) 
            as_ = random.uniform(0, 20)

            if render_video(t_v, t_a, out, txt, vs, as_):
                meta = {'name': out, 'parents': [UPLOTAN_ID], 'description': txt}
                service.files().create(body=meta, media_body=MediaFileUpload(out)).execute()
                print(f"✅ Berhasil diupload ke Drive.")
        finally:
            for f in [t_v, t_a, out]: 
                if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
