import os
import base64
import pickle
import subprocess
import random
import sys
import io
import time
import textwrap
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI SECRETS ---
TOKEN_B64 = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')
QUOTES_FILE_ID = os.environ.get('QUOTES_FILE_ID') 

SLOW_MOTION_FACTOR = 1.2
# ACAK DURASI: Antara 2700 detik (45 menit) hingga 3600 detik (60 menit)
LIVE_DURATION_SEC = random.randint(2700, 3600) 

def find_font():
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
    ]
    for p in paths:
        if os.path.exists(p): return p
    return None

def get_services():
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_B64))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        drive = build('drive', 'v3', credentials=creds)
        youtube = build('youtube', 'v3', credentials=creds)
        return drive, youtube
    except:
        return None, None

def get_quotes_from_drive(service):
    """Mengambil kutipan dari Google Docs/Drive untuk teks video & chat"""
    if not QUOTES_FILE_ID:
        return ["Tetap semangat hari ini!", "Fokus pada perjuanganmu."]
    try:
        file_metadata = service.files().get(fileId=QUOTES_FILE_ID).execute()
        mime_type = file_metadata.get('mimeType')
        fh = io.BytesIO()
        if 'google-apps.document' in mime_type:
            request = service.files().export_media(fileId=QUOTES_FILE_ID, mimeType='text/plain')
        else:
            request = service.files().get_media(fileId=QUOTES_FILE_ID)
        
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        content = fh.getvalue().decode('utf-8')
        return [line.strip() for line in content.split('\n') if line.strip()]
    except:
        return ["Tetap fokus dan berjuang!", "Jangan menyerah pada mimpimu."]

def get_live_chat_id(youtube):
    """Mendapatkan ID Live Chat dari siaran yang sedang berlangsung"""
    try:
        response = youtube.liveBroadcasts().list(part='snippet', broadcastStatus='active').execute()
        if response.get('items'):
            return response['items'][0]['snippet']['liveChatId']
    except:
        pass
    return None

def post_to_chat(youtube, chat_id, message):
    """Mengirim pesan ke kolom Live Chat setiap interval tertentu"""
    if not chat_id: return
    try:
        youtube.liveChatMessages().insert(
            part='snippet',
            body={
                'snippet': {
                    'liveChatId': chat_id,
                    'type': 'textMessageEvent',
                    'textMessageDetails': {'messageText': message[:200]}
                }
            }
        ).execute()
        print(f"[💬] Chat Terkirim: {message[:30]}...")
    except Exception as e:
        print(f"[!] Gagal kirim chat: {e}")

def main():
    # --- LOGIKA JEDA ACAK (15:00 - 17:00 WITA) ---
    # Jika dipicu jam 15:00, kita beri jeda maksimal 120 menit (2 jam)
    delay_menit = random.randint(0, 120)
    print(f"[⏳] Robot sedang menunggu jeda acak selama {delay_menit} menit agar waktu mulai natural...")
    time.sleep(delay_menit * 60)
    
    print(f"=== MULAI LIVE CINEMA (DURASI ACAK: {LIVE_DURATION_SEC//60} MENIT) ===")
    drive, youtube = get_services()
    font_path = find_font()
    if not drive or not font_path: return

    # 1. Ambil Quotes & Bahan
    all_quotes = get_quotes_from_drive(drive)
    quote_overlay = random.choice(all_quotes) 
    
    v_files = drive.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video'").execute().get('files', [])
    m_files = drive.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio'").execute().get('files', [])
    
    if not v_files:
        print("[-] Tidak ada file video di Drive.")
        return

    v_samp = random.sample(v_files, min(len(v_files), 3))
    m_samp = random.sample(m_files, min(len(m_files), 10))

    # 2. Download & Playlist
    v_paths, m_paths = [], []
    for i, f in enumerate(v_samp):
        n = f"v_{i}.mp4"
        with open(n, "wb") as fh: fh.write(drive.files().get_media(fileId=f['id']).execute())
        v_paths.append(n)
    for i, f in enumerate(m_samp):
        n = f"m_{i}.mp3"
        with open(n, "wb") as fh: fh.write(drive.files().get_media(fileId=f['id']).execute())
        m_paths.append(n)

    with open("v_list.txt", "w") as f:
        for p in v_paths: f.write(f"file '{os.path.abspath(p)}'\n")
    with open("m_list.txt", "w") as f:
        for p in m_paths: f.write(f"file '{os.path.abspath(p)}'\n")

    # 3. Filter Teks
    wrapped_quote = "\n".join(textwrap.wrap(quote_overlay, width=40))
    safe_quote = wrapped_quote.replace("'", "").replace(":", "\\:")
    
    text_f = (
        f"drawtext=text='REC':fontcolor=red:fontsize=40:x=60:y=60:fontfile={font_path}:enable='lt(mod(t,2),1)',"
        f"drawtext=text='LIVE':fontcolor=white:fontsize=40:x=60:y=60:fontfile={font_path}:enable='gt(mod(t,2),1)',"
        f"drawtext=text='%{{pts\\:hms}}':fontcolor=white:fontsize=30:x=w-200:y=60:fontfile={font_path},"
        f"drawtext=text='{safe_quote}':fontcolor=white@0.8:fontsize=35:x=(w-text_w)/2:y=h-100:fontfile={font_path}:"
        f"box=1:boxcolor=black@0.4:boxborderw=15"
    )

    rtmp = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"
    cmd = [
        'ffmpeg', '-y', '-re',
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'v_list.txt',
        '-stream_loop', '-1', '-f', 'concat', '-safe', '0', '-i', 'm_list.txt',
        '-t', str(LIVE_DURATION_SEC),
        '-filter_complex', (
            f'[0:v]scale=1280:720,setpts={SLOW_MOTION_FACTOR}*PTS,fps=30,{text_f}[vout]; '
            f'[0:a]atempo={1.0/SLOW_MOTION_FACTOR:.4f},volume=0.3[a1]; '
            f'[1:a]volume=1.0[a2]; [a1][a2]amix=inputs=2:duration=first[aout]'
        ),
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '128k', '-f', 'flv', rtmp
    ]

    try:
        process = subprocess.Popen(cmd)
        print(f"[🚀] Live Stream Dimulai selama {LIVE_DURATION_SEC} detik...")
        
        start_time = time.time()
        chat_id = None
        
        while process.poll() is None:
            if not chat_id:
                chat_id = get_live_chat_id(youtube)
            
            if chat_id:
                msg = random.choice(all_quotes)
                post_to_chat(youtube, chat_id, msg)
            
            # Chat setiap 10 menit
            time.sleep(600) 
            
            if time.time() - start_time > LIVE_DURATION_SEC:
                process.terminate()
                break

    except Exception as e:
        print(f"[-] Error: {e}")
    finally:
        for f in v_paths + m_paths + ["v_list.txt", "m_list.txt"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
