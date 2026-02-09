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

# Robot akan mencoba mencari ID Folder dari beberapa kemungkinan nama secret
SOURCE_ID = os.environ.get('UPLOTAN_FOLDER_ID') or os.environ.get('SOURCE_FOLDER_ID')
ARCHIVE_ID = os.environ.get('PROCESSED_FOLDER_ID')

def validate_secrets():
    """Memastikan semua kunci penting tersedia sebelum memulai"""
    print("[*] Tahap 1: Validasi Kunci Secret...")
    errors = []
    if not CLIENT_SECRETS: errors.append("CLIENT_SECRETS_DATA")
    if not TOKEN_DATA: errors.append("TOKEN_DATA")
    if not SOURCE_ID or SOURCE_ID == "None": errors.append("UPLOTAN_FOLDER_ID (Folder Hasil Render)")
    if not ARCHIVE_ID: errors.append("PROCESSED_FOLDER_ID (Folder Arsip)")
    
    if errors:
        print(f"⛔ ERROR: Secret berikut tidak terbaca: {', '.join(errors)}")
        print("Saran: Periksa tab 'Settings > Secrets' di GitHub dan pastikan namanya sama.")
        sys.exit(1)
    
    print(f"✅ Kunci ditemukan. Mengambil video dari folder: {SOURCE_ID}")

def get_services():
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_DATA))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        
        # Tulis client_secrets secara lokal untuk library Google
        with open("client_secrets.json", "wb") as f:
            f.write(base64.b64decode(CLIENT_SECRETS))
            
        drive = build('drive', 'v3', credentials=creds)
        youtube = build('youtube', 'v3', credentials=creds)
        return drive, youtube
    except Exception as e:
        print(f"⛔ Auth Error: {e}")
        return None, None

def main():
    print("=== MULAI UPLOADER (FINAL ROBUST VERSION) ===")
    validate_secrets()
    
    drive, youtube = get_services()
    if not drive: return

    # Cari file di folder Uplotan (hasil render)
    # Query dipastikan tidak akan mengirim 'None' lagi
    query = f"'{SOURCE_ID}' in parents and mimeType='video/mp4' and trashed=false"
    
    try:
        res = drive.files().list(
            q=query, 
            orderBy="createdTime", 
            pageSize=1, 
            fields="files(id, name, description)"
        ).execute()
        files = res.get('files', [])
    except Exception as e:
        print(f"⛔ Gagal mengakses Drive: {e}")
        return

    if not files:
        print("[-] Tidak ada video baru di folder Uplotan.")
        return
    
    f = files[0]
    # Mengambil teks yang disimpan di metadata 'description' Drive oleh skrip render
    judul_shorts = f.get('description', f['name'].split('.')[0]) 
    
    print(f"[*] Memproses file: {f['name']}")
    print(f"[*] Judul YouTube: {judul_shorts}")
    
    # Download file ke server GitHub sementara
    v_path = "upload_ready.mp4"
    try:
        request = drive.files().get_media(fileId=f['id'])
        with io.FileIO(v_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
    except Exception as e:
        print(f"⛔ Gagal download dari Drive: {e}")
        return

    # Hitung waktu jadwal (1 jam dari sekarang agar kualitas HD terproses dulu)
    publish_time = (datetime.utcnow() + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Susun Metadata YouTube (Judul dimasukkan ke deskripsi juga)
    full_description = f"{judul_shorts}\n\n#shorts #viral #perjuangan #kehidupan"

    body = {
        'snippet': {
            'title': judul_shorts[:100], 
            'description': full_description,
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'private', 
            'publishAt': publish_time,   
            'selfDeclaredMadeForKids': False
        }
    }
    
    print(f"[*] Mengunggah & Menjadwalkan ke jam: {publish_time} (UTC)")
    try:
        media = MediaFileUpload(v_path, mimetype='video/mp4', chunksize=-1, resumable=True)
        response = youtube.videos().insert(part='snippet,status', body=body, media_body=media).execute()
        print(f"[✅] BERHASIL! Video dijadwalkan. ID: {response['id']}")

        # Pindahkan file asli di Drive ke folder Arsip agar tidak upload ulang
        drive.files().update(fileId=f['id'], addParents=ARCHIVE_ID, removeParents=SOURCE_ID).execute()
        print("[#] File di Drive sudah dipindahkan ke Arsip.")
    except Exception as e:
        print(f"⛔ GAGAL UPLOAD YOUTUBE: {e}")

    # Hapus file sampah di server GitHub
    for tmp in [v_path, "client_secrets.json"]:
        if os.path.exists(tmp): os.remove(tmp)

if __name__ == "__main__":
    main()
