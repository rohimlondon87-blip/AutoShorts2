import os
import base64
import pickle
import io
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI ---
TOKEN_DATA = os.environ.get('TOKEN_DATA') 
SOURCE_ID = os.environ.get('UPLOTAN_VISUAL_ID')       # Folder antrean video
ARCHIVE_ID = os.environ.get('SELESAI_ID')             # Folder arsip

def get_services():
    try:
        t_str = TOKEN_DATA.strip().replace('\xa0', '').replace(" ", "")
        pad = len(t_str) % 4
        if pad: t_str += '=' * (4 - pad)
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds), build('youtube', 'v3', credentials=creds)
    except Exception as e:
        print(f"⛔ Auth Error: {e}")
        return None, None

def download_drive_file(service, file_id, local_name):
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(local_name, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

def main():
    print("=== ROBOT UPLOAD VISUALIZER (METADATA TXT MODE) ===")
    drive, youtube = get_services()
    if not drive or not youtube: return

    # 1. Cari video paling lama di folder UPLOTAN
    query_vid = f"'{SOURCE_ID}' in parents and mimeType contains 'video/' and trashed=false"
    res_vid = drive.files().list(q=query_vid, orderBy="createdTime", pageSize=1, fields="files(id, name)").execute()
    v_files = res_vid.get('files', [])

    if not v_files:
        print("[-] Antrean kosong.")
        return

    video = v_files[0]
    base_name = os.path.splitext(video['name'])[0] # Nama tanpa .mp4
    
    print(f"[*] Memproses Video: {video['name']}")

    # 2. Cari file TXT dengan nama yang sama di folder yang sama
    query_txt = f"'{SOURCE_ID}' in parents and name = '{base_name}.txt' and trashed=false"
    res_txt = drive.files().list(q=query_txt, fields="files(id, name)").execute()
    t_files = res_txt.get('files', [])

    final_title = base_name.replace("_", " ")
    final_desc = "Original music by NightPulse AI\nFuturistic smooth jazz lounge atmosphere."

    txt_id = None
    if t_files:
        print(f"[+] Ditemukan file metadata: {t_files[0]['name']}")
        txt_id = t_files[0]['id']
        download_drive_file(drive, txt_id, "metadata.txt")
        
        with open("metadata.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
            if lines:
                final_title = lines[0].strip() # Baris 1 = Judul
                if len(lines) > 1:
                    final_desc = "".join(lines[1:]).strip() # Baris 2 dst = Deskripsi
    else:
        print("[!] File .txt tidak ditemukan. Menggunakan nama file sebagai judul.")

    # 3. Download Video
    print("[*] Mendownload video...")
    download_drive_file(drive, video['id'], "temp_video.mp4")

    # 4. Upload ke YouTube (Private -> Publik 30 Menit)
    publish_time = (datetime.utcnow() + timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    body = {
        'snippet': {
            'title': final_title[:100],
            'description': final_desc,
            'categoryId': '10'
        },
        'status': {
            'privacyStatus': 'private',
            'publishAt': publish_time,
            'selfDeclaredMadeForKids': False
        }
    }

    try:
        req = youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=MediaFileUpload("temp_video.mp4", chunksize=-1, resumable=True)
        )
        response = req.execute()
        print(f"✅ SUKSES UPLOAD! ID: {response['id']}")

        # 5. Pindahkan Video & TXT ke Arsip (SELESAI_ID)
        for f_id in [video['id'], txt_id] if txt_id else [video['id']]:
            file_meta = drive.files().get(fileId=f_id, fields='parents').execute()
            prev = ",".join(file_meta.get('parents'))
            drive.files().update(fileId=f_id, addParents=ARCHIVE_ID, removeParents=prev).execute()
        print("[+] Semua file dipindahkan ke folder Selesai.")

    except Exception as e:
        print(f"⛔ Error: {e}")
    finally:
        for f in ["temp_video.mp4", "metadata.txt"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
