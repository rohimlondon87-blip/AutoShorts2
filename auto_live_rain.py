import os
import base64
import pickle
import subprocess
import random
import io
import json
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth.transport.requests import Request


# ==============================
# KONFIGURASI ENVIRONMENT
# ==============================

TOKEN_B64 = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')
STREAM_KEY = os.environ.get('YOUTUBE_STREAM_KEY')

LIVE_DURATION_SEC = random.randint(2700, 3600)
DELAY_MENIT = random.randint(0, 1)


# ==============================
# AUTH GOOGLE DRIVE
# ==============================

def get_services():

    try:

        if not TOKEN_B64:
            print("⛔ TOKEN_DATA tidak ditemukan")
            return None

        t_str = TOKEN_B64.strip().replace('\xa0', '').replace(" ", "")

        missing_padding = len(t_str) % 4
        if missing_padding:
            t_str += '=' * (4 - missing_padding)

        creds = pickle.loads(base64.b64decode(t_str))

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

        service = build('drive', 'v3', credentials=creds)

        print("✅ Login Google Drive berhasil")

        return service

    except Exception as e:

        print("⛔ Login gagal:", e)

        return None


# ==============================
# DOWNLOAD FILE DRIVE
# ==============================

def download_file(service, file_id, output_name):

    try:

        request = service.files().get_media(fileId=file_id)

        with io.FileIO(output_name, 'wb') as fh:

            downloader = MediaIoBaseDownload(fh, request)

            done = False

            while not done:

                _, done = downloader.next_chunk()

        return True

    except Exception as e:

        print("Download error:", e)

        return False


# ==============================
# DETEKSI ROTASI VIDEO
# ==============================

def get_video_rotation(path):

    try:

        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries',
            'stream_tags=rotate:stream_side_data=rotation',
            '-of', 'json',
            path
        ]

        result = subprocess.check_output(cmd).decode('utf-8')

        data = json.loads(result)

        stream = data.get("streams", [{}])[0]

        tags = stream.get("tags", {})

        if "rotate" in tags:
            return int(float(tags["rotate"]))

        side_data = stream.get("side_data_list", [])

        for item in side_data:

            if "rotation" in item:
                return int(float(item["rotation"]))

        return 0

    except Exception as e:

        print("Rotation detect error:", e)

        return 0


# ==============================
# FIX VIDEO AGAR TIDAK TERBALIK
# ==============================

def standardize_video(input_path, output_path):

    rotation = get_video_rotation(input_path)

    print(f"    [*] Rotasi terdeteksi: {rotation}")

    filters = []

    # perbaiki rotasi dengan toleransi
    if 45 <= rotation <= 135:
        filters.append("transpose=1")

    elif -135 <= rotation <= -45 or 225 <= rotation <= 315:
        filters.append("transpose=2")

    elif rotation >= 135 or rotation <= -135:
        filters.append("hflip,vflip")

    # paksa landscape 16:9
    filters.append(
        "scale=1280:720:force_original_aspect_ratio=increase,"
        "cr
