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
# Skrip akan mencoba Kunci A dulu, jika gagal/habis kuota, pindah ke Kunci B
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
    """Membersihkan ID Folder dari karakter sampah."""
    if not folder_id: return ""
    return re.sub(r'[^a-zA-Z0-9_-]', '', folder_id).strip()

UPLOTAN_ID = clean_id(os.environ.get('UPLOTAN_FOLDER_ID', ''))
SELESAI_ID = clean_id(os.environ.get('PROCESSED_FOLDER_ID', ''))

def get_services(token_b64, secret_b64, label):
    """
    Fungsi login super robust.
    Membersihkan spasi hantu dan memperbaiki padding Base64 secara otomatis.
    """
    try:
        if not token_b64 or not secret_b64:
            return None, None
            
        # 1. Bersihkan karakter non-standar (spasi hantu \xa0, newline, dll)
        t_str = token_b64.replace('\xa0', '').strip().replace(" ", "").replace("\n", "").replace("\r", "")
        s_str = secret_b64.replace('\xa0', '').strip().replace(" ", "").replace("\n", "").replace("\r", "")
        
        # 2. Perbaiki Padding Base64 (Wajib kelipatan 4)
        missing_padding = len(t_str) % 4
        if missing_padding:
            t_str += '=' * (4 - missing_padding)

        # 3. Muat Kredensial
        creds = pickle.loads(base64.b64decode(t_str))
        
        # 4. Refresh Token jika kadaluarsa
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"⚠️ {label}: Gagal refresh token ({e})")
                return None, None
            
        drive = build('drive', 'v3', credentials=creds)
        youtube = build('youtube', 'v3', credentials=creds)
        return drive, youtube

    except Exception as e:
        print(f"⚠️ {label} Gagal Login: {e}")
        return None, None

def get_channel_info(youtube):
    """Mendapatkan nama channel untuk verifikasi target upload."""
    try:
        response = youtube.channels().list(part='snippet', mine=True).execute()
        return response['items'][0]['snippet']['title']
    except:
        return "Channel Tidak Diketahui"

def upload_to_youtube(youtube, file_path, metadata_text, label):
    """Proses upload dengan logika Private -> Publik (15 Menit)."""
    channel_name = get_channel_info(youtube)
    print(f"[*] Target Upload: {channel_name} (Via {label})")
    
    # Hitung waktu tayang (15 menit dari detik ini dalam UTC)
    publish_time = (datetime.utcnow() + timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    body = {
        'snippet': {
            'title': metadata_text[:100],
            'description': f"{metadata_text}\n\n#shorts #viral #mucrowild",
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'private', # Harus private agar bisa dijadwalkan
            'publishAt': publish_time,   # YouTube akan mempublikasikan otomatis
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
                print(f"    -> Progress Upload: {int(status.progress() * 100)}%", end='\r')
        print("") 
        return response.get('id'), publish_time
    except HttpError as e:
        if e.resp.status == 403 and "quotaExceeded" in str(e):
            return None, "QUOTA_FULL"
        return None, str(e)

def main():
    print(f"=== ROBOT LIVE UPLOADER (Waktu Sistem: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
    
    if not UPLOTAN_ID:
        print("⛔ ERROR: UPLOTAN_FOLDER_ID tidak ditemukan di Secrets!")
        return

    # 1. Pilih Kunci Drive yang Sehat
    drive_service = None
    for cred in CREDENTIAL_SETS:
        drive_service, _ = get_services(cred['token'], cred['secret'], cred['label'])
        if drive_service: break

    if not drive_service:
        print("⛔ SEMUA KUNCI GAGAL LOGIN. Cek kembali TOKEN_DATA Anda.")
        return

    # 2. Cari Video dengan Metode FIFO (First In, First Out)
    # orderBy='createdTime' memastikan file tertua diambil lebih dulu
    query = f"'{UPLOTAN_ID}' in parents and mimeType='video/mp4' and not name contains '[UPLOADED]' and trashed=false"
    try:
        res = drive_service.files().list(
            q=query, 
            orderBy="createdTime", 
            pageSize=10, 
            fields="files(id, name, description, createdTime, parents)"
        ).execute()
        all_files = res.get('files', [])
    except Exception as e:
        print(f"⛔ Gagal membaca folder Drive: {e}")
        return

    if not all_files:
        print("[-] Tidak ada antrean video baru di folder Uplotan.")
        return

    # Ambil file paling lama dari daftar
    video_file = all_files[0]
    total_antrean = len(all_files)
    
    file_id = video_file['id']
    file_name = video_file['name']
    file_time = video_file['createdTime']
    curr_parents = ",".join(video_file.get('parents', []))
    meta_text = video_file.get('description', file_name.replace('.mp4', ''))

    print(f"[*] Total Antrean: {total_antrean} video.")
    print(f"[*] Memproses File Terlama:")
    print(f"    🎬 Nama  : {file_name}")
    print(f"    📅 Dibuat: {file_time}")

    # 3. Download File ke Server Sementara
    temp_v = "live_upload.mp4"
    print(f"[*] Mendownload video...")
    try:
        request = drive_service.files().get_media(fileId=file_id)
        with io.FileIO(temp_v, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
    except Exception as e:
        print(f"⛔ Download Gagal: {e}")
        return

    # 4. Upload dengan Sistem Estafet (Failover A ke B)
    success = False
    for cred in CREDENTIAL_SETS:
        # Coba YouTube service untuk kunci saat ini
        _, youtube = get_services(cred['token'], cred['secret'], cred['label'])
        if not youtube: continue

        vid_id, result = upload_to_youtube(youtube, temp_v, meta_text, cred['label'])
        
        if vid_id:
            print(f"[✅] SUKSES! Video ID: {vid_id}")
            print(f"[⏰] Status: Terjadwal Publikasi dalam 15 Menit ({result} UTC)")
            success = True
            break
        elif result == "QUOTA_FULL":
            print(f"⚠️ {cred['label']} Kuota Habis. Mencoba Kunci Cadangan...")
        else:
            print(f"❌ {cred['label']} Error: {result}")

    # 5. Pasca Proses (Pindah Folder atau Ganti Nama)
    if success:
        print("[*] Membersihkan antrean folder...")
        try:
            if SELESAI_ID:
                drive_service.files().update(
                    fileId=file_id, 
                    addParents=SELESAI_ID, 
                    removeParents=curr_parents
                ).execute()
                print("[✨] Berhasil dipindahkan ke folder ARSIP (Selesai).")
            else:
                drive_service.files().update(
                    fileId=file_id, 
                    body={'name': f"[UPLOADED]_{file_name}"}
                ).execute()
                print("[🏷️] Berhasil ditandai dengan label [UPLOADED].")
        except Exception as e:
            print(f"⚠️ Gagal merapikan folder: {e}")

    # Hapus sampah di server GitHub
    if os.path.exists(temp_v):
        os.remove(temp_v)

if __name__ == "__main__":
    main()
