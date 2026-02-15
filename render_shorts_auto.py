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
from googleapiclient.errors import HttpError

# --- KONFIGURASI ---
TOKEN_DATA = os.environ.get('TOKEN_DATA_B') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')      
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')   
UPLOTAN_ID = os.environ.get('UPLOTAN_FOLDER_ID') 
QUOTES_ID = os.environ.get('QUOTES_FILE_ID') 

MAX_DURATION = 45
BATCH_LIMIT = 5 

# Cadangan jika Drive Gagal Total
INTERNAL_BACKUP = [
    "Perjuangan hari ini adalah kekuatan esok.",
    "Jangan menyerah, bangkitlah!",
    "Sukses butuh proses."
]

def get_drive_service():
    try:
        if not TOKEN_DATA:
            print("⛔ ERROR: Token tidak ditemukan!")
            return None
        
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

def find_font():
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
    ]
    for p in paths:
        if os.path.exists(p): return p
    return None

def get_quotes_robust(service):
    """Mendeteksi tipe file Quotes dan membacanya dengan metode yang benar."""
    if not QUOTES_ID:
        print("⚠️ QUOTES_FILE_ID belum diisi di Secrets. Pakai backup.")
        return INTERNAL_BACKUP
    
    print(f"[*] Mencoba membaca file Quotes ID: {QUOTES_ID}")
    try:
        # 1. Cek Tipe File Dulu
        file_meta = service.files().get(fileId=QUOTES_ID).execute()
        mime_type = file_meta.get('mimeType', '')
        print(f"   - Tipe File: {mime_type}")

        fh = io.BytesIO()
        
        # 2. Pilih Metode Download
        if 'application/vnd.google-apps' in mime_type:
            # Jika Google Doc/Sheet/Slide -> HARUS EXPORT
            print("   - Metode: Export to Text")
            request = service.files().export_media(fileId=QUOTES_ID, mimeType='text/plain')
        else:
            # Jika File .txt/.csv biasa -> DOWNLOAD BIASA
            print("   - Metode: Direct Download")
            request = service.files().get_media(fileId=QUOTES_ID)

        # 3. Eksekusi
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        
        # 4. Parsing Teks
        content = fh.getvalue().decode('utf-8-sig') # utf-8-sig untuk handle BOM
        lines = [l.strip() for l in content.splitlines() if len(l.strip()) > 5]
        
        if not lines:
            print("⚠️ File Quotes kosong atau tidak terbaca! Menggunakan backup.")
            return INTERNAL_BACKUP
            
        print(f"✅ Berhasil memuat {len(lines)} kutipan.")
        random.shuffle(lines)
        return lines

    except HttpError as e:
        print(f"⛔ Gagal Akses File Quotes (Error {e.resp.status}): {e}")
        if e.resp.status == 404:
            print("   -> ID File Salah atau File sudah dihapus.")
        elif e.resp.status == 403:
            print("   -> Robot tidak punya izin akses ke file ini. Share file ke email robot!")
        return INTERNAL_BACKUP
    except Exception as e:
        print(f"⛔ Error Sistem Baca Quotes: {e}")
        return INTERNAL_BACKUP

def get_media_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        return float(subprocess.check_output(cmd).decode().strip())
    except: return 0

def render_video(v_in, a_in, v_out, text, v_start, a_start, font_p):
    wrapped = "\n".join(textwrap.wrap(text, width=20))
    safe_txt = wrapped.replace("'", "").replace(":", "\\:")
    
    # Filter Teks: Besar (80), Tengah, Box Hitam
    v_filter = (
        f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=text='{safe_txt}':fontcolor=white:fontsize=80:fontfile={font_p}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.6:boxborderw=40:line_spacing=20"
    )

    cmd = [
        'ffmpeg', '-y',
        '-ss', str(round(v_start, 2)), '-t', str(MAX_DURATION), '-i', v_in,
        '-ss', str(round(a_start, 2)), '-t', str(MAX_DURATION), '-i', a_in,
        '-filter_complex', f'[0:v]{v_filter}[vout]; [0:a]volume=0.3[a1]; [1:a]volume=1.2[a2]; [a1][a2]amix=inputs=2:duration=first[aout]',
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', '-t', str(MAX_DURATION), 
        v_out 
    ]
    
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        print(f"[-] FFmpeg Error: {res.stderr.decode()[:200]}")
        return False
    return True

def main():
    print("=== ROBOT RENDER MUCRO WILD (FIX READ QUOTES) ===")
    service = get_drive_service()
    font_path = find_font()
    if not service or not font_path: return

    # 1. SIAPKAN BAHAN (Dengan Diagnosa Quotes)
    try:
        quotes_pool = get_quotes_robust(service) 
        
        v_files = service.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video'").execute().get('files', [])
        m_files = service.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio'").execute().get('files', [])
        
        if not v_files or not m_files:
            print("⛔ Bahan Video/Musik kosong.")
            return
            
        random.shuffle(v_files)
        random.shuffle(m_files)
        
    except Exception as e:
        print(f"Error Drive: {e}")
        return

    # 2. PROSES LOOPING
    limit = min(BATCH_LIMIT, len(v_files))
    
    for i in range(limit):
        f_vid = v_files[i]
        f_mus = m_files[i % len(m_files)]
        txt = quotes_pool[i % len(quotes_pool)]
        
        print(f"\n[▶] Render {i+1}: {f_vid['name']}")
        print(f"📝 Teks: {txt[:30]}...") # Pastikan ini tidak sama terus
        
        t_v, t_a = f"v{i}.mp4", f"a{i}.mp3"
        out_name = f"Shorts_{int(time.time())}_{i}.mp4"

        try:
            # Download
            with open(t_v, "wb") as f: f.write(service.files().get_media(fileId=f_vid['id']).execute())
            with open(t_a, "wb") as f: f.write(service.files().get_media(fileId=f_mus['id']).execute())
            
            # Waktu acak
            dv = get_media_duration(t_v)
            da = get_media_duration(t_a)
            vs = random.uniform(0, max(0, dv - MAX_DURATION - 2))
            as_ = random.uniform(0, max(0, da - MAX_DURATION - 2))

            # Render
            if render_video(t_v, t_a, out_name, txt, vs, as_, font_path):
                meta = {'name': out_name, 'parents': [UPLOTAN_ID], 'description': txt}
                media = MediaFileUpload(out_name, mimetype='video/mp4')
                service.files().create(body=meta, media_body=media).execute()
                print(f"[✅] SUKSES UPLOAD: {out_name}")
            else:
                print("❌ Gagal Render")

        except Exception as e:
            print(f"❌ Error File: {e}")
        
        finally:
            for f in [t_v, t_a, out_name]:
                if os.path.exists(f): os.remove(f)

    print("\n[✨] Selesai.")

if __name__ == "__main__":
    main()