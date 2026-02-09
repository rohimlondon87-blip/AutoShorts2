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

# --- AMBIL KUNCI GITHUB ---
CLIENT_SECRETS = os.environ.get('CLIENT_SECRETS_DATA')
TOKEN_DATA = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('UPLOTAN_FOLDER_ID') # Ambil dari folder hasil render
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
    print("=== MULAI UPLOADER (JUDUL TEKS & JADWAL 1 JAM) ===")
    drive, youtube = get_services()
    if not drive: return

    # Cari file di folder Uplotan (hasil render)
    q = f"'{SOURCE_ID}' in parents and mimeType='video/mp4' and trashed=false"
    res = drive.files().list(q=q, orderBy="createdTime", pageSize=1, fields="files(id, name, description)").execute()
    files = res.get('files', [])

    if not files:
        print("[-] Tidak ada video di folder Uplotan.")
        return
    
    f = files[0]
    # Ambil judul dari deskripsi file Drive (yang diisi oleh render_shorts_auto.py)
    judul_video = f.get('description', f['name'].split('.')[0])
    print(f"[*] Memproses: {f['name']}")
    print(f"[*] Judul YouTube: {judul_video}")
    
    # Download file ke server GitHub
    request = drive.files().get_media(fileId=f['id'])
    final_v = "upload.mp4"
    with io.FileIO(final_v, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()

    # HITUNG WAKTU JADWAL (Sekarang + 1 Jam)
    # Format: 2024-05-20T15:00:00Z (ISO 8601)
    publish_time = (datetime.utcnow() + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    print(f"[*] Menjadwalkan publikasi pada: {publish_time} UTC")

    # Upload ke YouTube
    # PENTING: privacyStatus HARUS 'private' agar publishAt berfungsi
    body = {
        'snippet': {
            'title': judul_video[:100], # Potong jika lebih dari 100 karakter
            'description': f"{judul_video}\n\n#shorts #perjuangan #kehidupan",
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'private',
            'publishAt': publish_time,
            'selfDeclaredMadeForKids': False
        }
    }
    
    media = MediaFileUpload(final_v, chunksize=-1, resumable=True)
    resp = youtube.videos().insert(part='snippet,status', body=body, media_body=media).execute()
    
    print(f"[🚀] SUKSES! Video dijadwalkan. ID: {resp['id']}")

    # Pindah ke Arsip & hapus file lokal
    drive.files().update(fileId=f['id'], addParents=ARCHIVE_ID, removeParents=SOURCE_ID).execute()
    if os.path.exists(final_v): os.remove(final_v)
    if os.path.exists("client_secrets.json"): os.remove("client_secrets.json")

if __name__ == "__main__":
    main()
