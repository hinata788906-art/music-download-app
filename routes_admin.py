"""Gizli admin paneli: kullanım istatistikleri ve IP banlama."""
from flask import Blueprint, request, render_template, redirect, url_for, abort

import config
import stats

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin')
def admin_panel():
    key = request.args.get('key')
    if key != config.ADMIN_SECRET_KEY:
        abort(404)  # Doğru gizli anahtar verilmezse 404 hatası verir (sayfa yokmuş gibi)

    total_users = len(stats.user_stats)
    total_plays = sum(u['plays'] for u in stats.user_stats.values())
    total_mp3 = sum(u['mp3'] for u in stats.user_stats.values())
    total_mp4 = sum(u['mp4'] for u in stats.user_stats.values())

    return render_template(
        'admin.html',
        users=stats.user_stats,
        total_users=total_users,
        total_plays=total_plays,
        total_mp3=total_mp3,
        total_mp4=total_mp4,
        secret_key=config.ADMIN_SECRET_KEY
    )


@admin_bp.route('/admin/ban')
def admin_ban_ip():
    key = request.args.get('key')
    if key != config.ADMIN_SECRET_KEY:
        abort(404)
    ip = request.args.get('ip')
    if ip in stats.user_stats:
        stats.user_stats[ip]['banned'] = True
        stats.save_stats(stats.user_stats)
    return redirect(url_for('admin.admin_panel', key=config.ADMIN_SECRET_KEY))


@admin_bp.route('/admin/unban')
def admin_unban_ip():
    key = request.args.get('key')
    if key != config.ADMIN_SECRET_KEY:
        abort(404)
    ip = request.args.get('ip')
    if ip in stats.user_stats:
        stats.user_stats[ip]['banned'] = False
        stats.save_stats(stats.user_stats)
    return redirect(url_for('admin.admin_panel', key=config.ADMIN_SECRET_KEY))
