from flask import Flask, request, jsonify, send_file, render_template_string, redirect, url_for, abort
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
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

# Railway / bulut ortamı için rastgele admin key
ADMIN_SECRET_KEY = secrets.token_hex(16)

CORS(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Railway uyumlu olarak geçici veya kalıcı /tmp dizini kullanımı
BASE_STORAGE_DIR = '/tmp/hmusic_storage'
DEFAULT_DOWNLOAD_FOLDER = os.path.join(BASE_STORAGE_DIR, 'MusicDownloads')
STATS_FILE = os.path.join(BASE_STORAGE_DIR, 'stats.json')
CONFIG_FILE = os.path.join(BASE_STORAGE_DIR, 'config.json')
LIBRARY_FILE = os.path.join(BASE_STORAGE_DIR, 'library.json')

# Gerekli klasörleri oluştur
os.makedirs(DEFAULT_DOWNLOAD_FOLDER, exist_ok=True)

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

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

def get_storage_options():
    """Railway bulut ortamı için depolama seçenekleri."""
    return [
        {
            'key': 'tmp_storage',
            'label': 'Bulut Geçici Depolama (/tmp)',
            'path': DEFAULT_DOWNLOAD_FOLDER
        }
    ]

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
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
        body { background-color: #0b0e14; color: #f3f4f6; padding: 20px 15px 140px 15px; }
        .header { text-align: center; margin-bottom: 25px; position: relative; }
        .header h1 { font-size: 24px; font-weight: 700; color: #10b981; letter-spacing: -0.5px; }
        .header p { font-size: 12px; color: #6b7280; margin-top: 4px; }

        .settings-btn { position: fixed; top: 18px; left: 15px; width: 38px; height: 38px; border-radius: 12px; background: #171c26; border: 1px solid #232a3b; color: #9ca3af; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 30; transition: 0.2s; }
        .settings-btn:active { transform: scale(0.94); color: #10b981; }
        .settings-btn svg { width: 20px; height: 20px; fill: currentColor; }

        .settings-panel { position: fixed; top: 62px; left: 15px; background: #171c26; border: 1px solid #232a3b; border-radius: 14px; padding: 8px; z-index: 30; display: none; flex-direction: column; gap: 4px; box-shadow: 0 10px 30px rgba(0,0,0,0.4); min-width: 190px; }
        .settings-panel.active { display: flex; }
        .settings-item { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 10px; cursor: pointer; color: #f3f4f6; font-size: 13px; font-weight: 500; }
        .settings-item:active { background: #202738; }
        .settings-item svg { width: 18px; height: 18px; fill: #10b981; flex-shrink: 0; }

        .overlay-bg { position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 40; display: flex; align-items: flex-end; justify-content: center; opacity: 0; visibility: hidden; transition: opacity 0.25s ease, visibility 0.25s ease; }
        .overlay-bg.active { opacity: 1; visibility: visible; }
        .eq-modal { background: #12161f; border: 1px solid #232a3b; border-radius: 20px 20px 0 0; width: 100%; max-width: 480px; padding: 20px 20px 28px 20px; transform: translateY(24px); transition: transform 0.28s ease; }
        .overlay-bg.active .eq-modal { transform: translateY(0); }
        .eq-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
        .eq-header h2 { font-size: 16px; font-weight: 700; color: #f3f4f6; }
        .eq-close-btn { width: 30px; height: 30px; border-radius: 8px; border: none; background: #202738; color: #9ca3af; font-size: 15px; cursor: pointer; }
        .eq-sub { font-size: 11px; color: #6b7280; margin-bottom: 18px; }
        .eq-toggle-row { display: flex; align-items: center; justify-content: space-between; background: #171c26; padding: 12px 14px; border-radius: 12px; margin-bottom: 18px; border: 1px solid #232a3b; }
        .eq-toggle-row span { font-size: 13px; font-weight: 600; color: #f3f4f6; }
        .switch { position: relative; width: 42px; height: 24px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .switch-slider { position: absolute; inset: 0; background: #2a3447; border-radius: 24px; cursor: pointer; transition: 0.2s; }
        .switch-slider:before { content: ""; position: absolute; width: 18px; height: 18px; left: 3px; top: 3px; background: #fff; border-radius: 50%; transition: 0.2s; }
        .switch input:checked + .switch-slider { background: #10b981; }
        .switch input:checked + .switch-slider:before { transform: translateX(18px); }
        .eq-bands { display: flex; justify-content: space-between; gap: 6px; height: 160px; margin-bottom: 20px; }
        .eq-band { display: flex; flex-direction: column; align-items: center; gap: 8px; flex: 1; }
        .eq-band-slider { -webkit-appearance: slider-vertical; writing-mode: vertical-lr; direction: rtl; width: 6px; height: 110px; background: #2a3447; border-radius: 4px; outline: none; accent-color: #10b981; }
        .eq-band-freq { font-size: 10px; color: #6b7280; }
        .eq-band-val { font-size: 10px; color: #10b981; font-weight: 600; }
        .eq-presets { display: flex; gap: 8px; flex-wrap: wrap; }
        .eq-preset-btn { flex: 1; background: #171c26; border: 1px solid #232a3b; color: #d1d5db; padding: 9px 6px; border-radius: 10px; font-size: 11px; font-weight: 600; cursor: pointer; }
        .eq-preset-btn.active { background: rgba(16,185,129,0.15); border-color: #10b981; color: #10b981; }
        .player-controls-right { display: flex; align-items: center; gap: 8px; }
        .player-next-btn { width: 34px; height: 34px; border-radius: 50%; background: #202738; border: none; color: #f3f4f6; display: flex; align-items: center; justify-content: center; cursor: pointer; }
        .player-next-btn svg { width: 16px; height: 16px; fill: currentColor; }

        .storage-modal { background: #12161f; border: 1px solid #232a3b; border-radius: 20px 20px 0 0; width: 100%; max-width: 480px; padding: 20px 20px 28px 20px; transform: translateY(24px); transition: transform 0.28s ease; }
        .overlay-bg.active .storage-modal { transform: translateY(0); }
        .storage-list { display: flex; flex-direction: column; gap: 10px; margin-top: 16px; }
        .storage-item { display: flex; align-items: center; gap: 12px; background: #171c26; border: 1px solid #232a3b; border-radius: 14px; padding: 12px 14px; cursor: pointer; }
        .storage-item.active { border-color: #10b981; background: rgba(16, 185, 129, 0.08); }
        .storage-item-icon { width: 36px; height: 36px; border-radius: 10px; background: rgba(16, 185, 129, 0.12); color: #10b981; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .storage-item-icon svg { width: 18px; height: 18px; fill: currentColor; }
        .storage-item-info { flex: 1; overflow: hidden; }
        .storage-item-label { font-size: 13px; font-weight: 600; color: #f3f4f6; }
        .storage-item-path { font-size: 10px; color: #6b7280; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .storage-item-check { width: 18px; height: 18px; border-radius: 50%; border: 2px solid #2a3447; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
        .storage-item.active .storage-item-check { border-color: #10b981; background: #10b981; }
        .storage-item-check svg { width: 11px; height: 11px; fill: #0b0e14; display: none; }
        .storage-item.active .storage-item-check svg { display: block; }
        .storage-status { font-size: 11px; color: #10b981; margin-top: 12px; min-height: 14px; }
        .search-box { display: flex; gap: 10px; background: #171c26; padding: 6px; border-radius: 14px; border: 1px solid #232a3b; }
        .search-box input { flex: 1; border: none; background: transparent; padding: 12px 16px; color: #fff; font-size: 15px; outline: none; }
        .search-box button { background: #10b981; border: none; color: #fff; padding: 0 20px; border-radius: 10px; font-weight: 600; cursor: pointer; }
        .results-list { display: flex; flex-direction: column; gap: 12px; margin-top: 20px; }
        .card { display: flex; align-items: center; background: #171c26; padding: 10px 14px; border-radius: 14px; gap: 12px; border: 1px solid #202738; opacity: 0; transform: translateY(10px); animation: cardIn 0.35s ease forwards; }
        .card img { width: 52px; height: 52px; border-radius: 10px; object-fit: cover; }
        .card-info { flex: 1; overflow: hidden; }
        .card-title { font-size: 14px; font-weight: 600; color: #f3f4f6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .card-artist { font-size: 12px; color: #9ca3af; margin-top: 2px; }
        .action-btns { display: flex; gap: 6px; }
        .icon-btn { width: 38px; height: 38px; border-radius: 10px; border: none; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: transform 0.15s ease; }
        .icon-btn:active { transform: scale(0.9); }
        .btn-play { background: rgba(16, 185, 129, 0.15); color: #10b981; }
        .btn-heart { background: rgba(239, 68, 68, 0.1); color: #6b7280; }
        .btn-heart.active { color: #ef4444; background: rgba(239, 68, 68, 0.18); }
        .btn-heart.pop svg { animation: heartPop 0.4s ease; }
        .btn-more { background: rgba(107, 114, 128, 0.15); color: #9ca3af; }
        .icon-btn svg { width: 18px; height: 18px; fill: currentColor; }
        .spinner { width: 16px; height: 16px; border: 2.5px solid rgba(255,255,255,0.2); border-top-color: currentColor; border-radius: 50%; animation: spin 0.8s linear infinite; }
        @keyframes cardIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes heartPop { 0% { transform: scale(1); } 40% { transform: scale(1.4); } 100% { transform: scale(1); } }

        .tab-bar { display: flex; gap: 6px; background: #12161f; border: 1px solid #232a3b; border-radius: 14px; padding: 5px; margin-top: 16px; }
        .tab-btn { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px; background: transparent; border: none; color: #6b7280; padding: 9px 4px; border-radius: 10px; font-size: 10px; font-weight: 600; cursor: pointer; transition: 0.2s; }
        .tab-btn svg { width: 18px; height: 18px; fill: currentColor; }
        .tab-btn.active { background: rgba(16, 185, 129, 0.14); color: #10b981; }
        .tab-content { display: none; }
        .tab-content.active { display: block; animation: fadeSlideIn 0.25s ease; }
        @keyframes fadeSlideIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        .empty-hint { text-align: center; color: #6b7280; margin-top: 24px; font-size: 12px; }

        .create-playlist-btn { width: 100%; background: rgba(16, 185, 129, 0.12); border: 1px dashed #10b981; color: #10b981; padding: 13px; border-radius: 14px; font-size: 13px; font-weight: 600; cursor: pointer; margin-top: 18px; transition: transform 0.15s ease; }
        .create-playlist-btn:active { transform: scale(0.98); }
        .playlist-grid { display: flex; flex-direction: column; gap: 10px; margin-top: 14px; }
        .playlist-card { display: flex; align-items: center; gap: 12px; background: #171c26; border: 1px solid #202738; padding: 12px 14px; border-radius: 14px; cursor: pointer; opacity: 0; transform: translateY(10px); animation: cardIn 0.35s ease forwards; transition: transform 0.15s ease; }
        .playlist-card:active { transform: scale(0.98); }
        .playlist-card-icon { width: 44px; height: 44px; border-radius: 12px; background: rgba(16, 185, 129, 0.15); color: #10b981; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .playlist-card-icon svg { width: 20px; height: 20px; fill: currentColor; }
        .playlist-card-info { flex: 1; overflow: hidden; }
        .playlist-card-name { font-size: 14px; font-weight: 600; color: #f3f4f6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .playlist-card-count { font-size: 11px; color: #6b7280; margin-top: 2px; }

        .action-sheet, .storage-modal.picker-modal { background: #12161f; border: 1px solid #232a3b; border-radius: 20px 20px 0 0; width: 100%; max-width: 480px; padding: 18px 20px 26px 20px; transform: translateY(24px); transition: transform 0.28s ease; }
        .overlay-bg.active .action-sheet { transform: translateY(0); }
        .action-sheet-title { font-size: 13px; font-weight: 700; color: #f3f4f6; margin-bottom: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .action-sheet-item { display: flex; align-items: center; gap: 12px; padding: 13px 6px; border-radius: 10px; cursor: pointer; color: #f3f4f6; font-size: 13px; font-weight: 500; border-bottom: 1px solid #1c2230; }
        .action-sheet-item:last-child { border-bottom: none; }
        .action-sheet-item:active { background: #1a2130; }
        .action-sheet-item svg { width: 18px; height: 18px; fill: #10b981; flex-shrink: 0; }
        .action-sheet-item.danger svg { fill: #ef4444; }
        .action-sheet-item.danger span { color: #ef4444; }
        .new-playlist-row { display: flex; gap: 8px; margin-top: 10px; }
        .new-playlist-row input { flex: 1; background: #171c26; border: 1px solid #232a3b; border-radius: 10px; padding: 11px 12px; color: #fff; font-size: 13px; outline: none; }
        .new-playlist-row button { background: #10b981; border: none; color: #fff; padding: 0 16px; border-radius: 10px; font-weight: 600; cursor: pointer; }
        .play-all-btn { flex: 1; background: rgba(16, 185, 129, 0.15); border: none; color: #10b981; padding: 11px; border-radius: 12px; font-size: 12px; font-weight: 700; cursor: pointer; }
        .delete-playlist-btn { background: rgba(239, 68, 68, 0.12); border: none; color: #ef4444; padding: 11px 16px; border-radius: 12px; font-size: 12px; font-weight: 700; cursor: pointer; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .modern-player { position: fixed; bottom: 15px; left: 15px; right: 15px; background: rgba(23, 28, 38, 0.95); backdrop-filter: blur(12px); border: 1px solid #2a3447; padding: 12px 16px; border-radius: 18px; display: flex; flex-direction: column; gap: 8px; opacity: 0; pointer-events: none; transition: 0.3s; }
        .modern-player.active { opacity: 1; pointer-events: auto; }
        .player-top { display: flex; align-items: center; gap: 12px; }
        .player-cover { width: 44px; height: 44px; border-radius: 8px; object-fit: cover; }
        .player-details { flex: 1; overflow: hidden; }
        .player-title { font-size: 13px; font-weight: 600; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .player-status { font-size: 11px; color: #10b981; margin-top: 2px; }
        .player-main-btn { width: 40px; height: 40px; border-radius: 50%; background: #10b981; border: none; color: #fff; display: flex; align-items: center; justify-content: center; cursor: pointer; }
        .player-main-btn svg { width: 20px; height: 20px; fill: #fff; }
        .progress-container { width: 100%; display: flex; align-items: center; gap: 8px; }
        .progress-bar { flex: 1; height: 4px; background: #2a3447; border-radius: 2px; appearance: none; outline: none; cursor: pointer; }
        .time-text { font-size: 10px; color: #6b7280; width: 30px; }
    </style>
</head>
<body>
    <button class="settings-btn" id="settingsBtn" onclick="toggleSettings(event)">
        <svg viewBox="0 0 24 24"><path d="M19.14,12.94c0.04,-0.3 0.06,-0.61 0.06,-0.94c0,-0.32 -0.02,-0.64 -0.07,-0.94l2.03,-1.58c0.18,-0.14 0.23,-0.41 0.12,-0.61l-1.92,-3.32c-0.12,-0.22 -0.37,-0.29 -0.59,-0.22l-2.39,0.96c-0.5,-0.38 -1.03,-0.7 -1.62,-0.94L14.4,2.81c-0.04,-0.24 -0.24,-0.41 -0.48,-0.41h-3.84c-0.24,0 -0.43,0.17 -0.47,0.41L9.25,5.35C8.66,5.59 8.12,5.92 7.63,6.29L5.24,5.33c-0.22,-0.08 -0.47,0 -0.59,0.22L2.74,8.87C2.62,9.08 2.66,9.34 2.86,9.48l2.03,1.58C4.84,11.36 4.8,11.69 4.8,12s0.02,0.64 0.07,0.94l-2.03,1.58c-0.18,0.14 -0.23,0.41 -0.12,0.61l1.92,3.32c0.12,0.22 0.37,0.29 0.59,0.22l2.39,-0.96c0.5,0.38 1.03,0.7 1.62,0.94l0.36,2.54c0.05,0.24 0.24,0.41 0.48,0.41h3.84c0.24,0 0.44,-0.17 0.47,-0.41l0.36,-2.54c0.59,-0.24 1.13,-0.56 1.62,-0.94l2.39,0.96c0.22,0.08 0.47,0 0.59,-0.22l1.92,-3.32c0.12,-0.22 0.07,-0.47 -0.12,-0.61L19.14,12.94z M12,15.6c-1.98,0 -3.6,-1.62 -3.6,-3.6s1.62,-3.6 3.6,-3.6s3.6,1.62 3.6,3.6S13.98,15.6 12,15.6z"/></svg>
    </button>
    <div class="settings-panel" id="settingsPanel">
        <div class="settings-item" onclick="openEqualizer()">
            <svg viewBox="0 0 24 24"><path d="M3 17h4v-7H3v7zm7 4h4V3h-4v18zm7-11v11h4V10h-4z"/></svg>
            <span>Ses Efektleri</span>
        </div>
        <div class="settings-item" onclick="openStorageSettings()">
            <svg viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM5 19V5h14v14H5zM7 10h2v7H7v-7zm4-3h2v10h-2V7zm4 5h2v5h-2v-5z"/></svg>
            <span>İndirme Konumu</span>
        </div>
    </div>

    <div class="overlay-bg" id="storageOverlay" onclick="if(event.target===this) closeStorageSettings()">
        <div class="storage-modal">
            <div class="eq-header">
                <h2>İndirme Konumu</h2>
                <button class="eq-close-btn" onclick="closeStorageSettings()">✕</button>
            </div>
            <p class="eq-sub">İndirilen müziklerin kaydedileceği depolama alanını seçin</p>
            <div class="storage-list" id="storageList">
                <p style="text-align:center; color:#6b7280; font-size:12px;">Yükleniyor...</p>
            </div>
            <p class="storage-status" id="storageStatus"></p>
        </div>
    </div>

    <div class="overlay-bg" id="eqOverlay" onclick="if(event.target===this) closeEqualizer()">
        <div class="eq-modal">
            <div class="eq-header">
                <h2>Ses Efektleri</h2>
                <button class="eq-close-btn" onclick="closeEqualizer()">✕</button>
            </div>
            <p class="eq-sub">Ekolayzır ve 8D ses deneyimini kişiselleştirin</p>
            <div class="eq-toggle-row">
                <span>Ekolayzır Aktif</span>
                <label class="switch">
                    <input type="checkbox" id="eqEnabledToggle" onchange="onEqToggle()">
                    <span class="switch-slider"></span>
                </label>
            </div>
            <div class="eq-bands" id="eqBands"></div>
            <div class="eq-presets" id="eqPresets"></div>

            <div class="eq-toggle-row" style="margin-top: 18px;">
                <span>8D Ses Efekti</span>
                <label class="switch">
                    <input type="checkbox" id="eightDToggle" onchange="on8DToggle()">
                    <span class="switch-slider"></span>
                </label>
            </div>
            <div class="eq-toggle-row" id="eightDSpeedRow" style="display:none; flex-direction:column; align-items:stretch; gap:10px;">
                <div style="display:flex; justify-content:space-between;">
                    <span style="font-size:12px; color:#9ca3af; font-weight:500;">Dönüş Hızı</span>
                    <span id="eightDSpeedVal" style="font-size:12px; color:#10b981; font-weight:600;">8s</span>
                </div>
                <input type="range" id="eightDSpeedSlider" min="3" max="15" step="1" value="8" oninput="on8DSpeedChange(this.value)" style="width:100%; accent-color:#10b981;">
            </div>

            <div class="eq-toggle-row" style="margin-top: 18px;">
                <span>Sinema Ses (Surround)</span>
                <label class="switch">
                    <input type="checkbox" id="surroundToggle" onchange="onSurroundToggle()">
                    <span class="switch-slider"></span>
                </label>
            </div>
            <div class="eq-toggle-row" id="surroundAmountRow" style="display:none; flex-direction:column; align-items:stretch; gap:10px;">
                <div style="display:flex; justify-content:space-between;">
                    <span style="font-size:12px; color:#9ca3af; font-weight:500;">Etki Gücü</span>
                    <span id="surroundAmountVal" style="font-size:12px; color:#10b981; font-weight:600;">40%</span>
                </div>
                <input type="range" id="surroundAmountSlider" min="0" max="100" step="5" value="40" oninput="onSurroundAmountChange(this.value)" style="width:100%; accent-color:#10b981;">
            </div>
        </div>
    </div>

    <div class="header">
        <h1>HMusic</h1>
        <p>Ağsız Müzik ve Video Deneyimi</p>
    </div>

    <div class="tab-bar">
        <button class="tab-btn active" id="tabSearchBtn" onclick="switchTab('search')">
            <svg viewBox="0 0 24 24"><path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
            <span>Ara</span>
        </button>
        <button class="tab-btn" id="tabFavoritesBtn" onclick="switchTab('favorites')">
            <svg viewBox="0 0 24 24"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
            <span>Favoriler</span>
        </button>
        <button class="tab-btn" id="tabPlaylistsBtn" onclick="switchTab('playlists')">
            <svg viewBox="0 0 24 24"><path d="M15 6H3v2h12V6zm0 4H3v2h12v-2zM3 16h8v-2H3v2zM17 6v8.18c-.31-.11-.65-.18-1-.18-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3V8h3V6h-5z"/></svg>
            <span>Listelerim</span>
        </button>
    </div>

    <div class="tab-content active" id="searchTabContent">
        <div class="search-box" style="margin-top: 16px;">
            <input type="text" id="searchInput" maxlength="100" placeholder="Şarkı veya sanatçı ara..." onkeypress="if(event.key==='Enter') searchMusic()">
            <button onclick="searchMusic()">Ara</button>
        </div>
        <div class="results-list" id="resultsList"></div>
    </div>

    <div class="tab-content" id="favoritesTabContent">
        <div class="results-list" id="favoritesList"></div>
    </div>

    <div class="tab-content" id="playlistsTabContent">
        <button class="create-playlist-btn" onclick="openCreatePlaylistPrompt()">+ Yeni Çalma Listesi</button>
        <div class="playlist-grid" id="playlistGrid"></div>
    </div>

    <audio id="audioPlayer"></audio>

    <div class="overlay-bg" id="actionSheetOverlay" onclick="if(event.target===this) closeActionSheet()">
        <div class="action-sheet">
            <div class="action-sheet-title" id="actionSheetTitle">Şarkı</div>
            <div class="action-sheet-item" onclick="actionSheetAddToPlaylist()">
                <svg viewBox="0 0 24 24"><path d="M14 10H2v2h12v-2zm0-4H2v2h12V6zm4 8v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zM2 16h8v-2H2v2z"/></svg>
                <span>Çalma Listesine Ekle</span>
            </div>
            <div class="action-sheet-item" onclick="actionSheetDownload('mp3')">
                <svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
                <span>MP3 İndir</span>
            </div>
            <div class="action-sheet-item" onclick="actionSheetDownload('mp4')">
                <svg viewBox="0 0 24 24"><path d="M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4z"/></svg>
                <span>MP4 İndir</span>
            </div>
            <div class="action-sheet-item danger" id="actionSheetRemoveFromPlaylist" style="display:none;" onclick="actionSheetRemoveFromPlaylist()">
                <svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
                <span>Listeden Çıkar</span>
            </div>
        </div>
    </div>

    <div class="overlay-bg" id="addToPlaylistOverlay" onclick="if(event.target===this) closeAddToPlaylist()">
        <div class="storage-modal">
            <div class="eq-header">
                <h2>Çalma Listesine Ekle</h2>
                <button class="eq-close-btn" onclick="closeAddToPlaylist()">✕</button>
            </div>
            <div class="storage-list" id="addToPlaylistList"></div>
            <div class="new-playlist-row">
                <input type="text" id="newPlaylistNameInput" maxlength="60" placeholder="Yeni liste adı...">
                <button onclick="createPlaylistFromPicker()">Oluştur</button>
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
                <button class="play-all-btn" onclick="playPlaylistFromStart()">▶ Tümünü Çal</button>
                <button class="delete-playlist-btn" onclick="deleteCurrentPlaylist()">Listeyi Sil</button>
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

    function getQueueArray(queueType) {
        if (queueType === 'search') return searchResults;
        if (queueType === 'favorites') return favoritesData;
        if (queueType === 'playlist') return activePlaylistSongs;
        return [];
    }

    function songCardHTML(item, queueType, index) {
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

    async function searchMusic() {
        const query = document.getElementById('searchInput').value.trim();
        if (!query) return;
        const resultsList = document.getElementById('resultsList');
        resultsList.innerHTML = '<p style="text-align:center; color:#6b7280; margin-top:20px;">Aranıyor...</p>';
        try {
            const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
            if (res.status === 403) {
                resultsList.innerHTML = '<p style="text-align:center; color:#ef4444; margin-top:20px;">Erişiminiz Engellendi!</p>';
                return;
            }
            const data = await res.json();
            if (!data || data.length === 0 || data.error) {
                resultsList.innerHTML = '<p style="text-align:center; color:#6b7280; margin-top:20px;">Sonuç bulunamadı.</p>';
                return;
            }
            searchResults = data;
            renderCardList(resultsList, searchResults, 'search', 'Sonuç bulunamadı.');
        } catch (err) {
            resultsList.innerHTML = '<p style="text-align:center; color:#ef4444; margin-top:20px;">Bir hata oluştu!</p>';
        }
    }

    function switchTab(tab) {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.getElementById('tab' + tab.charAt(0).toUpperCase() + tab.slice(1) + 'Btn').classList.add('active');
        document.getElementById(tab + 'TabContent').classList.add('active');
        if (tab === 'favorites') loadFavoritesTab();
        if (tab === 'playlists') loadPlaylistsTab();
    }

    async function loadLibrary() {
        try {
            const res = await fetch('/api/library');
            const data = await res.json();
            favoritesData = data.favorites || [];
            favoriteIds = new Set(favoritesData.map(s => s.id));
            playlistsData = data.playlists || [];
        } catch (err) {}
    }

    async function loadFavoritesTab() {
        await loadLibrary();
        renderCardList(document.getElementById('favoritesList'), favoritesData, 'favorites', 'Henüz favori şarkınız yok.');
    }

    async function loadPlaylistsTab() {
        await loadLibrary();
        renderPlaylistGrid();
    }

    function renderPlaylistGrid() {
        const grid = document.getElementById('playlistGrid');
        grid.innerHTML = '';
        if (!playlistsData.length) {
            grid.innerHTML = '<p class="empty-hint">Henüz çalma listeniz yok.</p>';
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
                    <div class="playlist-card-count">${pl.count} şarkı</div>
                </div>
            `;
            grid.appendChild(card);
        });
    }

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
                renderCardList(document.getElementById('favoritesList'), favoritesData, 'favorites', 'Henüz favori şarkınız yok.');
            }
        } catch (err) {}
    }

    function openCreatePlaylistPrompt() {
        const name = prompt('Yeni çalma listesi adı:');
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
            renderCardList(document.getElementById('playlistDetailSongs'), activePlaylistSongs, 'playlist', 'Bu listede henüz şarkı yok.');
            document.getElementById('playlistDetailOverlay').classList.add('active');
        } catch (err) {}
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
        if (!confirm('Bu çalma listesini silmek istediğinize emin misiniz?')) return;
        try {
            await fetch(`/api/playlists/${activePlaylistId}`, { method: 'DELETE' });
            playlistsData = playlistsData.filter(p => p.id !== activePlaylistId);
            renderPlaylistGrid();
            closePlaylistDetail();
        } catch (err) {}
    }

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
            renderCardList(document.getElementById('playlistDetailSongs'), activePlaylistSongs, 'playlist', 'Bu listede henüz şarkı yok.');
            const pl = playlistsData.find(p => p.id === activePlaylistId);
            if (pl) pl.count = activePlaylistSongs.length;
        } catch (err) {}
    }

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
            listEl.innerHTML = '<p class="empty-hint">Henüz çalma listeniz yok, aşağıdan oluşturun.</p>';
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
                    <div class="storage-item-path">${pl.count} şarkı</div>
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
        statusEl.innerText = 'Ekleniyor...';
        try {
            const res = await fetch(`/api/playlists/${playlistId}/songs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(actionSheetContext.item)
            });
            const data = await res.json();
            if (!res.ok || data.error) {
                statusEl.style.color = '#ef4444';
                statusEl.innerText = data.error || 'Eklenemedi.';
                return;
            }
            itemEl.classList.add('active');
            const pl = playlistsData.find(p => p.id === playlistId);
            if (pl) pl.count = (data.songs || []).length;
            statusEl.style.color = '#10b981';
            statusEl.innerText = data.already_exists ? 'Bu şarkı zaten listede.' : 'Listeye eklendi ✓';
        } catch (err) {
            statusEl.style.color = '#ef4444';
            statusEl.innerText = 'Bir hata oluştu.';
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
            document.getElementById('addToPlaylistStatus').innerText = 'Liste oluşturuldu, şimdi şarkıya dokunun.';
        }
    }

    function closeAddToPlaylist() {
        document.getElementById('addToPlaylistOverlay').classList.remove('active');
    }

    function playSong(btn, queueType, index) {
        const list = getQueueArray(queueType);
        const item = list[index];
        if (!item) return;
        ensureAudioGraph();
        if (currentBtn) resetBtnIcon(currentBtn);
        currentBtn = btn;
        activeQueue = list;
        activeQueueType = queueType;
        activeQueueIndex = index;
        if (btn) setBtnLoading(btn);
        playerCover.src = item.thumbnail;
        playerTitle.innerText = item.title;
        playerStatus.innerText = "Hazırlanıyor...";
        playerPanel.classList.add('active');
        audioPlayer.src = `/api/stream?url=${encodeURIComponent(item.url)}`;
        if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
        audioPlayer.play().catch(()=>{});
    }

    function playNext() {
        if (!activeQueue.length || !activeQueueType) return;
        const nextIndex = activeQueueIndex + 1;
        if (nextIndex >= activeQueue.length) {
            playerStatus.innerText = "Liste sonu";
            return;
        }
        playSong(null, activeQueueType, nextIndex);
    }

    function setBtnLoading(btn) { btn.innerHTML = '<div class="spinner"></div>'; btn.disabled = true; }
    function resetBtnIcon(btn) { btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>'; btn.disabled = false; }

    audioPlayer.addEventListener('playing', () => {
        if (currentBtn) resetBtnIcon(currentBtn);
        playerStatus.innerText = "Çalınıyor";
        playIcon.style.display = "none";
        pauseIcon.style.display = "block";
    });
    audioPlayer.addEventListener('pause', () => {
        playerStatus.innerText = "Duraklatıldı";
        playIcon.style.display = "block";
        pauseIcon.style.display = "none";
    });
    audioPlayer.addEventListener('timeupdate', () => {
        if (!isNaN(audioPlayer.duration)) {
            const progress = (audioPlayer.currentTime / audioPlayer.duration) * 100;
            seekBar.value = progress;
            currentTimeEl.innerText = formatTime(audioPlayer.currentTime);
            durationTimeEl.innerText = formatTime(audioPlayer.duration);
        }
    });
    seekBar.addEventListener('input', () => {
        if (!isNaN(audioPlayer.duration)) {
            audioPlayer.currentTime = (seekBar.value / 100) * audioPlayer.duration;
        }
    });
    audioPlayer.addEventListener('ended', () => {
        if (autoAdvance) playNext();
    });
    function togglePlay() {
        if (audioPlayer.paused) audioPlayer.play();
        else audioPlayer.pause();
    }
    function formatTime(secs) {
        const m = Math.floor(secs / 60);
        const s = Math.floor(secs % 60);
        return `${m}:${s < 10 ? '0' : ''}${s}`;
    }

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

    let audioCtx = null;
    let sourceNode = null;
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
        flat:   { name: 'Düz',   gains: [0, 0, 0, 0, 0] },
        bass:   { name: 'Bas',   gains: [7, 4, 0, -1, -2] },
        vocal:  { name: 'Vokal', gains: [-2, 0, 4, 4, 1] },
        treble: { name: 'Tiz',   gains: [-2, -1, 0, 4, 7] }
    };

    function ensureAudioGraph() {
        if (audioCtx) return;
        try {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            sourceNode = audioCtx.createMediaElementSource(audioPlayer);
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
        } catch (err) {}
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
            b.innerText = eqPresets[key].name;
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

    const folderIconSvg = '<svg viewBox="0 0 24 24"><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>';

    async function openStorageSettings() {
        document.getElementById('settingsPanel').classList.remove('active');
        document.getElementById('storageOverlay').classList.add('active');
        document.getElementById('storageStatus').innerText = '';
        const listEl = document.getElementById('storageList');
        listEl.innerHTML = '<p style="text-align:center; color:#6b7280; font-size:12px;">Yükleniyor...</p>';
        try {
            const res = await fetch('/api/settings/storage');
            const data = await res.json();
            renderStorageList(data.options || [], data.current || '');
        } catch (err) {
            listEl.innerHTML = '<p style="text-align:center; color:#ef4444; font-size:12px;">Depolama bilgisi alınamadı.</p>';
        }
    }

    function renderStorageList(options, current) {
        const listEl = document.getElementById('storageList');
        listEl.innerHTML = '';
        if (!options.length) {
            listEl.innerHTML = '<p style="text-align:center; color:#6b7280; font-size:12px;">Depolama bulunamadı.</p>';
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
        statusEl.innerText = 'Kaydediliyor...';
        try {
            const res = await fetch('/api/settings/storage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key })
            });
            const data = await res.json();
            if (!res.ok || data.error) {
                statusEl.style.color = '#ef4444';
                statusEl.innerText = data.error || 'Değiştirilemedi.';
                return;
            }
            document.querySelectorAll('.storage-item').forEach(el => el.classList.remove('active'));
            itemEl.classList.add('active');
            statusEl.style.color = '#10b981';
            statusEl.innerText = 'Kaydedildi: ' + data.current;
        } catch (err) {
            statusEl.style.color = '#ef4444';
            statusEl.innerText = 'Bir hata oluştu.';
        }
    }

    function closeStorageSettings() {
        document.getElementById('storageOverlay').classList.remove('active');
    }

    loadLibrary();
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
        abort(404)
    
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
        return jsonify({"error": "Klasör oluşturulamadı."}), 500
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

def process_youtube_mp3(url):
    out_template = f"{DOWNLOAD_FOLDER}/%(id)s.%(ext)s"
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
        file_path = f"{DOWNLOAD_FOLDER}/{info['id']}.mp3"
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
        file_path, _ = process_youtube_mp3(url)
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
        file_path, title = process_youtube_mp3(url)
        clean_title = re.sub(r'[^\w\s\d\-]', '', title).strip()
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

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"error": "Çok fazla istek gönderdiniz. Lütfen bir süre bekleyin."}), 429

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print("\n" + "="*50)
    print(" GİZLİ ADMİN PANELİ LİNKİNİZ:")
    print(f" https://<proje-adiniz>.up.railway.app/admin?key={ADMIN_SECRET_KEY}")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=port, debug=False)
