"""Kullanıcıya açık sayfa ve API uç noktaları."""
import os
import re
import secrets

from flask import Blueprint, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename

import config
import stats
import library
import youtube
from extensions import limiter

user_bp = Blueprint('user', __name__)


# ---------- Ana sayfa ----------
@user_bp.route('/')
def home():
    ip = request.remote_addr
    stats.track_user_action(ip, None)
    return render_template('user.html')


# ---------- Depolama ayarları ----------
@user_bp.route('/api/settings/storage', methods=['GET'])
def get_storage_settings():
    return jsonify({
        'current': config.DOWNLOAD_FOLDER,
        'options': config.get_storage_options()
    })


@user_bp.route('/api/settings/storage', methods=['POST'])
@limiter.limit("10 per minute")
def set_storage_settings():
    data = request.get_json(silent=True) or {}
    key = data.get('key')
    options = config.get_storage_options()
    match = next((o for o in options if o['key'] == key), None)
    if not match:
        return jsonify({"error": "Geçersiz depolama seçimi"}), 400
    try:
        os.makedirs(match['path'], exist_ok=True)
    except Exception:
        return jsonify({"error": "Klasör oluşturulamadı. Depolama izinlerini kontrol edin."}), 500
    config.set_download_folder(match['path'])
    return jsonify({"success": True, "current": config.DOWNLOAD_FOLDER})


# ---------- Kütüphane: favoriler & çalma listeleri ----------
@user_bp.route('/api/library', methods=['GET'])
def get_library():
    ip = request.remote_addr
    lib = library.get_user_lib(ip)
    playlists = [
        {"id": pid, "name": pl["name"], "count": len(pl["songs"])}
        for pid, pl in lib["playlists"].items()
    ]
    return jsonify({"favorites": lib["favorites"], "playlists": playlists})


@user_bp.route('/api/favorites/toggle', methods=['POST'])
@limiter.limit("60 per minute")
def toggle_favorite():
    ip = request.remote_addr
    data = request.get_json(silent=True) or {}
    song_id = (data.get('id') or '').strip()
    if not song_id:
        return jsonify({"error": "Geçersiz şarkı"}), 400
    lib = library.get_user_lib(ip)
    exists = any(s["id"] == song_id for s in lib["favorites"])
    if exists:
        lib["favorites"] = [s for s in lib["favorites"] if s["id"] != song_id]
        is_fav = False
    else:
        song = library.clean_song_payload(data)
        if not song:
            return jsonify({"error": "Geçersiz şarkı verisi"}), 400
        lib["favorites"].insert(0, song)
        is_fav = True
    library.save_library(library.user_library)
    return jsonify({"success": True, "is_favorite": is_fav, "favorites": lib["favorites"]})


@user_bp.route('/api/playlists', methods=['POST'])
@limiter.limit("20 per minute")
def create_playlist():
    ip = request.remote_addr
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()[:60]
    if not name:
        return jsonify({"error": "Çalma listesi adı gerekli"}), 400
    lib = library.get_user_lib(ip)
    pl_id = secrets.token_hex(6)
    lib["playlists"][pl_id] = {"name": name, "songs": []}
    library.save_library(library.user_library)
    return jsonify({"success": True, "id": pl_id, "name": name, "count": 0})


@user_bp.route('/api/playlists/<playlist_id>', methods=['GET'])
def get_playlist(playlist_id):
    ip = request.remote_addr
    lib = library.get_user_lib(ip)
    pl = lib["playlists"].get(playlist_id)
    if not pl:
        return jsonify({"error": "Çalma listesi bulunamadı"}), 404
    return jsonify({"id": playlist_id, "name": pl["name"], "songs": pl["songs"]})


@user_bp.route('/api/playlists/<playlist_id>', methods=['DELETE'])
@limiter.limit("20 per minute")
def delete_playlist(playlist_id):
    ip = request.remote_addr
    lib = library.get_user_lib(ip)
    if playlist_id in lib["playlists"]:
        del lib["playlists"][playlist_id]
        library.save_library(library.user_library)
    return jsonify({"success": True})


