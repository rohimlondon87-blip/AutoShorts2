import os
import base64
import pickle
import io
import time
import re
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError

# --- KONFIGURASI DUAL TOKEN ---
CREDENTIAL_SETS = [
    {
        'label': 'KUNCI UTAMA (A)',
        'token': os.environ.get('TOKEN_DATA'),
        'secret': os.environ.get('CLIENT_SECRETS_DATA')
    },
    {
        'label': 'KUNCI CADANGAN (B)',
        'token': os.environ.get('TOKEN_DATA_B'),
        'secret': os.environ.get('CLIENT_SECRETS_DATA_B')
    }
]

def clean_id(folder_id):
    if not folder_id: return ""
    return re.sub(r'[^a-zA-Z0-9_-]', '', folder_id).strip()

UPLOTAN_ID = clean_id(os.environ.get('UPLOTAN_FOLDER_ID', ''))
SELESAI_ID = clean_id(os.environ.get('PROCESSED_FOLDER_ID', ''))

def get_services(token_b64, secret_b64, label):
    """Fungsi login dengan perbaikan otomatis untuk error padding."""
    try:
        if not token_b64 or not secret_b64:
            return None, None
            
        token_b64 = token_b64.strip()
        secret_b64 = secret_b64.strip()
        
        # Tambahkan padding '=' jika kurang (Mengatasi error padding Base64)
        missing_padding = len(token_b64) % 4
        if missing_padding:
            token_b64 += '=' * (4 - missing_padding)
            
        creds = pickle.loads(base64.b64decode(token_b64))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            
        drive = build('drive', 'v3', credentials=creds)
        youtube = build('youtube', 'v3', credentials=creds)
        return drive, youtube
    except Exception as e:
        print(f"⚠️ {label} Gagal: {e}")
        return None, None

def upload_to_youtube(youtube, file_path, metadata_text):
    """Proses upload dengan logika Private 45 menit."""
    try:
        # Cek nama channel untuk konfirmasi di log
        ch = youtube.channels().list(part='snippet', mine=True).execute()
        ch_name = ch['items'][0]['snippet']['title']
    except: ch_name = "Unknown Channel"

    print(f"[*] Target Upload: {ch_name}")
    
    # LOGIKA UTAMA: Jadwalkan 45 menit ke depan (Waktu UTC)
    now = datetime.utcnow()
    publish_time = (now + timedelta(minutes=45)).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    body = {
        'snippet': {
            'title': metadata_text[:100],
            'description': f"{metadata_text}\n\n#shorts #viral #mucrowild",
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'private', # Wajib Private agar 'publishAt' bisa berfungsi
            'publishAt': publish_time,   # YouTube akan mempublikasikan otomatis di waktu ini
            'selfDeclaredMadeForKids': False
        }
    }
    
    media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    
    try:
        response = request.execute()
        return response.get('id'), publish_time
    except HttpError as e:
        if "quotaExceeded" in str(e): return None, "QUOTA_FULL"
        return None, str(e)

def main():
    print("=== ROBOT PENGUNGGAH SHORTS (LOGIKA 45 MENIT) ===")
    
    # 1. Pilih Kunci Drive yang Aktif
    drive_service = None
    for cred in CREDENTIAL_SETS:
        drive_service, _ = get_services(cred['token'], cred['secret'], cred['label'])
        if drive_service: break

    if not drive_service:
        print("⛔ ERROR: Tidak ada token yang valid untuk akses Drive.")
        return

    # 2. Cari Video Baru di Folder Uplotan
    query = f"'{UPLOTAN_ID}' in parents and mimeType='video/mp4' and not name contains '[UPLOADED]' and trashed=false"
    res = drive_service.files().list(q=query, orderBy="createdTime", pageSize=1, fields="files(id, name, description, parents)").execute()
    files = res.get('files', [])

    if not files:
        print("[-] Folder uplotan kosong. Menunggu hasil render baru...")
        return

    video_file = files[0]
    file_id = video_file['id']
    file_name = video_file['name']
    curr_parents = ",".join(video_file.get('parents', []))
    meta_text = video_file.get('description', file_name.replace('.mp4', ''))

    # 3. Download ke Server Sementara
    print(f"[*] Mendownload: {file_name}")
    temp_v = "temp_upload.mp4"
    request = drive_service.files().get_media(fileId=file_id)
    with io.FileIO(temp_v, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()

    # 4. Upload dengan Sistem Estafet (Failover A -> B)
    success = False
    for cred in CREDENTIAL_SETS:
        _, youtube = get_services(cred['token'], cred['secret'], cred['label'])
        if not youtube: continue

        video_id, result = upload_to_youtube(youtube, temp_v, meta_text)
        if video_id:
            print(f"[✅] BERHASIL UPLOAD! ID: {video_id}")
            print(f"[⏰] Status: Private (Akan Publik Otomatis pada {result} UTC)")
            success = True
            break
        elif result == "QUOTA_FULL":
            print(f"⚠️ {cred['label']} Kuota Habis. Mencoba Kunci Cadangan...")
            continue
        else:
            print(f"❌ Gagal dengan {cred['label']}: {result}")

    # 5. Penandaan File (Rename atau Pindah Folder)
    if success:
        print("[*] Menandai file di Drive agar tidak double upload...")
        try:
            if SELESAI_ID:
                drive_service.files().update(fileId=file_id, addParents=SELESAI_ID, removeParents=curr_parents).execute()
                print("[✨] Berhasil dipindahkan ke folder Selesai.")
            else: raise Exception()
        except:
            drive_service.files().update(fileId=file_id, body={'name': f"[UPLOADED]_{file_name}"}).execute()
            print(f"[🏷️] Berhasil ditandai: [UPLOADED]_{file_name}")

    if os.path.exists(temp_v): os.remove(temp_v)

if __name__ == "__main__":
    main()
