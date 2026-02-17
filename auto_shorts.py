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

# --- KONFIGURASI DUAL TOKEN ---
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
    """
    Fungsi login Super Robust.
    Membersihkan '\xa0' (Ghost Space) dan memperbaiki Padding Base64.
    """
    try:
        if not token_b64 or not secret_b64:
            return None, None
            
        # 1. SUPER CLEANER: Hapus spasi hantu (\xa0), spasi biasa, dan newline
        token_b64 = token_b64.replace('\xa0', '').strip().replace(" ", "").replace("\n", "").replace("\r", "")
        secret_b64 = secret_b64.replace('\xa0', '').strip().replace(" ", "").replace("\n", "").replace("\r", "")
        
        # 2. Fix Padding Base64
        missing_padding = len(token_b64) % 4
        if missing_padding:
            token_b64 += '=' * (4 - missing_padding)

        # 3. Decode & Login
        try:
            creds = pickle.loads(base64.b64decode(token_b64))
        except Exception as decode_err:
            print(f"⚠️ {label}: Gagal Decode Base64 (Token Rusak). Error: {decode_err}")
            return None, None

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except:
                print(f"⚠️ {label}: Token Expired & Gagal Refresh.")
                return None, None
            
        drive = build('drive', 'v3', credentials=creds)
        youtube = build('youtube', 'v3', credentials=creds)
        return drive, youtube

    except Exception as e:
        print(f"⚠️ {label} Gagal Login: {e}")
        return None, None

def get_channel_info(youtube):
    try:
        response = youtube.channels().list(part='snippet', mine=True).execute()
        return response['items'][0]['snippet']['title']
    except:
        return "Unknown Channel"

def upload_to_youtube(youtube, file_path, metadata_text, label):
    channel_name = get_channel_info(youtube)
    print(f"[*] Target Upload: {channel_name} (Via {label})")
    
    # Jadwal 45 Menit dari sekarang
    publish_time = (datetime.utcnow() + timedelta(minutes=45)).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    body = {
        'snippet': {
            'title': metadata_text[:100],
            'description': f"{metadata_text}\n\n#shorts #viral #perjuangan #kehidupan",
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'private', 
            'publishAt': publish_time,
            'selfDeclaredMadeForKids': False
        }
    }
    
    media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    
    try:
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"    -> Uploading: {int(status.progress() * 100)}%", end='\r')
        print("") 
        return response.get('id'), publish_time
    except HttpError as e:
        if e.resp.status == 403: return None, "QUOTA_EXCEEDED"
        return None, str(e)

def main():
    print("=== ROBOT UPLOAD SHORTS (ANTI-GHOST SPACE) ===")
    
    if not UPLOTAN_ID:
        print("⛔ ERROR: Folder Uplotan ID kosong.")
        return

    # 1. Login Drive (Cek Kunci A dulu, kalau rusak coba B)
    drive_service = None
    active_label = ""
    
    for cred in CREDENTIAL_SETS:
        drive_service, _ = get_services(cred['token'], cred['secret'], cred['label'])
        if drive_service: 
            active_label = cred['label']
            break

    if not drive_service:
        print("⛔ SEMUA KUNCI GAGAL (Cek GitHub Secrets Anda).")
        return

    # 2. Cari Video (Terlama)
    query = f"'{UPLOTAN_ID}' in parents and mimeType='video/mp4' and not name contains '[UPLOADED]' and trashed=false"
    try:
        res = drive_service.files().list(
            q=query, 
            orderBy="createdTime", 
            pageSize=1, 
            fields="files(id, name, description, createdTime, parents)"
        ).execute()
        files = res.get('files', [])
    except Exception as e:
        print(f"⛔ Gagal baca Drive ({active_label}): {e}")
        return

    if not files:
        print("[-] Antrean kosong. Robot istirahat.")
        return

    video_file = files[0]
    file_id = video_file['id']
    file_name = video_file['name']
    file_time = video_file['createdTime']
    curr_parents = ",".join(video_file.get('parents', []))
    meta_text = video_file.get('description', file_name.replace('.mp4', ''))

    print(f"[*] Mengambil Antrean Terdepan")
    print(f"    🎬 File  : {file_name}")
    print(f"    📅 Dibuat: {file_time}")

    # 3. Download
    print(f"[*] Menyiapkan proses download...")
    temp_v = "upload_temp.mp4"
    try:
        request = drive_service.files().get_media(fileId=file_id)
        with io.FileIO(temp_v, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
    except Exception as e:
        print(f"⛔ Gagal download: {e}")
        return

    # 4. Upload Failover
    success = False
    for cred in CREDENTIAL_SETS:
        _, youtube = get_services(cred['token'], cred['secret'], cred['label'])
        if not youtube: continue

        video_id, result = upload_to_youtube(youtube, temp_v, meta_text, cred['label'])
        if video_id:
            print(f"[✅] BERHASIL! ID: {video_id}")
            print(f"[⏰] Jadwal Tayang: {result} UTC")
            success = True
            break
        elif result == "QUOTA_EXCEEDED":
            print(f"⚠️ {cred['label']} Habis. Pindah ke cadangan...")
        else:
            print(f"❌ {cred['label']} Error: {result}")

    # 5. Tandai Selesai
    if success:
        print("[*] Membersihkan antrean...")
        try:
            if SELESAI_ID:
                drive_service.files().update(fileId=file_id, addParents=SELESAI_ID, removeParents=curr_parents).execute()
                print("[✨] File dipindahkan ke Arsip.")
            else: raise Exception
        except:
            try:
                drive_service.files().update(fileId=file_id, body={'name': f"[UPLOADED]_{file_name}"}).execute()
                print("[🏷️] File ditandai [UPLOADED].")
            except: pass

    if os.path.exists(temp_v): os.remove(temp_v)

if __name__ == "__main__":
    main()