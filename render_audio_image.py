import os
import base64
import pickle
import subprocess
import random
import time
import io
import textwrap
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI FOLDER ---
TOKEN_DATA = os.environ.get('TOKEN_DATA')
IMAGE_FOLDER_ID = os.environ.get('IMAGE_FOLDER_ID') 
AUDIO_FOLDER_ID = os.environ.get('AUDIO_VISUAL_ID') 
RENDER_OUTPUT_ID = os.environ.get('UPLOTAN_VISUAL_ID') 
PROCESSED_ID = os.environ.get('PROCESSED_VISUAL_ID') 
QUOTES_ID = os.environ.get('QUOTES_FILE_ID') 

def get_services():
    try:
        t_str = TOKEN_DATA.strip().replace('\xa0', '').replace(" ", "")
        pad = len(t_str) % 4
        if pad: t_str += '=' * (4 - pad)
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"⛔ Auth Error: {e}")
        return None

def get_quotes_batch(service, count=3):
    try:
        file_meta = service.files().get(fileId=QUOTES_ID).execute()
        fh = io.BytesIO()
        if 'application/vnd.google-apps' in file_meta.get('mimeType', ''):
            request = service.files().export_media(fileId=QUOTES_ID, mimeType='text/plain')
        else:
            request = service.files().get_media(fileId=QUOTES_ID)
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        lines = [l.strip() for l in fh.getvalue().decode('utf-8-sig').splitlines() if len(l.strip()) > 5]
        if len(lines) < count: return (lines + ["Tetap Semangat", "Fokus", "Micro Wild"])[:count]
        return random.sample(lines, count)
    except:
        return ["Ketenangan adalah kunci.", "Teruslah melangkah.", "Hari yang indah menanti."]

def find_font():
    paths = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
    for p in paths:
        if os.path.exists(p): return p
    return None

def get_media_duration(file_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        return float(subprocess.check_output(cmd).decode().strip())
    except: return 0

def move_file(service, file_id, old_parent):
    if PROCESSED_ID:
        try:
            service.files().update(fileId=file_id, addParents=PROCESSED_ID, removeParents=old_parent).execute()
            print(f"    -> Berkas dipindahkan ke Arsip.")
        except: pass

def process_single_render(drive, img_file, aud_file, font_p):
    nama_audio = os.path.splitext(aud_file['name'])[0]
    nama_bersih = "".join([c for c in nama_audio if c.isalnum() or c in " _-"]).strip()
    out_name = f"{nama_bersih}.mp4"
    l_img, l_aud = "bg.jpg", "bg.mp3"

    print(f"\n[*] Mengunduh: {nama_audio}")
    with open(l_img, "wb") as f: f.write(drive.files().get_media(fileId=img_file['id']).execute())
    with open(l_aud, "wb") as f: f.write(drive.files().get_media(fileId=aud_file['id']).execute())

    dur = round(get_media_duration(l_aud), 2)
    if dur == 0: dur = 60 
    t_step = round(dur / 3, 2)
    quotes = get_quotes_batch(drive, 3)

    def get_drawtext(text, start, end):
        wrapped = "\\n".join(textwrap.wrap(text, width=40))
        safe = wrapped.replace("'", "").replace(":", "\\:")
        return (f"drawtext=text='{safe}':fontfile='{font_p}':fontcolor=white:fontsize=45:"
                f"x=(w-text_w)/2:y=(h-text_h)/2-100:box=1:boxcolor=black@0.4:boxborderw=20:"
                f"alpha='if(lt(t,{start}),0,if(lt(t,{start}+1),t-{start},if(lt(t,{end}-1),1,if(lt(t,{end}),{end}-t,0))))':"
                f"enable='between(t,{start},{end})'")

    v_filter = (
        f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
        f"eq=brightness='0.05*sin(2*PI*t*0.5)':contrast=1.1[bg];"
        f"[1:a]showfreqs=s=1920x250:mode=bar:colors=white@0.8[vis];"
        f"[bg][vis]overlay=0:H-h[v1];"
        f"[v1]{get_drawtext(quotes[0], 1, t_step)},{get_drawtext(quotes[1], t_step, t_step*2)},{get_drawtext(quotes[2], t_step*2, dur-1)}[final]"
    )

    cmd = [
        'ffmpeg', '-y', '-loop', '1', '-i', l_img, '-i', l_aud,
        '-filter_complex', v_filter, '-map', '[final]', '-map', '1:a',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', 
        '-c:a', 'aac', '-b:a', '128k', '-shortest', '-t', str(dur), out_name
    ]

    print(f"[🎬] Merender: {out_name}...")
    if subprocess.run(cmd, capture_output=True).returncode == 0:
        meta = {'name': out_name, 'parents': [RENDER_OUTPUT_ID]}
        drive.files().create(body=meta, media_body=MediaFileUpload(out_name)).execute()
        print(f"✅ Berhasil Upload: {out_name}")
        move_file(drive, img_file['id'], IMAGE_FOLDER_ID)
        move_file(drive, aud_file['id'], AUDIO_FOLDER_ID)
        return True
    return False

def main():
    print("=== ROBOT RENDER VISUALIZER: MODE CUCI GUDANG (FIFO) ===")
    drive = get_services()
    font_p = find_font()
    if not drive or not font_p: return

    while True:
        # Cari 1 Gambar Tertua
        img_res = drive.files().list(q=f"'{IMAGE_FOLDER_ID}' in parents and mimeType contains 'image/' and trashed=false", 
                                    orderBy="createdTime", pageSize=1).execute().get('files', [])
        # Cari 1 Audio Tertua
        aud_res = drive.files().list(q=f"'{AUDIO_FOLDER_ID}' in parents and mimeType contains 'audio/' and trashed=false", 
                                    orderBy="createdTime", pageSize=1).execute().get('files', [])

        if not img_res or not aud_res:
            print("\n[🏁] Selesai! Bahan di folder sudah habis.")
            break

        success = process_single_render(drive, img_res[0], aud_res[0], font_p)
        if not success:
            print("⚠️ Terjadi kesalahan pada satu file, mencoba file berikutnya...")
            # Pindahkan file yang rusak ke arsip agar tidak macet di sini
            move_file(drive, aud_res[0]['id'], AUDIO_FOLDER_ID)
        
        # Bersihkan file lokal sebelum loop berikutnya
        for f in ["bg.jpg", "bg.mp3"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
