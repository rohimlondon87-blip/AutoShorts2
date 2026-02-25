import os
import base64
import pickle
import time
import io
import random
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.auth.transport.requests import Request

# --- KONFIGURASI MICRO WILD ---
TOKEN_DATA = os.environ.get('TOKEN_DATA')
UPLOTAN_ID = os.environ.get('UPLOTAN_FOLDER_ID')
DONE_ID = os.environ.get('PROCESSED_FOLDER_ID')

def random_delay():
    """Memberikan jeda acak agar upload tidak selalu tepat di menit 00."""
    # Acak antara 1 menit (60 detik) sampai 45 menit (2700 detik)
    jeda_detik = random.randint(60, 2700)
    jeda_menit = jeda_detik // 60
    
    print(f"\n[🎲] MODE JADWAL ACAK AKTIF")
    print(f"    Robot akan menunggu selama {jeda_menit} menit agar waktu upload terlihat natural...")
    print(f"    (Estimasi Upload: {jeda_menit} menit dari sekarang)")
    
    time.sleep(jeda_detik)
    print(f"[▶] Waktu tunggu selesai. Memulai proses upload...\n")

def get_services():
    try:
        if not TOKEN_DATA: return None, None
        t_str = TOKEN_DATA.strip().replace('\xa0', '').replace(" ", "")
        pad = len(t_str) % 4
        if pad: t_str += '=' * (4 - pad)
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds), build('youtube', 'v3', credentials=creds)
    except: return None, None

def main():
    # --- LANGKAH 1: JEDA ACAK ---
    random_delay() 
    # ----------------------------

    print("=== MICRO WILD: ROBOT UPLOAD SHORTS START ===")
    drive, youtube = get_services()
    if not drive or not youtube: return

    # Ambil antrean terlama (FIFO)
    query = f"'{UPLOTAN_ID}' in parents and mimeType contains 'video' and trashed=false"
    results = drive.files().list(
        q=query, 
        fields="files(id, name, description)", 
        orderBy="createdTime", 
        pageSize=1
    ).execute()
    
    files = results.get('files', [])
    
    if not files:
        print("📭 Antrean Kosong.")
        return

    v_file = files[0]
    print(f"[*] Memproses Video: {v_file['name']}")

    # Ambil judul dari Deskripsi Drive
    raw_title = v_file.get('description', v_file['name'].split('.')[0].replace('_', ' '))
    print(f"[*] Judul Ditemukan: {raw_title}")

    hashtags = " #Shorts #MicroWild"
    max_len = 100 - len(hashtags)
    if len(raw_title) > max_len:
        raw_title = raw_title[:max_len-3] + "..."
        
    final_title = raw_title + hashtags

    with open("temp_up.mp4", "wb") as f:
        f.write(drive.files().get_media(fileId=v_file['id']).execute())

    # Setting Public langsung atau Private (15 menit)
    # Kita pakai Private + PublishAt 15 menit agar aman
    publish_time = (datetime.utcnow() + timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')

    body = {
        'snippet': {
            'title': final_title, 
            'description': f"{raw_title}\n\nJangan lupa Subscribe! #Shorts #MicroWild", 
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'private',
            'publishAt': publish_time,
            'selfDeclaredMadeForKids': False
        }
    }
    
    try:
        print(f"[*] Mengunggah ke YouTube...")
        res = youtube.videos().insert(part='snippet,status', body=body, media_body=MediaFileUpload("temp_up.mp4")).execute()
        print(f"✅ SUKSES! Video ID: {res['id']}")
        
        if DONE_ID:
            drive.files().update(fileId=v_file['id'], addParents=DONE_ID, removeParents=UPLOTAN_ID).execute()
        else:
            drive.files().delete(fileId=v_file['id']).execute()
            
    except Exception as e:
        print(f"❌ Gagal Upload: {e}")

    if os.path.exists("temp_up.mp4"): os.remove("temp_up.mp4")

if __name__ == "__main__":
    main()
