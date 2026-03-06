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

def download_metadata_file(service, file_id, mime_type, local_name):
    """
    Mengunduh metadata dengan cerdas. 
    Mendukung file binary (.txt) dan Google Docs (Export).
    """
    fh = io.FileIO(local_name, 'wb')
    
    # Jika file adalah Google Doc (bukan binary)
    if 'application/vnd.google-apps' in mime_type:
        request = service.files().export_media(fileId=file_id, mimeType='text/plain')
    else:
        # Jika file adalah .txt asli yang diupload
        request = service.files().get_media(fileId=file_id)
        
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.close()

def main():
    print("=== ROBOT UPLOAD VISUALIZER (FIX DOCS EXPORT MODE) ===")
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
    base_name = os.path.splitext(video['name'])[0] 
    
    print(f"[*] Memproses Video: {video['name']}")

    # 2. Cari file metadata (Bisa nama.txt atau Google Doc bernama nama.txt)
    # Kami mencari file yang namanya sama dengan video
    query_txt = f"'{SOURCE_ID}' in parents and name contains '{base_name}' and not mimeType contains 'video' and trashed=false"
    res_txt = drive.files().list(q=query_txt, fields="files(id, name, mimeType)").execute()
    t_files = res_txt.get('files', [])

    final_title = base_name.replace("_", " ")
    final_desc = "Original music by NightPulse AI\nFuturistic smooth jazz lounge atmosphere."

    txt_id = None
    if t_files:
        # Cari yang benar-benar pas namanya (menghindari salah ambil file lain)
        target_txt = None
        for tf in t_files:
            if tf['name'] == f"{base_name}.txt" or tf['name'] == base_name:
                target_txt = tf
                break
        
        if target_txt:
            print(f"[+] Ditemukan file metadata: {target_txt['name']} ({target_txt['mimeType']})")
            txt_id = target_txt['id']
            try:
                download_metadata_file(drive, txt_id, target_txt['mimeType'], "metadata.txt")
                
                with open("metadata.txt", "r", encoding="utf-8-sig") as f:
                    lines = f.readlines()
                    if lines:
                        final_title = lines[0].strip()
                        if len(lines) > 1:
                            final_desc = "".join(lines[1:]).strip()
            except Exception as e:
                print(f"⚠️ Gagal membaca metadata: {e}. Menggunakan default.")
    else:
        print("[!] File metadata tidak ditemukan. Menggunakan nama file.")

    # 3. Download Video
    print("[*] Mendownload video...")
    request_v = drive.files().get_media(fileId=video['id'])
    with io.FileIO("temp_video.mp4", 'wb') as fh_v:
        downloader_v = MediaIoBaseDownload(fh_v, request_v)
        done_v = False
        while not done_v:
            _, done_v = downloader_v.next_chunk()

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

        # 5. Pindahkan Video & Metadata ke Arsip
        for f_id in [video['id'], txt_id] if txt_id else [video['id']]:
            try:
                file_meta = drive.files().get(fileId=f_id, fields='parents').execute()
                prev = ",".join(file_meta.get('parents'))
                drive.files().update(fileId=f_id, addParents=ARCHIVE_ID, removeParents=prev).execute()
            except: pass
        print("[+] Semua file dipindahkan ke folder Selesai.")

    except Exception as e:
        print(f"⛔ Error saat upload: {e}")
    finally:
        for f in ["temp_video.mp4", "metadata.txt"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
