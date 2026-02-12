import os
import base64
import pickle
import json
from datetime import datetime
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# --- KONFIGURASI ---
TOKEN_DATA = os.environ.get('TOKEN_DATA')

def get_services():
    """Autentikasi menggunakan token dari GitHub Secrets."""
    try:
        creds = pickle.loads(base64.b64decode(TOKEN_DATA))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('youtube', 'v3', credentials=creds)
    except Exception as e:
        print(f"⛔ Masalah Autentikasi: {e}")
        return None

def main():
    print("=== MEMULAI PENYUSUNAN LAPORAN PERFORMA ===")
    youtube = get_services()
    if not youtube: return

    # 1. Ambil Data Channel Utama
    ch_res = youtube.channels().list(part='statistics,snippet', mine=True).execute()
    channel = ch_res['items'][0]
    ch_stats = channel['statistics']
    ch_name = channel['snippet']['title']

    # 2. Ambil 20 Video Terbaru
    search_res = youtube.search().list(
        part='snippet',
        forMine=True,
        type='video',
        maxResults=20,
        order='date'
    ).execute()

    video_ids = [item['id']['videoId'] for item in search_res.get('items', [])]
    
    video_details = []
    total_v_views = 0
    total_v_likes = 0

    if video_ids:
        stats_res = youtube.videos().list(
            part='statistics,snippet,contentDetails',
            id=','.join(video_ids)
        ).execute()
        
        for v in stats_res.get('items', []):
            views = int(v['statistics'].get('viewCount', 0))
            likes = int(v['statistics'].get('likeCount', 0))
            total_v_views += views
            total_v_likes += likes
            
            video_details.append({
                'title': v['snippet']['title'],
                'views': views,
                'likes': likes,
                'comments': v['statistics'].get('commentCount', '0'),
                'date': v['snippet']['publishedAt'][:10]
            })

    # 3. Hitung Rata-rata
    avg_views = total_v_views / len(video_details) if video_details else 0
    avg_likes = total_v_likes / len(video_details) if video_details else 0

    # 4. Susun Laporan Markdown
    now = datetime.now().strftime("%d %B %Y - %H:%M")
    
    report = f"""# 📊 Laporan Performa YouTube: {ch_name}
> Terakhir diperbarui pada: **{now} WITA**

## 📈 Ringkasan Channel
* **Total Subscriber:** {int(ch_stats['subscriberCount']):,}
* **Total Seluruh Tayangan:** {int(ch_stats['viewCount']):,}
* **Total Video Diunggah:** {ch_stats['videoCount']}

## ⚡ Analisis 20 Video Terakhir
* **Rata-rata Penonton per Video:** {int(avg_views):,} views
* **Rata-rata Like per Video:** {int(avg_likes):,} likes
* **Tingkat Interaksi:** {((total_v_likes + total_v_views*0.01) / total_v_views * 100 if total_v_views > 0 else 0):.2f}%

## 🎥 Detail Video Terbaru
| Tanggal | Judul Video | 👀 Views | 👍 Likes | 💬 Komentar |
| :--- | :--- | :--- | :--- | :--- |
"""
    for v in video_details:
        report += f"| {v['date']} | {v['title']} | {v['views']:,} | {v['likes']:,} | {v['comments']} |\n"

    report += """
---
*Catatan: Data Jam Tayang (Watch Time) secara detail memerlukan akses API Analytics yang lebih kompleks. Laporan ini menggunakan estimasi berdasarkan jumlah tayangan video terbaru.*

**Robot Laporan Harian - Status: AKTIF ✅**
"""

    # Simpan laporan
    with open("LAPORAN_YOUTUBE.md", "w", encoding="utf-8") as f:
        f.write(report)
    
    print("[✅] Laporan berhasil dibuat di LAPORAN_YOUTUBE.md")

if __name__ == "__main__":
    main()
