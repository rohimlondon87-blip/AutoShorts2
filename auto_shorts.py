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
    # Membersihkan ID dari spasi atau karakter aneh yang sering terbawa saat copypaste
    cleaned = re.sub(r'[^a-zA-Z0-9_-]', '', folder_id)
    return cleaned.strip()

UPLOTAN_ID = clean_id(os.environ.get('UPLOTAN_FOLDER_ID', ''))
SELESAI_ID = clean_id(os.environ.get('PROCESSED_FOLDER_ID', ''))

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

def upload_to_youtube(youtube, file_path, metadata_text, label):
    print(f"[*] Menggunakan {label} untuk upload...")
    publish_time = (datetime.utcnow() + timedelta(minutes=45)).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    body = {
        'snippet': {
            'title': metadata_text[:100],
            'description': f"{metadata_text}\n\n#shorts #viral #otomasi",
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'private',
            'publishAt': publish_time,
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
    print("=== ROBOT PENGUNGGAH DUAL-TOKEN (FIXED MOVE) ===")
    
    if not UPLOTAN_ID or not SELESAI_ID:
        print("⛔ ERROR: ID Folder Uplotan atau Selesai belum diisi di Secrets!")
        return

    # 1. Pilih Kunci yang Aktif untuk Drive
    drive_service = None
    active_label = ""
    for cred in CREDENTIAL_SETS:
        drive_service, _ = get_services(cred['token'], cred['secret'], cred['label'])
        if drive_service:
            active_label = cred['label']
            break

    if not drive_service:
        print("⛔ Semua kunci gagal login ke Drive.")
        return

    # 2. Cari Video
    try:
        query = f"'{UPLOTAN_ID}' in parents and mimeType='video/mp4' and trashed=false"
        res = drive_service.files().list(q=query, orderBy="createdTime", pageSize=1, fields="files(id, name, description)").execute()
        files = res.get('files', [])
    except HttpError as e:
        print(f"⛔ Gagal listing folder: {e}")
        return

    if not files:
        print("[-] Tidak ada video di folder uplotan.")
        return

    video_file = files[0]
    file_id = video_file['id']
    metadata_text = video_file.get('description', video_file['name'].replace('.mp4', ''))
    print(f"[*] Menyiapkan: {video_file['name']}")

    # 3. Download
    temp_file = "upload_temp.mp4"
    try:
        request = drive_service.files().get_media(fileId=file_id)
        with io.FileIO(temp_file, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
    except Exception as e:
        print(f"⛔ Gagal download: {e}")
        return

    # 4. Upload ke YouTube
    success_upload = False
    for cred in CREDENTIAL_SETS:
        _, youtube = get_services(cred['token'], cred['secret'], cred['label'])
        if not youtube: continue

        video_id, result = upload_to_youtube(youtube, temp_file, metadata_text, cred['label'])
        
        if video_id:
            print(f"[✅] BERHASIL! Video ID: {video_id}")
            print(f"[⏰] Terjadwal tayang: {result}")
            success_upload = True
            break
        elif result == "QUOTA_EXCEEDED":
            print(f"⚠️ {cred['label']} Kuota Habis. Mencoba cadangan...")
            continue
        else:
            print(f"❌ Gagal dengan {cred['label']}: {result}")

    # 5. Pindahkan File (PENTING: Error handling khusus agar tidak crash)
    if success_upload:
        print(f"[*] Memindahkan file {file_id} ke folder Selesai...")
        try:
            # Menggunakan API Drive untuk memindahkan file
            drive_service.files().update(
                fileId=file_id, 
                addParents=SELESAI_ID, 
                removeParents=UPLOTAN_ID,
                fields='id, parents'
            ).execute()
            print("[✨] Berhasil dipindahkan!")
        except HttpError as e:
            print(f"⚠️ PERINGATAN: Video terupload TAPI gagal dipindahkan ke folder Selesai.")
            print(f"Cek ID Folder Selesai: {SELESAI_ID}")
            print(f"Detail Error: {e}")
            # Opsional: Jika gagal pindah, kita hapus saja file aslinya agar tidak upload dobel
            # drive_service.files().delete(fileId=file_id).execute()
    
    if os.path.exists(temp_file): os.remove(temp_file)

if __name__ == "__main__":
    main()