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

# DISAMAKAN DENGAN SCREENSHOT GITHUB ANDA
UPLOTAN_ID = clean_id(os.environ.get('UPLOTAN_FOLDER_ID', ''))
SELESAI_ID = clean_id(os.environ.get('PROCESSED_FOLDER_ID', '')) # Perubahan di sini

def get_services(token_b64, secret_b64, label):
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

def upload_to_youtube(youtube, file_path, title, label):
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
        response = request.execute()
        return response.get('id'), None
    except HttpError as e:
        if e.resp.status == 403:
            return None, "QUOTA_EXCEEDED"
        return None, str(e)

def main():
    print("=== ROBOT PENGUNGGAH DUAL-TOKEN (FIXED ID) ===")
    
    # Validasi ID Folder
    if not UPLOTAN_ID:
        print("⛔ ERROR: UPLOTAN_FOLDER_ID belum diisi di GitHub Secrets!")
        return
    if not SELESAI_ID:
        print("⛔ ERROR: PROCESSED_FOLDER_ID belum diisi di GitHub Secrets!")
        return

    # 1. Login & Cari Video
    drive_service = None
    for cred in CREDENTIAL_SETS:
        drive_service, _ = get_services(cred['token'], cred['secret'], cred['label'])
        if drive_service: break

    if not drive_service:
        print("⛔ Semua kunci gagal login.")
        return

    query = f"'{UPLOTAN_ID}' in parents and mimeType='video/mp4' and trashed=false"
    res = drive_service.files().list(q=query, orderBy="createdTime", pageSize=1).execute()
    files = res.get('files', [])

    if not files:
        print("[-] Tidak ada video di folder uplotan.")
        return

    video_file = files[0]
    file_id = video_file['id']
    judul = video_file['name'].replace('.mp4', '')

    # 2. Download
    temp_file = "temp_dual.mp4"
    request = drive_service.files().get_media(fileId=file_id)
    with io.FileIO(temp_file, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()

    # 3. Upload Failover
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

    # 4. Pindahkan file
    if success_upload:
        drive_service.files().update(
            fileId=file_id, 
            addParents=SELESAI_ID, 
            removeParents=UPLOTAN_ID
        ).execute()
        print("[✨] Berhasil dipindahkan ke folder selesai!")
    
    if os.path.exists(temp_file): os.remove(temp_file)

if __name__ == "__main__":
    main()
