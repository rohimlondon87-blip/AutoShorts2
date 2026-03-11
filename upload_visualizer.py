import os
import base64
import pickle
import io
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError

# --- KONFIGURASI ---
TOKEN_DATA = os.environ.get('TOKEN_DATA') 
SOURCE_ID = os.environ.get('UPLOTAN_VISUAL_ID')       # Folder antrean video
ARCHIVE_ID = os.environ.get('SELESAI_ID')             # Folder arsip

def get_services():
    """Autentikasi ke Google Services."""
    try:
        if not TOKEN_DATA:
            print("⛔ TOKEN_DATA tidak ditemukan!")
            return None, None
            
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

def download_file_robust(service, file_id, local_name):
    """Mengunduh file video atau mengekspor Google Doc metadata."""
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.FileIO(local_name, 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.close()
        return True
    except HttpError as e:
        if e.resp.status == 403 and "fileNotDownloadable" in str(e):
            try:
                request = service.files().export_media(fileId=file_id, mimeType='text/plain')
                fh = io.FileIO(local_name, 'wb')
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                fh.close()
                return True
            except: pass
    return False

def main():
    print("=== ROBOT UPLOAD VISUALIZER (MODE PRIVATE) ===")
    drive, youtube = get_services()
    if not drive or not youtube: return

    # 1. Cari video paling lama di folder UPLOTAN (FIFO)
    query_vid = f"'{SOURCE_ID}' in parents and mimeType contains 'video/' and trashed=false"
    res_vid = drive.files().list(q=query_vid, orderBy="createdTime", pageSize=1, fields="files(id, name)").execute()
    v_files = res_vid.get('files', [])

    if not v_files:
        print("[-] Antrean kosong. Tidak ada video untuk diupload.")
        return

    video = v_files[0]
    base_name = os.path.splitext(video['name'])[0] 
    print(f"[*] Memproses Video: {video['name']}")

    # 2. Ambil Metadata (Jika ada file teks dengan nama sama)
    final_title = base_name.replace("_", " ")
    final_desc = "Visualizer Video - Diunggah secara otomatis.\n#music #visualizer"
    
    query_txt = f"'{SOURCE_ID}' in parents and name contains '{base_name}' and not mimeType contains 'video' and trashed=false"
    res_txt = drive.files().list(q=query_txt, fields="files(id, name)").execute()
    t_files = res_txt.get('files', [])

    txt_id = None
    if t_files:
        for tf in t_files:
            if tf['name'].startswith(base_name):
                txt_id = tf['id']
                if download_file_robust(drive, txt_id, "metadata.txt"):
                    try:
                        with open("metadata.txt", "r", encoding="utf-8-sig") as f:
                            lines = f.readlines()
                            if lines:
                                final_title = lines[0].strip()
                                if len(lines) > 1:
                                    final_desc = "".join(lines[1:]).strip()
                    except: pass
                break

    # 3. Download Video ke server sementara
    print("[*] Mendownload video...")
    if not download_file_robust(drive, video['id'], "temp_video.mp4"):
        print("⛔ Gagal mengunduh video.")
        return

    # 4. Upload ke YouTube dengan Status PRIVATE
    # publishAt dihapus agar video benar-benar Private murni (bukan Scheduled)
    body = {
        'snippet': {
            'title': final_title[:100],
            'description': final_desc,
            'categoryId': '10' # Kategori: Music
        },
        'status': {
            'privacyStatus': 'private', # SET PRIVATE MURNI
            'selfDeclaredMadeForKids': False
        }
    }

    try:
        print("[🚀] Mengunggah ke YouTube sebagai Private...")
        req = youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=MediaFileUpload("temp_video.mp4", chunksize=-1, resumable=True)
        )
        response = req.execute()
        print(f"✅ BERHASIL! Video ID: {response['id']}")
        print(f"💡 Silakan cek YouTube Studio untuk edit & publish.")

        # 5. Pindahkan ke Folder Selesai
        print("[*] Mengarsipkan file di Drive...")
        for f_id in [video['id'], txt_id] if txt_id else [video['id']]:
            try:
                file_meta = drive.files().get(fileId=f_id, fields='parents').execute()
                prev = ",".join(file_meta.get('parents'))
                drive.files().update(fileId=f_id, addParents=ARCHIVE_ID, removeParents=prev).execute()
            except: pass

    except Exception as e:
        print(f"⛔ Gagal Upload: {e}")
    finally:
        # Bersihkan file sampah di server
        for f in ["temp_video.mp4", "metadata.txt"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
