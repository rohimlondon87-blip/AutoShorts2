import os
import base64
import pickle
import subprocess
import json
import time
import io
import random
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request

# --- KONFIGURASI SECRETS DINAMIS ---
TOKEN_DATA = os.environ.get('TOKEN_DATA')
# Folder ID sesuai permintaan user
INPUT_FOLDER_ID = os.environ.get('input_video_id')
OUTPUT_GABUNGAN_ID = os.environ.get('Gabungan_short_id')
DONE_ARCHIVE_ID = os.environ.get('Selesai_render_short_id')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')

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

def main():
    print("=== ROBOT KOMPILASI MICRO WILD: CUSTOM FOLDER MODE ===")
    
    # --- VALIDASI AWAL (Mencegah Error 404) ---
    missing_secrets = []
    if not INPUT_FOLDER_ID: missing_secrets.append("input_video_id")
    if not OUTPUT_GABUNGAN_ID: missing_secrets.append("Gabungan_short_id")
    if not DONE_ARCHIVE_ID: missing_secrets.append("Selesai_render_short_id")
    
    if missing_secrets:
        print(f"⛔ ERROR: Kunci Secret berikut BELUM ADA di GitHub:")
        for s in missing_secrets:
            print(f"   >> {s}")
        print("\n👉 Buka GitHub > Settings > Secrets > Actions, lalu tambahkan ID Folder tersebut.")
        return

    drive, youtube = get_services()
    if not drive: return

    # 1. AMBIL KLIP TERTUA DARI FOLDER INPUT
    print(f"[*] Mencari klip di folder input: {INPUT_FOLDER_ID}")
    try:
        query = f"'{INPUT_FOLDER_ID}' in parents and mimeType contains 'video' and trashed=false"
        res = drive.files().list(q=query, orderBy="createdTime", pageSize=10, fields="files(id, name)").execute()
        files = res.get('files', [])
    except Exception as e:
        print(f"⛔ Gagal akses Google Drive: {e}")
        return

    if len(files) < 2:
        print("[-] Bahan minimal 2 video. Antrean belum cukup.")
        return

    # ... (Sisa kode render tetap sama seperti sebelumnya) ...
    # Saya potong di sini untuk efisiensi, pastikan Anda menggunakan logika render sebelumnya
    print(f"[*] Menemukan {len(files)} file. Memulai proses...")
