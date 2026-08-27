"""YouTube ile ilgili işlemler: URL doğrulama, arama, mp3/mp4 indirme."""
import re
import urllib.parse
import requests
import yt_dlp

import config


def is_valid_youtube_url(url):
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    allowed_domains = ['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be']
    return parsed.netloc in allowed_domains


def search_youtube(clean_query):
    """Invidious node'larını dener, hepsi başarısız olursa yt-dlp arama sonucuna düşer.
    Sonuç listesini (list) veya bulunamazsa None döner."""
    invidious_nodes = [
        f"https://inv.tux.pizza/api/v1/search?q={clean_query}&type=video",
        f"https://vid.puffyan.us/api/v1/search?q={clean_query}&type=video"
    ]

    for node in invidious_nodes:
        try:
            res = requests.get(node, timeout=3)
            if res.status_code == 200:
                data = res.json()
                results = []
                for item in data[:10]:
                    results.append({
                        'id': item.get('videoId'),
                        'title': item.get('title'),
                        'url': f"https://www.youtube.com/watch?v={item.get('videoId')}",
                        'thumbnail': f"https://i.ytimg.com/vi/{item.get('videoId')}/hqdefault.jpg"
                    })
                return results
        except Exception:
            continue

    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'extract_flat': True,
        'extractor_args': {'youtube': {'player_client': ['android']}}
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch10:{clean_query}", download=False)
        results = []
        for entry in info.get('entries', []):
            if entry:
                results.append({
                    'id': entry.get('id'),
                    'title': entry.get('title'),
                    'url': f"https://www.youtube.com/watch?v={entry.get('id')}",
                    'thumbnail': f"https://i.ytimg.com/vi/{entry.get('id')}/hqdefault.jpg"
                })
        return results


def process_youtube_audio(url, folder=None, fmt='mp3', sample_rate=None, bit_depth=None):
    """MP3 (kayıplı, hızlı) veya WAV/FLAC (kayıpsız) olarak indirir.

    Not: Kaynak her durumda YouTube'un kendi (kayıplı) ses akışıdır. WAV/FLAC
    seçimi orijinal kaydı geri getirmez; sadece MP3'e ek bir kayıplı sıkıştırma
    turu eklenmesini önler ve dosyayı istenen örnekleme hızı/bit derinliğinde
    teslim eder.
    """
    folder = folder or config.DOWNLOAD_FOLDER
    fmt = fmt if fmt in ('mp3', 'wav', 'flac') else 'mp3'
    out_template = f"{folder}/%(id)s.%(ext)s"

    postprocessor = {'key': 'FFmpegExtractAudio', 'preferredcodec': fmt}
    if fmt == 'mp3':
        postprocessor['preferredquality'] = '192'

    extra_args = []
    if sample_rate in (44100, 48000, 96000):
        extra_args += ['-ar', str(sample_rate)]
    if fmt == 'wav' and bit_depth in (16, 24, 32):
        codec = {16: 'pcm_s16le', 24: 'pcm_s24le', 32: 'pcm_f32le'}[bit_depth]
        extra_args += ['-acodec', codec]
    elif fmt == 'flac' and bit_depth in (24, 32):
        extra_args += ['-sample_fmt', 's32']

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': out_template,
        'postprocessors': [postprocessor],
        'quiet': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'ios']}}
    }
    if extra_args:
        ydl_opts['postprocessor_args'] = {'ffmpeg': extra_args}

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = f"{folder}/{info['id']}.{fmt}"
        return file_path, info.get('title', 'muzik')


def process_youtube_mp3(url, folder=None):
    return process_youtube_audio(url, folder, fmt='mp3')


def process_youtube_mp4(url):
    out_template = f"{config.DOWNLOAD_FOLDER}/%(id)s_video.%(ext)s"
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': out_template,
        'quiet': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'ios']}}
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = f"{config.DOWNLOAD_FOLDER}/{info['id']}_video.mp4"
        return file_path, info.get('title', 'video')
