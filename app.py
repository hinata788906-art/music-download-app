from flask import Flask, request, jsonify, send_file, render_template_string, redirect, url_for, session, abort
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
import yt_dlp
import requests
import os
import re
import json
import secrets
import urllib.parse
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.urandom(32)

# Termux her çalıştığında tamamen rastgele ve tahmin edilemez bir admin key üretir
ADMIN_SECRET_KEY = secrets.token_hex(16)

CORS(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

BASE_STORAGE_DIR = os.path.expanduser('~/storage')
DEFAULT_DOWNLOAD_FOLDER = os.path.join(BASE_STORAGE_DIR, 'shared', 'MusicDownloads')
STATS_FILE = os.path.expanduser('~/storage/shared/MusicDownloads/stats.json')
CONFIG_FILE = os.path.expanduser('~/.hmusic_config.json')

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ayar kaydetme hatasi: {e}")

app_config = load_config()
DOWNLOAD_FOLDER = app_config.get('download_folder', DEFAULT_DOWNLOAD_FOLDER)
CACHE_FOLDER = os.path.join(os.path.expanduser('~'), '.hmusic_cache')

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
if not os.path.exists(CACHE_FOLDER):
    os.makedirs(CACHE_FOLDER, exist_ok=True)

def get_storage_options():
    """Termux ~/storage altındaki dahili depolamayı ve takılı SD kart(lar)ı listeler."""
    options = []
    try:
        if os.path.isdir(BASE_STORAGE_DIR):
            for entry in sorted(os.listdir(BASE_STORAGE_DIR)):
                full = os.path.join(BASE_STORAGE_DIR, entry)
                if not os.path.isdir(full):
                    continue
                if entry == 'shared':
                    label = 'Dahili Depolama'
                elif entry.startswith('external'):
                    suffix = entry.replace('external-', '').replace('external', '').strip()
                    label = 'SD Kart' + (f' {suffix}' if suffix else '')
                else:
                    continue
                options.append({
                    'key': entry,
                    'label': label,
                    'path': os.path.join(full, 'MusicDownloads')
                })
    except Exception:
        pass
    if not options:
        options.append({'key': 'shared', 'label': 'Dahili Depolama', 'path': DEFAULT_DOWNLOAD_FOLDER})
    return options

def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_stats(stats):
    try:
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Stats kaydetme hatasi: {e}")

user_stats = load_stats()

LIBRARY_FILE = os.path.expanduser('~/storage/shared/MusicDownloads/library.json')

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

def track_user_action(ip, action_type):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if ip not in user_stats:
        user_stats[ip] = {"plays": 0, "mp3": 0, "mp4": 0, "last_active": now, "banned": False}
    user_stats[ip]["last_active"] = now
    if action_type in user_stats[ip]:
        user_stats[ip][action_type] += 1
    save_stats(user_stats)

@app.before_request
def check_ip_ban():
    ip = request.remote_addr
    if request.path.startswith('/admin'):
        return
    if ip in user_stats and user_stats[ip].get("banned", False):
        return jsonify({"error": "Erişiminiz engellenmiştir."}), 403

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

def is_valid_youtube_url(url):
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    allowed_domains = ['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be']
    return parsed.netloc in allowed_domains

USER_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HMusic</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0b0e14;
            --bg-alt: #12161f;
            --bg-card: #171c26;
            --bg-card-alt: #202738;
            --border: #232a3b;
            --border-alt: #2a3447;
            --border-soft: #1c2230;
            --border-active-bg: #1a2130;
            --text: #f3f4f6;
            --text-on-accent: #fff;
            --text-muted: #6b7280;
            --text-muted2: #9ca3af;
            --text-faint: #d1d5db;
            --accent: #10b981;
            --accent-soft: rgba(16, 185, 129, 0.15);
            --danger: #ef4444;
            --danger-soft: rgba(239, 68, 68, 0.1);
        }
        [data-theme="light"] {
            --bg: #f2f3f7;
            --bg-alt: #ffffff;
            --bg-card: #ffffff;
            --bg-card-alt: #eceef2;
            --border: #e1e4ea;
            --border-alt: #d5d9e0;
            --border-soft: #ececf0;
            --border-active-bg: #eef0f4;
            --text: #171a21;
            --text-on-accent: #fff;
            --text-muted: #6b7280;
            --text-muted2: #545b68;
            --text-faint: #3a3f4a;
            --accent: #10b981;
            --accent-soft: rgba(16, 185, 129, 0.12);
            --danger: #ef4444;
            --danger-soft: rgba(239, 68, 68, 0.08);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
        body { background-color: var(--bg); color: var(--text); padding: 20px 15px 140px 15px; transition: background-color 0.2s ease, color 0.2s ease; }
        .header { text-align: center; margin-bottom: 25px; position: relative; }
        .header h1 { font-size: 24px; font-weight: 700; color: var(--accent); letter-spacing: -0.5px; }
        .header p { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

        .settings-btn { position: fixed; top: 18px; left: 15px; width: 38px; height: 38px; border-radius: 12px; background: var(--bg-card); border: 1px solid var(--border); color: var(--text-muted2); display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 30; transition: 0.2s; }
        .settings-btn:active { transform: scale(0.94); color: var(--accent); }
        .settings-btn svg { width: 20px; height: 20px; fill: currentColor; }

        .settings-panel { position: fixed; top: 62px; left: 15px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 8px; z-index: 30; display: none; flex-direction: column; gap: 4px; box-shadow: 0 10px 30px rgba(0,0,0,0.4); min-width: 220px; max-height: 70vh; overflow-y: auto; }
        .settings-panel.active { display: flex; }
        .settings-item { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 10px; cursor: pointer; color: var(--text); font-size: 13px; font-weight: 500; }
        .settings-item:active { background: var(--bg-card-alt); }
        .settings-item svg { width: 18px; height: 18px; fill: var(--accent); flex-shrink: 0; }
        .settings-item.lang-row { cursor: default; justify-content: space-between; }
        .settings-item.lang-row .lang-row-left { display: flex; align-items: center; gap: 10px; }
        .lang-opt-btn { border: 1px solid var(--border); background: var(--bg-alt); color: var(--text-muted2); font-size: 11px; font-weight: 700; padding: 5px 9px; border-radius: 8px; cursor: pointer; }
        .lang-opt-btn.active { background: rgba(16,185,129,0.15); border-color: var(--accent); color: var(--accent); }
        .settings-divider { height: 1px; background: var(--border); margin: 4px 2px; }
        .theme-opt-btn { border: 1px solid var(--border); background: var(--bg-alt); color: var(--text-muted2); font-size: 10px; font-weight: 700; padding: 5px 8px; border-radius: 8px; cursor: pointer; }
        .theme-opt-btn.active { background: rgba(16,185,129,0.15); border-color: var(--accent); color: var(--accent); }
        .crossfade-modal, .cache-modal { background: var(--bg-alt); border: 1px solid var(--border); border-radius: 20px 20px 0 0; width: 100%; max-width: 480px; padding: 20px 20px 28px 20px; transform: translateY(24px); transition: transform 0.28s ease; }
        .overlay-bg.active .crossfade-modal, .overlay-bg.active .cache-modal { transform: translateY(0); }
        .crossfade-value-row { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
        .crossfade-value-row span:last-child { color: var(--accent); font-weight: 700; font-size: 15px; }
        .cache-size-box { background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 16px; text-align: center; margin: 14px 0; }
        .cache-size-box .cache-size-num { font-size: 22px; font-weight: 700; color: var(--accent); }
        .cache-size-box .cache-size-label { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
        .clear-cache-btn { width: 100%; background: rgba(239, 68, 68, 0.1); border: 1px solid var(--danger); color: var(--danger); padding: 12px; border-radius: 12px; font-size: 13px; font-weight: 700; cursor: pointer; }
        .canvas-bg { position: fixed; inset: 0; z-index: -1; overflow: hidden; opacity: 0; transition: opacity 0.6s ease; pointer-events: none; }
        .canvas-bg.active { opacity: 1; }
        .canvas-bg img { width: 100%; height: 100%; object-fit: cover; filter: blur(38px) brightness(0.55) saturate(1.4); transform: scale(1.3); animation: canvasDrift 14s ease-in-out infinite alternate; }
        @keyframes canvasDrift { from { transform: scale(1.3) rotate(0deg); } to { transform: scale(1.45) rotate(2deg); } }

        .overlay-bg { position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 40; display: flex; align-items: flex-end; justify-content: center; opacity: 0; visibility: hidden; transition: opacity 0.25s ease, visibility 0.25s ease; }
        .overlay-bg.active { opacity: 1; visibility: visible; }
        .eq-modal { background: var(--bg-alt); border: 1px solid var(--border); border-radius: 20px 20px 0 0; width: 100%; max-width: 480px; padding: 20px 20px 28px 20px; transform: translateY(24px); transition: transform 0.28s ease; }
        .overlay-bg.active .eq-modal { transform: translateY(0); }
        .eq-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
        .eq-header h2 { font-size: 16px; font-weight: 700; color: var(--text); }
        .eq-close-btn { width: 30px; height: 30px; border-radius: 8px; border: none; background: var(--bg-card-alt); color: var(--text-muted2); font-size: 15px; cursor: pointer; }
        .eq-sub { font-size: 11px; color: var(--text-muted); margin-bottom: 18px; }
        .eq-toggle-row { display: flex; align-items: center; justify-content: space-between; background: var(--bg-card); padding: 12px 14px; border-radius: 12px; margin-bottom: 18px; border: 1px solid var(--border); }
        .eq-toggle-row span { font-size: 13px; font-weight: 600; color: var(--text); }
        .switch { position: relative; width: 42px; height: 24px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .switch-slider { position: absolute; inset: 0; background: var(--border-alt); border-radius: 24px; cursor: pointer; transition: 0.2s; }
        .switch-slider:before { content: ""; position: absolute; width: 18px; height: 18px; left: 3px; top: 3px; background: #fff; border-radius: 50%; transition: 0.2s; }
        .switch input:checked + .switch-slider { background: var(--accent); }
        .switch input:checked + .switch-slider:before { transform: translateX(18px); }
        .eq-bands { display: flex; justify-content: space-between; gap: 6px; height: 160px; margin-bottom: 20px; }
        .eq-band { display: flex; flex-direction: column; align-items: center; gap: 8px; flex: 1; }
        .eq-band-slider { -webkit-appearance: slider-vertical; writing-mode: vertical-lr; direction: rtl; width: 6px; height: 110px; background: var(--border-alt); border-radius: 4px; outline: none; accent-color: var(--accent); }
        .eq-band-freq { font-size: 10px; color: var(--text-muted); }
        .eq-band-val { font-size: 10px; color: var(--accent); font-weight: 600; }
        .eq-presets { display: flex; gap: 8px; flex-wrap: wrap; }
        .eq-preset-btn { flex: 1; background: var(--bg-card); border: 1px solid var(--border); color: var(--text-faint); padding: 9px 6px; border-radius: 10px; font-size: 11px; font-weight: 600; cursor: pointer; }
        .eq-preset-btn.active { background: rgba(16,185,129,0.15); border-color: var(--accent); color: var(--accent); }
        .player-controls-right { display: flex; align-items: center; gap: 8px; }
        .player-next-btn { width: 34px; height: 34px; border-radius: 50%; background: var(--bg-card-alt); border: none; color: var(--text); display: flex; align-items: center; justify-content: center; cursor: pointer; }
        .player-next-btn svg { width: 16px; height: 16px; fill: currentColor; }

        .storage-modal { background: var(--bg-alt); border: 1px solid var(--border); border-radius: 20px 20px 0 0; width: 100%; max-width: 480px; padding: 20px 20px 28px 20px; transform: translateY(24px); transition: transform 0.28s ease; }
        .overlay-bg.active .storage-modal { transform: translateY(0); }
        .storage-list { display: flex; flex-direction: column; gap: 10px; margin-top: 16px; }
        .storage-item { display: flex; align-items: center; gap: 12px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 12px 14px; cursor: pointer; }
        .storage-item.active { border-color: var(--accent); background: rgba(16, 185, 129, 0.08); }
        .storage-item-icon { width: 36px; height: 36px; border-radius: 10px; background: rgba(16, 185, 129, 0.12); color: var(--accent); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .storage-item-icon svg { width: 18px; height: 18px; fill: currentColor; }
        .storage-item-info { flex: 1; overflow: hidden; }
        .storage-item-label { font-size: 13px; font-weight: 600; color: var(--text); }
        .storage-item-path { font-size: 10px; color: var(--text-muted); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .storage-item-check { width: 18px; height: 18px; border-radius: 50%; border: 2px solid var(--border-alt); flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
        .storage-item.active .storage-item-check { border-color: var(--accent); background: var(--accent); }
        .storage-item-check svg { width: 11px; height: 11px; fill: var(--bg); display: none; }
        .storage-item.active .storage-item-check svg { display: block; }
        .storage-status { font-size: 11px; color: var(--accent); margin-top: 12px; min-height: 14px; }
        .search-box { display: flex; gap: 10px; background: var(--bg-card); padding: 6px; border-radius: 14px; border: 1px solid var(--border); }
        .search-box input { flex: 1; border: none; background: transparent; padding: 12px 16px; color: #fff; font-size: 15px; outline: none; }
        .search-box button { background: var(--accent); border: none; color: #fff; padding: 0 20px; border-radius: 10px; font-weight: 600; cursor: pointer; }
        .results-list { display: flex; flex-direction: column; gap: 12px; margin-top: 20px; }
        .card { display: flex; align-items: center; background: var(--bg-card); padding: 10px 14px; border-radius: 14px; gap: 12px; border: 1px solid var(--bg-card-alt); opacity: 0; transform: translateY(10px); animation: cardIn 0.35s ease forwards; }
        .card img { width: 52px; height: 52px; border-radius: 10px; object-fit: cover; }
        .card-info { flex: 1; overflow: hidden; }
        .card-title { font-size: 14px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .card-artist { font-size: 12px; color: var(--text-muted2); margin-top: 2px; }
        .action-btns { display: flex; gap: 6px; }
        .icon-btn { width: 38px; height: 38px; border-radius: 10px; border: none; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: transform 0.15s ease; }
        .icon-btn:active { transform: scale(0.9); }
        .btn-play { background: rgba(16, 185, 129, 0.15); color: var(--accent); }
        .btn-heart { background: rgba(239, 68, 68, 0.1); color: var(--text-muted); }
        .btn-heart.active { color: var(--danger); background: rgba(239, 68, 68, 0.18); }
        .btn-heart.pop svg { animation: heartPop 0.4s ease; }
        .btn-more { background: rgba(107, 114, 128, 0.15); color: var(--text-muted2); }
        .icon-btn svg { width: 18px; height: 18px; fill: currentColor; }
        .spinner { width: 16px; height: 16px; border: 2.5px solid rgba(255,255,255,0.2); border-top-color: currentColor; border-radius: 50%; animation: spin 0.8s linear infinite; }
        @keyframes cardIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes heartPop { 0% { transform: scale(1); } 40% { transform: scale(1.4); } 100% { transform: scale(1); } }

        .tab-bar { display: flex; gap: 6px; background: var(--bg-alt); border: 1px solid var(--border); border-radius: 14px; padding: 5px; margin-top: 16px; }
        .tab-btn { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px; background: transparent; border: none; color: var(--text-muted); padding: 9px 4px; border-radius: 10px; font-size: 10px; font-weight: 600; cursor: pointer; transition: 0.2s; }
        .tab-btn svg { width: 18px; height: 18px; fill: currentColor; }
        .tab-btn.active { background: rgba(16, 185, 129, 0.14); color: var(--accent); }
        .tab-content { display: none; }
        .tab-content.active { display: block; animation: fadeSlideIn 0.25s ease; }
        @keyframes fadeSlideIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        .empty-hint { text-align: center; color: var(--text-muted); margin-top: 24px; font-size: 12px; }

        .create-playlist-btn { width: 100%; background: rgba(16, 185, 129, 0.12); border: 1px dashed var(--accent); color: var(--accent); padding: 13px; border-radius: 14px; font-size: 13px; font-weight: 600; cursor: pointer; margin-top: 18px; transition: transform 0.15s ease; }
        .create-playlist-btn:active { transform: scale(0.98); }
        .playlist-grid { display: flex; flex-direction: column; gap: 10px; margin-top: 14px; }
        .playlist-card { display: flex; align-items: center; gap: 12px; background: var(--bg-card); border: 1px solid var(--bg-card-alt); padding: 12px 14px; border-radius: 14px; cursor: pointer; opacity: 0; transform: translateY(10px); animation: cardIn 0.35s ease forwards; transition: transform 0.15s ease; }
        .playlist-card:active { transform: scale(0.98); }
        .playlist-card-icon { width: 44px; height: 44px; border-radius: 12px; background: rgba(16, 185, 129, 0.15); color: var(--accent); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .playlist-card-icon svg { width: 20px; height: 20px; fill: currentColor; }
        .playlist-card-info { flex: 1; overflow: hidden; }
        .playlist-card-name { font-size: 14px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .playlist-card-count { font-size: 11px; color: var(--text-muted); margin-top: 2px; }

        .action-sheet, .storage-modal.picker-modal { background: var(--bg-alt); border: 1px solid var(--border); border-radius: 20px 20px 0 0; width: 100%; max-width: 480px; padding: 18px 20px 26px 20px; transform: translateY(24px); transition: transform 0.28s ease; }
        .overlay-bg.active .action-sheet { transform: translateY(0); }
        .action-sheet-title { font-size: 13px; font-weight: 700; color: var(--text); margin-bottom: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .action-sheet-item { display: flex; align-items: center; gap: 12px; padding: 13px 6px; border-radius: 10px; cursor: pointer; color: var(--text); font-size: 13px; font-weight: 500; border-bottom: 1px solid var(--border-soft); }
        .action-sheet-item:last-child { border-bottom: none; }
        .action-sheet-item:active { background: var(--border-active-bg); }
        .action-sheet-item svg { width: 18px; height: 18px; fill: var(--accent); flex-shrink: 0; }
        .action-sheet-item.danger svg { fill: var(--danger); }
        .action-sheet-item.danger span { color: var(--danger); }
        .new-playlist-row { display: flex; gap: 8px; margin-top: 10px; }
        .new-playlist-row input { flex: 1; background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 11px 12px; color: #fff; font-size: 13px; outline: none; }
        .new-playlist-row button { background: var(--accent); border: none; color: #fff; padding: 0 16px; border-radius: 10px; font-weight: 600; cursor: pointer; }
        .play-all-btn { flex: 1; background: rgba(16, 185, 129, 0.15); border: none; color: var(--accent); padding: 11px; border-radius: 12px; font-size: 12px; font-weight: 700; cursor: pointer; }
        .delete-playlist-btn { background: rgba(239, 68, 68, 0.12); border: none; color: var(--danger); padding: 11px 16px; border-radius: 12px; font-size: 12px; font-weight: 700; cursor: pointer; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .modern-player { position: fixed; bottom: 15px; left: 15px; right: 15px; background: rgba(23, 28, 38, 0.95); backdrop-filter: blur(12px); border: 1px solid var(--border-alt); padding: 12px 16px; border-radius: 18px; display: flex; flex-direction: column; gap: 8px; opacity: 0; pointer-events: none; transition: 0.3s; }
        .modern-player.active { opacity: 1; pointer-events: auto; }
        .player-top { display: flex; align-items: center; gap: 12px; }
        .player-cover { width: 44px; height: 44px; border-radius: 8px; object-fit: cover; }
        .player-details { flex: 1; overflow: hidden; }
        .player-title { font-size: 13px; font-weight: 600; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .player-status { font-size: 11px; color: var(--accent); margin-top: 2px; }
        .player-main-btn { width: 40px; height: 40px; border-radius: 50%; background: var(--accent); border: none; color: #fff; display: flex; align-items: center; justify-content: center; cursor: pointer; }
        .player-main-btn svg { width: 20px; height: 20px; fill: #fff; }
        .progress-container { width: 100%; display: flex; align-items: center; gap: 8px; }
        .progress-bar { flex: 1; height: 4px; background: var(--border-alt); border-radius: 2px; appearance: none; outline: none; cursor: pointer; }
        .time-text { font-size: 10px; color: var(--text-muted); width: 30px; }
    </style>
</head>
<body>
    <div class="canvas-bg" id="canvasBg"><img id="canvasBgImg" src="" alt=""></div>
    <button class="settings-btn" id="settingsBtn" onclick="toggleSettings(event)">
        <svg viewBox="0 0 24 24"><path d="M19.14,12.94c0.04,-0.3 0.06,-0.61 0.06,-0.94c0,-0.32 -0.02,-0.64 -0.07,-0.94l2.03,-1.58c0.18,-0.14 0.23,-0.41 0.12,-0.61l-1.92,-3.32c-0.12,-0.22 -0.37,-0.29 -0.59,-0.22l-2.39,0.96c-0.5,-0.38 -1.03,-0.7 -1.62,-0.94L14.4,2.81c-0.04,-0.24 -0.24,-0.41 -0.48,-0.41h-3.84c-0.24,0 -0.43,0.17 -0.47,0.41L9.25,5.35C8.66,5.59 8.12,5.92 7.63,6.29L5.24,5.33c-0.22,-0.08 -0.47,0 -0.59,0.22L2.74,8.87C2.62,9.08 2.66,9.34 2.86,9.48l2.03,1.58C4.84,11.36 4.8,11.69 4.8,12s0.02,0.64 0.07,0.94l-2.03,1.58c-0.18,0.14 -0.23,0.41 -0.12,0.61l1.92,3.32c0.12,0.22 0.37,0.29 0.59,0.22l2.39,-0.96c0.5,0.38 1.03,0.7 1.62,0.94l0.36,2.54c0.05,0.24 0.24,0.41 0.48,0.41h3.84c0.24,0 0.44,-0.17 0.47,-0.41l0.36,-2.54c0.59,-0.24 1.13,-0.56 1.62,-0.94l2.39,0.96c0.22,0.08 0.47,0 0.59,-0.22l1.92,-3.32c0.12,-0.22 0.07,-0.47 -0.12,-0.61L19.14,12.94z M12,15.6c-1.98,0 -3.6,-1.62 -3.6,-3.6s1.62,-3.6 3.6,-3.6s3.6,1.62 3.6,3.6S13.98,15.6 12,15.6z"/></svg>
    </button>
    <div class="settings-panel" id="settingsPanel">
        <div class="settings-item" onclick="openEqualizer()">
            <svg viewBox="0 0 24 24"><path d="M3 17h4v-7H3v7zm7 4h4V3h-4v18zm7-11v11h4V10h-4z"/></svg>
            <span id="settingsEqLabel">Ses Efektleri</span>
        </div>
        <div class="settings-item" onclick="openStorageSettings()">
            <svg viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM5 19V5h14v14H5zM7 10h2v7H7v-7zm4-3h2v10h-2V7zm4 5h2v5h-2v-5z"/></svg>
            <span id="settingsStorageLabel">İndirme Konumu</span>
        </div>
        <div class="settings-item lang-row">
            <div class="lang-row-left">
                <svg viewBox="0 0 24 24"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zm6.93 6h-2.95c-.32-1.25-.78-2.45-1.38-3.56 1.84.63 3.37 1.9 4.33 3.56zM12 4.04c.83 1.2 1.48 2.53 1.91 3.96h-3.82c.43-1.43 1.08-2.76 1.91-3.96zM4.26 14C4.1 13.36 4 12.69 4 12s.1-1.36.26-2h3.38c-.08.66-.14 1.32-.14 2s.06 1.34.14 2H4.26zm.82 2h2.95c.32 1.25.78 2.45 1.38 3.56-1.84-.63-3.37-1.89-4.33-3.56zm2.95-8H5.08c.96-1.66 2.49-2.93 4.33-3.56C8.81 5.55 8.35 6.75 8.03 8zM12 19.96c-.83-1.2-1.48-2.53-1.91-3.96h3.82c-.43 1.43-1.08 2.76-1.91 3.96zM14.34 14H9.66c-.09-.66-.16-1.32-.16-2s.07-1.35.16-2h4.68c.09.65.16 1.32.16 2s-.07 1.34-.16 2zm.25 5.56c.6-1.11 1.06-2.31 1.38-3.56h2.95c-.96 1.65-2.49 2.93-4.33 3.56zM16.36 14c.08-.66.14-1.32.14-2s-.06-1.34-.14-2h3.38c.16.64.26 1.31.26 2s-.1 1.36-.26 2h-3.38z"/></svg>
                <span id="settingsLangLabel">Dil</span>
            </div>
            <div style="display:flex; gap:6px;">
                <button type="button" class="lang-opt-btn" id="langBtnTr" onclick="event.stopPropagation(); setLanguage('tr')">TR</button>
                <button type="button" class="lang-opt-btn" id="langBtnEn" onclick="event.stopPropagation(); setLanguage('en')">EN</button>
            </div>
        </div>
        <div class="settings-divider"></div>
        <div class="settings-item" onclick="openCrossfadeSettings()">
            <svg viewBox="0 0 24 24"><path d="M9 3v2H4v14h5v2H2V3h7zm6 0h7v18h-7v-2h5V5h-5V3zM12 8l4 4-4 4v-3H8v-2h4V8z"/></svg>
            <span id="settingsCrossfadeLabel">Çapraz Geçiş</span>
        </div>
        <div class="settings-item" onclick="openCacheSettings()">
            <svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
            <span id="settingsCacheLabel">Önbelleği Temizle</span>
        </div>
        <div class="settings-item lang-row">
            <div class="lang-row-left">
                <svg viewBox="0 0 24 24"><path d="M1 9l2-2c4.97-4.97 13.03-4.97 18 0l2 2-2 2c-4.97 4.97-13.03 4.97-18 0L1 9zm11 3a3 3 0 100-6 3 3 0 000 6z"/></svg>
                <span id="settingsOfflineLabel">Çevrimdışı Mod</span>
            </div>
            <label class="switch">
                <input type="checkbox" id="offlineModeToggle" onchange="onOfflineModeToggle()">
                <span class="switch-slider"></span>
            </label>
        </div>
        <div class="settings-item" onclick="openThemeSettings()">
            <svg viewBox="0 0 24 24"><path d="M12 3a9 9 0 109 9c0-.46-.04-.92-.1-1.36a5.389 5.389 0 01-4.4 2.26 5.403 5.403 0 01-3.14-9.8c-.44-.06-.9-.1-1.36-.1z"/></svg>
            <span id="settingsThemeLabel">Tema</span>
        </div>
        <div class="settings-item lang-row">
            <div class="lang-row-left">
                <svg viewBox="0 0 24 24"><path d="M4 6h16v10H4V6zm2 12h12v2H6v-2z"/></svg>
                <span id="settingsCanvasLabel">Hareketli Kapak</span>
            </div>
            <label class="switch">
                <input type="checkbox" id="canvasToggle" onchange="onCanvasToggle()">
                <span class="switch-slider"></span>
            </label>
        </div>
        <div class="settings-item lang-row">
            <div class="lang-row-left">
                <svg viewBox="0 0 24 24"><path d="M6 10V8a6 6 0 1112 0v2h1a1 1 0 011 1v9a1 1 0 01-1 1H5a1 1 0 01-1-1v-9a1 1 0 011-1h1zm2 0h8V8a4 4 0 00-8 0v2z"/></svg>
                <span id="settingsLockLabel">Kilit Ekranı Kontrolleri</span>
            </div>
            <label class="switch">
                <input type="checkbox" id="lockScreenToggle" onchange="onLockScreenToggle()">
                <span class="switch-slider"></span>
            </label>
        </div>
    </div>

    <div class="overlay-bg" id="storageOverlay" onclick="if(event.target===this) closeStorageSettings()">
        <div class="storage-modal">
            <div class="eq-header">
                <h2 id="storageModalTitle">İndirme Konumu</h2>
                <button class="eq-close-btn" onclick="closeStorageSettings()">✕</button>
            </div>
            <p class="eq-sub" id="storageModalSub">İndirilen müziklerin kaydedileceği depolama alanını seçin</p>
            <div class="storage-list" id="storageList">
                <p style="text-align:center; color:#6b7280; font-size:12px;">Yükleniyor...</p>
            </div>
            <p class="storage-status" id="storageStatus"></p>
        </div>
    </div>

    <div class="overlay-bg" id="eqOverlay" onclick="if(event.target===this) closeEqualizer()">
        <div class="eq-modal">
            <div class="eq-header">
                <h2 id="eqModalTitle">Ses Efektleri</h2>
                <button class="eq-close-btn" onclick="closeEqualizer()">✕</button>
            </div>
            <p class="eq-sub" id="eqModalSub">Ekolayzır ve 8D ses deneyimini kişiselleştirin</p>
            <div class="eq-toggle-row">
                <span id="eqActiveLabel">Ekolayzır Aktif</span>
                <label class="switch">
                    <input type="checkbox" id="eqEnabledToggle" onchange="onEqToggle()">
                    <span class="switch-slider"></span>
                </label>
            </div>
            <div class="eq-bands" id="eqBands"></div>
            <div class="eq-presets" id="eqPresets"></div>

            <div class="eq-toggle-row" style="margin-top: 18px;">
                <span id="eightDLabel">8D Ses Efekti</span>
                <label class="switch">
                    <input type="checkbox" id="eightDToggle" onchange="on8DToggle()">
                    <span class="switch-slider"></span>
                </label>
            </div>
            <div class="eq-toggle-row" id="eightDSpeedRow" style="display:none; flex-direction:column; align-items:stretch; gap:10px;">
                <div style="display:flex; justify-content:space-between;">
                    <span id="rotationSpeedLabel" style="font-size:12px; color:var(--text-muted2); font-weight:500;">Dönüş Hızı</span>
                    <span id="eightDSpeedVal" style="font-size:12px; color:var(--accent); font-weight:600;">8s</span>
                </div>
                <input type="range" id="eightDSpeedSlider" min="3" max="15" step="1" value="8" oninput="on8DSpeedChange(this.value)" style="width:100%; accent-color:var(--accent);">
            </div>

            <div class="eq-toggle-row" style="margin-top: 18px;">
                <span id="surroundLabel">Sinema Ses (Surround)</span>
                <label class="switch">
                    <input type="checkbox" id="surroundToggle" onchange="onSurroundToggle()">
                    <span class="switch-slider"></span>
                </label>
            </div>
            <div class="eq-toggle-row" id="surroundAmountRow" style="display:none; flex-direction:column; align-items:stretch; gap:10px;">
                <div style="display:flex; justify-content:space-between;">
                    <span id="effectStrengthLabel" style="font-size:12px; color:var(--text-muted2); font-weight:500;">Etki Gücü</span>
                    <span id="surroundAmountVal" style="font-size:12px; color:var(--accent); font-weight:600;">40%</span>
                </div>
                <input type="range" id="surroundAmountSlider" min="0" max="100" step="5" value="40" oninput="onSurroundAmountChange(this.value)" style="width:100%; accent-color:var(--accent);">
            </div>
        </div>
    </div>

    <div class="overlay-bg" id="crossfadeOverlay" onclick="if(event.target===this) closeCrossfadeSettings()">
        <div class="crossfade-modal">
            <div class="eq-header">
                <h2 id="crossfadeModalTitle">Çapraz Geçiş</h2>
                <button class="eq-close-btn" onclick="closeCrossfadeSettings()">✕</button>
            </div>
            <p class="eq-sub" id="crossfadeModalSub">Şarkılar arasında sessizlik olmadan yumuşak geçiş süresi</p>
            <div class="crossfade-value-row">
                <span id="crossfadeOffLabel">Kapalı</span>
                <span id="crossfadeValueLabel">0s</span>
            </div>
            <input type="range" id="crossfadeSlider" min="0" max="12" step="1" value="0" oninput="onCrossfadeChange(this.value)" style="width:100%; accent-color: var(--accent);">
        </div>
    </div>

    <div class="overlay-bg" id="cacheOverlay" onclick="if(event.target===this) closeCacheSettings()">
        <div class="cache-modal">
            <div class="eq-header">
                <h2 id="cacheModalTitle">Önbelleği Temizle</h2>
                <button class="eq-close-btn" onclick="closeCacheSettings()">✕</button>
            </div>
            <p class="eq-sub" id="cacheModalSub">Dinlemek için geçici olarak indirilen dosyaları sil</p>
            <div class="cache-size-box">
                <div class="cache-size-num" id="cacheSizeNum">—</div>
                <div class="cache-size-label" id="cacheSizeLabel">önbellek boyutu</div>
            </div>
            <button class="clear-cache-btn" id="clearCacheBtn" onclick="clearCache()">Önbelleği Temizle</button>
            <p class="storage-status" id="cacheStatus"></p>
        </div>
    </div>

    <div class="overlay-bg" id="themeOverlay" onclick="if(event.target===this) closeThemeSettings()">
        <div class="cache-modal">
            <div class="eq-header">
                <h2 id="themeModalTitle">Tema</h2>
                <button class="eq-close-btn" onclick="closeThemeSettings()">✕</button>
            </div>
            <div style="display:flex; gap:8px; margin-top:14px;">
                <button type="button" class="theme-opt-btn" id="themeBtnSystem" style="flex:1;" onclick="setTheme('system')">Cihaz</button>
                <button type="button" class="theme-opt-btn" id="themeBtnDark" style="flex:1;" onclick="setTheme('dark')">Koyu</button>
                <button type="button" class="theme-opt-btn" id="themeBtnLight" style="flex:1;" onclick="setTheme('light')">Açık</button>
            </div>
        </div>
    </div>

    <div class="header">
        <h1>HMusic</h1>
        <p id="headerSubtitle">Ağsız Müzik ve Video Deneyimi</p>
    </div>

    <div class="tab-bar">
        <button class="tab-btn active" id="tabSearchBtn" onclick="switchTab('search')">
            <svg viewBox="0 0 24 24"><path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
            <span id="tabSearchLabel">Ara</span>
        </button>
        <button class="tab-btn" id="tabFavoritesBtn" onclick="switchTab('favorites')">
            <svg viewBox="0 0 24 24"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
            <span id="tabFavoritesLabel">Favoriler</span>
        </button>
        <button class="tab-btn" id="tabDownloadedBtn" onclick="switchTab('downloaded')">
            <svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
            <span id="tabDownloadedLabel">İndirilenler</span>
        </button>
        <button class="tab-btn" id="tabPlaylistsBtn" onclick="switchTab('playlists')">
            <svg viewBox="0 0 24 24"><path d="M15 6H3v2h12V6zm0 4H3v2h12v-2zM3 16h8v-2H3v2zM17 6v8.18c-.31-.11-.65-.18-1-.18-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3V8h3V6h-5z"/></svg>
            <span id="tabPlaylistsLabel">Listelerim</span>
        </button>
    </div>


    <div class="tab-content active" id="searchTabContent">
        <div class="search-box" style="margin-top: 16px;">
            <input type="text" id="searchInput" maxlength="100" placeholder="Şarkı veya sanatçı ara..." onkeypress="if(event.key==='Enter') searchMusic()">
            <button id="searchBtn" onclick="searchMusic()">Ara</button>
        </div>
        <div class="results-list" id="resultsList"></div>
    </div>

    <div class="tab-content" id="favoritesTabContent">
        <div class="results-list" id="favoritesList"></div>
    </div>

    <div class="tab-content" id="downloadedTabContent">
        <p class="empty-hint" id="offlineModeHint" style="display:none;"></p>
        <div class="results-list" id="downloadedList"></div>
    </div>

    <div class="tab-content" id="playlistsTabContent">
        <button class="create-playlist-btn" id="newPlaylistBtn" onclick="openCreatePlaylistPrompt()">+ Yeni Çalma Listesi</button>
        <div class="playlist-grid" id="playlistGrid"></div>
    </div>

    <audio id="audioPlayer"></audio>
    <audio id="audioPlayerAlt"></audio>

    <div class="overlay-bg" id="actionSheetOverlay" onclick="if(event.target===this) closeActionSheet()">
        <div class="action-sheet">
            <div class="action-sheet-title" id="actionSheetTitle">Şarkı</div>
            <div class="action-sheet-item" onclick="actionSheetAddToPlaylist()">
                <svg viewBox="0 0 24 24"><path d="M14 10H2v2h12v-2zm0-4H2v2h12V6zm4 8v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zM2 16h8v-2H2v2z"/></svg>
                <span id="actionSheetAddLabel">Çalma Listesine Ekle</span>
            </div>
            <div class="action-sheet-item" onclick="actionSheetDownload('mp3')">
                <svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
                <span id="actionSheetMp3Label">MP3 İndir</span>
            </div>
            <div class="action-sheet-item" onclick="actionSheetDownload('mp4')">
                <svg viewBox="0 0 24 24"><path d="M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4z"/></svg>
                <span id="actionSheetMp4Label">MP4 İndir</span>
            </div>
            <div class="action-sheet-item danger" id="actionSheetRemoveFromPlaylist" style="display:none;" onclick="actionSheetRemoveFromPlaylist()">
                <svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
                <span id="actionSheetRemoveLabel">Listeden Çıkar</span>
            </div>
        </div>
    </div>

    <div class="overlay-bg" id="addToPlaylistOverlay" onclick="if(event.target===this) closeAddToPlaylist()">
        <div class="storage-modal">
            <div class="eq-header">
                <h2 id="addToPlaylistTitle">Çalma Listesine Ekle</h2>
                <button class="eq-close-btn" onclick="closeAddToPlaylist()">✕</button>
            </div>
            <div class="storage-list" id="addToPlaylistList"></div>
            <div class="new-playlist-row">
                <input type="text" id="newPlaylistNameInput" maxlength="60" placeholder="Yeni liste adı...">
                <button id="createPlaylistBtn" onclick="createPlaylistFromPicker()">Oluştur</button>
            </div>
            <p class="storage-status" id="addToPlaylistStatus"></p>
        </div>
    </div>

    <div class="overlay-bg" id="playlistDetailOverlay" onclick="if(event.target===this) closePlaylistDetail()">
        <div class="storage-modal">
            <div class="eq-header">
                <h2 id="playlistDetailName">Liste</h2>
                <button class="eq-close-btn" onclick="closePlaylistDetail()">✕</button>
            </div>
            <div style="display:flex; gap:8px; margin: 6px 0 16px 0;">
                <button class="play-all-btn" id="playAllBtn" onclick="playPlaylistFromStart()">▶ Tümünü Çal</button>
                <button class="delete-playlist-btn" id="deletePlaylistBtn" onclick="deleteCurrentPlaylist()">Listeyi Sil</button>
            </div>
            <div class="results-list" id="playlistDetailSongs" style="max-height:48vh; overflow-y:auto;"></div>
        </div>
    </div>

    <div class="modern-player" id="playerPanel">
        <div class="player-top">
            <img src="" id="playerCover" class="player-cover">
            <div class="player-details">
                <div class="player-title" id="playerTitle">Şarkı Adı</div>
                <div class="player-status" id="playerStatus">Hazırlanıyor...</div>
            </div>
            <div class="player-controls-right">
                <button class="player-main-btn" id="playPauseBtn" onclick="togglePlay()">
                    <svg id="playIcon" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                    <svg id="pauseIcon" viewBox="0 0 24 24" style="display:none;"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
                </button>
                <button class="player-next-btn" id="nextBtn" onclick="playNext()">
                    <svg viewBox="0 0 24 24"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg>
                </button>
            </div>
        </div>
        <div class="progress-container">
            <span class="time-text" id="currentTime">0:00</span>
            <input type="range" class="progress-bar" id="seekBar" value="0" min="0" max="100">
            <span class="time-text" id="durationTime">0:00</span>
        </div>
    </div>
<script>
    const audioPlayer = document.getElementById('audioPlayer');
    const audioPlayerAlt = document.getElementById('audioPlayerAlt');
    let activeAudioPlayer = audioPlayer;
    let standbyAudioPlayer = audioPlayerAlt;
    let crossfadeSeconds = parseInt(localStorage.getItem('hmusic_crossfade') || '0', 10);
    let crossfadeInProgress = false;
    let downloadedData = [];
    const playerPanel = document.getElementById('playerPanel');
    const playerCover = document.getElementById('playerCover');
    const playerTitle = document.getElementById('playerTitle');
    const playerStatus = document.getElementById('playerStatus');
    const playIcon = document.getElementById('playIcon');
    const pauseIcon = document.getElementById('pauseIcon');
    const seekBar = document.getElementById('seekBar');
    const currentTimeEl = document.getElementById('currentTime');
    const durationTimeEl = document.getElementById('durationTime');
    let currentBtn = null;
    let searchResults = [];
    let favoritesData = [];
    let favoriteIds = new Set();
    let playlistsData = [];
    let activePlaylistId = null;
    let activePlaylistSongs = [];
    let activeQueue = [];
    let activeQueueType = null;
    let activeQueueIndex = -1;
    let autoAdvance = true;
    let actionSheetContext = null;

    // ---------- Dil / Language ----------
    const LANG_DICT = {
        header_subtitle: { tr: 'Ağsız Müzik ve Video Deneyimi', en: 'Seamless Music & Video Experience' },
        settings_eq: { tr: 'Ses Efektleri', en: 'Sound Effects' },
        settings_storage: { tr: 'İndirme Konumu', en: 'Download Location' },
        settings_lang: { tr: 'Dil', en: 'Language' },
        storage_modal_title: { tr: 'İndirme Konumu', en: 'Download Location' },
        storage_modal_sub: { tr: 'İndirilen müziklerin kaydedileceği depolama alanını seçin', en: 'Choose where downloaded music will be saved' },
        eq_modal_title: { tr: 'Ses Efektleri', en: 'Sound Effects' },
        eq_modal_sub: { tr: 'Ekolayzır ve 8D ses deneyimini kişiselleştirin', en: 'Customize your equalizer and 8D sound experience' },
        eq_active: { tr: 'Ekolayzır Aktif', en: 'Equalizer Active' },
        eightd_label: { tr: '8D Ses Efekti', en: '8D Sound Effect' },
        rotation_speed: { tr: 'Dönüş Hızı', en: 'Rotation Speed' },
        surround_label: { tr: 'Sinema Ses (Surround)', en: 'Cinema Sound (Surround)' },
        effect_strength: { tr: 'Etki Gücü', en: 'Effect Strength' },
        tab_search: { tr: 'Ara', en: 'Search' },
        tab_favorites: { tr: 'Favoriler', en: 'Favorites' },
        tab_playlists: { tr: 'Listelerim', en: 'My Playlists' },
        search_placeholder: { tr: 'Şarkı veya sanatçı ara...', en: 'Search for a song or artist...' },
        search_btn: { tr: 'Ara', en: 'Search' },
        new_playlist_btn: { tr: '+ Yeni Çalma Listesi', en: '+ New Playlist' },
        add_to_playlist: { tr: 'Çalma Listesine Ekle', en: 'Add to Playlist' },
        download_mp3: { tr: 'MP3 İndir', en: 'Download MP3' },
        download_mp4: { tr: 'MP4 İndir', en: 'Download MP4' },
        remove_from_playlist: { tr: 'Listeden Çıkar', en: 'Remove from Playlist' },
        new_playlist_placeholder: { tr: 'Yeni liste adı...', en: 'New playlist name...' },
        create_btn: { tr: 'Oluştur', en: 'Create' },
        play_all: { tr: '▶ Tümünü Çal', en: '▶ Play All' },
        delete_playlist: { tr: 'Listeyi Sil', en: 'Delete Playlist' },
        playlist_default_name: { tr: 'Liste', en: 'Playlist' },
        song_default_title: { tr: 'Şarkı', en: 'Song' },
        player_title_default: { tr: 'Şarkı Adı', en: 'Song Title' },
        preparing: { tr: 'Hazırlanıyor...', en: 'Preparing...' },
        searching: { tr: 'Aranıyor...', en: 'Searching...' },
        access_denied: { tr: 'Erişiminiz Engellendi!', en: 'Your access has been blocked!' },
        no_results: { tr: 'Sonuç bulunamadı.', en: 'No results found.' },
        error_occurred: { tr: 'Bir hata oluştu!', en: 'An error occurred!' },
        generic_error_dot: { tr: 'Bir hata oluştu.', en: 'An error occurred.' },
        no_playlists_yet: { tr: 'Henüz çalma listeniz yok.', en: "You don't have any playlists yet." },
        no_favorites_yet: { tr: 'Henüz favori şarkınız yok.', en: "You don't have any favorite songs yet." },
        no_songs_in_playlist: { tr: 'Bu listede henüz şarkı yok.', en: 'There are no songs in this playlist yet.' },
        confirm_delete_playlist: { tr: 'Bu çalma listesini silmek istediğinize emin misiniz?', en: 'Are you sure you want to delete this playlist?' },
        prompt_new_playlist: { tr: 'Yeni çalma listesi adı:', en: 'New playlist name:' },
        no_playlists_create_below: { tr: 'Henüz çalma listeniz yok, aşağıdan oluşturun.', en: "You don't have any playlists yet, create one below." },
        adding: { tr: 'Ekleniyor...', en: 'Adding...' },
        add_failed: { tr: 'Eklenemedi.', en: 'Could not add.' },
        already_in_playlist: { tr: 'Bu şarkı zaten listede.', en: 'This song is already in the playlist.' },
        added_to_playlist: { tr: 'Listeye eklendi ✓', en: 'Added to playlist ✓' },
        playlist_created_now_tap: { tr: 'Liste oluşturuldu, şimdi şarkıya dokunun.', en: 'Playlist created, now tap the song.' },
        end_of_list: { tr: 'Liste sonu', en: 'End of list' },
        playing: { tr: 'Çalınıyor', en: 'Playing' },
        paused: { tr: 'Duraklatıldı', en: 'Paused' },
        song_count_suffix: { tr: 'şarkı', en: 'songs' },
        loading: { tr: 'Yükleniyor...', en: 'Loading...' },
        storage_load_failed: { tr: 'Depolama bilgisi alınamadı.', en: 'Could not retrieve storage info.' },
        storage_none_found: { tr: 'Depolama bulunamadı.', en: 'No storage found.' },
        saving: { tr: 'Kaydediliyor...', en: 'Saving...' },
        change_failed: { tr: 'Değiştirilemedi.', en: 'Could not be changed.' },
        saved_prefix: { tr: 'Kaydedildi: ', en: 'Saved: ' },
        preset_flat: { tr: 'Düz', en: 'Flat' },
        preset_bass: { tr: 'Bas', en: 'Bass' },
        preset_vocal: { tr: 'Vokal', en: 'Vocal' },
        preset_treble: { tr: 'Tiz', en: 'Treble' },
        settings_crossfade: { tr: 'Çapraz Geçiş', en: 'Crossfade' },
        settings_cache: { tr: 'Önbelleği Temizle', en: 'Clear Cache' },
        settings_offline: { tr: 'Çevrimdışı Mod', en: 'Offline Mode' },
        settings_theme: { tr: 'Tema', en: 'Theme' },
        settings_canvas: { tr: 'Hareketli Kapak', en: 'Animated Cover' },
        settings_lock: { tr: 'Kilit Ekranı Kontrolleri', en: 'Lock Screen Controls' },
        crossfade_modal_title: { tr: 'Çapraz Geçiş', en: 'Crossfade' },
        crossfade_modal_sub: { tr: 'Şarkılar arasında sessizlik olmadan yumuşak geçiş süresi', en: 'Smooth transition time between songs, with no silence' },
        crossfade_off: { tr: 'Kapalı', en: 'Off' },
        cache_modal_title: { tr: 'Önbelleği Temizle', en: 'Clear Cache' },
        cache_modal_sub: { tr: 'Dinlemek için geçici olarak indirilen dosyaları sil', en: 'Delete files temporarily downloaded for streaming' },
        cache_size_label: { tr: 'önbellek boyutu', en: 'cache size' },
        theme_modal_title: { tr: 'Tema', en: 'Theme' },
        theme_system: { tr: 'Cihaz', en: 'System' },
        theme_dark: { tr: 'Koyu', en: 'Dark' },
        theme_light: { tr: 'Açık', en: 'Light' },
        tab_downloaded: { tr: 'İndirilenler', en: 'Downloads' },
        offline_hint: { tr: 'Çevrimdışı moddasınız, sadece cihaza indirilmiş şarkılar çalınabilir.', en: "You're in offline mode, only songs downloaded to this device can play." },
        offline_blocked: { tr: 'Bu şarkı cihazınıza indirilmemiş. Çevrimdışı moddayken sadece indirilen şarkılar çalınabilir.', en: 'This song is not downloaded to your device. Only downloaded songs can play in offline mode.' },
        no_downloads_yet: { tr: 'Henüz indirilmiş şarkı yok.', en: 'No downloaded songs yet.' },
        confirm_delete_download: { tr: 'Bu indirilen şarkıyı cihazdan silmek istediğinize emin misiniz?', en: 'Are you sure you want to delete this downloaded song from your device?' }
    };
    let currentLang = localStorage.getItem('hmusic_lang') || 'tr';
    function t(key) {
        const entry = LANG_DICT[key];
        if (!entry) return key;
        return entry[currentLang] || entry.tr;
    }

    function applyStaticTexts() {
        document.getElementById('headerSubtitle').textContent = t('header_subtitle');
        document.getElementById('settingsEqLabel').textContent = t('settings_eq');
        document.getElementById('settingsStorageLabel').textContent = t('settings_storage');
        document.getElementById('settingsLangLabel').textContent = t('settings_lang');
        document.getElementById('storageModalTitle').textContent = t('storage_modal_title');
        document.getElementById('storageModalSub').textContent = t('storage_modal_sub');
        document.getElementById('eqModalTitle').textContent = t('eq_modal_title');
        document.getElementById('eqModalSub').textContent = t('eq_modal_sub');
        document.getElementById('eqActiveLabel').textContent = t('eq_active');
        document.getElementById('eightDLabel').textContent = t('eightd_label');
        document.getElementById('rotationSpeedLabel').textContent = t('rotation_speed');
        document.getElementById('surroundLabel').textContent = t('surround_label');
        document.getElementById('effectStrengthLabel').textContent = t('effect_strength');
        document.getElementById('tabSearchLabel').textContent = t('tab_search');
        document.getElementById('tabFavoritesLabel').textContent = t('tab_favorites');
        document.getElementById('tabPlaylistsLabel').textContent = t('tab_playlists');
        document.getElementById('searchInput').placeholder = t('search_placeholder');
        document.getElementById('searchBtn').textContent = t('search_btn');
        document.getElementById('newPlaylistBtn').textContent = t('new_playlist_btn');
        document.getElementById('actionSheetAddLabel').textContent = t('add_to_playlist');
        document.getElementById('actionSheetMp3Label').textContent = t('download_mp3');
        document.getElementById('actionSheetMp4Label').textContent = t('download_mp4');
        document.getElementById('actionSheetRemoveLabel').textContent = t('remove_from_playlist');
        document.getElementById('addToPlaylistTitle').textContent = t('add_to_playlist');
        document.getElementById('newPlaylistNameInput').placeholder = t('new_playlist_placeholder');
        document.getElementById('createPlaylistBtn').textContent = t('create_btn');
        document.getElementById('playAllBtn').textContent = t('play_all');
        document.getElementById('deletePlaylistBtn').textContent = t('delete_playlist');
        document.getElementById('settingsCrossfadeLabel').textContent = t('settings_crossfade');
        document.getElementById('settingsCacheLabel').textContent = t('settings_cache');
        document.getElementById('settingsOfflineLabel').textContent = t('settings_offline');
        document.getElementById('settingsThemeLabel').textContent = t('settings_theme');
        document.getElementById('settingsCanvasLabel').textContent = t('settings_canvas');
        document.getElementById('settingsLockLabel').textContent = t('settings_lock');
        document.getElementById('crossfadeModalTitle').textContent = t('crossfade_modal_title');
        document.getElementById('crossfadeModalSub').textContent = t('crossfade_modal_sub');
        document.getElementById('crossfadeOffLabel').textContent = t('crossfade_off');
        document.getElementById('crossfadeValueLabel').textContent = crossfadeSeconds === 0 ? t('crossfade_off') : crossfadeSeconds + 's';
        document.getElementById('cacheModalTitle').textContent = t('cache_modal_title');
        document.getElementById('cacheModalSub').textContent = t('cache_modal_sub');
        document.getElementById('cacheSizeLabel').textContent = t('cache_size_label');
        document.getElementById('clearCacheBtn').textContent = t('settings_cache');
        document.getElementById('themeModalTitle').textContent = t('theme_modal_title');
        document.getElementById('themeBtnSystem').textContent = t('theme_system');
        document.getElementById('themeBtnDark').textContent = t('theme_dark');
        document.getElementById('themeBtnLight').textContent = t('theme_light');
        document.getElementById('tabDownloadedLabel').textContent = t('tab_downloaded');
        applyOfflineModeUI();
        document.documentElement.lang = currentLang;
        document.getElementById('langBtnTr').classList.toggle('active', currentLang === 'tr');
        document.getElementById('langBtnEn').classList.toggle('active', currentLang === 'en');
    }

    function refreshDynamicTexts() {
        if (document.getElementById('searchTabContent').classList.contains('active')) {
            renderCardList(document.getElementById('resultsList'), searchResults, 'search', t('no_results'));
        }
        if (document.getElementById('favoritesTabContent').classList.contains('active')) {
            renderCardList(document.getElementById('favoritesList'), favoritesData, 'favorites', t('no_favorites_yet'));
        }
        if (document.getElementById('playlistsTabContent').classList.contains('active')) {
            renderPlaylistGrid();
        }
        if (document.getElementById('downloadedTabContent').classList.contains('active')) {
            renderCardList(document.getElementById('downloadedList'), downloadedData, 'downloaded', t('no_downloads_yet'));
        }
    }

    function setLanguage(lang) {
        currentLang = lang;
        localStorage.setItem('hmusic_lang', lang);
        applyStaticTexts();
        refreshDynamicTexts();
    }

    function getQueueArray(queueType) {
        if (queueType === 'search') return searchResults;
        if (queueType === 'favorites') return favoritesData;
        if (queueType === 'playlist') return activePlaylistSongs;
        if (queueType === 'downloaded') return downloadedData;
        return [];
    }

    // ---------- Şarkı kartı üretimi (arama / favoriler / çalma listesi / indirilenler ortak) ----------
    function songCardHTML(item, queueType, index) {
        if (queueType === 'downloaded') {
            return `
                <img src="${item.thumbnail || ''}" alt="thumb" onerror="this.style.visibility='hidden'">
                <div class="card-info">
                    <div class="card-title">${item.title}</div>
                    <div class="card-artist">HMusic Stream</div>
                </div>
                <div class="action-btns">
                    <button class="icon-btn btn-play" onclick="playSong(this, 'downloaded', ${index})">
                        <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                    </button>
                    <button class="icon-btn btn-more" onclick="deleteLocalDownload(${index})">
                        <svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
                    </button>
                </div>
            `;
        }
        const isFav = favoriteIds.has(item.id);
        return `
            <img src="${item.thumbnail}" alt="thumb">
            <div class="card-info">
                <div class="card-title">${item.title}</div>
                <div class="card-artist">HMusic Stream</div>
            </div>
            <div class="action-btns">
                <button class="icon-btn btn-play" onclick="playSong(this, '${queueType}', ${index})">
                    <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                </button>
                <button class="icon-btn btn-heart${isFav ? ' active' : ''}" onclick="toggleFavoriteFromCard(this, '${queueType}', ${index})">
                    <svg viewBox="0 0 24 24"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
                </button>
                <button class="icon-btn btn-more" onclick="openActionSheet('${queueType}', ${index})">
                    <svg viewBox="0 0 24 24"><path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/></svg>
                </button>
            </div>
        `;
    }

    function renderCardList(container, list, queueType, emptyMessage) {
        container.innerHTML = '';
        if (!list.length) {
            container.innerHTML = `<p class="empty-hint">${emptyMessage}</p>`;
            return;
        }
        list.forEach((item, index) => {
            const card = document.createElement('div');
            card.className = 'card';
            card.style.animationDelay = (index * 0.04) + 's';
            card.innerHTML = songCardHTML(item, queueType, index);
            container.appendChild(card);
        });
    }

    // ---------- Arama ----------
    async function searchMusic() {
        const query = document.getElementById('searchInput').value.trim();
        if (!query) return;
        const resultsList = document.getElementById('resultsList');
        resultsList.innerHTML = `<p style="text-align:center; color:#6b7280; margin-top:20px;">${t('searching')}</p>`;
        try {
            const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
            if (res.status === 403) {
                resultsList.innerHTML = `<p style="text-align:center; color:#ef4444; margin-top:20px;">${t('access_denied')}</p>`;
                return;
            }
            const data = await res.json();
            if (!data || data.length === 0 || data.error) {
                resultsList.innerHTML = `<p style="text-align:center; color:#6b7280; margin-top:20px;">${t('no_results')}</p>`;
                return;
            }
            searchResults = data;
            renderCardList(resultsList, searchResults, 'search', t('no_results'));
        } catch (err) {
            resultsList.innerHTML = `<p style="text-align:center; color:#ef4444; margin-top:20px;">${t('error_occurred')}</p>`;
        }
    }

    // ---------- Sekmeler ----------
    function switchTab(tab) {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.getElementById('tab' + tab.charAt(0).toUpperCase() + tab.slice(1) + 'Btn').classList.add('active');
        document.getElementById(tab + 'TabContent').classList.add('active');
        if (tab === 'favorites') loadFavoritesTab();
        if (tab === 'playlists') loadPlaylistsTab();
        if (tab === 'downloaded') loadDownloadedTab();
    }

    async function loadLibrary() {
        try {
            const res = await fetch('/api/library');
            const data = await res.json();
            favoritesData = data.favorites || [];
            favoriteIds = new Set(favoritesData.map(s => s.id));
            playlistsData = data.playlists || [];
        } catch (err) { /* sessizce geç */ }
    }

    async function loadFavoritesTab() {
        await loadLibrary();
        renderCardList(document.getElementById('favoritesList'), favoritesData, 'favorites', t('no_favorites_yet'));
    }

    async function loadPlaylistsTab() {
        await loadLibrary();
        renderPlaylistGrid();
    }

    function renderPlaylistGrid() {
        const grid = document.getElementById('playlistGrid');
        grid.innerHTML = '';
        if (!playlistsData.length) {
            grid.innerHTML = `<p class="empty-hint">${t('no_playlists_yet')}</p>`;
            return;
        }
        playlistsData.forEach((pl, i) => {
            const card = document.createElement('div');
            card.className = 'playlist-card';
            card.style.animationDelay = (i * 0.04) + 's';
            card.onclick = () => openPlaylistDetail(pl.id);
            card.innerHTML = `
                <div class="playlist-card-icon">
                    <svg viewBox="0 0 24 24"><path d="M15 6H3v2h12V6zm0 4H3v2h12v-2zM3 16h8v-2H3v2zM17 6v8.18c-.31-.11-.65-.18-1-.18-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3V8h3V6h-5z"/></svg>
                </div>
                <div class="playlist-card-info">
                    <div class="playlist-card-name">${pl.name}</div>
                    <div class="playlist-card-count">${pl.count} ${t('song_count_suffix')}</div>
                </div>
            `;
            grid.appendChild(card);
        });
    }

    // ---------- Favoriler ----------
    async function toggleFavoriteFromCard(btn, queueType, index) {
        const item = getQueueArray(queueType)[index];
        if (!item) return;
        btn.classList.add('pop');
        setTimeout(() => btn.classList.remove('pop'), 400);
        try {
            const res = await fetch('/api/favorites/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(item)
            });
            const data = await res.json();
            if (!res.ok || data.error) return;
            favoritesData = data.favorites || [];
            favoriteIds = new Set(favoritesData.map(s => s.id));
            btn.classList.toggle('active', data.is_favorite);
            if (queueType === 'favorites') {
                renderCardList(document.getElementById('favoritesList'), favoritesData, 'favorites', t('no_favorites_yet'));
            }
        } catch (err) { /* sessizce geç */ }
    }

    // ---------- Çalma Listeleri ----------
    function openCreatePlaylistPrompt() {
        const name = prompt(t('prompt_new_playlist'));
        if (!name || !name.trim()) return;
        createPlaylist(name.trim());
    }

    async function createPlaylist(name) {
        try {
            const res = await fetch('/api/playlists', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            const data = await res.json();
            if (!res.ok || data.error) return null;
            playlistsData.push({ id: data.id, name: data.name, count: 0 });
            renderPlaylistGrid();
            return data.id;
        } catch (err) { return null; }
    }

    async function openPlaylistDetail(playlistId) {
        try {
            const res = await fetch(`/api/playlists/${playlistId}`);
            const data = await res.json();
            if (!res.ok || data.error) return;
            activePlaylistId = playlistId;
            activePlaylistSongs = data.songs || [];
            document.getElementById('playlistDetailName').innerText = data.name;
            renderCardList(document.getElementById('playlistDetailSongs'), activePlaylistSongs, 'playlist', t('no_songs_in_playlist'));
            document.getElementById('playlistDetailOverlay').classList.add('active');
        } catch (err) { /* sessizce geç */ }
    }

    function closePlaylistDetail() {
        document.getElementById('playlistDetailOverlay').classList.remove('active');
    }

    function playPlaylistFromStart() {
        if (!activePlaylistSongs.length) return;
        playSong(null, 'playlist', 0);
    }

    async function deleteCurrentPlaylist() {
        if (!activePlaylistId) return;
        if (!confirm(t('confirm_delete_playlist'))) return;
        try {
            await fetch(`/api/playlists/${activePlaylistId}`, { method: 'DELETE' });
            playlistsData = playlistsData.filter(p => p.id !== activePlaylistId);
            renderPlaylistGrid();
            closePlaylistDetail();
        } catch (err) { /* sessizce geç */ }
    }

    // ---------- Alt sayfa (action sheet) ----------
    function openActionSheet(queueType, index) {
        const item = getQueueArray(queueType)[index];
        if (!item) return;
        actionSheetContext = { item, queueType, index };
        document.getElementById('actionSheetTitle').innerText = item.title;
        document.getElementById('actionSheetRemoveFromPlaylist').style.display = queueType === 'playlist' ? 'flex' : 'none';
        document.getElementById('actionSheetOverlay').classList.add('active');
    }

    function closeActionSheet() {
        document.getElementById('actionSheetOverlay').classList.remove('active');
    }

    function actionSheetDownload(type) {
        if (!actionSheetContext) return;
        const item = actionSheetContext.item;
        closeActionSheet();
        const endpoint = type === 'mp4' ? '/api/download-mp4' : '/api/download';
        window.location.href = `${endpoint}?url=${encodeURIComponent(item.url)}`;
    }

    async function actionSheetRemoveFromPlaylist() {
        if (!actionSheetContext || !activePlaylistId) return;
        const item = actionSheetContext.item;
        closeActionSheet();
        try {
            const res = await fetch(`/api/playlists/${activePlaylistId}/songs/${encodeURIComponent(item.id)}`, { method: 'DELETE' });
            const data = await res.json();
            if (!res.ok || data.error) return;
            activePlaylistSongs = data.songs || [];
            renderCardList(document.getElementById('playlistDetailSongs'), activePlaylistSongs, 'playlist', t('no_songs_in_playlist'));
            const pl = playlistsData.find(p => p.id === activePlaylistId);
            if (pl) pl.count = activePlaylistSongs.length;
        } catch (err) { /* sessizce geç */ }
    }

    // ---------- Çalma listesine ekleme seçici ----------
    async function actionSheetAddToPlaylist() {
        closeActionSheet();
        await loadLibrary();
        renderAddToPlaylistList();
        document.getElementById('addToPlaylistStatus').innerText = '';
        document.getElementById('addToPlaylistOverlay').classList.add('active');
    }

    function renderAddToPlaylistList() {
        const listEl = document.getElementById('addToPlaylistList');
        listEl.innerHTML = '';
        if (!playlistsData.length) {
            listEl.innerHTML = `<p class="empty-hint">${t('no_playlists_create_below')}</p>`;
            return;
        }
        playlistsData.forEach(pl => {
            const item = document.createElement('div');
            item.className = 'storage-item';
            item.innerHTML = `
                <div class="storage-item-icon">
                    <svg viewBox="0 0 24 24"><path d="M15 6H3v2h12V6zm0 4H3v2h12v-2zM3 16h8v-2H3v2zM17 6v8.18c-.31-.11-.65-.18-1-.18-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3V8h3V6h-5z"/></svg>
                </div>
                <div class="storage-item-info">
                    <div class="storage-item-label">${pl.name}</div>
                    <div class="storage-item-path">${pl.count} ${t('song_count_suffix')}</div>
                </div>
                <div class="storage-item-check"><svg viewBox="0 0 24 24"><path d="M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg></div>
            `;
            item.onclick = () => addSongToPlaylist(pl.id, item);
            listEl.appendChild(item);
        });
    }

    async function addSongToPlaylist(playlistId, itemEl) {
        if (!actionSheetContext) return;
        const statusEl = document.getElementById('addToPlaylistStatus');
        statusEl.style.color = '#6b7280';
        statusEl.innerText = t('adding');
        try {
            const res = await fetch(`/api/playlists/${playlistId}/songs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(actionSheetContext.item)
            });
            const data = await res.json();
            if (!res.ok || data.error) {
                statusEl.style.color = '#ef4444';
                statusEl.innerText = data.error || t('add_failed');
                return;
            }
            itemEl.classList.add('active');
            const pl = playlistsData.find(p => p.id === playlistId);
            if (pl) pl.count = (data.songs || []).length;
            statusEl.style.color = '#10b981';
            statusEl.innerText = data.already_exists ? t('already_in_playlist') : t('added_to_playlist');
        } catch (err) {
            statusEl.style.color = '#ef4444';
            statusEl.innerText = t('generic_error_dot');
        }
    }

    async function createPlaylistFromPicker() {
        const input = document.getElementById('newPlaylistNameInput');
        const name = input.value.trim();
        if (!name) return;
        const id = await createPlaylist(name);
        input.value = '';
        if (id) {
            renderAddToPlaylistList();
            document.getElementById('addToPlaylistStatus').style.color = '#10b981';
            document.getElementById('addToPlaylistStatus').innerText = t('playlist_created_now_tap');
        }
    }

    function closeAddToPlaylist() {
        document.getElementById('addToPlaylistOverlay').classList.remove('active');
    }

    // ---------- Çalma motoru (arama / favoriler / çalma listesi / indirilenler ortak kuyruk) ----------
    function getStreamUrl(item) {
        if (item.local) return `/api/local-audio/${encodeURIComponent(item.filename)}`;
        return `/api/stream?url=${encodeURIComponent(item.url)}`;
    }

    function playSong(btn, queueType, index) {
        const list = getQueueArray(queueType);
        const item = list[index];
        if (!item) return;
        if (offlineMode && !item.local) {
            showOfflineBlockedToast();
            return;
        }
        ensureAudioGraph();
        if (currentBtn) resetBtnIcon(currentBtn);
        currentBtn = btn;
        activeQueue = list;
        activeQueueType = queueType;
        activeQueueIndex = index;
        if (btn) setBtnLoading(btn);
        crossfadeInProgress = false;
        standbyAudioPlayer.pause();
        standbyAudioPlayer.removeAttribute('src');
        standbyAudioPlayer.volume = 1;
        playerCover.src = item.thumbnail || '';
        playerTitle.innerText = item.title;
        playerStatus.innerText = t('preparing');
        playerPanel.classList.add('active');
        activeAudioPlayer.volume = 1;
        activeAudioPlayer.src = getStreamUrl(item);
        if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
        activeAudioPlayer.play().catch(()=>{});
        updateCanvasBackground(item);
        updateMediaSessionMeta(item);
    }

    function playNext() {
        if (!activeQueue.length || !activeQueueType) return;
        const nextIndex = activeQueueIndex + 1;
        if (nextIndex >= activeQueue.length) {
            playerStatus.innerText = t('end_of_list');
            return;
        }
        playSong(null, activeQueueType, nextIndex);
    }

    function startCrossfade() {
        if (crossfadeInProgress) return;
        const nextIndex = activeQueueIndex + 1;
        const nextItem = activeQueue[nextIndex];
        if (!nextItem || (offlineMode && !nextItem.local)) return;
        crossfadeInProgress = true;
        ensureAudioGraph();
        standbyAudioPlayer.src = getStreamUrl(nextItem);
        standbyAudioPlayer.currentTime = 0;
        standbyAudioPlayer.volume = 0;
        standbyAudioPlayer.play().catch(()=>{});
        const fromEl = activeAudioPlayer;
        const toEl = standbyAudioPlayer;
        const totalMs = crossfadeSeconds * 1000;
        const steps = Math.max(6, crossfadeSeconds * 5);
        const stepTime = totalMs / steps;
        let stepCount = 0;
        const fadeTimer = setInterval(() => {
            stepCount++;
            const ratio = stepCount / steps;
            fromEl.volume = Math.max(0, 1 - ratio);
            toEl.volume = Math.min(1, ratio);
            if (stepCount >= steps) {
                clearInterval(fadeTimer);
                fromEl.pause();
                fromEl.currentTime = 0;
                fromEl.volume = 1;
                activeAudioPlayer = toEl;
                standbyAudioPlayer = fromEl;
                activeQueueIndex = nextIndex;
                crossfadeInProgress = false;
                playerTitle.innerText = nextItem.title;
                playerCover.src = nextItem.thumbnail || '';
                updateCanvasBackground(nextItem);
                updateMediaSessionMeta(nextItem);
            }
        }, stepTime);
    }

    function setBtnLoading(btn) { btn.innerHTML = '<div class="spinner"></div>'; btn.disabled = true; }
    function resetBtnIcon(btn) { btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>'; btn.disabled = false; }

    function onAudioPlaying(e) {
        if (e.target !== activeAudioPlayer) return;
        if (currentBtn) resetBtnIcon(currentBtn);
        playerStatus.innerText = t('playing');
        playIcon.style.display = "none";
        pauseIcon.style.display = "block";
        if ('mediaSession' in navigator) navigator.mediaSession.playbackState = 'playing';
    }
    function onAudioPause(e) {
        if (e.target !== activeAudioPlayer) return;
        playerStatus.innerText = t('paused');
        playIcon.style.display = "block";
        pauseIcon.style.display = "none";
        if ('mediaSession' in navigator) navigator.mediaSession.playbackState = 'paused';
    }
    function onAudioTimeUpdate(e) {
        const el = e.target;
        if (el !== activeAudioPlayer) return;
        if (!isNaN(el.duration)) {
            const progress = (el.currentTime / el.duration) * 100;
            seekBar.value = progress;
            currentTimeEl.innerText = formatTime(el.currentTime);
            durationTimeEl.innerText = formatTime(el.duration);
            if (crossfadeSeconds > 0 && !crossfadeInProgress && autoAdvance &&
                activeQueue.length && activeQueueIndex < activeQueue.length - 1 &&
                (el.duration - el.currentTime) <= crossfadeSeconds && (el.duration - el.currentTime) > 0.15) {
                startCrossfade();
            }
        }
    }
    function onAudioEnded(e) {
        if (e.target !== activeAudioPlayer) return;
        if (autoAdvance) playNext();
    }
    [audioPlayer, audioPlayerAlt].forEach(el => {
        el.addEventListener('playing', onAudioPlaying);
        el.addEventListener('pause', onAudioPause);
        el.addEventListener('timeupdate', onAudioTimeUpdate);
        el.addEventListener('ended', onAudioEnded);
    });
    seekBar.addEventListener('input', () => {
        if (!isNaN(activeAudioPlayer.duration)) {
            activeAudioPlayer.currentTime = (seekBar.value / 100) * activeAudioPlayer.duration;
        }
    });
    function togglePlay() {
        if (activeAudioPlayer.paused) activeAudioPlayer.play();
        else activeAudioPlayer.pause();
    }
    function formatTime(secs) {
        const m = Math.floor(secs / 60);
        const s = Math.floor(secs % 60);
        return `${m}:${s < 10 ? '0' : ''}${s}`;
    }

    // ---------- Ayarlar Paneli ----------
    function toggleSettings(e) {
        if (e) e.stopPropagation();
        document.getElementById('settingsPanel').classList.toggle('active');
    }
    document.addEventListener('click', (e) => {
        const panel = document.getElementById('settingsPanel');
        const btn = document.getElementById('settingsBtn');
        if (panel.classList.contains('active') && !panel.contains(e.target) && e.target !== btn) {
            panel.classList.remove('active');
        }
    });

    // ---------- Çapraz Geçiş (Crossfade) ----------
    function openCrossfadeSettings() {
        document.getElementById('crossfadeSlider').value = crossfadeSeconds;
        document.getElementById('crossfadeValueLabel').innerText = crossfadeSeconds + 's';
        document.getElementById('crossfadeOverlay').classList.add('active');
    }
    function closeCrossfadeSettings() {
        document.getElementById('crossfadeOverlay').classList.remove('active');
    }
    function onCrossfadeChange(val) {
        crossfadeSeconds = parseInt(val, 10);
        localStorage.setItem('hmusic_crossfade', crossfadeSeconds);
        document.getElementById('crossfadeValueLabel').innerText = crossfadeSeconds === 0 ? t('crossfade_off') : crossfadeSeconds + 's';
    }

    // ---------- Önbelleği Temizle ----------
    function formatBytes(bytes) {
        if (!bytes) return '0 MB';
        const mb = bytes / (1024 * 1024);
        if (mb < 1024) return mb.toFixed(1) + ' MB';
        return (mb / 1024).toFixed(2) + ' GB';
    }
    async function openCacheSettings() {
        document.getElementById('cacheOverlay').classList.add('active');
        document.getElementById('cacheStatus').innerText = '';
        document.getElementById('cacheSizeNum').innerText = t('loading');
        try {
            const res = await fetch('/api/cache/info');
            const data = await res.json();
            document.getElementById('cacheSizeNum').innerText = formatBytes(data.size_bytes || 0);
        } catch (err) {
            document.getElementById('cacheSizeNum').innerText = '—';
        }
    }
    function closeCacheSettings() {
        document.getElementById('cacheOverlay').classList.remove('active');
    }
    async function clearCache() {
        const statusEl = document.getElementById('cacheStatus');
        statusEl.style.color = 'var(--text-muted)';
        statusEl.innerText = t('saving');
        try {
            const res = await fetch('/api/cache/clear', { method: 'POST' });
            const data = await res.json();
            if (!res.ok || data.error) {
                statusEl.style.color = 'var(--danger)';
                statusEl.innerText = data.error || t('change_failed');
                return;
            }
            document.getElementById('cacheSizeNum').innerText = formatBytes(0);
            statusEl.style.color = 'var(--accent)';
            statusEl.innerText = t('saved_prefix') + formatBytes(data.freed_bytes || 0);
        } catch (err) {
            statusEl.style.color = 'var(--danger)';
            statusEl.innerText = t('generic_error_dot');
        }
    }

    // ---------- Çevrimdışı Mod ----------
    let offlineMode = localStorage.getItem('hmusic_offline') === '1';
    function applyOfflineModeUI() {
        document.getElementById('offlineModeToggle').checked = offlineMode;
        const searchBtnTab = document.getElementById('tabSearchBtn');
        searchBtnTab.style.opacity = offlineMode ? '0.4' : '1';
        const hint = document.getElementById('offlineModeHint');
        if (offlineMode) {
            hint.style.display = 'block';
            hint.innerText = t('offline_hint');
        } else {
            hint.style.display = 'none';
        }
    }
    function onOfflineModeToggle() {
        offlineMode = document.getElementById('offlineModeToggle').checked;
        localStorage.setItem('hmusic_offline', offlineMode ? '1' : '0');
        applyOfflineModeUI();
        if (offlineMode && document.getElementById('searchTabContent').classList.contains('active')) {
            switchTab('downloaded');
        }
    }
    function showOfflineBlockedToast() {
        alert(t('offline_blocked'));
    }

    // ---------- İndirilenler ----------
    async function loadDownloadedTab() {
        const listEl = document.getElementById('downloadedList');
        listEl.innerHTML = `<p class="empty-hint">${t('loading')}</p>`;
        try {
            const res = await fetch('/api/downloads/local');
            const data = await res.json();
            downloadedData = (data.items || []).map(x => ({ ...x, local: true }));
            renderCardList(listEl, downloadedData, 'downloaded', t('no_downloads_yet'));
        } catch (err) {
            listEl.innerHTML = `<p class="empty-hint">${t('error_occurred')}</p>`;
        }
    }
    async function deleteLocalDownload(index) {
        const item = downloadedData[index];
        if (!item) return;
        if (!confirm(t('confirm_delete_download'))) return;
        try {
            await fetch(`/api/local-audio/${encodeURIComponent(item.filename)}`, { method: 'DELETE' });
        } catch (err) {}
        loadDownloadedTab();
    }

    // ---------- Tema ----------
    let themeMode = localStorage.getItem('hmusic_theme') || 'system';
    function applyTheme() {
        let effective = themeMode;
        if (themeMode === 'system') {
            effective = (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark';
        }
        document.documentElement.setAttribute('data-theme', effective);
        document.getElementById('themeBtnSystem').classList.toggle('active', themeMode === 'system');
        document.getElementById('themeBtnDark').classList.toggle('active', themeMode === 'dark');
        document.getElementById('themeBtnLight').classList.toggle('active', themeMode === 'light');
    }
    function setTheme(mode) {
        themeMode = mode;
        localStorage.setItem('hmusic_theme', mode);
        applyTheme();
    }
    function openThemeSettings() {
        document.getElementById('themeOverlay').classList.add('active');
    }
    function closeThemeSettings() {
        document.getElementById('themeOverlay').classList.remove('active');
    }
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
            if (themeMode === 'system') applyTheme();
        });
    }

    // ---------- Hareketli Kapak (Canvas) ----------
    let canvasEnabled = localStorage.getItem('hmusic_canvas') === '1';
    function onCanvasToggle() {
        canvasEnabled = document.getElementById('canvasToggle').checked;
        localStorage.setItem('hmusic_canvas', canvasEnabled ? '1' : '0');
        if (!canvasEnabled) document.getElementById('canvasBg').classList.remove('active');
        else if (playerPanel.classList.contains('active')) document.getElementById('canvasBg').classList.add('active');
    }
    function updateCanvasBackground(item) {
        const bg = document.getElementById('canvasBg');
        const img = document.getElementById('canvasBgImg');
        if (!canvasEnabled || !item.thumbnail) {
            bg.classList.remove('active');
            return;
        }
        img.src = item.thumbnail;
        bg.classList.add('active');
    }

    // ---------- Kilit Ekranı Kontrolleri (Media Session) ----------
    let lockScreenEnabled = localStorage.getItem('hmusic_lockscreen') !== '0';
    function onLockScreenToggle() {
        lockScreenEnabled = document.getElementById('lockScreenToggle').checked;
        localStorage.setItem('hmusic_lockscreen', lockScreenEnabled ? '1' : '0');
        if (!lockScreenEnabled && 'mediaSession' in navigator) {
            navigator.mediaSession.metadata = null;
        }
    }
    function updateMediaSessionMeta(item) {
        if (!lockScreenEnabled || !('mediaSession' in navigator)) return;
        navigator.mediaSession.metadata = new MediaMetadata({
            title: item.title,
            artist: 'HMusic Stream',
            artwork: item.thumbnail ? [{ src: item.thumbnail, sizes: '512x512', type: 'image/jpeg' }] : []
        });
    }
    if ('mediaSession' in navigator) {
        navigator.mediaSession.setActionHandler('play', () => activeAudioPlayer.play());
        navigator.mediaSession.setActionHandler('pause', () => activeAudioPlayer.pause());
        navigator.mediaSession.setActionHandler('nexttrack', () => playNext());
    }

    // ---------- Ekolayzır & 8D (Web Audio API) ----------
    let audioCtx = null;
    let sourceNode = null;
    let sourceNodeAlt = null;
    let eqFilters = [];
    let eqEnabled = false;
    let pannerNode = null;
    let panLFO = null;
    let panLFOGain = null;
    let eightDEnabled = false;
    let eightDSpeed = 8;
    let compressorNode = null;
    let airFilterNode = null;
    let convolverNode = null;
    let dryGain = null;
    let wetGain = null;
    let sumGain = null;
    let widenSplitter = null;
    let widenMerger = null;
    let widenDelay = null;
    let surroundEnabled = false;
    let surroundAmount = 40;
    const eqBandsConfig = [
        { freq: 60, label: '60' },
        { freq: 250, label: '250' },
        { freq: 1000, label: '1K' },
        { freq: 4000, label: '4K' },
        { freq: 12000, label: '12K' }
    ];
    const eqPresets = {
        flat:   { nameKey: 'preset_flat',   gains: [0, 0, 0, 0, 0] },
        bass:   { nameKey: 'preset_bass',   gains: [7, 4, 0, -1, -2] },
        vocal:  { nameKey: 'preset_vocal',  gains: [-2, 0, 4, 4, 1] },
        treble: { nameKey: 'preset_treble', gains: [-2, -1, 0, 4, 7] }
    };

    function ensureAudioGraph() {
        if (audioCtx) return;
        try {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            sourceNode = audioCtx.createMediaElementSource(audioPlayer);
            sourceNodeAlt = audioCtx.createMediaElementSource(audioPlayerAlt);
            eqFilters = eqBandsConfig.map(band => {
                const f = audioCtx.createBiquadFilter();
                f.type = 'peaking';
                f.frequency.value = band.freq;
                f.Q.value = 1;
                f.gain.value = 0;
                return f;
            });
            let prevNode = sourceNode;
            eqFilters.forEach(f => { prevNode.connect(f); prevNode = f; });
            sourceNodeAlt.connect(eqFilters[0]);

            // Sinema Ses (Surround): dinamik/netlik işleme + algoritmik yankı + stereo genişletme
            compressorNode = audioCtx.createDynamicsCompressor();
            compressorNode.threshold.value = -18;
            compressorNode.knee.value = 24;
            compressorNode.ratio.value = 3;
            compressorNode.attack.value = 0.005;
            compressorNode.release.value = 0.25;

            airFilterNode = audioCtx.createBiquadFilter();
            airFilterNode.type = 'highshelf';
            airFilterNode.frequency.value = 9000;
            airFilterNode.gain.value = 0;

            convolverNode = audioCtx.createConvolver();
            convolverNode.normalize = true;
            convolverNode.buffer = createImpulseResponse(audioCtx, 2.2, 2.6);

            dryGain = audioCtx.createGain();
            dryGain.gain.value = 1;
            wetGain = audioCtx.createGain();
            wetGain.gain.value = 0;
            sumGain = audioCtx.createGain();

            widenSplitter = audioCtx.createChannelSplitter(2);
            widenMerger = audioCtx.createChannelMerger(2);
            widenDelay = audioCtx.createDelay(0.05);
            widenDelay.delayTime.value = 0;

            prevNode.connect(compressorNode);
            compressorNode.connect(airFilterNode);
            airFilterNode.connect(dryGain);
            airFilterNode.connect(convolverNode);
            convolverNode.connect(wetGain);
            dryGain.connect(sumGain);
            wetGain.connect(sumGain);
            sumGain.connect(widenSplitter);
            widenSplitter.connect(widenMerger, 0, 0);
            widenSplitter.connect(widenDelay, 1);
            widenDelay.connect(widenMerger, 0, 1);

            pannerNode = audioCtx.createStereoPanner();
            widenMerger.connect(pannerNode);
            pannerNode.connect(audioCtx.destination);
        } catch (err) {
            console.error('Audio graph oluşturulamadı:', err);
        }
    }

    function createImpulseResponse(ctx, duration, decay) {
        const rate = ctx.sampleRate;
        const length = Math.floor(rate * duration);
        const impulse = ctx.createBuffer(2, length, rate);
        for (let ch = 0; ch < 2; ch++) {
            const data = impulse.getChannelData(ch);
            for (let i = 0; i < length; i++) {
                data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / length, decay);
            }
        }
        return impulse;
    }

    function onSurroundToggle() {
        surroundEnabled = document.getElementById('surroundToggle').checked;
        ensureAudioGraph();
        if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
        applySurroundAmount();
        document.getElementById('surroundAmountRow').style.display = surroundEnabled ? 'flex' : 'none';
    }

    function applySurroundAmount() {
        if (!wetGain || !widenDelay || !airFilterNode) return;
        if (surroundEnabled) {
            const amt = surroundAmount / 100;
            wetGain.gain.value = amt * 0.55;
            widenDelay.delayTime.value = 0.006 + amt * 0.02;
            airFilterNode.gain.value = amt * 5;
        } else {
            wetGain.gain.value = 0;
            widenDelay.delayTime.value = 0;
            airFilterNode.gain.value = 0;
        }
    }

    function onSurroundAmountChange(val) {
        surroundAmount = parseFloat(val);
        document.getElementById('surroundAmountVal').innerText = surroundAmount + '%';
        applySurroundAmount();
    }

    function start8DEffect() {
        if (!audioCtx || !pannerNode) return;
        stop8DEffect();
        panLFO = audioCtx.createOscillator();
        panLFO.type = 'sine';
        panLFO.frequency.value = 1 / eightDSpeed;
        panLFOGain = audioCtx.createGain();
        panLFOGain.gain.value = 1;
        panLFO.connect(panLFOGain);
        panLFOGain.connect(pannerNode.pan);
        panLFO.start();
    }

    function stop8DEffect() {
        if (panLFO) {
            try { panLFO.stop(); } catch (e) {}
            panLFO.disconnect();
            panLFO = null;
        }
        if (panLFOGain) {
            panLFOGain.disconnect();
            panLFOGain = null;
        }
        if (pannerNode) pannerNode.pan.value = 0;
    }

    function on8DToggle() {
        eightDEnabled = document.getElementById('eightDToggle').checked;
        ensureAudioGraph();
        if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
        const speedRow = document.getElementById('eightDSpeedRow');
        if (eightDEnabled) {
            start8DEffect();
            speedRow.style.display = 'flex';
        } else {
            stop8DEffect();
            speedRow.style.display = 'none';
        }
    }

    function on8DSpeedChange(val) {
        eightDSpeed = parseFloat(val);
        document.getElementById('eightDSpeedVal').innerText = eightDSpeed + 's';
        if (panLFO) panLFO.frequency.value = 1 / eightDSpeed;
    }

    function buildEqUI() {
        const bandsContainer = document.getElementById('eqBands');
        bandsContainer.innerHTML = '';
        eqBandsConfig.forEach((band, i) => {
            const wrap = document.createElement('div');
            wrap.className = 'eq-band';
            wrap.innerHTML = `
                <span class="eq-band-val" id="eqVal${i}">0dB</span>
                <input type="range" class="eq-band-slider" id="eqSlider${i}" min="-12" max="12" value="0" step="1" orient="vertical">
                <span class="eq-band-freq">${band.label}</span>
            `;
            bandsContainer.appendChild(wrap);
        });
        eqBandsConfig.forEach((band, i) => {
            const slider = document.getElementById(`eqSlider${i}`);
            slider.addEventListener('input', () => {
                const val = parseInt(slider.value, 10);
                document.getElementById(`eqVal${i}`).innerText = `${val}dB`;
                if (eqFilters[i]) eqFilters[i].gain.value = val;
                clearActivePreset();
            });
        });

        const presetsContainer = document.getElementById('eqPresets');
        presetsContainer.innerHTML = '';
        Object.keys(eqPresets).forEach(key => {
            const b = document.createElement('button');
            b.className = 'eq-preset-btn';
            b.id = `preset-${key}`;
            b.innerText = t(eqPresets[key].nameKey);
            b.onclick = () => applyPreset(key);
            presetsContainer.appendChild(b);
        });
    }

    function clearActivePreset() {
        document.querySelectorAll('.eq-preset-btn').forEach(b => b.classList.remove('active'));
    }

    function applyPreset(key) {
        const preset = eqPresets[key];
        if (!preset) return;
        preset.gains.forEach((g, i) => {
            const slider = document.getElementById(`eqSlider${i}`);
            if (slider) slider.value = g;
            document.getElementById(`eqVal${i}`).innerText = `${g}dB`;
            if (eqFilters[i]) eqFilters[i].gain.value = g;
        });
        clearActivePreset();
        const btn = document.getElementById(`preset-${key}`);
        if (btn) btn.classList.add('active');
        if (key !== 'flat' && !eqEnabled) {
            document.getElementById('eqEnabledToggle').checked = true;
            onEqToggle();
        }
    }

    function onEqToggle() {
        eqEnabled = document.getElementById('eqEnabledToggle').checked;
        const targetGains = eqEnabled ? null : [0, 0, 0, 0, 0];
        if (!eqEnabled) {
            eqFilters.forEach(f => { f.gain.value = 0; });
        } else {
            eqBandsConfig.forEach((band, i) => {
                const slider = document.getElementById(`eqSlider${i}`);
                if (slider && eqFilters[i]) eqFilters[i].gain.value = parseInt(slider.value, 10);
            });
        }
    }

    function openEqualizer() {
        ensureAudioGraph();
        if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
        buildEqUI();
        document.getElementById('eqEnabledToggle').checked = eqEnabled;
        document.getElementById('eightDToggle').checked = eightDEnabled;
        document.getElementById('eightDSpeedRow').style.display = eightDEnabled ? 'flex' : 'none';
        document.getElementById('eightDSpeedSlider').value = eightDSpeed;
        document.getElementById('eightDSpeedVal').innerText = eightDSpeed + 's';
        document.getElementById('surroundToggle').checked = surroundEnabled;
        document.getElementById('surroundAmountRow').style.display = surroundEnabled ? 'flex' : 'none';
        document.getElementById('surroundAmountSlider').value = surroundAmount;
        document.getElementById('surroundAmountVal').innerText = surroundAmount + '%';
        document.getElementById('settingsPanel').classList.remove('active');
        document.getElementById('eqOverlay').classList.add('active');
    }

    function closeEqualizer() {
        document.getElementById('eqOverlay').classList.remove('active');
    }

    // ---------- İndirme Konumu ----------
    const folderIconSvg = '<svg viewBox="0 0 24 24"><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>';

    async function openStorageSettings() {
        document.getElementById('settingsPanel').classList.remove('active');
        document.getElementById('storageOverlay').classList.add('active');
        document.getElementById('storageStatus').innerText = '';
        const listEl = document.getElementById('storageList');
        listEl.innerHTML = `<p style="text-align:center; color:#6b7280; font-size:12px;">${t('loading')}</p>`;
        try {
            const res = await fetch('/api/settings/storage');
            const data = await res.json();
            renderStorageList(data.options || [], data.current || '');
        } catch (err) {
            listEl.innerHTML = `<p style="text-align:center; color:#ef4444; font-size:12px;">${t('storage_load_failed')}</p>`;
        }
    }

    function renderStorageList(options, current) {
        const listEl = document.getElementById('storageList');
        listEl.innerHTML = '';
        if (!options.length) {
            listEl.innerHTML = `<p style="text-align:center; color:#6b7280; font-size:12px;">${t('storage_none_found')}</p>`;
            return;
        }
        options.forEach(opt => {
            const isActive = opt.path === current;
            const item = document.createElement('div');
            item.className = 'storage-item' + (isActive ? ' active' : '');
            item.onclick = () => selectStorage(opt.key, item);
            item.innerHTML = `
                <div class="storage-item-icon">${folderIconSvg}</div>
                <div class="storage-item-info">
                    <div class="storage-item-label">${opt.label}</div>
                    <div class="storage-item-path">${opt.path}</div>
                </div>
                <div class="storage-item-check">
                    <svg viewBox="0 0 24 24"><path d="M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg>
                </div>
            `;
            listEl.appendChild(item);
        });
    }

    async function selectStorage(key, itemEl) {
        const statusEl = document.getElementById('storageStatus');
        statusEl.style.color = '#6b7280';
        statusEl.innerText = t('saving');
        try {
            const res = await fetch('/api/settings/storage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key })
            });
            const data = await res.json();
            if (!res.ok || data.error) {
                statusEl.style.color = '#ef4444';
                statusEl.innerText = data.error || t('change_failed');
                return;
            }
            document.querySelectorAll('.storage-item').forEach(el => el.classList.remove('active'));
            itemEl.classList.add('active');
            statusEl.style.color = '#10b981';
            statusEl.innerText = t('saved_prefix') + data.current;
        } catch (err) {
            statusEl.style.color = '#ef4444';
            statusEl.innerText = t('generic_error_dot');
        }
    }

    function closeStorageSettings() {
        document.getElementById('storageOverlay').classList.remove('active');
    }

    loadLibrary();
    applyStaticTexts();
    applyTheme();
    document.getElementById('canvasToggle').checked = canvasEnabled;
    document.getElementById('lockScreenToggle').checked = lockScreenEnabled;
</script>
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HMusic - Yönetim Paneli</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
        body { background-color: #0b0e14; color: #f3f4f6; padding: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        .admin-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; }
        .admin-header h1 { font-size: 22px; color: #10b981; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 25px; }
        .stat-card { background: #171c26; padding: 16px; border-radius: 12px; border: 1px solid #232a3b; }
        .stat-card h3 { font-size: 11px; color: #9ca3af; text-transform: uppercase; margin-bottom: 4px; }
        .stat-card p { font-size: 20px; font-weight: 700; color: #fff; }
        .table-container { background: #171c26; border-radius: 12px; border: 1px solid #232a3b; overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th, td { padding: 12px 14px; font-size: 12px; border-bottom: 1px solid #202738; }
        th { background: #11151f; color: #9ca3af; }
        .badge { padding: 3px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; }
        .badge-active { background: rgba(16, 185, 129, 0.2); color: #10b981; }
        .badge-banned { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
        .btn-action { border: none; padding: 5px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; cursor: pointer; }
        .btn-ban { background: #ef4444; color: #fff; }
        .btn-unban { background: #10b981; color: #fff; }
    </style>
</head>
<body>
    <div class="container">
        <div class="admin-header">
            <h1>HMusic Yönetim Paneli</h1>
        </div>
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Toplam Ziyaretçi</h3>
                <p>{{ total_users }}</p>
            </div>
            <div class="stat-card">
                <h3>Toplam Dinleme</h3>
                <p>{{ total_plays }}</p>
            </div>
            <div class="stat-card">
                <h3>İndirilen MP3</h3>
                <p>{{ total_mp3 }}</p>
            </div>
            <div class="stat-card">
                <h3>İndirilen MP4</h3>
                <p>{{ total_mp4 }}</p>
            </div>
        </div>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>IP Adresi</th>
                        <th>Dinleme</th>
                        <th>MP3</th>
                        <th>MP4</th>
                        <th>Son Aktiflik</th>
                        <th>Durum</th>
                        <th>İşlem</th>
                    </tr>
                </thead>
                <tbody>
                    {% for ip, stats in users.items() %}
                    <tr>
                        <td><strong>{{ ip }}</strong></td>
                        <td>{{ stats.plays }}</td>
                        <td>{{ stats.mp3 }}</td>
                        <td>{{ stats.mp4 }}</td>
                        <td>{{ stats.last_active }}</td>
                        <td>
                            {% if stats.banned %}
                            <span class="badge badge-banned">Banlı</span>
                            {% else %}
                            <span class="badge badge-active">Aktif</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if stats.banned %}
                            <a href="/admin/unban?ip={{ ip }}&key={{ secret_key }}"><button class="btn-action btn-unban">Ban Kaldır</button></a>
                            {% else %}
                            <a href="/admin/ban?ip={{ ip }}&key={{ secret_key }}"><button class="btn-action btn-ban">Banla</button></a>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                    {% if not users %}
                    <tr>
                        <td colspan="7" style="text-align: center; color: #6b7280;">Henüz kullanıcı kaydı yok.</td>
                    </tr>
                    {% endif %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    ip = request.remote_addr
    track_user_action(ip, None)
    return render_template_string(USER_HTML)

@app.route('/admin')
def admin_panel():
    key = request.args.get('key')
    if key != ADMIN_SECRET_KEY:
        abort(404) # Doğru gizli anahtar verilmezse 404 hatası verir (sayfa yokmuş gibi)
    
    total_users = len(user_stats)
    total_plays = sum(u['plays'] for u in user_stats.values())
    total_mp3 = sum(u['mp3'] for u in user_stats.values())
    total_mp4 = sum(u['mp4'] for u in user_stats.values())

    return render_template_string(
        ADMIN_HTML,
        users=user_stats,
        total_users=total_users,
        total_plays=total_plays,
        total_mp3=total_mp3,
        total_mp4=total_mp4,
        secret_key=ADMIN_SECRET_KEY
    )

@app.route('/admin/ban')
def admin_ban_ip():
    key = request.args.get('key')
    if key != ADMIN_SECRET_KEY:
        abort(404)
    ip = request.args.get('ip')
    if ip in user_stats:
        user_stats[ip]['banned'] = True
        save_stats(user_stats)
    return redirect(url_for('admin_panel', key=ADMIN_SECRET_KEY))

@app.route('/admin/unban')
def admin_unban_ip():
    key = request.args.get('key')
    if key != ADMIN_SECRET_KEY:
        abort(404)
    ip = request.args.get('ip')
    if ip in user_stats:
        user_stats[ip]['banned'] = False
        save_stats(user_stats)
    return redirect(url_for('admin_panel', key=ADMIN_SECRET_KEY))

@app.route('/api/settings/storage', methods=['GET'])
def get_storage_settings():
    return jsonify({
        'current': DOWNLOAD_FOLDER,
        'options': get_storage_options()
    })

@app.route('/api/settings/storage', methods=['POST'])
@limiter.limit("10 per minute")
def set_storage_settings():
    global DOWNLOAD_FOLDER
    data = request.get_json(silent=True) or {}
    key = data.get('key')
    options = get_storage_options()
    match = next((o for o in options if o['key'] == key), None)
    if not match:
        return jsonify({"error": "Geçersiz depolama seçimi"}), 400
    try:
        os.makedirs(match['path'], exist_ok=True)
    except Exception:
        return jsonify({"error": "Klasör oluşturulamadı. Depolama izinlerini kontrol edin."}), 500
    DOWNLOAD_FOLDER = match['path']
    app_config['download_folder'] = DOWNLOAD_FOLDER
    save_config(app_config)
    return jsonify({"success": True, "current": DOWNLOAD_FOLDER})

@app.route('/api/library', methods=['GET'])
def get_library():
    ip = request.remote_addr
    lib = get_user_lib(ip)
    playlists = [
        {"id": pid, "name": pl["name"], "count": len(pl["songs"])}
        for pid, pl in lib["playlists"].items()
    ]
    return jsonify({"favorites": lib["favorites"], "playlists": playlists})

@app.route('/api/favorites/toggle', methods=['POST'])
@limiter.limit("60 per minute")
def toggle_favorite():
    ip = request.remote_addr
    data = request.get_json(silent=True) or {}
    song_id = (data.get('id') or '').strip()
    if not song_id:
        return jsonify({"error": "Geçersiz şarkı"}), 400
    lib = get_user_lib(ip)
    exists = any(s["id"] == song_id for s in lib["favorites"])
    if exists:
        lib["favorites"] = [s for s in lib["favorites"] if s["id"] != song_id]
        is_fav = False
    else:
        song = clean_song_payload(data)
        if not song:
            return jsonify({"error": "Geçersiz şarkı verisi"}), 400
        lib["favorites"].insert(0, song)
        is_fav = True
    save_library(user_library)
    return jsonify({"success": True, "is_favorite": is_fav, "favorites": lib["favorites"]})

@app.route('/api/playlists', methods=['POST'])
@limiter.limit("20 per minute")
def create_playlist():
    ip = request.remote_addr
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()[:60]
    if not name:
        return jsonify({"error": "Çalma listesi adı gerekli"}), 400
    lib = get_user_lib(ip)
    pl_id = secrets.token_hex(6)
    lib["playlists"][pl_id] = {"name": name, "songs": []}
    save_library(user_library)
    return jsonify({"success": True, "id": pl_id, "name": name, "count": 0})

@app.route('/api/playlists/<playlist_id>', methods=['GET'])
def get_playlist(playlist_id):
    ip = request.remote_addr
    lib = get_user_lib(ip)
    pl = lib["playlists"].get(playlist_id)
    if not pl:
        return jsonify({"error": "Çalma listesi bulunamadı"}), 404
    return jsonify({"id": playlist_id, "name": pl["name"], "songs": pl["songs"]})

@app.route('/api/playlists/<playlist_id>', methods=['DELETE'])
@limiter.limit("20 per minute")
def delete_playlist(playlist_id):
    ip = request.remote_addr
    lib = get_user_lib(ip)
    if playlist_id in lib["playlists"]:
        del lib["playlists"][playlist_id]
        save_library(user_library)
    return jsonify({"success": True})

@app.route('/api/playlists/<playlist_id>/songs', methods=['POST'])
@limiter.limit("60 per minute")
def add_song_to_playlist(playlist_id):
    ip = request.remote_addr
    lib = get_user_lib(ip)
    pl = lib["playlists"].get(playlist_id)
    if not pl:
        return jsonify({"error": "Çalma listesi bulunamadı"}), 404
    data = request.get_json(silent=True) or {}
    song = clean_song_payload(data)
    if not song:
        return jsonify({"error": "Geçersiz şarkı verisi"}), 400
    if any(s["id"] == song["id"] for s in pl["songs"]):
        return jsonify({"success": True, "already_exists": True, "songs": pl["songs"]})
    pl["songs"].append(song)
    save_library(user_library)
    return jsonify({"success": True, "songs": pl["songs"]})

@app.route('/api/playlists/<playlist_id>/songs/<song_id>', methods=['DELETE'])
@limiter.limit("60 per minute")
def remove_song_from_playlist(playlist_id, song_id):
    ip = request.remote_addr
    lib = get_user_lib(ip)
    pl = lib["playlists"].get(playlist_id)
    if not pl:
        return jsonify({"error": "Çalma listesi bulunamadı"}), 404
    pl["songs"] = [s for s in pl["songs"] if s["id"] != song_id]
    save_library(user_library)
    return jsonify({"success": True, "songs": pl["songs"]})

@app.route('/api/search', methods=['GET'])
@limiter.limit("15 per minute")
def search_music():
    ip = request.remote_addr
    track_user_action(ip, None)
    
    query = request.args.get('q', '').strip()
    if not query or len(query) > 100:
        return jsonify({"error": "Geçersiz arama terimi"}), 400
    
    clean_query = re.sub(r'[^\w\s\d\-]', '', query)

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
                return jsonify(results)
        except Exception:
            continue

    try:
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
            return jsonify(results)
    except Exception:
        return jsonify({"error": "Arama işlemi gerçekleştirilemedi."}), 500

DOWNLOADS_META_FILE = os.path.join(DOWNLOAD_FOLDER, '.hmusic_meta.json')

def load_downloads_meta():
    if os.path.exists(DOWNLOADS_META_FILE):
        try:
            with open(DOWNLOADS_META_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_downloads_meta(meta):
    try:
        with open(DOWNLOADS_META_FILE, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Meta kaydetme hatasi: {e}")

def process_youtube_mp3(url, folder=None):
    folder = folder or DOWNLOAD_FOLDER
    out_template = f"{folder}/%(id)s.%(ext)s"
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': out_template,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'ios']}}
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = f"{folder}/{info['id']}.mp3"
        return file_path, info.get('title', 'muzik')

def process_youtube_mp4(url):
    out_template = f"{DOWNLOAD_FOLDER}/%(id)s_video.%(ext)s"
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': out_template,
        'quiet': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'ios']}}
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = f"{DOWNLOAD_FOLDER}/{info['id']}_video.mp4"
        return file_path, info.get('title', 'video')

@app.route('/api/stream', methods=['GET'])
@limiter.limit("20 per minute")
def stream_audio():
    ip = request.remote_addr
    track_user_action(ip, "plays")
    
    url = request.args.get('url')
    if not is_valid_youtube_url(url):
        return jsonify({"error": "Geçersiz veya yetkisiz URL"}), 400
    try:
        file_path, _ = process_youtube_mp3(url, CACHE_FOLDER)
        return send_file(file_path, mimetype='audio/mpeg')
    except Exception:
        return jsonify({"error": "Ses akışı başlatılamadı."}), 500

@app.route('/api/download', methods=['GET'])
@limiter.limit("5 per minute")
def download_audio():
    ip = request.remote_addr
    track_user_action(ip, "mp3")
    
    url = request.args.get('url')
    if not is_valid_youtube_url(url):
        return jsonify({"error": "Geçersiz veya yetkisiz URL"}), 400
    try:
        file_path, title = process_youtube_mp3(url, DOWNLOAD_FOLDER)
        clean_title = re.sub(r'[^\w\s\d\-]', '', title).strip()
        video_id = os.path.splitext(os.path.basename(file_path))[0]
        meta = load_downloads_meta()
        meta[video_id] = title
        save_downloads_meta(meta)
        return send_file(file_path, as_attachment=True, download_name=f"{clean_title}.mp3", mimetype='audio/mpeg')
    except Exception:
        return jsonify({"error": "İndirme başarısız."}), 500

@app.route('/api/download-mp4', methods=['GET'])
@limiter.limit("3 per minute")
def download_video():
    ip = request.remote_addr
    track_user_action(ip, "mp4")
    
    url = request.args.get('url')
    if not is_valid_youtube_url(url):
        return jsonify({"error": "Geçersiz veya yetkisiz URL"}), 400
    try:
        file_path, title = process_youtube_mp4(url)
        clean_title = re.sub(r'[^\w\s\d\-]', '', title).strip()
        return send_file(file_path, as_attachment=True, download_name=f"{clean_title}.mp4", mimetype='video/mp4')
    except Exception:
        return jsonify({"error": "Video indirme başarısız."}), 500

@app.route('/api/cache/info', methods=['GET'])
def cache_info():
    total = 0
    try:
        for fname in os.listdir(CACHE_FOLDER):
            fpath = os.path.join(CACHE_FOLDER, fname)
            if os.path.isfile(fpath):
                total += os.path.getsize(fpath)
    except Exception:
        pass
    return jsonify({"size_bytes": total})

@app.route('/api/cache/clear', methods=['POST'])
def cache_clear():
    freed = 0
    try:
        for fname in os.listdir(CACHE_FOLDER):
            fpath = os.path.join(CACHE_FOLDER, fname)
            if os.path.isfile(fpath):
                freed += os.path.getsize(fpath)
                os.remove(fpath)
    except Exception:
        return jsonify({"error": "Önbellek temizlenemedi."}), 500
    return jsonify({"success": True, "freed_bytes": freed})

@app.route('/api/downloads/local', methods=['GET'])
def downloads_local():
    meta = load_downloads_meta()
    items = []
    try:
        for fname in sorted(os.listdir(DOWNLOAD_FOLDER)):
            if not fname.lower().endswith('.mp3'):
                continue
            video_id = os.path.splitext(fname)[0]
            title = meta.get(video_id, video_id)
            items.append({
                'id': video_id,
                'title': title,
                'filename': fname,
                'thumbnail': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
            })
    except Exception:
        pass
    return jsonify({"items": items})

def _safe_local_audio_path(filename):
    safe_name = secure_filename(filename)
    if not safe_name or not safe_name.lower().endswith('.mp3'):
        return None
    full_path = os.path.abspath(os.path.join(DOWNLOAD_FOLDER, safe_name))
    if not full_path.startswith(os.path.abspath(DOWNLOAD_FOLDER) + os.sep):
        return None
    return full_path

@app.route('/api/local-audio/<path:filename>', methods=['GET'])
def local_audio(filename):
    full_path = _safe_local_audio_path(filename)
    if not full_path or not os.path.isfile(full_path):
        return jsonify({"error": "Dosya bulunamadı."}), 404
    return send_file(full_path, mimetype='audio/mpeg')

@app.route('/api/local-audio/<path:filename>', methods=['DELETE'])
def local_audio_delete(filename):
    full_path = _safe_local_audio_path(filename)
    if not full_path or not os.path.isfile(full_path):
        return jsonify({"error": "Dosya bulunamadı."}), 404
    try:
        os.remove(full_path)
        video_id = os.path.splitext(os.path.basename(full_path))[0]
        meta = load_downloads_meta()
        if video_id in meta:
            del meta[video_id]
            save_downloads_meta(meta)
        return jsonify({"success": True})
    except Exception:
        return jsonify({"error": "Silinemedi."}), 500

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"error": "Çok fazla istek gönderdiniz. Lütfen bir süre bekleyin."}), 429

if __name__ == '__main__':
    print("\n" + "="*50)
    print(" GİZLİ ADMİN PANELİ LİNKİNİZ:")
    print(f" http://127.0.0.1:5000/admin?key={ADMIN_SECRET_KEY}")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
