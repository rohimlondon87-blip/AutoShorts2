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


# ============================================
# ENVIRONMENT VARIABLES
# ============================================

TOKEN_B64 = os.environ.get("TOKEN_DATA")
SOURCE_ID = os.environ.get("SOURCE_LIVE_ID")
MUSIC_ID = os.environ.get("MUSIC_FOLDER_ID")
STREAM_KEY = os.environ.get("YOUTUBE_STREAM_KEY")

LIVE_DURATION_SEC = random.randint(2700, 3600)
DELAY_MENIT = random.randint(0, 1)


# ============================================
# GOOGLE DRIVE LOGIN
# ============================================

def get_services():

    try:

        if not TOKEN_B64:
            print("⛔ TOKEN_DATA tidak ditemukan")
            return None

        t_str = TOKEN_B64.strip().replace("\xa0", "").replace(" ", "")

        missing_padding = len(t_str) % 4

        if missing_padding:
            t_str += "=" * (4 - missing_padding)

        creds = pickle.loads(base64.b64decode(t_str))

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

        service = build("drive", "v3", credentials=creds)

        print("✅ Login Google Drive OK")

        return service

    except Exception as e:

        print("⛔ Login gagal:", e)

        return None


# ============================================
# DOWNLOAD FILE
# ============================================

def download_file(service, file_id, output_name):

    try:

        request = service.files().get_media(fileId=file_id)

        with io.FileIO(output_name, "wb") as fh:

            downloader = MediaIoBaseDownload(fh, request)

            done = False

            while not done:
                _, done = downloader.next_chunk()

        return True

    except Exception as e:

        print("Download error:", e)

        return False


# ============================================
# DETECT ROTATION
# ============================================

def get_video_rotation(path):

    try:

        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries",
            "stream_tags=rotate:stream_side_data=rotation",
            "-of", "json",
            path
        ]

        result = subprocess.check_output(cmd).decode("utf-8")

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


# ============================================
# FIX VIDEO ORIENTATION
# ============================================

def standardize_video(input_path, output_path):

    rotation = get_video_rotation(input_path)

    print(f"Fix rotation: {rotation}")

    filters = []

    if 45 <= rotation <= 135:
        filters.append("transpose=1")

    elif -135 <= rotation <= -45 or 225 <= rotation <= 315:
        filters.append("transpose=2")

    elif rotation >= 135 or rotation <= -135:
        filters.append("hflip,vflip")

    filters.append(
        "scale=1280:720:force_original_aspect_ratio=increase,"
        "crop=1280:720,"
        "setsar=1"
    )

    vf = ",".join(filters)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-vf", vf,
        "-metadata:s:v:0", "rotate=0",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-an",
        output_path
    ]

    result = subprocess.run(cmd)

    return result.returncode == 0


# ============================================
# MAIN FUNCTION
# ============================================

def main():

    print("=================================")
    print(" YOUTUBE AUTO LIVE START ")
    print("=================================")

    if DELAY_MENIT > 0:

        print(f"Delay {DELAY_MENIT} menit")

        time.sleep(DELAY_MENIT * 60)

    drive = get_services()

    if not drive:
        return

    try:

        # ============================================
        # GET VIDEO FILES
        # ============================================

        v_res = drive.files().list(
            q=f"'{SOURCE_ID}' in parents and mimeType contains 'video' and trashed=false"
        ).execute()

        v_files = v_res.get("files", [])

        if not v_files:
            print("⛔ Video kosong")
            return

        random.shuffle(v_files)

        v_files = v_files[:8]

        v_list = ""

        for i, file in enumerate(v_files):

            raw = f"raw_{i}.mp4"
            fixed = f"fixed_{i}.mp4"

            print("Download:", file["name"])

            if download_file(drive, file["id"], raw):

                ok = standardize_video(raw, fixed)

                if ok:
                    v_list += f"file '{fixed}'\n"

                os.remove(raw)

        with open("v_list.txt", "w") as f:
            f.write(v_list)


        # ============================================
        # GET AUDIO FILES
        # ============================================

        m_res = drive.files().list(
            q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio' and trashed=false"
        ).execute()

        m_files = m_res.get("files", [])

        if not m_files:
            print("⛔ Audio kosong")
            return

        random.shuffle(m_files)

        m_list = ""

        for i, file in enumerate(m_files[:15]):

            name = f"mus_{i}.mp3"

            if download_file(drive, file["id"], name):

                m_list += f"file '{name}'\n"

        with open("m_list.txt", "w") as f:
            f.write(m_list)


        # ============================================
        # START STREAM
        # ============================================

        rtmp = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"

        print("🚀 LIVE START")

        cmd = [

            "ffmpeg",

            "-y",

            "-f", "concat",
            "-safe", "0",
            "-stream_loop", "-1",
            "-i", "v_list.txt",

            "-f", "concat",
            "-safe", "0",
            "-stream_loop", "-1",
            "-i", "m_list.txt",

            "-t", str(LIVE_DURATION_SEC),

            "-map", "0:v",
            "-map", "1:a",

            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-b:v", "2500k",

            "-r", "30",
            "-g", "60",
            "-keyint_min", "60",

            "-c:a", "aac",
            "-ar", "44100",
            "-b:a", "128k",

            "-pix_fmt", "yuv420p",

            "-f", "flv",

            rtmp

        ]

        process = subprocess.Popen(cmd)

        process.wait()

    except Exception as e:

        print("ERROR:", e)

    finally:

        print("Cleanup")

        for f in os.listdir():

            if f.startswith("fixed_") or f.startswith("mus_") or f.endswith(".txt"):

                try:
                    os.remove(f)
                except:
                    pass


# ============================================
# RUN
# ============================================

if __name__ == "__main__":
    main()
