import os
import base64
import pickle
import io
import json
import sys
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request
import google.generativeai as genai

# --- AMBIL KUNCI DARI GITHUB SECRETS ---
CLIENT_SECRETS = os.environ.get('CLIENT_SECRETS_DATA')
TOKEN_DATA = os.environ.get('TOKEN_DATA')
# Pastikan ini mengambil SOURCE_LONG_ID
SOURCE_ID = os.environ.get('SOURCE_LONG_ID') 
ARCHIVE_ID = os.environ.get('PROCESSED_FOLDER_ID')
API_KEY = os.environ.get('GEMINI_API_KEY')
PRIVACY = os.environ.get('YOUTUBE_PRIVACY', 'public').strip().lower()

# --- VALIDASI KUNCI (Mencegah Error 404 'None') ---
def validate_secrets():
    missing = []
    # Cek apakah None atau string 'None' atau kosong
    def is_empty(val):
        return val is None or str(val).lower() == 'none' or str(val).strip() == ''

    if is_empty(CLIENT_SECRETS): missing.append("CLIENT_SECRETS_DATA")
    if is_empty(TOKEN_DATA): missing.append("TOKEN_DATA")
    if is_empty(SOURCE_ID): missing.append("SOURCE_LONG_ID")
    if is_empty(ARCHIVE_ID): missing.append("PROCESSED_FOLDER_ID")
    if is_empty(API_KEY): missing.append("GEMINI_API_KEY")
    
    if missing:
        print("="*60)
        print("⛔ ERROR FATAL: KUNCI BERIKUT TIDAK TERDETEKSI:")
        for m in missing:
            print(f"   - {m}")
        print("\nDIAGNOSA:")
        print("1. Cek di GitHub: Settings > Secrets and variables > Actions.")
        print("2. Pastikan Secret bernama SOURCE_LONG_ID (Huruf Besar Semua).")
        print("3. Pastikan file '.github/workflows/long_video.yml' sudah")
        print("   mengirimkan SOURCE_LONG_ID ke environment script.")
        print("="*60)
        sys.exit(1)

validate_secrets()

# Setup AI
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def get_services():
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_DATA))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        with open("client_secrets.json", "wb") as f:
            f.write(base64.b64decode(CLIENT_SECRETS))
        return build('drive', 'v3', credentials=creds), build('youtube', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error: {e}")
        return None, None

def get_long_metadata(filename):
    prompt = f"Buatkan metadata YouTube SEO-Friendly untuk video panjang berjudul: '{filename}'. Berikan HANYA JSON: {{'title': '...', 'description': '...', 'tags': []}}"
    try:
        res = model.generate_content(prompt)
        text = res.text.replace('```json','').replace('```','').strip()
        return json.loads(text)
    except:
        return {"title": filename, "description": "#video #trending", "tags": []}

def main():
    print("=== MULAI ROBOT VIDEO PANJANG ===")
    print(f"[*] ID Folder Terdeteksi: {SOURCE_ID[:5]}***") # Bukti ID masuk
    
    drive, youtube = get_services()
    if not drive: return

    # Cari file video mp4 terlama
    q = f"'{SOURCE_ID}' in parents and mimeType='video/mp4' and trashed=false"
    
    try:
        results = drive.files().list(q=q, orderBy="createdTime", pageSize=1, fields="files(id, name)").execute()
        files = results.get('files', [])
    except Exception as e:
        print(f"⛔ ERROR GOOGLE DRIVE (404): {e}")
        print("Periksa kembali apakah ID Folder Drive sudah benar.")
        return

    if not files:
        print("[-] Tidak ada antrean video panjang di Drive.")
        return
    
    f = files[0]
    print(f"[*] Mendownload: {f['name']}")
    
    # Download
    request = drive.files().get_media(fileId=f['id'])
    with io.FileIO("video_input.mp4", 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
    
    # Metadata SEO
    meta = get_long_metadata(f['name'])
    print(f"[*] Judul SEO: {meta['title']}")

    # Upload
    body = {
        'snippet': {'title': meta['title'], 'description': meta['description'], 'tags': meta.get('tags'), 'categoryId': '22'},
        'status': {'privacyStatus': PRIVACY, 'selfDeclaredMadeForKids': False}
    }
    
    print("[*] Mengupload video panjang...")
    response = youtube.videos().insert(
        part='snippet,status',
        body=body,
        media_body=MediaFileUpload("video_input.mp4", chunksize=1024*1024, resumable=True)
    ).execute()
    
    print(f"[🚀] BERHASIL! Link: https://www.youtube.com/watch?v={response.get('id')}")
    
    # Arsip
    drive.files().update(fileId=f['id'], addParents=ARCHIVE_ID, removeParents=SOURCE_ID).execute()
    print("[+] Selesai diarsipkan.")

    if os.path.exists("video_input.mp4"): os.remove("video_input.mp4")
    if os.path.exists("client_secrets.json"): os.remove("client_secrets.json")

if __name__ == "__main__":
    main()