@user_bp.route('/api/playlists/<playlist_id>/songs', methods=['POST'])
@limiter.limit("60 per minute")
def add_song_to_playlist(playlist_id):
    ip = request.remote_addr
    lib = library.get_user_lib(ip)
    pl = lib["playlists"].get(playlist_id)
    if not pl:
        return jsonify({"error": "Çalma listesi bulunamadı"}), 404
    data = request.get_json(silent=True) or {}
    song = library.clean_song_payload(data)
    if not song:
        return jsonify({"error": "Geçersiz şarkı verisi"}), 400
    if any(s["id"] == song["id"] for s in pl["songs"]):
        return jsonify({"success": True, "already_exists": True, "songs": pl["songs"]})
    pl["songs"].append(song)
    library.save_library(library.user_library)
    return jsonify({"success": True, "songs": pl["songs"]})


@user_bp.route('/api/playlists/<playlist_id>/songs/<song_id>', methods=['DELETE'])
@limiter.limit("60 per minute")
def remove_song_from_playlist(playlist_id, song_id):
    ip = request.remote_addr
    lib = library.get_user_lib(ip)
    pl = lib["playlists"].get(playlist_id)
    if not pl:
        return jsonify({"error": "Çalma listesi bulunamadı"}), 404
    pl["songs"] = [s for s in pl["songs"] if s["id"] != song_id]
    library.save_library(library.user_library)
    return jsonify({"success": True, "songs": pl["songs"]})


# ---------- Arama ----------
@user_bp.route('/api/search', methods=['GET'])
@limiter.limit("15 per minute")
def search_music():
    ip = request.remote_addr
    stats.track_user_action(ip, None)

    query = request.args.get('q', '').strip()
    if not query or len(query) > 100:
        return jsonify({"error": "Geçersiz arama terimi"}), 400

    clean_query = re.sub(r'[^\w\s\d\-]', '', query)
    try:
        results = youtube.search_youtube(clean_query)
        return jsonify(results)
    except Exception:
        return jsonify({"error": "Arama işlemi gerçekleştirilemedi."}), 500


# ---------- Akış / indirme ----------
@user_bp.route('/api/stream', methods=['GET'])
@limiter.limit("20 per minute")
def stream_audio():
    ip = request.remote_addr
    stats.track_user_action(ip, "plays")

    url = request.args.get('url')
    if not youtube.is_valid_youtube_url(url):
        return jsonify({"error": "Geçersiz veya yetkisiz URL"}), 400
    try:
        file_path, _ = youtube.process_youtube_mp3(url, config.CACHE_FOLDER)
        return send_file(file_path, mimetype='audio/mpeg')
    except Exception:
        return jsonify({"error": "Ses akışı başlatılamadı."}), 500


