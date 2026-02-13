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
# Kita definisikan dua set kredensial
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
    """Melakukan autentikasi menggunakan set token tertentu."""
    try:
        if not token_b64 or not secret_b64:
            print(f"⚠️ {label}: Data secret/token tidak ditemukan di GitHub.")
            return None, None
            
        creds = pickle.loads(base64.b64decode(token_b64))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        
        # Buat file sementara secrets.json untuk kebutuhan internal library
        with open(f"secrets_{label.replace(' ', '_')}.json", "wb") as f:
            f.write(base64.b64decode(secret_b64))
            
        drive = build('drive', 'v3', credentials=creds)
        youtube = build('youtube', 'v3', credentials=creds)
        return drive, youtube
    except Exception as e:
        print(f"⚠️ {label} Gagal Login: {e}")
        return None, None

def upload_to_youtube(youtube, file_path, title, label):
    """Proses upload video ke YouTube."""
    print(f"[*] Menggunakan {label} untuk upload: {title}")
    
    body = {
        'snippet': {
            'title': title[:100],
            'description': f"{title}\n\n#shorts #viral #otomasi",
            'categoryId': '22' 
        },
        'status': {
            'privacyStatus': 'public', 
            'selfDeclaredMadeForKids': False
        }
    }
    
    media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    
    try:
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"   - Progress {label}: {int(status.progress() * 100)}%")
        return response.get('id'), None
    except HttpError as e:
        # Deteksi jika kuota habis (Error 403)
        if e.resp.status == 403:
            return None, "QUOTA_EXCEEDED"
        return None, str(e)

def main():
    print("=== ROBOT PENGUNGGAH DUAL-TOKEN (SMART FAILOVER) ===")
    
    if not UPLOTAN_ID or not SELESAI_ID:
        print("⛔ ERROR: ID Folder belum diisi!")
        return

    # 1. Cari video tertua (antrean) menggunakan Kunci A (sebagai pembuka pintu Drive)
    # Kita coba login pakai Kunci A dulu untuk cek file
    drive_service = None
    for cred in CREDENTIAL_SETS:
        drive_service, _ = get_services(cred['token'], cred['secret'], cred['label'])
        if drive_service: break

    if not drive_service:
        print("⛔ Semua kunci gagal login ke Drive.")
        return

    query = f"'{UPLOTAN_ID}' in parents and mimeType='video/mp4' and trashed=false"
    res = drive_service.files().list(q=query, orderBy="createdTime", pageSize=1, fields="files(id, name, description)").execute()
    files = res.get('files', [])

    if not files:
        print("[-] Tidak ada video di folder UPLOTAN.")
        return

    video_file = files[0]
    file_id = video_file['id']
    judul = video_file.get('description', video_file['name'].replace('.mp4', ''))

    # 2. Download video
    temp_file = "temp_dual.mp4"
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

        video_id, error_status = upload_to_youtube(youtube, temp_file, judul, cred['label'])
        
        if video_id:
            print(f"[✅] SUKSES! Video ID: {video_id} (Via {cred['label']})")
            success_upload = True
            break
        elif error_status == "QUOTA_EXCEEDED":
            print(f"⚠️ {cred['label']} KUOTA HABIS. Mencoba kunci selanjutnya...")
            continue
        else:
            print(f"❌ Gagal dengan {cred['label']}: {error_status}")

    # 4. Pindahkan file jika upload berhasil di salah satu kunci
    if success_upload:
        print("[*] Memindahkan file ke folder SELESAI...")
        drive_service.files().update(
            fileId=file_id, 
            addParents=SELESAI_ID, 
            removeParents=UPLOTAN_ID
        ).execute()
        print("[✨] Selesai!")
    
    # Pembersihan
    if os.path.exists(temp_file): os.remove(temp_file)
    for cred in CREDENTIAL_SETS:
        f_name = f"secrets_{cred['label'].replace(' ', '_')}.json"
        if os.path.exists(f_name): os.remove(f_name)

if __name__ == "__main__":
    main()
