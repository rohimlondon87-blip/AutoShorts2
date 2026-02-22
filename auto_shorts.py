import os
import base64
import pickle
import time
import io
import random
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.auth.transport.requests import Request

# --- KONFIGURASI MICRO WILD ---
# Mendukung Dual Token A & B
CREDENTIAL_SETS = [
    {'label': 'KUNCI UTAMA (A)', 'token': os.environ.get('TOKEN_DATA'), 'secret': os.environ.get('CLIENT_SECRETS_DATA')},
    {'label': 'KUNCI CADANGAN (B)', 'token': os.environ.get('TOKEN_DATA_B'), 'secret': os.environ.get('CLIENT_SECRETS_DATA_B')}
]

UPLOTAN_ID = os.environ.get('UPLOTAN_FOLDER_ID')
DONE_ID = os.environ.get('PROCESSED_FOLDER_ID')

def get_services(token_b64, label):
    try:
        if not token_b64: return None, None
        t_str = token_b64.strip().replace('\xa0', '').replace(" ", "")
        pad = len(t_str) % 4
        if pad: t_str += '=' * (4 - pad)
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds), build('youtube', 'v3', credentials=creds)
    except: return None, None

def main():
    print("=== MICRO WILD: ROBOT UPLOAD SHORTS START ===")
    
    # Pilih token yang aktif
    drive, youtube, used_label = None, None, ""
    for cred in CREDENTIAL_SETS:
        drive, youtube = get_services(cred['token'], cred['label'])
        if drive:
            used_label = cred['label']
            break
    
    if not drive:
        print("⛔ Semua Token Gagal Login.")
        return

    # Ambil antrean terlama (FIFO)
    query = f"'{UPLOTAN_ID}' in parents and mimeType contains 'video' and trashed=false"
    files = drive.files().list(q=query, orderBy="createdTime", pageSize=1).execute().get('files', [])
    
    if not files:
        print("[-] Antrean Kosong.")
        return

    v_file = files[0]
    print(f"[*] Memproses: {v_file['name']} via {used_label}")

    # Download & Upload
    with open("temp_up.mp4", "wb") as f:
        f.write(drive.files().get_media(fileId=v_file['id']).execute())

    body = {
        'snippet': {'title': f"{v_file['name'].split('.')[0]} #shorts #microwild", 'categoryId': '22'},
        'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
    }
    
    try:
        res = youtube.videos().insert(part='snippet,status', body=body, media_body=MediaFileUpload("temp_up.mp4")).execute()
        print(f"[✅] SUKSES! Video ID: {res['id']}")
        
        # Pindahkan ke folder Selesai
        drive.files().update(fileId=v_file['id'], addParents=DONE_ID, removeParents=UPLOTAN_ID).execute()
        print("[✨] Berhasil diarsipkan.")
    except Exception as e:
        print(f"❌ Gagal: {e}")

    if os.path.exists("temp_up.mp4"): os.remove("temp_up.mp4")

if __name__ == "__main__":
    main()