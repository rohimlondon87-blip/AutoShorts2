import os
import base64
import pickle
import io
import json
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request
import google.generativeai as genai
from moviepy.editor import ImageClip

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
    """Membuka kunci token dan menghubungkan ke Google"""
    try:
        # Decode Token
        creds = pickle.loads(base64.b64decode(TOKEN_DATA))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        
        # Decode Client Secrets sementara
        with open("client_secrets.json", "wb") as f:
            f.write(base64.b64decode(CLIENT_SECRETS))
            
        drive = build('drive', 'v3', credentials=creds)
        youtube = build('youtube', 'v3', credentials=creds)
        return drive, youtube
    except Exception as e:
        print(f"ERROR AUTENTIKASI: {e}")
        return None, None

def image_to_video(img_path, out_path):
    """Mengubah gambar jadi video 8 detik"""
    print(f"[*] Mengubah gambar {img_path} menjadi video...")
    try:
        clip = ImageClip(img_path)
        # Logika Smart Crop (Vertical 9:16)
        if clip.w > clip.h:
            # Jika Landscape -> Resize tinggi 1920 -> Crop tengah
            clip = clip.resize(height=1920)
            clip = clip.crop(x1=clip.w/2 - 540, width=1080, height=1920)
        else:
            # Jika Portrait -> Resize lebar 1080 -> Posisikan di tengah layar hitam
            clip = clip.resize(width=1080)
            clip = clip.on_color(size=(1080, 1920), color=(0,0,0), pos='center')
        
        # Render tanpa audio
        clip.set_duration(8).write_videofile(out_path, fps=24, codec='libx264', audio=False, verbose=False, logger=None)
        return True
    except Exception as e:
        print(f"[!] Gagal konversi gambar: {e}")
        return False

def get_metadata(filename, type):
    """Minta AI membuat judul & deskripsi"""
    context = "Video" if type == 'video' else "Gambar Quotes/Meme"
    prompt = f"""
    Buatkan metadata YouTube Shorts viral (Bahasa Indonesia) untuk file {context} bernama: '{filename}'.
    JANGAN pakai format markdown. Jawab HANYA JSON valid:
    {{
        "title": "Judul Menarik (Max 90 char)",
        "description": "Deskripsi singkat + hashtag #shorts",
        "tags": ["tag1", "tag2"]
    }}
    """
    try:
        res = model.generate_content(prompt)
        text = res.text.replace('```json','').replace('```','').strip()
        return json.loads(text)
    except:
        return {"title": filename, "description": "#shorts #viral", "tags": []}

def main():
    print("=== MULAI ROBOT AUTO SHORTS ===")
    drive, youtube = get_services()
    if not drive: return

    # 1. Cari File Terlama (Antrean Pertama)
    # mimeType video/mp4 ATAU image/jpeg ATAU image/png
    q = f"'{SOURCE_ID}' in parents and (mimeType='video/mp4' or mimeType='image/jpeg' or mimeType='image/png') and trashed=false"
    
    # orderBy='createdTime' memastikan kita ambil yang paling lama (First In First Out)
    results = drive.files().list(q=q, orderBy="createdTime", pageSize=1, fields="files(id, name, mimeType)").execute()
    files = results.get('files', [])

    if not files:
        print("[-] Tidak ada file baru di folder Drive.")
        return
    
    f = files[0]
    print(f"[*] Memproses file: {f['name']} ({f['mimeType']})")
    
    # 2. Download File
    request = drive.files().get_media(fileId=f['id'])
    input_filename = "input_raw.jpg" if "image" in f['mimeType'] else "input_raw.mp4"
    
    with io.FileIO(input_filename, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
    
    # 3. Proses (Convert jika Gambar)
    final_file = "ready_to_upload.mp4"
    is_image = "image" in f['mimeType']
    
    if is_image:
        if not image_to_video(input_filename, final_file): return
    else:
        # Jika video, ganti nama saja
        os.rename(input_filename, final_file)

    # 4. Generate Metadata AI
    meta = get_metadata(f['name'], "image" if is_image else "video")
    print(f"[*] Judul AI: {meta['title']}")

    # 5. Upload ke YouTube
    body = {
        'snippet': {
            'title': meta['title'], 
            'description': meta['description'], 
            'tags': meta.get('tags'), 
            'categoryId': '22'
        }, 
        'status': {
            'privacyStatus': PRIVACY,
            'selfDeclaredMadeForKids': False
        }
    }
    
    print("[*] Sedang mengupload ke YouTube...")
    youtube.videos().insert(
        part='snippet,status', 
        body=body, 
        media_body=MediaFileUpload(final_file, chunksize=-1, resumable=True)
    ).execute()
    
    # 6. Pindahkan ke Arsip (PENTING AGAR TIDAK DOUBLE)
    drive.files().update(fileId=f['id'], addParents=ARCHIVE_ID, removeParents=SOURCE_ID).execute()
    print("[+] SUKSES! Video terupload dan dipindahkan ke arsip.")
    
    # Bersihkan file sampah
    if os.path.exists("client_secrets.json"): os.remove("client_secrets.json")

if __name__ == "__main__":
    main()
