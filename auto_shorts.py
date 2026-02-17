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
    """Login dengan pembersihan karakter spasi hantu."""
    try:
        if not token_b64 or not secret_b64:
            return None, None
        
        # Bersihkan karakter \xa0 atau spasi yang tidak terlihat
        t_str = token_b64.replace('\xa0', '').strip().replace(" ", "").replace("\n", "")
        s_str = secret_b64.replace('\xa0', '').strip().replace(" ", "").replace("\n", "")
        
        missing_padding = len(t_str) % 4
        if missing_padding:
            t_str += '=' * (4 - missing_padding)

        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            
        return build('drive', 'v3', credentials=creds), build('youtube', 'v3', credentials=creds)
    except Exception as e:
        print(f"⚠️ {label} Login Error: {e}")
        return None, None

def upload_to_youtube(youtube, file_path, metadata_text, label):
    try:
        ch = youtube.channels().list(part='snippet', mine=True).execute()
        ch_name = ch['items'][0]['snippet']['title']
    except: ch_name = "Unknown"

    print(f"[*] Target Upload: {ch_name} (Via {label})")
    
    # Penjadwalan 45 Menit
    publish_time = (datetime.utcnow() + timedelta(minutes=45)).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    body = {
        'snippet': {
            'title': metadata_text[:100],
            'description': f"{metadata_text}\n\n#shorts #viral #mucrowild",
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
                print(f"    -> Progress: {int(status.progress() * 100)}%", end='\r')
        print("") 
        return response.get('id'), publish_time
    except HttpError as e:
        if e.resp.status == 403: return None, "QUOTA_FULL"
        return None, str(e)

def main():
    print("=== ROBOT UPLOAD SHORTS (SISTEM ANTREAN FIFO) ===")
    
    # 1. Login Drive
    drive_service = None
    for cred in CREDENTIAL_SETS:
        drive_service, _ = get_services(cred['token'], cred['secret'], cred['label'])
        if drive_service: break

    if not drive_service:
        print("⛔ SEMUA TOKEN GAGAL LOGIN.")
        return

    # 2. Cari Video (Urutan Terlama)
    # Gunakan createdTime (Waktu file masuk ke Drive)
    query = f"'{UPLOTAN_ID}' in parents and mimeType='video/mp4' and not name contains '[UPLOADED]' and trashed=false"
    try:
        # Kita ambil lebih dari 1 dulu untuk menghitung total antrean di log
        res = drive_service.files().list(
            q=query, 
            orderBy="createdTime", # Tanpa 'desc' agar yang terlama (paling atas) diambil
            fields="files(id, name, description, createdTime, parents)"
        ).execute()
        all_files = res.get('files', [])
    except Exception as e:
        print(f"⛔ Gagal baca Drive: {e}")
        return

    if not all_files:
        print("[-] Tidak ada antrean video baru. Menunggu proses render...")
        return

    # Ambil file pertama (paling lama sesuai orderBy)
    video_file = all_files[0]
    total_antrean = len(all_files)
    
    file_id = video_file['id']
    file_name = video_file['name']
    file_time = video_file['createdTime']
    curr_parents = ",".join(video_file.get('parents', []))
    meta_text = video_file.get('description', file_name.replace('.mp4', ''))

    print(f"[*] Total Antrean: {total_antrean} video")
    print(f"[*] Memilih File TERLAMA (Front of Queue):")
    print(f"    🎬 Nama  : {file_name}")
    print(f"    📅 Dibuat: {file_time}")

    # 3. Download
    temp_v = "upload_now.mp4"
    print(f"[*] Mendownload file dari Drive...")
    request = drive_service.files().get_media(fileId=file_id)
    with io.FileIO(temp_v, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()

    # 4. Upload (Failover A -> B)
    success = False
    for cred in CREDENTIAL_SETS:
        _, youtube = get_services(cred['token'], cred['secret'], cred['label'])
        if not youtube: continue

        video_id, result = upload_to_youtube(youtube, temp_v, meta_text, cred['label'])
        if video_id:
            print(f"[✅] BERHASIL! Video ID: {video_id}")
            print(f"[⏰] Jadwal Publikasi Otomatis: {result} (UTC)")
            success = True
            break
        elif result == "QUOTA_FULL":
            print(f"⚠️ {cred['label']} Habis Kuota. Mencoba Cadangan...")
        else:
            print(f"❌ {cred['label']} Error: {result}")

    # 5. Pasca Upload
    if success:
        print("[*] Membersihkan antrean...")
        try:
            if SELESAI_ID:
                drive_service.files().update(fileId=file_id, addParents=SELESAI_ID, removeParents=curr_parents).execute()
                print("[✨] Berhasil dipindahkan ke folder Selesai.")
            else: raise Exception
        except:
            drive_service.files().update(fileId=file_id, body={'name': f"[UPLOADED]_{file_name}"}).execute()
            print("[🏷️] Berhasil ditandai sebagai [UPLOADED].")

    if os.path.exists(temp_v): os.remove(temp_v)

if __name__ == "__main__":
    main()