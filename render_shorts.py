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

# --- KONFIGURASI ---
TOKEN_DATA = os.environ.get('TOKEN_DATA_B') or os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')      
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')   
UPLOTAN_ID = os.environ.get('UPLOTAN_FOLDER_ID') 
QUOTES_ID = os.environ.get('QUOTES_FILE_ID') 

MAX_DURATION = 52 
BATCH_LIMIT = 6

# Cadangan jika Drive Gagal Total
INTERNAL_BACKUP = [
    "Perjuangan hari ini adalah kekuatan esok.",
    "Jangan menyerah, bangkitlah!",
    "Sukses butuh proses."
]

def get_random_dark_rgb():
    """Menghasilkan tuple RGB warna gelap secara acak untuk gradasi."""
    return (random.randint(10, 80), random.randint(10, 80), random.randint(20, 100))

def get_drive_service():
    try:
        if not TOKEN_DATA:
            print("⛔ ERROR: Token tidak ditemukan di Environment Variables!")
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
    available_fonts = [p for p in paths if os.path.exists(p)]
    
    if not available_fonts:
        print("⚠️ Peringatan: Font kustom tidak ditemukan. Menggunakan fallback lokal.")
        available_fonts = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        
    return available_fonts

def get_quotes_robust(service):
    """Mendeteksi tipe file Quotes dan membacanya dengan metode yang benar."""
    if not QUOTES_ID:
        print("⚠️ QUOTES_FILE_ID belum diisi. Pakai backup.")
        return INTERNAL_BACKUP
    
    print(f"[*] Mengambil Quotes Acak dari Drive...")
    try:
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
        lines = [l.strip() for l in content.splitlines() if len(l.strip()) > 5]
        
        if not lines: return INTERNAL_BACKUP
            
        random.shuffle(lines) 
        return lines

    except Exception as e:
        print(f"⛔ Gagal Baca Quotes: {e}")
        return INTERNAL_BACKUP

def get_media_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        return float(subprocess.check_output(cmd).decode().strip())
    except: return 0

def render_video(v_in, a_in, v_out, text, v_start, a_start, font_p, font_color, color_top=(0,0,0), color_bottom=(0,0,0)):
    wrapped = "\n".join(textwrap.wrap(text, width=20))
    safe_txt = wrapped.replace("'", "").replace(":", "\\:")
    
    # Filter Teks
    v_filter = (
        f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=text='{safe_txt}':fontcolor={font_color}:fontsize=80:fontfile={font_p}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.6:boxborderw=40:line_spacing=20"
    )

    cmd = ['ffmpeg', '-y']
    
    if v_in:
        # 1. JIKA MENGGUNAKAN VIDEO ASLI DARI DRIVE
        cmd.extend(['-ss', str(round(v_start, 2)), '-t', str(MAX_DURATION), '-i', v_in])
        cmd.extend(['-ss', str(round(a_start, 2)), '-t', str(MAX_DURATION), '-i', a_in])
        
        # Campur suara video asli (30%) dan musik (120%)
        filter_complex = f'[0:v]{v_filter}[vout]; [0:a]volume=0.3[a1]; [1:a]volume=1.2[a2]; [a1][a2]amix=inputs=2:duration=first[aout]'
        cmd.extend(['-filter_complex', filter_complex, '-map', '[vout]', '-map', '[aout]'])
    else:
        # 2. JIKA MENGGUNAKAN GRADASI VIRTUAL
        r1, g1, b1 = color_top
        r2, g2, b2 = color_bottom
        
        grad_filter = (
            f"nullsrc=s=1080x1920:d={MAX_DURATION}:r=30,"
            f"geq=r='{r1}*(1-Y/H)+{r2}*(Y/H)':"
            f"g='{g1}*(1-Y/H)+{g2}*(Y/H)':"
            f"b='{b1}*(1-Y/H)+{b2}*(Y/H)'"
        )
        cmd.extend(['-f', 'lavfi', '-i', grad_filter])
        cmd.extend(['-ss', str(round(a_start, 2)), '-t', str(MAX_DURATION), '-i', a_in])
        
        # Karena gradasi tidak punya suara, kita HANYA pakai suara musik [1:a] tanpa dicampur (amix)
        filter_complex = f'[0:v]{v_filter}[vout]; [1:a]volume=1.2[aout]'
        cmd.extend(['-filter_complex', filter_complex, '-map', '[vout]', '-map', '[aout]'])

    # Pengaturan Output Video dan Audio
    cmd.extend([
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', 
        '-c:a', 'aac', # Tambahkan konversi audio ke AAC agar aman
        '-t', str(MAX_DURATION), 
        v_out 
    ])
    
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        # Perbaikan sistem log: Ambil 500 karakter TERAKHIR dari log error agar penyebab pastinya terlihat
        err_msg = res.stderr.decode()
        print(f"[-] FFmpeg Error Detail:\n{err_msg[-500:]}")
        return False
    return True

