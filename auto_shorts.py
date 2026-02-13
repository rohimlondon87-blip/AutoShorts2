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
    return re.sub(r'[^a-zA-Z0-9_-]', '', folder_id).strip()

UPLOTAN_ID = clean_id(os.environ.get('UPLOTAN_FOLDER_ID', ''))
SELESAI_ID = clean_id(os.environ.get('PROCESSED_FOLDER_ID', ''))

def get_services(token_b64, secret_b64, label):
    try:
        if not token_b64 or not secret_b64:
            return None, None
        creds = pickle.loads(base64.b64decode(token_b64))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds), build('youtube', 'v3', credentials=creds)
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
    print("=== ROBOT PENGUNGGAH DUAL-TOKEN (ANTI-DOUBLE UPLOAD) ===")
    
    if not UPLOTAN_ID:
        print("⛔ ERROR: ID Folder Uplotan belum diisi!")
        return

    # 1. Pilih Kunci Aktif
    drive_service = None
    for cred in CREDENTIAL_SETS:
        drive_service, _ = get_services(cred['token'], cred['secret'], cred['label'])
        if drive_service: break

    if not drive_service:
        print("⛔ Semua kunci gagal login.")
        return

    # 2. Cari Video (FILTER: Abaikan yang sudah ada tanda [UPLOADED])
    try:
        # Query: Mencari mp4 di folder uplotan yang namanya TIDAK mengandung '[UPLOADED]'
        query = f"'{UPLOTAN_ID}' in parents and mimeType='video/mp4' and not name contains '[UPLOADED]' and trashed=false"
        res = drive_service.files().list(
            q=query, 
            orderBy="createdTime", 
            pageSize=1, 
            fields="files(id, name, description, parents)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        files = res.get('files', [])
    except HttpError as e:
        print(f"⛔ Gagal akses Drive: {e}")
        return

    if not files:
        print("[-] Tidak ada video baru di folder uplotan.")
        return

    video_file = files[0]
    file_id = video_file['id']
    file_name = video_file['name']
    current_parents = ",".join(video_file.get('parents', []))
    metadata_text = video_file.get('description', file_name.replace('.mp4', ''))
    
    print(f"[*] Menemukan video baru: {file_name}")

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

    # 4. Upload ke YouTube (Failover A ke B)
    success_upload = False
    for cred in CREDENTIAL_SETS:
        _, youtube = get_services(cred['token'], cred['secret'], cred['label'])
        if not youtube: continue

        video_id, result = upload_to_youtube(youtube, temp_file, metadata_text, cred['label'])
        
        if video_id:
            print(f"[✅] BERHASIL UPLOAD! Video ID: {video_id}")
            success_upload = True
            break
        elif result == "QUOTA_EXCEEDED":
            print(f"⚠️ {cred['label']} Kuota Habis. Mencoba cadangan...")
            continue
        else:
            print(f"❌ Gagal dengan {cred['label']}: {result}")

    # 5. Penanganan File Setelah Upload
    if success_upload:
        # Percobaan A: Pindahkan ke folder Selesai
        if SELESAI_ID:
            print(f"[*] Mencoba memindahkan ke folder Selesai...")
            try:
                drive_service.files().update(
                    fileId=file_id,
                    addParents=SELESAI_ID,
                    removeParents=current_parents,
                    supportsAllDrives=True
                ).execute()
                print("[✨] Berhasil dipindahkan!")
                if os.path.exists(temp_file): os.remove(temp_file)
                return 
            except:
                print("⚠️ Gagal memindahkan (Izin Terbatas).")

        # Percobaan B: Ganti Nama (Tandai sebagai sudah diupload)
        print(f"[*] Menandai file dengan awalan [UPLOADED]...")
        try:
            new_name = f"[UPLOADED]_{file_name}"
            drive_service.files().update(
                fileId=file_id,
                body={'name': new_name},
                supportsAllDrives=True
            ).execute()
            print(f"[🏷️] Berhasil ditandai: {new_name}")
        except Exception as e:
            print(f"❌ Gagal menandai file: {e}")
            print("[!] Peringatan: File mungkin akan terupload ulang. Harap cek folder Drive Anda.")
    
    if os.path.exists(temp_file): os.remove(temp_file)

if __name__ == "__main__":
    main()