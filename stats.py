"""IP bazlı kullanım istatistikleri, ban listesi ve güvenlik başlıkları."""
import os
import json
from datetime import datetime
from flask import request, jsonify

import config

STATS_FILE = config.STATS_FILE


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


def track_user_action(ip, action_type):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if ip not in user_stats:
        user_stats[ip] = {"plays": 0, "mp3": 0, "mp4": 0, "last_active": now, "banned": False}
    user_stats[ip]["last_active"] = now
    if action_type in user_stats[ip]:
        user_stats[ip][action_type] += 1
    save_stats(user_stats)


def check_ip_ban():
    """app.before_request olarak kaydedilir (bkz. app.py)."""
    ip = request.remote_addr
    if request.path.startswith('/admin'):
        return
    if ip in user_stats and user_stats[ip].get("banned", False):
        return jsonify({"error": "Erişiminiz engellenmiştir."}), 403


def add_security_headers(response):
    """app.after_request olarak kaydedilir (bkz. app.py)."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response
