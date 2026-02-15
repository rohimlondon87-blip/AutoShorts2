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
# Mencoba Token B dahulu karena di log Anda Token B yang terbukti sukses
TOKEN_DATA = os.environ.get('TOKEN_DATA_B') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')      
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')   
UPLOTAN_ID = os.environ.get('UPLOTAN_FOLDER_ID') 
QUOTES_ID = os.environ.get('QUOTES_FILE_ID') 

MAX_DURATION = 15 
BATCH_LIMIT = 4  # Batasi 4 video per jalan agar tidak kena limit waktu GitHub

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
        
        # Perbaikan otomatis jika ada masalah padding pada base64
        token_str = TOKEN_DATA.strip()
        missing_padding = len(token_str) % 4
        if missing_padding:
            token_str += '=' * (4 - missing_padding)
            
        creds = pickle.loads(base64.b64decode(token_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error: {e}")
        return None

def get_quotes_cleaned(service):
    """Mengambil kutipan dan membersihkan baris kosong (Fix Image 5)"""
    if not QUOTES_ID:
        return ["Tetap semangat!"]
    try:
        fh = io.BytesIO()
        request = service.files().get_media(fileId=QUOTES_ID)
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        content = fh.getvalue().decode('utf-8')
        
        # Membersihkan baris kosong dan spasi berlebih
        raw_lines = content.splitlines()
        clean_lines = [l.strip() for l in raw_lines if len(l.strip()) > 3]
        
        if not clean_lines:
            return ["Jadilah versi terbaik dirimu."]
            
        random.shuffle(clean_lines) # Acak urutan kutipan
        return clean_lines
    except Exception as e:
        print(f"Gagal ambil quotes: {e}")
        return ["Terus melangkah maju."]

def get_media_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        return float(subprocess.check_output(cmd).decode().strip())
    except: return 0

def render_ffmpeg(v_in, a_in, v_out, text, v_start, a_start, font_p):
    # Bungkus teks agar proporsional di layar HP (9:16)
    wrapped = "\n".join(textwrap.wrap(text, width=18))
    safe_text = wrapped.replace("'", "").replace(":", "\\:")
    
    # Filter: Scale ke Portrait, Crop Tengah, Tambah Box Teks
    v_filter = (
        f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=text='{safe_text}':fontcolor=white:fontsize=85:fontfile={font_p}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.5:boxborderw=40:line_spacing=25"
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
        print(f"FFmpeg Error: {e.stderr.decode()[:150]}")
        return False

def main():
    print("=== ROBOT RENDER MUCRO WILD (ANTI-DUPLIKAT) ===")
    service = get_drive_service()
    font_path = find_font()
    if not service or not font_path: return

    try:
        # Load Data
        all_quotes = get_quotes_cleaned(service)
        v_res = service.files().list(q=f"'{SOURCE_ID}' in parents and trashed=false", fields="files(id, name)").execute()
        m_res = service.files().list(q=f"'{MUSIC_ID}' in parents and trashed=false", fields="files(id, name)").execute()
        
        v_files = v_res.get('files', [])
        m_files = m_res.get('files', [])

        if not v_files or not m_files:
            print("⛔ Bahan tidak lengkap di Drive.")
            return
            
        # PENGACAKAN TOTAL
        random.shuffle(v_files)
        random.shuffle(m_files)
        
        # Batasi jumlah per sesi
        process_list = v_files[:BATCH_LIMIT]
        print(f"[*] Memulai pembuatan {len(process_list)} video unik...")

    except Exception as e:
        print(f"Gagal akses Drive: {e}")
        return

    for i, f_vid in enumerate(process_list):
        # Ambil elemen unik untuk setiap video
        f_mus = m_files[i % len(m_files)]
        txt = all_quotes[i % len(all_quotes)]
        
        print(f"\n[Video {i+1}] 🎬 {f_vid['name']} | 🎵 {f_mus['name']}")
        print(f"📝 Teks: {txt[:30]}...")

        t_v, t_a = f"v_{i}.mp4", f"a_{i}.mp3"
        out = f"Shorts_{int(time.time())}_{i}.mp4"

        try:
            # Download
            with open(t_v, "wb") as f: f.write(service.files().get_media(fileId=f_vid['id']).execute())
            with open(t_a, "wb") as f: f.write(service.files().get_media(fileId=f_mus['id']).execute())

            # Randomize Start Points
            d_v = get_media_duration(t_v)
            vs = random.uniform(0, max(0, d_v - MAX_DURATION - 2)) if d_v > MAX_DURATION + 2 else 0
            
            d_a = get_media_duration(t_a)
            as_ = random.uniform(0, max(0, d_a - MAX_DURATION - 2)) if d_a > MAX_DURATION + 2 else 0

            # Render & Upload
            if render_ffmpeg(t_v, t_a, out, txt, vs, as_, font_path):
                meta = {'name': out, 'parents': [UPLOTAN_ID], 'description': f"{txt}\n\n#shorts #wisdom #mucrowild"}
                media = MediaFileUpload(out, mimetype='video/mp4')
                service.files().create(body=meta, media_body=media).execute()
                print(f"✅ BERHASIL: {out}")

        except Exception as e:
            print(f"❌ Gagal: {e}")
        finally:
            for tmp in [t_v, t_a, out]:
                if os.path.exists(tmp): os.remove(tmp)

    print("\n[✨] Batch Selesai. Cek folder Uplotan!")

if __name__ == "__main__":
    main()
