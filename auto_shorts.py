import os
import base64
import pickle
import io
import json
import sys
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI KUNCI GITHUB ---
CLIENT_SECRETS = os.environ.get('CLIENT_SECRETS_DATA')
TOKEN_DATA = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('UPLOTAN_FOLDER_ID') # Folder hasil render
ARCHIVE_ID = os.environ.get('PROCESSED_FOLDER_ID')

def get_services():
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_DATA))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        with open("client_secrets.json", "wb") as f:
            f.write(base64.b64decode(CLIENT_SECRETS))
        return build('drive', 'v3', credentials=creds), build('youtube', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error: {e}")
        return None, None

def main():
    print("=== MULAI UPLOADER (JUDUL DALAM DESKRIPSI) ===")
    drive, youtube = get_services()
    if not drive: return

    # Ambil 1 file terbaru dari folder Uplotan
    q = f"'{SOURCE_ID}' in parents and mimeType='video/mp4' and trashed=false"
    res = drive.files().list(q=q, orderBy="createdTime", pageSize=1, fields="files(id, name, description)").execute()
    files = res.get('files', [])

    if not files:
        print("[-] Tidak ada video baru untuk di-upload.")
        return
    
    f = files[0]
    # Mengambil teks yang disimpan di metadata 'description' Drive oleh skrip render
    judul_shorts = f.get('description', 'Shorts Perjuangan') 
    
    print(f"[*] Judul Terdeteksi: {judul_shorts}")
    
    # Download file ke server GitHub sementara
    request = drive.files().get_media(fileId=f['id'])
    v_path = "upload_ready.mp4"
    with io.FileIO(v_path, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()

    # Hitung waktu jadwal (1 jam dari sekarang)
    publish_time = (datetime.utcnow() + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Susun Metadata YouTube
    # Deskripsi sekarang menggabungkan Judul + Hashtag sesuai permintaan Anda
    full_description = f"{judul_shorts}\n\n#shorts #viral #perjuangan #kehidupan #motivation"

    body = {
        'snippet': {
            'title': judul_shorts[:100], # Judul YouTube
            'description': full_description, # Judul dimasukkan ke deskripsi
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'private', # Wajib private agar bisa dijadwalkan
            'publishAt': publish_time,   # Jadwal publikasi otomatis
            'selfDeclaredMadeForKids': False
        }
    }
    
    print(f"[*] Mengunggah ke YouTube & Menjadwalkan ke jam: {publish_time}")
    media = MediaFileUpload(v_path, chunksize=-1, resumable=True)
    response = youtube.videos().insert(part='snippet,status', body=body, media_body=media).execute()
    
    print(f"[✅] BERHASIL! Video dijadwalkan. ID: {response['id']}")

    # Pindahkan file asli di Drive ke folder Arsip agar tidak upload ulang
    drive.files().update(fileId=f['id'], addParents=ARCHIVE_ID, removeParents=SOURCE_ID).execute()
    
    # Hapus file sampah
    for tmp in [v_path, "client_secrets.json"]:
        if os.path.exists(tmp): os.remove(tmp)

if __name__ == "__main__":
    main()
