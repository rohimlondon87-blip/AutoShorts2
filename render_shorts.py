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
BATCH_LIMIT = 7 

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

def get_available_fonts():
    """Mencari semua font yang tersedia di server GitHub untuk diacak."""
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Comic_Sans_MS.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Trebuchet_MS_Bold.ttf"
    ]
    # Filter hanya font yang benar-benar berhasil diinstal di server
    available_fonts = [p for p in paths if os.path.exists(p)]
    
    # Fallback jika terjadi kesalahan instalasi font
    if not available_fonts:
        available_fonts = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        
    return available_fonts

def get_quotes_robust(service):
    """Mendeteksi tipe file Quotes dan membacanya dengan metode yang benar."""
    if not QUOTES_ID:
        print("⚠️ QUOTES_FILE_ID belum diisi. Pakai backup.")
        return INTERNAL_BACKUP
    
    print(f"[*] Mengambil Quotes Acak dari Drive...")
    try:
        # Cek Tipe File
        file_meta = service.files().get(fileId=QUOTES_ID).execute()
        mime_type = file_meta.get('mimeType', '')

        fh = io.BytesIO()
        if 'application/vnd.google-apps' in mime_type:
            request = service.files().export_media(fileId=QUOTES_ID, mimeType='text/plain')
        else:
            request = service.files().get_media(fileId=QUOTES_ID)

        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        
        content = fh.getvalue().decode('utf-8-sig')
        # Hapus baris kosong & spasi
        lines = [l.strip() for l in content.splitlines() if len(l.strip()) > 5]
        
        if not lines: return INTERNAL_BACKUP
            
        random.shuffle(lines) # <--- DIACAK DI SINI
        return lines

    except Exception as e:
        print(f"⛔ Gagal Baca Quotes: {e}")
        return INTERNAL_BACKUP

def get_media_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        return float(subprocess.check_output(cmd).decode().strip())
    except: return 0

def render_video(v_in, a_in, v_out, text, v_start, a_start, font_p, font_color):
    wrapped = "\n".join(textwrap.wrap(text, width=20))
    safe_txt = wrapped.replace("'", "").replace(":", "\\:")
    
    # Filter Teks: Menggunakan font_p (jenis huruf acak) dan font_color (warna acak)
    v_filter = (
        f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=text='{safe_txt}':fontcolor={font_color}:fontsize=80:fontfile={font_p}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.6:boxborderw=40:line_spacing=20"
    )

    cmd = [
        'ffmpeg', '-y',
        # Potong video dari detik acak (v_start)
        '-ss', str(round(v_start, 2)), '-t', str(MAX_DURATION), '-i', v_in,
        # Potong musik dari detik acak (a_start)
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
    print("=== ROBOT RENDER MUCRO WILD (TOTAL RANDOM) ===")
    service = get_drive_service()
    
    # Ambil koleksi font yang tersedia
    available_fonts = get_available_fonts()
    
    if not service or not available_fonts: return

    # 1. SIAPKAN BAHAN
    try:
        quotes_pool = get_quotes_robust(service) 
        
        v_res = service.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video'").execute()
        m_res = service.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio'").execute()
        
        v_files = v_res.get('files', [])
        m_files = m_res.get('files', [])
        
        if not v_files or not m_files:
            print("⛔ Bahan Video/Musik kosong.")
            return
            
        # --- KUNCI PENGACAKAN ---
        random.shuffle(v_files) # Acak urutan video
        random.shuffle(m_files) # Acak urutan musik
        
    except Exception as e:
        print(f"Error Drive: {e}")
        return

    # 2. PROSES LOOPING
    limit = min(BATCH_LIMIT, len(v_files))
    
    for i in range(limit):
        f_vid = v_files[i]
        f_mus = m_files[i % len(m_files)]
        txt = quotes_pool[i % len(quotes_pool)]
        
        # --- LOGIKA ACAK VISUAL ---
        chosen_font = random.choice(available_fonts)
        # Daftar warna estetik yang terang agar kontras dengan background hitam
        warna_pilihan = ["white", "yellow", "#00FFFF", "#FFD700", "#FFC0CB", "#98FB98"]
        chosen_color = random.choice(warna_pilihan)
        
        # Ambil nama font saja untuk ditampilkan di log (misal: "Impact.ttf")
        nama_font_log = os.path.basename(chosen_font)
        
        print(f"\n[▶] Render {i+1}")
        print(f"   🎬 Video: {f_vid['name']}")
        print(f"   🎵 Musik: {f_mus['name']}")
        print(f"   📝 Teks : {txt[:30]}...") 
        print(f"   🎨 Style: Font [{nama_font_log}] | Warna [{chosen_color}]") 
        
        t_v, t_a = f"v{i}.mp4", f"a{i}.mp3"
        out_name = f"Shorts_{int(time.time())}_{i}.mp4"

        try:
            with open(t_v, "wb") as f: f.write(service.files().get_media(fileId=f_vid['id']).execute())
            with open(t_a, "wb") as f: f.write(service.files().get_media(fileId=f_mus['id']).execute())
            
            # Hitung Detik Mulai Secara ACAK
            dv = get_media_duration(t_v)
            da = get_media_duration(t_a)
            
            # Ambil potongan acak dari tengah video (bukan cuma awal)
            vs = random.uniform(0, max(0, dv - MAX_DURATION - 2))
            as_ = random.uniform(0, max(0, da - MAX_DURATION - 2))

            print(f"   ⏱️ Potong: Video dari {vs:.1f}s | Musik dari {as_:.1f}s")

            # Kirim data font dan warna acak ke fungsi render
            if render_video(t_v, t_a, out_name, txt, vs, as_, chosen_font, chosen_color):
                meta = {'name': out_name, 'parents': [UPLOTAN_ID], 'description': txt}
                media = MediaFileUpload(out_name, mimetype='video/mp4')
                service.files().create(body=meta, media_body=media).execute()
                print(f"   ✅ SUKSES UPLOAD")
            else:
                print("   ❌ Gagal Render")

        except Exception as e:
            print(f"   ❌ Error File: {e}")
        
        finally:
            for f in [t_v, t_a, out_name]:
                if os.path.exists(f): os.remove(f)

    print("\n[✨] Selesai.")

if __name__ == "__main__":
    main()
