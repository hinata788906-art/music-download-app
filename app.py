from datetime import datetime
import json
import os
import re
import secrets
import urllib.parse
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_file,
    url_for,
)
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import requests
import yt_dlp

app = Flask(__name__)
app.secret_key = os.urandom(32)

ADMIN_SECRET_KEY = secrets.token_hex(16)

CORS(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["500 per day", "100 per hour"],
    storage_uri="memory://",
)

# Bulut sunuculara uygun geçici indirme dizinleri
DOWNLOAD_FOLDER = "/tmp/MusicDownloads"
STATS_FILE = "/tmp/stats.json"

if not os.path.exists(DOWNLOAD_FOLDER):
  os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)


def load_stats():
  if os.path.exists(STATS_FILE):
    try:
      with open(STATS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      return {}
  return {}


def save_stats(stats):
  try:
    with open(STATS_FILE, "w", encoding="utf-8") as f:
      json.dump(stats, f, ensure_ascii=False, indent=2)
  except Exception as e:
    print(f"Stats kaydetme hatasi: {e}")


user_stats = load_stats()


def track_user_action(ip, action_type):
  now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  if ip not in user_stats:
    user_stats[ip] = {
        "plays": 0,
        "mp3": 0,
        "mp4": 0,
        "last_active": now,
        "banned": False,
    }
  user_stats[ip]["last_active"] = now
  if action_type in user_stats[ip]:
    user_stats[ip][action_type] += 1
  save_stats(user_stats)


@app.before_request
def check_ip_ban():
  ip = request.remote_addr
  if request.path.startswith("/admin"):
    return
  if ip in user_stats and user_stats[ip].get("banned", False):
    return jsonify({"error": "Erişiminiz engellenmiştir."}), 403


@app.after_request
def add_security_headers(response):
  response.headers["X-Content-Type-Options"] = "nosniff"
  response.headers["X-Frame-Options"] = "DENY"
  response.headers["X-XSS-Protection"] = "1; mode=block"
  return response


def is_valid_youtube_url(url):
  if not url:
    return False
  parsed = urllib.parse.urlparse(url)
  allowed_domains = [
      "youtube.com",
      "www.youtube.com",
      "m.youtube.com",
      "youtu.be",
  ]
  return parsed.netloc in allowed_domains


# Arayüz HTML Kodu
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
        .header { text-align: center; margin-bottom: 25px; }
        .header h1 { font-size: 24px; font-weight: 700; color: #10b981; letter-spacing: -0.5px; }
        .header p { font-size: 12px; color: #6b7280; margin-top: 4px; }
        .search-box { display: flex; gap: 10px; background: #171c26; padding: 6px; border-radius: 14px; border: 1px solid #232a3b; }
        .search-box input { flex: 1; border: none; background: transparent; padding: 12px 16px; color: #fff; font-size: 15px; outline: none; }
        .search-box button { background: #10b981; border: none; color: #fff; padding: 0 20px; border-radius: 10px; font-weight: 600; cursor: pointer; }
        .results-list { display: flex; flex-direction: column; gap: 12px; margin-top: 20px; }
        .card { display: flex; align-items: center; background: #171c26; padding: 10px 14px; border-radius: 14px; gap: 12px; border: 1px solid #202738; }
        .card img { width: 52px; height: 52px; border-radius: 10px; object-fit: cover; }
        .card-info { flex: 1; overflow: hidden; }
        .card-title { font-size: 14px; font-weight: 600; color: #f3f4f6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .card-artist { font-size: 12px; color: #9ca3af; margin-top: 2px; }
        .action-btns { display: flex; gap: 6px; }
        .icon-btn { width: 38px; height: 38px; border-radius: 10px; border: none; display: flex; align-items: center; justify-content: center; cursor: pointer; }
        .btn-play { background: rgba(16, 185, 129, 0.15); color: #10b981; }
        .btn-mp3 { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
        .btn-mp4 { background: rgba(168, 85, 247, 0.15); color: #a855f7; }
        .icon-btn svg { width: 18px; height: 18px; fill: currentColor; }
        .spinner { width: 16px; height: 16px; border: 2.5px solid rgba(255,255,255,0.2); border-top-color: currentColor; border-radius: 50%; animation: spin 0.8s linear infinite; }
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
    <div class="header">
        <h1>HMusic</h1>
        <p>Ağsız Müzik ve Video Deneyimi</p>
    </div>
    <div class="search-box">
        <input type="text" id="searchInput" maxlength="100" placeholder="Şarkı veya sanatçı ara..." onkeypress="if(event.key==='Enter') searchMusic()">
        <button onclick="searchMusic()">Ara</button>
    </div>
    <div class="results-list" id="resultsList"></div>
    <audio id="audioPlayer"></audio>
    <div class="modern-player" id="playerPanel">
        <div class="player-top">
            <img src="" id="playerCover" class="player-cover">
            <div class="player-details">
                <div class="player-title" id="playerTitle">Şarkı Adı</div>
                <div class="player-status" id="playerStatus">Hazırlanıyor...</div>
            </div>
            <button class="player-main-btn" id="playPauseBtn" onclick="togglePlay()">
                <svg id="playIcon" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                <svg id="pauseIcon" viewBox="0 0 24 24" style="display:none;"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
            </button>
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
            resultsList.innerHTML = '';
            if (!data || data.length === 0 || data.error) {
                resultsList.innerHTML = '<p style="text-align:center; color:#6b7280; margin-top:20px;">Sonuç bulunamadı.</p>';
                return;
            }
            data.forEach(item => {
                const card = document.createElement('div');
                card.className = 'card';
                const safeTitle = item.title ? item.title.replace(/'/g, "") : "";
                card.innerHTML = `
                    <img src="${item.thumbnail}" alt="thumb">
                    <div class="card-info">
                        <div class="card-title">${item.title}</div>
                        <div class="card-artist">HMusic Stream</div>
                    </div>
                    <div class="action-btns">
                        <button class="icon-btn btn-play" onclick="playSong(this, '${item.url}', '${safeTitle}', '${item.thumbnail}')">
                            <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                        </button>
                        <button class="icon-btn btn-mp3" onclick="downloadMedia(this, '${item.url}', 'mp3')">
                            <svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
                        </button>
                        <button class="icon-btn btn-mp4" onclick="downloadMedia(this, '${item.url}', 'mp4')">
                            <svg viewBox="0 0 24 24"><path d="M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4z"/></svg>
                        </button>
                    </div>
                `;
                resultsList.appendChild(card);
            });
        } catch (err) {
            resultsList.innerHTML = '<p style="text-align:center; color:#ef4444; margin-top:20px;">Bir hata oluştu!</p>';
        }
    }

    function playSong(btn, url, title, thumbnail) {
        if (currentBtn) resetBtnIcon(currentBtn);
        currentBtn = btn;
        setBtnLoading(btn);
        playerCover.src = thumbnail;
        playerTitle.innerText = title;
        playerStatus.innerText = "Hazırlanıyor...";
        playerPanel.classList.add('active');
        audioPlayer.src = `/api/stream?url=${encodeURIComponent(url)}`;
        audioPlayer.play().catch(()=>{});
    }

    function downloadMedia(btn, url, type) {
        const originalHTML = btn.innerHTML;
        btn.innerHTML = '<div class="spinner"></div>';
        btn.disabled = true;
        const endpoint = type === 'mp4' ? '/api/download-mp4' : '/api/download';
        window.location.href = `${endpoint}?url=${encodeURIComponent(url)}`;
        setTimeout(() => {
            btn.innerHTML = originalHTML;
            btn.disabled = false;
        }, 5000);
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
    function togglePlay() {
        if (audioPlayer.paused) audioPlayer.play();
        else audioPlayer.pause();
    }
    function formatTime(secs) {
        const m = Math.floor(secs / 60);
        const s = Math.floor(secs % 60);
        return `${m}:${s < 10 ? '0' : ''}${s}`;
    }
</script>
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>HMusic - Yönetim Paneli</title>
    <style>
        body { background-color: #0b0e14; color: #f3f4f6; font-family: sans-serif; padding: 20px; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { border: 1px solid #232a3b; padding: 10px; text-align: left; }
        th { background: #171c26; }
    </style>
</head>
<body>
    <h1>Yönetim Paneli</h1>
    <p>Toplam Kullanıcı: {{ total_users }}</p>
    <table>
        <tr><th>IP</th><th>Dinleme</th><th>MP3</th><th>MP4</th><th>Son Aktiflik</th></tr>
        {% for ip, stats in users.items() %}
        <tr>
            <td>{{ ip }}</td>
            <td>{{ stats.plays }}</td>
            <td>{{ stats.mp3 }}</td>
            <td>{{ stats.mp4 }}</td>
            <td>{{ stats.last_active }}</td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
"""


@app.route("/")
def home():
  ip = request.remote_addr
  track_user_action(ip, None)
  return render_template_string(USER_HTML)


@app.route("/admin")
def admin_panel():
  key = request.args.get("key")
  if key != ADMIN_SECRET_KEY:
    abort(404)

  total_users = len(user_stats)
  total_plays = sum(u["plays"] for u in user_stats.values())
  total_mp3 = sum(u["mp3"] for u in user_stats.values())
  total_mp4 = sum(u["mp4"] for u in user_stats.values())

  return render_template_string(
      ADMIN_HTML,
      users=user_stats,
      total_users=total_users,
      total_plays=total_plays,
      total_mp3=total_mp3,
      total_mp4=total_mp4,
      secret_key=ADMIN_SECRET_KEY,
  )


@app.route("/api/search", methods=["GET"])
@limiter.limit("30 per minute")
def search_music():
  ip = request.remote_addr
  track_user_action(ip, None)

  query = request.args.get("q", "").strip()
  if not query or len(query) > 100:
    return jsonify({"error": "Geçersiz arama terimi"}), 400

  clean_query = re.sub(r"[^\w\s\d\-]", "", query)

  try:
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "extract_flat": True,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
      info = ydl.extract_info(f"ytsearch10:{clean_query}", download=False)
      results = []
      for entry in info.get("entries", []):
        if entry:
          results.append({
              "id": entry.get("id"),
              "title": entry.get("title"),
              "url": f"https://www.youtube.com/watch?v={entry.get('id')}",
              "thumbnail": (
                  f"https://i.ytimg.com/vi/{entry.get('id')}/hqdefault.jpg"
              ),
          })
      return jsonify(results)
  except Exception:
    return jsonify({"error": "Arama gerçekleştirilemedi."}), 500


# CANLI STREAM (Anında Başlatır)
@app.route("/api/stream", methods=["GET"])
def stream_audio():
  ip = request.remote_addr
  track_user_action(ip, "plays")

  url = request.args.get("url")
  if not is_valid_youtube_url(url):
    return jsonify({"error": "Geçersiz URL"}), 400

  try:
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "nocheckcertificate": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
      info = ydl.extract_info(url, download=False)
      # Dosyayı sunucuya indirmeden doğrudan yönlendirir
      return redirect(info["url"])
  except Exception as e:
    return jsonify({"error": str(e)}), 500


# MP3 İNDİRME
@app.route("/api/download", methods=["GET"])
def download_audio():
  ip = request.remote_addr
  track_user_action(ip, "mp3")

  url = request.args.get("url")
  if not is_valid_youtube_url(url):
    return jsonify({"error": "Geçersiz URL"}), 400

  try:
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"{DOWNLOAD_FOLDER}/%(id)s.%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
      info = ydl.extract_info(url, download=True)
      filename = f"{DOWNLOAD_FOLDER}/{info['id']}.mp3"
      clean_title = re.sub(r"[^\w\s\d\-]", "", info.get("title", "music"))
      return send_file(
          filename,
          as_attachment=True,
          download_name=f"{clean_title}.mp3",
          mimetype="audio/mpeg",
      )
  except Exception as e:
    return jsonify({"error": f"İndirme başarısız: {str(e)}"}), 500


# MP4 İNDİRME
@app.route("/api/download-mp4", methods=["GET"])
def download_video():
  ip = request.remote_addr
  track_user_action(ip, "mp4")

  url = request.args.get("url")
  if not is_valid_youtube_url(url):
    return jsonify({"error": "Geçersiz URL"}), 400

  try:
    ydl_opts = {
        "format": (
            "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        ),
        "outtmpl": f"{DOWNLOAD_FOLDER}/%(id)s_video.%(ext)s",
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
      info = ydl.extract_info(url, download=True)
      filename = f"{DOWNLOAD_FOLDER}/{info['id']}_video.mp4"
      clean_title = re.sub(r"[^\w\s\d\-]", "", info.get("title", "video"))
      return send_file(
          filename,
          as_attachment=True,
          download_name=f"{clean_title}.mp4",
          mimetype="video/mp4",
      )
  except Exception as e:
    return jsonify({"error": f"Video indirme başarısız: {str(e)}"}), 500


if __name__ == "__main__":
  port = int(os.environ.get("PORT", 5000))
  app.run(host="0.0.0.0", port=port, debug=False)
