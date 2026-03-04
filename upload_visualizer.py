import os
import base64
import pickle
import io
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI KUNCI & FOLDER ---
# Sesuai permintaan, menggunakan Token A (Utama)
TOKEN_DATA = os.environ.get('TOKEN_DATA') 
CLIENT_SECRETS = os.environ.get('CLIENT_SECRETS_DATA')

# Mengambil ID Folder dari GitHub Secrets
SOURCE_ID = os.environ.get('UPLOTAN_VISUAL_ID')       # Folder ambil video
ARCHIVE_ID = os.environ.get('SELESAI_ID')             # Folder pindah (Arsip)

def get_services():
    """Autentikasi ke Google Drive dan YouTube"""
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_DATA))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        
        drive_service = build('drive', 'v3', credentials=creds)
        youtube_service = build('youtube', 'v3', credentials=creds)
        return drive_service, youtube_service
    except Exception as e:
        print(f"⛔ Auth Error: {e}")
        return None, None

def main():
    print("=== ROBOT UPLOAD VIDEO MUSIK / VISUALIZER ===")
    
    if not SOURCE_ID or not ARCHIVE_ID:
        print("⛔ ERROR: Pastikan UPLOTAN_VISUAL_ID dan SELESAI_ID sudah ada di GitHub Secrets!")
        return

    drive, youtube = get_services()
    if not drive or not youtube: return

    # 1. Cari video paling lama di folder UPLOTAN_VISUAL_ID
    print(f"[*] Mengecek antrean video di Drive...")
    query = f"'{SOURCE_ID}' in parents and mimeType='video/mp4' and trashed=false"
    res = drive.files().list(q=query, orderBy="createdTime", pageSize=1, fields="files(id, name)").execute()
    files = res.get('files', [])

    if not files:
        print("[-] Antrean kosong. Tidak ada video musik yang siap diunggah.")
        return

    f = files[0]
    file_id = f['id']
    file_name = f['name']
    
    # Gunakan nama file sebagai judul YouTube (tanpa .mp4)
    title = os.path.splitext(file_name)[0]

    print(f"[*] Menemukan video: {file_name}")
    print(f"[*] Mendownload video ke server...")
    
    # 2. Download File
    temp_file = "temp_music_video.mp4"
    request = drive.files().get_media(fileId=file_id)
    with io.FileIO(temp_file, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

    # 3. Upload ke YouTube
    print(f"[*] Mengunggah ke YouTube dengan judul: {title}")
    
    # Atur waktu rilis menjadi 30 menit dari sekarang (waktu UTC)
    publish_time = (datetime.utcnow() + timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    body = {
        'snippet': {
            'title': title[:100],
            'description': f"{title}\n\nOriginal music by NightPulse AI\nFuturistic smooth jazz lounge atmosphere.\n\n#MusikRelaksasi #Lofi #AudioVisualizer #MusikSantai",
            'tags': ['musik', 'relaksasi', 'lofi', 'visualizer', 'music'],
            'categoryId': '10' # 10 adalah kode Kategori 'Music' di YouTube
        },
        'status': {
            'privacyStatus': 'private', # Disetel private untuk penjadwalan
            'publishAt': publish_time,  # Akan publik otomatis dalam 30 menit
            'selfDeclaredMadeForKids': False
        }
    }
    
    try:
        insert_req = youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=MediaFileUpload(temp_file, chunksize=-1, resumable=True)
        )
        
        response = insert_req.execute()
        print(f"[✅] SUKSES! Video berhasil tayang.")
        print(f"🔗 Link Video: https://youtu.be/{response['id']}")

        # 4. Pindahkan File ke Folder Lain (Arsip)
        print("[*] Memindahkan file Drive ke folder Arsip...")
        file_meta = drive.files().get(fileId=file_id, fields='parents').execute()
        prev_parents = ",".join(file_meta.get('parents'))
        
        drive.files().update(
            fileId=file_id, 
            addParents=ARCHIVE_ID, 
            removeParents=prev_parents
        ).execute()
        
        print("[+] File sukses dipindahkan. Antrean bersih!")

    except Exception as e:
        print(f"⛔ ERROR saat upload: {e}")
        
    finally:
        # 5. Bersih-bersih file sementara
        if os.path.exists(temp_file):
            os.remove(temp_file)

if __name__ == "__main__":
    main()
