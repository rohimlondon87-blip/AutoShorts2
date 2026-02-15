import os
import base64
import pickle
import io
import time
import re
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError

# --- KONFIGURASI ---
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
        drive = build('drive', 'v3', credentials=creds)
        youtube = build('youtube', 'v3', credentials=creds)
        return drive, youtube
    except Exception as e:
        print(f"⚠️ {label} Gagal Login: {e}")
        return None, None

def get_channel_info(youtube):
    """Mendapatkan nama channel untuk memastikan tidak salah channel."""
    try:
        response = youtube.channels().list(part='snippet', mine=True).execute()
        return response['items'][0]['snippet']['title']
    except:
        return "Unknown Channel"

def upload_to_youtube(youtube, file_path, metadata_text, label):
    channel_name = get_channel_info(youtube)
    print(f"[*] Menuju Channel: {channel_name} (Via {label})")
    
    body = {
        'snippet': {
            'title': metadata_text[:100],
            'description': f"{metadata_text}\n\n#shorts #viral",
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'public', # SET KE PUBLIK LANGSUNG
            'selfDeclaredMadeForKids': False
        }
    }
    
    media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    
    try:
        response = request.execute()
        video_id = response.get('id')
        return video_id, f"https://www.youtube.com/watch?v={video_id}"
    except HttpError as e:
        if e.resp.status == 403:
            return None, "QUOTA_EXCEEDED"
        return None, str(e)

def main():
    print("=== ROBOT PENGUNGGAH (DIAGNOSIS CHANNEL) ===")
    
    if not UPLOTAN_ID:
        print("⛔ ERROR: Folder Uplotan ID kosong!")
        return

    # 1. Pilih Kunci Aktif
    drive_service = None
    for cred in CREDENTIAL_SETS:
        drive_service, _ = get_services(cred['token'], cred['secret'], cred['label'])
        if drive_service: break

    if not drive_service:
        print("⛔ Gagal akses Google Drive.")
        return

    # 2. Cari Video (Abaikan yang sudah diupload)
    query = f"'{UPLOTAN_ID}' in parents and mimeType='video/mp4' and not name contains '[UPLOADED]' and trashed=false"
    res = drive_service.files().list(q=query, orderBy="createdTime", pageSize=1, fields="files(id, name, description, parents)").execute()
    files = res.get('files', [])

    if not files:
        print("[-] Tidak ada video baru di folder uplotan.")
        return

    video_file = files[0]
    file_id = video_file['id']
    file_name = video_file['name']
    current_parents = ",".join(video_file.get('parents', []))
    metadata_text = video_file.get('description', file_name.replace('.mp4', ''))
    
    print(f"[*] Mendownload: {file_name}")

    # 3. Download
    temp_file = "upload_temp.mp4"
    request = drive_service.files().get_media(fileId=file_id)
    with io.FileIO(temp_file, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()

    # 4. Upload
    success_upload = False
    for cred in CREDENTIAL_SETS:
        _, youtube = get_services(cred['token'], cred['secret'], cred['label'])
        if not youtube: continue

        video_id, video_url = upload_to_youtube(youtube, temp_file, metadata_text, cred['label'])
        
        if video_id:
            print(f"[✅] BERHASIL! Video ID: {video_id}")
            print(f"[🔗] LINK VIDEO: {video_url}")
            success_upload = True
            break
        elif video_url == "QUOTA_EXCEEDED":
            print(f"⚠️ {cred['label']} Kuota Habis.")
            continue

    # 5. Penanganan File di Drive
    if success_upload:
        # Coba pindahkan
        if SELESAI_ID:
            try:
                drive_service.files().update(fileId=file_id, addParents=SELESAI_ID, removeParents=current_parents).execute()
                print("[✨] Berhasil dipindahkan folder.")
                if os.path.exists(temp_file): os.remove(temp_file)
                return
            except: pass
        
        # Ganti nama jika gagal pindah
        try:
            drive_service.files().update(fileId=file_id, body={'name': f"[UPLOADED]_{file_name}"}).execute()
            print("[🏷️] Berhasil ditandai [UPLOADED].")
        except: pass
    
    if os.path.exists(temp_file): os.remove(temp_file)

if __name__ == "__main__":
    main()
