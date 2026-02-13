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
# Mencari TOKEN_DATA_B agar sesuai dengan pengaturan di Workflow (.yml)
TOKEN_DATA = os.environ.get('TOKEN_DATA_B') 
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')      
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')   
UPLOTAN_ID = os.environ.get('UPLOTAN_FOLDER_ID') 
QUOTES_ID = os.environ.get('QUOTES_FILE_ID') 

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
        if not TOKEN_DATA:
            print("⛔ ERROR: TOKEN_DATA_B tidak ditemukan di GitHub Secrets!")
            return None
        creds = pickle.loads(base64.b64decode(TOKEN_DATA))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error (Proyek B): {e}")
        return None

def get_quotes_from_drive(service):
    if not QUOTES_ID:
        return ["Tetap semangat!", "Jangan menyerah."]
    try:
        fh = io.BytesIO()
        request = service.files().get_media(fileId=QUOTES_ID)
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        content = fh.getvalue().decode('utf-8')
        return [line.strip() for line in content.split('\n') if line.strip()]
    except Exception as e:
        print(f"Gagal ambil quotes: {e}")
        return ["Lakukan yang terbaik hari ini!"]

def get_media_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        return float(subprocess.check_output(cmd).decode().strip())
    except: return 0

def render_with_ffmpeg(v_in, a_in, v_out, text_overlay, v_start, a_start, font_p):
    wrapped = "\n".join(textwrap.wrap(text_overlay, width=22))
    safe_text = wrapped.replace("'", "").replace(":", "\\:")
    
    v_filter = (
        f"scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,"
        f"drawtext=text='{safe_text}':fontcolor=white:fontsize=85:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:fontfile={font_p}:"
        f"box=1:boxcolor=black@0.6:boxborderw=35:line_spacing=18:"
        f"shadowcolor=black@0.9:shadowx=5:shadowy=5"
    )

    cmd = [
        'ffmpeg', '-y',
        '-ss', str(round(v_start, 2)), '-t', str(MAX_DURATION), '-i', v_in,
        '-ss', str(round(a_start, 2)), '-t', str(MAX_DURATION), '-i', a_in,
        '-filter_complex', (
            f'[0:v]{v_filter}[vout]; '
            f'[0:a]volume=0.2[a1]; [1:a]volume=1.2[a2]; [a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26', '-t', str(MAX_DURATION),
        '-c:a', 'aac', '-b:a', '128k', v_out
    ]
    
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg Error: {e}")
        return False

def main():
    print("=== ROBOT RENDER SHORTS DINAMIS (9:16) - MENGGUNAKAN PROYEK B ===")
    service = get_drive_service()
    font_path = find_font()
    if not service or not font_path: return

    try:
        quotes_list = get_quotes_from_drive(service)
        v_res = service.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false", fields="files(id, name)").execute()
        m_res = service.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio' and trashed=false", fields="files(id, name)").execute()
        
        v_files = v_res.get('files', [])
        m_files = m_res.get('files', [])

        if not v_files:
            print("[-] Folder video sumber kosong.")
            return
        if not m_files:
            print("⛔ Folder musik kosong.")
            return
            
        print(f"[*] Memproses {len(v_files)} video...")

    except Exception as e:
        print(f"Gagal mengambil database Drive: {e}")
        return

    for index, f_vid in enumerate(v_files):
        f_mus = random.choice(m_files)
        selected_text = random.choice(quotes_list)
        
        temp_v = f"v_raw_{index}.mp4"
        temp_a = f"a_raw_{index}.mp3"
        output_name = f"Shorts_{random.randint(10000, 99999)}.mp4"

        try:
            with open(temp_v, "wb") as f: f.write(service.files().get_media(fileId=f_vid['id']).execute())
            with open(temp_a, "wb") as f: f.write(service.files().get_media(fileId=f_mus['id']).execute())

            dur_v = get_media_duration(temp_v)
            v_start = random.uniform(0, max(0, dur_v - MAX_DURATION - 1)) if dur_v > MAX_DURATION + 1 else 0

            dur_a = get_media_duration(temp_a)
            a_start = random.uniform(0, max(0, dur_a - MAX_DURATION - 1)) if dur_a > MAX_DURATION + 1 else 0

            if render_with_ffmpeg(temp_v, temp_a, output_name, selected_text, v_start, a_start, font_path):
                meta = {'name': output_name, 'parents': [UPLOTAN_ID], 'description': selected_text}
                media = MediaFileUpload(output_name, mimetype='video/mp4')
                service.files().create(body=meta, media_body=media).execute()
                print(f"[✅] SELESAI: {output_name}")

        except Exception as e:
            print(f"❌ Error file {f_vid['name']}: {e}")
        
        finally:
            for tmp in [temp_v, temp_a, output_name]:
                if os.path.exists(tmp): os.remove(tmp)

if __name__ == "__main__":
    main()
