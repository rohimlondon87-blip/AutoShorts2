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
SOURCE_ID = os.environ.get('SOURCE_FOLDER_ID')
ARCHIVE_ID = os.environ.get('PROCESSED_FOLDER_ID')
API_KEY = os.environ.get('GEMINI_API_KEY')
PRIVACY = os.environ.get('YOUTUBE_PRIVACY', 'public')

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
        print(f"Error Login: {e}")
        return None, None

def get_long_metadata(filename):
    """Gemini membuat SEO untuk Video Panjang"""
    prompt = f"""
    Buatkan metadata YouTube SEO-Friendly untuk video panjang berjudul: '{filename}'.
    Hasilkan dalam format JSON valid (Tanpa Markdown):
    {{
        "title": "Judul Menarik & Klik-able (Max 100 char)",
        "description": "Deskripsi lengkap minimal 3 paragraf yang menjelaskan isi video dan mengandung kata kunci terkait, berikan juga beberapa hashtag.",
        "tags": ["tag1", "tag2", "tag3", "keyword1", "keyword2"],
        "category": "22" 
    }}
    (Category 22 adalah People & Blogs, sesuaikan jika perlu)
    """
    try:
        res = model.generate_content(prompt)
        text = res.text.replace('```json','').replace('```','').strip()
        return json.loads(text)
    except:
        return {"title": filename, "description": "Video upload otomatis.", "tags": [], "category": "22"}

def main():
    print("=== MULAI ROBOT VIDEO PANJANG ===")
    drive, youtube = get_services()
    if not drive: return

    # Cari file video mp4 terlama
    q = f"'{SOURCE_ID}' in parents and mimeType='video/mp4' and trashed=false"
    results = drive.files().list(q=q, orderBy="createdTime", pageSize=1, fields="files(id, name)").execute()
    files = results.get('files', [])

    if not files:
        print("[-] Tidak ada antrean video di Drive.")
        return
    
    f = files[0]
    print(f"[*] Mendownload video panjang: {f['name']}")
    
    # Download
    request = drive.files().get_media(fileId=f['id'])
    with io.FileIO("video_input.mp4", 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
    
    # Metadata SEO by Gemini
    meta = get_long_metadata(f['name'])
    print(f"[*] Judul SEO: {meta['title']}")

    # Upload
    body = {
        'snippet': {
            'title': meta['title'],
            'description': meta['description'],
            'tags': meta.get('tags'),
            'categoryId': meta.get('category', '22')
        },
        'status': {'privacyStatus': PRIVACY, 'selfDeclaredMadeForKids': False}
    }
    
    print("[*] Sedang mengupload... (Video panjang mungkin butuh waktu lebih lama)")
    response = youtube.videos().insert(
        part='snippet,status',
        body=body,
        media_body=MediaFileUpload("video_input.mp4", chunksize=1024*1024, resumable=True)
    ).execute()
    
    video_id = response.get('id')
    print(f"\n[🚀] BERHASIL UPLOAD VIDEO PANJANG!")
    print(f"[🔗] LINK: https://www.youtube.com/watch?v={video_id}")
    
    # Arsip
    drive.files().update(fileId=f['id'], addParents=ARCHIVE_ID, removeParents=SOURCE_ID).execute()
    print("[+] File sudah diarsipkan.")

if __name__ == "__main__":
    main()
