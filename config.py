"""Uygulama genelindeki yollar, ayarlar dosyası ve depolama seçenekleri."""
import os
import json
import secrets

# Termux her çalıştığında tamamen rastgele ve tahmin edilemez bir admin key üretir
ADMIN_SECRET_KEY = secrets.token_hex(16)

BASE_STORAGE_DIR = os.path.expanduser('~/storage')
DEFAULT_DOWNLOAD_FOLDER = os.path.join(BASE_STORAGE_DIR, 'shared', 'MusicDownloads')
STATS_FILE = os.path.expanduser('~/storage/shared/MusicDownloads/stats.json')
LIBRARY_FILE = os.path.expanduser('~/storage/shared/MusicDownloads/library.json')
CONFIG_FILE = os.path.expanduser('~/.hmusic_config.json')
CACHE_FOLDER = os.path.join(os.path.expanduser('~'), '.hmusic_cache')


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

# Not: DOWNLOAD_FOLDER çalışma anında değişebilir (bkz. set_storage_settings).
# Diğer modüller bu değeri her zaman `config.DOWNLOAD_FOLDER` şeklinde,
# modül üzerinden okumalı; `from config import DOWNLOAD_FOLDER` ile kopyalamamalı,
# aksi halde ayar değişikliği diğer modüllere yansımaz.
DOWNLOAD_FOLDER = app_config.get('download_folder', DEFAULT_DOWNLOAD_FOLDER)

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
if not os.path.exists(CACHE_FOLDER):
    os.makedirs(CACHE_FOLDER, exist_ok=True)

DOWNLOADS_META_FILE = os.path.join(DOWNLOAD_FOLDER, '.hmusic_meta.json')


def set_download_folder(path):
    """Depolama konumunu değiştirir ve config dosyasına kaydeder."""
    global DOWNLOAD_FOLDER
    DOWNLOAD_FOLDER = path
    app_config['download_folder'] = DOWNLOAD_FOLDER
    save_config(app_config)


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