@user_bp.route('/api/download', methods=['GET'])
@limiter.limit("5 per minute")
def download_audio():
    ip = request.remote_addr
    stats.track_user_action(ip, "mp3")

    url = request.args.get('url')
    if not youtube.is_valid_youtube_url(url):
        return jsonify({"error": "Geçersiz veya yetkisiz URL"}), 400

    fmt = request.args.get('format', 'mp3')
    if fmt not in ('mp3', 'wav', 'flac'):
        fmt = 'mp3'
    try:
        sample_rate = int(request.args.get('samplerate', 0))
    except (TypeError, ValueError):
        sample_rate = 0
    if sample_rate not in (44100, 48000, 96000):
        sample_rate = None
    try:
        bit_depth = int(request.args.get('bitdepth', 0))
    except (TypeError, ValueError):
        bit_depth = 0
    if bit_depth not in (16, 24, 32):
        bit_depth = None

    try:
        file_path, title = youtube.process_youtube_audio(
            url, config.DOWNLOAD_FOLDER, fmt=fmt, sample_rate=sample_rate, bit_depth=bit_depth
        )
        clean_title = re.sub(r'[^\w\s\d\-]', '', title).strip()
        video_id = os.path.splitext(os.path.basename(file_path))[0]
        meta = config.load_downloads_meta()
        meta[video_id] = title
        config.save_downloads_meta(meta)
        mimetypes = {'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'flac': 'audio/flac'}
        return send_file(file_path, as_attachment=True, download_name=f"{clean_title}.{fmt}", mimetype=mimetypes[fmt])
    except Exception:
        return jsonify({"error": "İndirme başarısız."}), 500


@user_bp.route('/api/download-mp4', methods=['GET'])
@limiter.limit("3 per minute")
def download_video():
    ip = request.remote_addr
    stats.track_user_action(ip, "mp4")

    url = request.args.get('url')
    if not youtube.is_valid_youtube_url(url):
        return jsonify({"error": "Geçersiz veya yetkisiz URL"}), 400
    try:
        file_path, title = youtube.process_youtube_mp4(url)
        clean_title = re.sub(r'[^\w\s\d\-]', '', title).strip()
        return send_file(file_path, as_attachment=True, download_name=f"{clean_title}.mp4", mimetype='video/mp4')
    except Exception:
        return jsonify({"error": "Video indirme başarısız."}), 500


# ---------- Önbellek ----------
@user_bp.route('/api/cache/info', methods=['GET'])
def cache_info():
    total = 0
    try:
        for fname in os.listdir(config.CACHE_FOLDER):
            fpath = os.path.join(config.CACHE_FOLDER, fname)
            if os.path.isfile(fpath):
                total += os.path.getsize(fpath)
    except Exception:
        pass
    return jsonify({"size_bytes": total})


@user_bp.route('/api/cache/clear', methods=['POST'])
def cache_clear():
    freed = 0
    try:
        for fname in os.listdir(config.CACHE_FOLDER):
            fpath = os.path.join(config.CACHE_FOLDER, fname)
            if os.path.isfile(fpath):
                freed += os.path.getsize(fpath)
                os.remove(fpath)
    except Exception:
        return jsonify({"error": "Önbellek temizlenemedi."}), 500
    return jsonify({"success": True, "freed_bytes": freed})


AUDIO_EXTENSIONS = ('.mp3', '.wav', '.flac')
AUDIO_MIMETYPES = {'.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.flac': 'audio/flac'}


# ---------- Cihaza indirilenler (çevrimdışı mod) ----------
@user_bp.route('/api/downloads/local', methods=['GET'])
def downloads_local():
    meta = config.load_downloads_meta()
    items = []
    try:
        for fname in sorted(os.listdir(config.DOWNLOAD_FOLDER)):
            if not fname.lower().endswith(AUDIO_EXTENSIONS):
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
    if not safe_name or not safe_name.lower().endswith(AUDIO_EXTENSIONS):
        return None
    full_path = os.path.abspath(os.path.join(config.DOWNLOAD_FOLDER, safe_name))
    if not full_path.startswith(os.path.abspath(config.DOWNLOAD_FOLDER) + os.sep):
        return None
    return full_path


@user_bp.route('/api/local-audio/<path:filename>', methods=['GET'])
def local_audio(filename):
    full_path = _safe_local_audio_path(filename)
    if not full_path or not os.path.isfile(full_path):
        return jsonify({"error": "Dosya bulunamadı."}), 404
    ext = os.path.splitext(full_path)[1].lower()
    return send_file(full_path, mimetype=AUDIO_MIMETYPES.get(ext, 'audio/mpeg'))


@user_bp.route('/api/local-audio/<path:filename>', methods=['DELETE'])
def local_audio_delete(filename):
    full_path = _safe_local_audio_path(filename)
    if not full_path or not os.path.isfile(full_path):
        return jsonify({"error": "Dosya bulunamadı."}), 404
    try:
        os.remove(full_path)
        video_id = os.path.splitext(os.path.basename(full_path))[0]
        meta = config.load_downloads_meta()
        if video_id in meta:
            del meta[video_id]
            config.save_downloads_meta(meta)
        return jsonify({"success": True})
    except Exception:
        return jsonify({"error": "Silinemedi."}), 500
