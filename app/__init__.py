import os
import logging
from datetime import datetime

import truststore
from flask import Flask, render_template, request

from app.routes.materials import materials_bp
from app.routes.users import users_bp
from app.routes.link import link_bp
from app.routes.callback import callback_bp
from app.routes.admin import admin_bp
from app.config import Config
from app.services.db_service import init_database
from app.services.liff_service import liff_url_for


def create_app():
    logging.basicConfig(level=logging.INFO)
    truststore.inject_into_ssl()

    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads")
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    init_database(app)

    app.register_blueprint(materials_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(link_bp)
    app.register_blueprint(callback_bp)
    app.register_blueprint(admin_bp)

    @app.context_processor
    def inject_liff_id():
        return {
            "LIFF_ID": app.config["LIFF_ID"],
            "liff_url_for": liff_url_for,
        }

    @app.template_filter("date_jp")
    def date_jp(value):
        if not value:
            return ""

        text = str(value).strip()
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d",
        ):
            try:
                parsed = datetime.strptime(text[:19], fmt)
                return f"{parsed.year}年{parsed.month}月{parsed.day}日"
            except ValueError:
                continue

        return text.split(" ")[0]

    @app.before_request
    def log_debug_request():
        if request.path.startswith(("/link", "/users/me", "/callback")):
            app.logger.info(
                "[REQUEST DEBUG] method=%s path=%s query=%s remote_addr=%s referer=%s user_agent=%s",
                request.method,
                request.path,
                request.query_string.decode("utf-8", errors="ignore"),
                request.headers.get("X-Forwarded-For", request.remote_addr),
                request.headers.get("Referer", ""),
                request.headers.get("User-Agent", ""),
            )

    @app.route("/")
    def index():
        return render_template("index.html")

    return app
