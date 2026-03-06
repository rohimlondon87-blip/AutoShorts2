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

# --- KONFIGURASI BATCH ---
MAX_UPLOAD_PER_RUN = 1 # Kita set 1 dulu untuk tes kestabilan pemindahan

CREDENTIAL_SETS = [
    {
        'label': 'KUNCI UTAMA (A)',
        'token': os.environ.get('TOKEN_DATA'),
        'secret': os.environ.get('CLIENT_SECRETS_DATA')
    }
]

def clean_id(folder_id):
    if not folder_id: return ""
    return re.sub(r'[^a-zA-Z0-9_-]', '', folder_id).strip()

UPLOTAN_ID = clean_id(os.environ.get('UPLOTAN_FOLDER_ID', ''))
# Pastikan menggunakan SELESAI_ID jika itu nama secret Anda
SELESAI_ID = clean_id(os.environ.get('PROCESSED_FOLDER_ID') or os.environ.get('SELESAI_ID'))

def get_services(token_b64, secret_b64, label):
    try:
        if not token_b64: return None, None
        t_str = token_b64.strip().replace(" ", "").replace("\n", "")
        pad = len(t_str) % 4
        if pad: t_str += '=' * (4 - pad)
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds), build('youtube', 'v3', credentials=creds)
    except Exception as e:
        print(f"⚠️ {label} Gagal Auth: {e}")
        return None, None

def main():
    print(f"=== MICRO WILD: ROBOT UPLOAD SHORTS (ANTI-DUPLIKAT) ===")
    
    # 1. Inisialisasi
    drive_service, youtube_service = get_services(CREDENTIAL_SETS[0]['token'], CREDENTIAL_SETS[0]['secret'], "UTAMA")
    
    if not drive_service:
        print("⛔ Gagal akses Google Drive. Cek TOKEN_DATA!")
        return

    # 2. Cari Video (Metode FIFO)
    # Filter 'not name contains' sangat penting agar tidak ambil file yang sudah ditandai
    query = f"'{UPLOTAN_ID}' in parents and mimeType='video/mp4' and not name contains '[UPLOADED]' and trashed=false"
    res = drive_service.files().list(q=query, orderBy="createdTime", pageSize=MAX_UPLOAD_PER_RUN, fields="files(id, name, description, parents)").execute()
    files = res.get('files', [])

    if not files:
        print("[-] Antrean bersih. Tidak ada video baru.")
        return

    for i, video_file in enumerate(files):
        file_id = video_file['id']
        file_name = video_file['name']
        parent_id = video_file.get('parents', [UPLOTAN_ID])[0]
        
        print(f"\n[*] Memproses: {file_name}")
        
        # 3. Download
        temp_v = "temp_upload.mp4"
        request = drive_service.files().get_media(fileId=file_id)
        with io.FileIO(temp_v, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()

        # 4. Upload ke YouTube
        judul = video_file.get('description') or file_name.replace('.mp4', '')
        print(f"[*] Mengunggah ke YouTube: {judul[:50]}...")
        
        body = {
            'snippet': {'title': judul[:100], 'categoryId': '22'},
            'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
        }
        
        try:
            req = youtube_service.videos().insert(part='snippet,status', body=body, media_body=MediaFileUpload(temp_v, chunksize=-1, resumable=True))
            yt_res = req.execute()
            print(f"✅ SUKSES YOUTUBE! ID: {yt_res['id']}")

            # 5. PROSES PENGARSIPAN (KRUSIAL)
            print("[*] Mengamankan file di Drive agar tidak terupload ulang...")
            
            if SELESAI_ID and SELESAI_ID != UPLOTAN_ID:
                # Opsi A: Pindahkan ke folder lain
                try:
                    drive_service.files().update(
                        fileId=file_id, 
                        addParents=SELESAI_ID, 
                        removeParents=parent_id, 
                        fields='id, parents'
                    ).execute()
                    print(f"✨ Berhasil dipindahkan ke folder Arsip.")
                except Exception as e:
                    print(f"❌ Gagal pindah folder, mencoba ganti nama: {e}")
                    drive_service.files().update(fileId=file_id, body={'name': f"[UPLOADED]_{file_name}"}).execute()
            else:
                # Opsi B: Ganti nama file jika ID folder arsip tidak ada
                drive_service.files().update(fileId=file_id, body={'name': f"[UPLOADED]_{file_name}"}).execute()
                print(f"✨ Berhasil menandai file dengan [UPLOADED].")

        except Exception as e:
            print(f"❌ Terjadi kesalahan: {e}")
        finally:
            if os.path.exists(temp_v): os.remove(temp_v)

if __name__ == "__main__":
    main()
