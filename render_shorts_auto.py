import os
import base64
import pickle
import random
import io
import sys
import subprocess
import textwrap
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.auth.transport.requests import Request

# --- KONFIGURASI GITHUB SECRETS ---
TOKEN_DATA = os.environ.get('TOKEN_DATA_B') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')      
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')   
UPLOTAN_ID = os.environ.get('UPLOTAN_FOLDER_ID') 
QUOTES_ID = os.environ.get('QUOTES_FILE_ID') 

MAX_DURATION = 15 
BATCH_LIMIT = 5 # Batasi render sekali jalan agar tidak overload (misal 5 video)

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
        if not TOKEN_DATA:
            print("⛔ ERROR: Token tidak ditemukan!")
            return None
        creds = pickle.loads(base64.b64decode(TOKEN_DATA))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error: {e}")
        return None

def get_quotes_from_drive(service):
    if not QUOTES_ID:
        return ["Lakukan yang terbaik!"]
    try:
        fh = io.BytesIO()
        request = service.files().get_media(fileId=QUOTES_ID)
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        content = fh.getvalue().decode('utf-8')
        # Gunakan splitlines agar lebih akurat membagi baris
        lines = [l.strip() for l in content.splitlines() if len(l.strip()) > 5]
        random.shuffle(lines) # Acak urutan kutipan
        return lines
    except Exception as e:
        print(f"Gagal ambil quotes: {e}")
        return ["Tetap semangat hari ini!"]

def get_media_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        return float(subprocess.check_output(cmd).decode().strip())
    except: return 0

def render_with_ffmpeg(v_in, a_in, v_out, text_overlay, v_start, a_start, font_p):
    # Bungkus teks agar tidak melebar keluar layar
    wrapped = "\n".join(textwrap.wrap(text_overlay, width=20))
    # Escape karakter khusus untuk FFmpeg
    safe_text = wrapped.replace("'", "").replace(":", "\\:")
    
    v_filter = (
        f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=text='{safe_text}':fontcolor=white:fontsize=80:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:fontfile={font_p}:"
        f"box=1:boxcolor=black@0.6:boxborderw=40:line_spacing=20:"
        f"shadowcolor=black@0.9:shadowx=4:shadowy=4"
    )

    cmd = [
        'ffmpeg', '-y',
        '-ss', str(round(v_start, 2)), '-t', str(MAX_DURATION), '-i', v_in,
        '-ss', str(round(a_start, 2)), '-t', str(MAX_DURATION), '-i', a_in,
        '-filter_complex', (
            f'[0:v]{v_filter}[vout]; '
            f'[0:a]volume=0.3[a1]; [1:a]volume=1.0[a2]; [a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', '-t', str(MAX_DURATION),
        '-c:a', 'aac', '-b:a', '128k', v_out
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg Error: {e.stderr.decode()[:200]}")
        return False

def main():
    print("=== ROBOT RENDER SHORTS UNIK (MUCRO WILD) ===")
    service = get_drive_service()
    font_path = find_font()
    if not service or not font_path: return

    try:
        # Ambil database
        quotes_list = get_quotes_from_drive(service)
        v_res = service.files().list(q=f"'{SOURCE_ID}' in parents and trashed=false", fields="files(id, name)").execute()
        m_res = service.files().list(q=f"'{MUSIC_ID}' in parents and trashed=false", fields="files(id, name)").execute()
        
        v_files = v_res.get('files', [])
        m_files = m_res.get('files', [])

        if not v_files or not m_files:
            print("⛔ Bahan video atau musik tidak ditemukan.")
            return
            
        # ACAK SEMUA DAFTAR AGAR UNIK
        random.shuffle(v_files)
        random.shuffle(m_files)
        
        # Batasi jumlah render per sesi agar tidak kena limit waktu GitHub
        v_files = v_files[:BATCH_LIMIT]
        print(f"[*] Memulai render {len(v_files)} video unik...")

    except Exception as e:
        print(f"Gagal inisialisasi Drive: {e}")
        return

    for i, f_vid in enumerate(v_files):
        # Ambil musik dan kutipan secara berurutan dari daftar yang sudah diacak
        f_mus = m_files[i % len(m_files)]
        selected_text = quotes_list[i % len(quotes_list)]
        
        print(f"\n--- Memproses Video {i+1} ---")
        print(f"🎬 Video: {f_vid['name']}")
        print(f"🎵 Musik: {f_mus['name']}")
        print(f"📝 Quote: {selected_text[:40]}...")

        temp_v = f"v_{i}.mp4"
        temp_a = f"a_{i}.mp3"
        output_name = f"Shorts_{int(time.time())}_{i}.mp4"

        try:
            # Download
            with open(temp_v, "wb") as f: f.write(service.files().get_media(fileId=f_vid['id']).execute())
            with open(temp_a, "wb") as f: f.write(service.files().get_media(fileId=f_mus['id']).execute())

            # Durasi & Start Point Acak
            dur_v = get_media_duration(temp_v)
            v_start = random.uniform(0, max(0, dur_v - MAX_DURATION - 2)) if dur_v > MAX_DURATION + 2 else 0

            dur_a = get_media_duration(temp_a)
            a_start = random.uniform(0, max(0, dur_a - MAX_DURATION - 2)) if dur_a > MAX_DURATION + 2 else 0

            # Render
            if render_with_ffmpeg(temp_v, temp_a, output_name, selected_text, v_start, a_start, font_path):
                # Upload
                meta = {
                    'name': output_name, 
                    'parents': [UPLOTAN_ID], 
                    'description': f"{selected_text}\n\n#shorts #wisdom #mucrowild"
                }
                media = MediaFileUpload(output_name, mimetype='video/mp4')
                service.files().create(body=meta, media_body=media).execute()
                print(f"[✅] BERHASIL DIUPLOAD: {output_name}")

        except Exception as e:
            print(f"❌ Gagal pada video {i}: {e}")
        
        finally:
            # Hapus file sampah agar disk tidak penuh
            for tmp in [temp_v, temp_a, output_name]:
                if os.path.exists(tmp): os.remove(tmp)

    print("\n[✨] Seluruh Batch Selesai.")

if __name__ == "__main__":
    main()
