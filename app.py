"""HMusic - giriş noktası.

Çalıştırmak için:  python app.py
(Bu dosyanın bulunduğu klasörden çalıştırılmalı; diğer modülleri
 aynı klasörden düz import ile bulur.)
"""
import os
from flask import Flask
from flask_cors import CORS

import config
import stats
from extensions import limiter
from routes_user import user_bp
from routes_admin import admin_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = os.urandom(32)

    CORS(app)
    limiter.init_app(app)

    app.before_request(stats.check_ip_ban)
    app.after_request(stats.add_security_headers)

    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp)

    return app


app = create_app()

if __name__ == '__main__':
    print("\n" + "=" * 50)
    print(" GİZLİ ADMİN PANELİ LİNKİNİZ:")
    print(f" http://127.0.0.1:5000/admin?key={config.ADMIN_SECRET_KEY}")
    print("=" * 50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