def main():
    print("=== ROBOT RENDER MUCRO WILD (GRADASI & RANDOM) ===")
    service = get_drive_service()
    
    available_fonts = get_available_fonts()
    if not service or not available_fonts: return

    try:
        quotes_pool = get_quotes_robust(service) 
        
        v_res = service.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video'").execute()
        m_res = service.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio'").execute()
        
        v_files = v_res.get('files', [])
        m_files = m_res.get('files', [])
        
        if not m_files:
            print("⛔ Bahan Musik kosong. Skrip berhenti.")
            return
            
        if not v_files:
            print("⚠️ Folder Video kosong! Mengaktifkan mode Background Gradasi Acak.")
        else:
            random.shuffle(v_files) 
            
        random.shuffle(m_files) 
        
    except Exception as e:
        print(f"Error Drive: {e}")
        return

    limit = min(BATCH_LIMIT, len(v_files)) if v_files else BATCH_LIMIT
    
    for i in range(limit):
        f_vid = v_files[i] if v_files else None
        f_mus = m_files[i % len(m_files)]
        txt = quotes_pool[i % len(quotes_pool)]
        
        chosen_font = random.choice(available_fonts)
        warna_teks_pilihan = ["white", "yellow", "#00FFFF", "#FFD700", "#FFC0CB", "#98FB98"]
        chosen_color = random.choice(warna_teks_pilihan)
        
        warna_atas = get_random_dark_rgb()
        warna_bawah = get_random_dark_rgb()
        
        nama_font_log = os.path.basename(chosen_font)
        
        print(f"\n[▶] Render {i+1}")
        if f_vid:
            print(f"   🎬 Video: {f_vid['name']}")
        else:
            print(f"   🎨 Latar: Gradasi RGB {warna_atas} ke {warna_bawah}")
            
        print(f"   🎵 Musik: {f_mus['name']}")
        print(f"   📝 Teks : {txt[:30]}...") 
        print(f"   ✍️ Style: Font [{nama_font_log}] | Teks [{chosen_color}]") 
        
        t_v, t_a = f"v{i}.mp4", f"a{i}.mp3"
        out_name = f"Shorts_{int(time.time())}_{i}.mp4"

        try:
            if f_vid:
                with open(t_v, "wb") as f: f.write(service.files().get_media(fileId=f_vid['id']).execute())
                dv = get_media_duration(t_v)
                vs = random.uniform(0, max(0, dv - MAX_DURATION - 2))
                v_input_path = t_v
            else:
                vs = 0 
                v_input_path = None 

            with open(t_a, "wb") as f: f.write(service.files().get_media(fileId=f_mus['id']).execute())
            da = get_media_duration(t_a)
            as_ = random.uniform(0, max(0, da - MAX_DURATION - 2))

            print(f"   ⏱️ Potong: Musik dari {as_:.1f}s")

            if render_video(v_input_path, t_a, out_name, txt, vs, as_, chosen_font, chosen_color, warna_atas, warna_bawah):
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
