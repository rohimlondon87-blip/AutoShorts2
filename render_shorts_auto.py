import os
import base64
import pickle
import random
import io
import subprocess
import textwrap
import time
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.auth.transport.requests import Request

# --- KONFIGURASI MICRO WILD ---
TOKEN_DATA = os.environ.get('TOKEN_DATA')
SOURCE_ID = os.environ.get('SOURCE_LIVE_ID')      
MUSIC_ID = os.environ.get('MUSIC_FOLDER_ID')   
UPLOTAN_ID = os.environ.get('UPLOTAN_FOLDER_ID') 
QUOTES_ID = os.environ.get('QUOTES_FILE_ID') 

MAX_DURATION = 35 
BATCH_LIMIT = 5 

def get_drive_service():
    try:
        if not TOKEN_DATA: return None
        t_str = TOKEN_DATA.strip().replace('\xa0', '').replace(" ", "")
        pad = len(t_str) % 4
        if pad: t_str += '=' * (4 - pad)
        creds = pickle.loads(base64.b64decode(t_str))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Auth Error: {e}")
        return None

def get_video_rotation(path):
    try:
        cmd = ['ffprobe', '-loglevel', 'error', '-select_streams', 'v:0', '-show_entries', 'stream_tags=rotate', '-of', 'json', path]
        result = subprocess.check_output(cmd).decode('utf-8')
        tags = json.loads(result).get('streams', [{}])[0].get('tags', {})
        return int(tags.get('rotate', 0))
    except: return 0

def render_shorts(v_in, a_in, v_out, text, v_start, font_p):
    wrapped = "\n".join(textwrap.wrap(text, width=20))
    safe_txt = wrapped.replace("'", "").replace(":", "\\:")
    rotation = get_video_rotation(v_in)
    
    rot_filter = ""
    if rotation == 90: rot_filter = "transpose=1,"
    elif rotation == 180: rot_filter = "hflip,vflip,"
    elif rotation == 270: rot_filter = "transpose=2,"

    v_filter = (
        f"{rot_filter}scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=text='{safe_txt}':fontcolor=white:fontsize=85:fontfile={font_p}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.6:boxborderw=40:line_spacing=20"
    )

    cmd = [
        'ffmpeg', '-y', '-ss', str(v_start), '-t', str(MAX_DURATION), '-i', v_in,
        '-stream_loop', '-1', '-i', a_in,
        '-filter_complex', f'[0:v]{v_filter}[vout]; [0:a]volume=0.3[a1]; [1:a]volume=1.2[a2]; [a1][a2]amix=inputs=2:duration=first[aout]',
        '-map', '[vout]', '-map', '[aout]', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', v_out 
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0

def main():
    print("=== MICRO WILD: ROBOT RENDER SHORTS START ===")
    service = get_drive_service()
    if not service: return

    v_res = service.files().list(q=f"'{SOURCE_ID}' in parents and mimeType contains 'video'").execute().get('files', [])
    m_res = service.files().list(q=f"'{MUSIC_ID}' in parents and mimeType contains 'audio'").execute().get('files', [])
    
    if not v_res: return
    random.shuffle(v_res)
    
    for i in range(min(BATCH_LIMIT, len(v_res))):
        f_vid = v_res[i]
        f_mus = random.choice(m_res)
        out_name = f"MICRO_WILD_SHORTS_{int(time.time())}_{i}.mp4"
        
        with open("temp_v.mp4", "wb") as f: f.write(service.files().get_media(fileId=f_vid['id']).execute())
        with open("temp_a.mp3", "wb") as f: f.write(service.files().get_media(fileId=f_mus['id']).execute())
        
        if render_shorts("temp_v.mp4", "temp_a.mp3", out_name, "MICRO WILD EXPLORATION", 0, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            media = MediaFileUpload(out_name, mimetype='video/mp4')
            service.files().create(body={'name': out_name, 'parents': [UPLOTAN_ID]}, media_body=media).execute()
            print(f"✅ Success Upload to Drive: {out_name}")
        
        for f in ["temp_v.mp4", "temp_a.mp3", out_name]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
