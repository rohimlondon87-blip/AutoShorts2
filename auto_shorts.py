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

# --- KONFIGURASI DARI GITHUB SECRETS ---
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
    cleaned = re.sub(r'[^a-zA-Z0-9_-]', '', folder_id)
    return cleaned.strip()

UPLOTAN_ID = clean_id(os.environ.get('UPLOTAN_FOLDER_ID', ''))
SELESAI_ID = clean_id(os.environ.get('PROCESSED_FOLDER_ID', ''))

def get_services(token_b64, secret_b64, label):
    """Autentikasi API menggunakan Base64 token."""
    try:
        if not token_b64 or not secret_b64:
            return None, None
            
        creds = pickle.loads(base64.b64decode(token_b64))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        
        drive = build('drive', 'v3', credentials=creds)
        youtube = build('youtube', 'v3', credentials=creds)
        return drive, youtube
    except Exception as e:
        print(f"⚠️ {label} Gagal Login: {e}")
        return None, None

def upload_to_youtube(youtube, file_path, metadata_text, label):
    """Proses upload dengan jadwal publikasi 45 menit ke depan."""
    print(f"[*] Menggunakan {label} untuk upload...")
    
    # 1. Hitung waktu publikasi (45 menit dari sekarang dalam format UTC ISO 8601)
    publish_time = (datetime.utcnow() + timedelta(minutes=45)).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    # 2. Susun Metadata (Mengambil dari deskripsi file Drive)
    # Gunakan metadata_text sebagai judul dan deskripsi
    body = {
        'snippet': {
            'title': metadata_text[:100], # Maksimal 100 karakter untuk judul
            'description': f"{metadata_text}\n\n#shorts #viral #otomasi",
            'categoryId': '22' # People & Blogs
        },
        'status': {
            'privacyStatus': 'private',  # Wajib private agar bisa dijadwalkan
            'publishAt': publish_time,   # Jadwal publikasi
            'selfDeclaredMadeForKids': False
        }
    }
    
    media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    
    try:
        response = request.execute()
        return response.get('id'), publish_time
    except HttpError as e:
        if e.resp.status == 403:
            return None, "QUOTA_EXCEEDED"
        return None, str(e)

def main():
    print("=== ROBOT PENGUNGGAH DUAL-TOKEN (SCHEDULE 45M) ===")
    
    if not UPLOTAN_ID or not SELESAI_ID:
        print("⛔ ERROR: ID Folder belum diisi!")
        return

    # 1. Cari video di Drive menggunakan kunci pertama yang tersedia
    drive_service = None
    for cred in CREDENTIAL_SETS:
        drive_service, _ = get_services(cred['token'], cred['secret'], cred['label'])
        if drive_service: break

    if not drive_service:
        print("⛔ Semua kunci gagal login ke Google Drive.")
        return

    # Ambil file dengan menyertakan kolom 'description'
    query = f"'{UPLOTAN_ID}' in parents and mimeType='video/mp4' and trashed=false"
    res = drive_service.files().list(q=query, orderBy="createdTime", pageSize=1, fields="files(id, name, description)").execute()
    files = res.get('files', [])

    if not files:
        print("[-] Tidak ada video di folder uplotan.")
        return

    video_file = files[0]
    file_id = video_file['id']
    
    # AMBIL JUDUL DARI DESKRIPSI FILE DRIVE (Jika kosong, pakai nama file)
    metadata_text = video_file.get('description', video_file['name'].replace('.mp4', ''))
    print(f"[*] Menyiapkan Video: {video_file['name']}")
    print(f"[*] Metadata ditemukan: {metadata_text[:50]}...")

    # 2. Download video ke server sementara
    temp_file = "upload_temp.mp4"
    request = drive_service.files().get_media(fileId=file_id)
    with io.FileIO(temp_file, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()

    # 3. Jalankan Upload dengan strategi Failover
    success_upload = False
    for cred in CREDENTIAL_SETS:
        _, youtube = get_services(cred['token'], cred['secret'], cred['label'])
        if not youtube: continue

        video_id, result = upload_to_youtube(youtube, temp_file, metadata_text, cred['label'])
        
        if video_id:
            print(f"[✅] BERHASIL! Video ID: {video_id}")
            print(f"[⏰] Terjadwal tayang pada: {result} (45 Menit lagi)")
            success_upload = True
            break
        elif result == "QUOTA_EXCEEDED":
            print(f"⚠️ {cred['label']} KUOTA HABIS. Mencoba kunci cadangan...")
            continue
        else:
            print(f"❌ Gagal dengan {cred['label']}: {result}")

    # 4. Pindahkan file jika upload berhasil
    if success_upload:
        print("[*] Memindahkan file ke folder arsip...")
        drive_service.files().update(
            fileId=file_id, 
            addParents=SELESAI_ID, 
            removeParents=UPLOTAN_ID
        ).execute()
        print("[✨] Selesai!")
    
    if os.path.exists(temp_file): os.remove(temp_file)

if __name__ == "__main__":
    main()
