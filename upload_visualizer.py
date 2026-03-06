import os
import base64
import pickle
import io
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError

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

def download_file_robust(service, file_id, local_name):
    """
    Mengunduh file dengan logika fallback.
    Mencoba Download (Binary) -> Jika Gagal -> Mencoba Export (Google Docs).
    """
    try:
        # Coba cara 1: Download Media (untuk file mp4, txt asli, jpg)
        request = service.files().get_media(fileId=file_id)
        fh = io.FileIO(local_name, 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.close()
        return True
    except HttpError as e:
        # Jika error 403 'fileNotDownloadable', berarti ini adalah Google Doc
        if e.resp.status == 403 and "fileNotDownloadable" in str(e):
            try:
                print(f"    [*] Mendeteksi Google Doc, mencoba mode Ekspor...")
                request = service.files().export_media(fileId=file_id, mimeType='text/plain')
                fh = io.FileIO(local_name, 'wb')
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                fh.close()
                return True
            except Exception as ex:
                print(f"    ❌ Gagal ekspor dokumen: {ex}")
        else:
            print(f"    ❌ Gagal download: {e}")
    except Exception as e:
        print(f"    ❌ Error tidak terduga: {e}")
    return False

def main():
    print("=== ROBOT UPLOAD VISUALIZER (ROBUST METADATA MODE) ===")
    drive, youtube = get_services()
    if not drive or not youtube: return

    # 1. Cari video paling lama di folder UPLOTAN
    query_vid = f"'{SOURCE_ID}' in parents and mimeType contains 'video/' and trashed=false"
    res_vid = drive.files().list(q=query_vid, orderBy="createdTime", pageSize=1, fields="files(id, name)").execute()
    v_files = res_vid.get('files', [])

    if not v_files:
        print("[-] Antrean kosong. Tidak ada video ditemukan.")
        return

    video = v_files[0]
    base_name = os.path.splitext(video['name'])[0] 
    
    print(f"[*] Memproses Video: {video['name']}")

    # 2. Cari file metadata (Mencari file yang namanya mengandung nama video)
    query_txt = f"'{SOURCE_ID}' in parents and name contains '{base_name}' and not mimeType contains 'video' and trashed=false"
    res_txt = drive.files().list(q=query_txt, fields="files(id, name, mimeType)").execute()
    t_files = res_txt.get('files', [])

    final_title = base_name.replace("_", " ")
    final_desc = "Original music by NightPulse AI\nFuturistic smooth jazz lounge atmosphere."

    txt_id = None
    if t_files:
        target_txt = None
        for tf in t_files:
            # Cocokkan nama file secara presisi (dengan atau tanpa .txt)
            if tf['name'] == f"{base_name}.txt" or tf['name'] == base_name:
                target_txt = tf
                break
        
        if target_txt:
            print(f"[+] Ditemukan file metadata: {target_txt['name']}")
            txt_id = target_txt['id']
            if download_file_robust(drive, txt_id, "metadata.txt"):
                try:
                    # Gunakan utf-8-sig untuk menangani BOM pada file teks
                    with open("metadata.txt", "r", encoding="utf-8-sig") as f:
                        lines = f.readlines()
                        if lines:
                            final_title = lines[0].strip()
                            if len(lines) > 1:
                                final_desc = "".join(lines[1:]).strip()
                    print(f"    ✅ Metadata berhasil dimuat.")
                except Exception as e:
                    print(f"    ⚠️ Gagal memproses isi file teks: {e}")

    # 3. Download Video
    print("[*] Mendownload video...")
    if not download_file_robust(drive, video['id'], "temp_video.mp4"):
        print("⛔ Gagal mengunduh video. Menghentikan proses.")
        return

    # 4. Upload ke YouTube (Jadwal 30 Menit)
    publish_time = (datetime.utcnow() + timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    body = {
        'snippet': {
            'title': final_title[:100],
            'description': final_desc,
            'categoryId': '10' # Music
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
        print("[*] Memindahkan file ke folder Selesai...")
        target_files = [video['id']]
        if txt_id: target_files.append(txt_id)

        for f_id in target_files:
            try:
                file_meta = drive.files().get(fileId=f_id, fields='parents').execute()
                prev = ",".join(file_meta.get('parents'))
                drive.files().update(fileId=f_id, addParents=ARCHIVE_ID, removeParents=prev).execute()
            except: pass
        print("[+] Semua file berhasil diarsipkan.")

    except Exception as e:
        print(f"⛔ Error saat upload: {e}")
    finally:
        # Hapus file sementara di server
        for f in ["temp_video.mp4", "metadata.txt"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
