"""IP başına favoriler ve çalma listeleri (kütüphane) yönetimi."""
import os
import json

import config
from youtube import is_valid_youtube_url

LIBRARY_FILE = config.LIBRARY_FILE


def load_library():
    if os.path.exists(LIBRARY_FILE):
        try:
            with open(LIBRARY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_library(lib):
    try:
        with open(LIBRARY_FILE, 'w', encoding='utf-8') as f:
            json.dump(lib, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Kutuphane kaydetme hatasi: {e}")


user_library = load_library()


def get_user_lib(ip):
    if ip not in user_library:
        user_library[ip] = {"favorites": [], "playlists": {}}
    if "favorites" not in user_library[ip]:
        user_library[ip]["favorites"] = []
    if "playlists" not in user_library[ip]:
        user_library[ip]["playlists"] = {}
    return user_library[ip]


def clean_song_payload(data):
    """Gelen şarkı verisini doğrular ve güvenli hale getirir."""
    song_id = (data.get('id') or '').strip()
    url = (data.get('url') or '').strip()
    if not song_id or not is_valid_youtube_url(url):
        return None
    return {
        "id": song_id,
        "title": (data.get('title') or 'Bilinmeyen Şarkı')[:200],
        "url": url,
        "thumbnail": (data.get('thumbnail') or '')[:500]
    }
