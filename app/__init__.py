import os
import logging

from flask import Flask, request

from app.routes.materials import materials_bp
from app.routes.users import users_bp
from app.routes.link import link_bp
from app.routes.callback import callback_bp
from app.routes.admin import admin_bp
from app.config import Config


def create_app():
    logging.basicConfig(level=logging.INFO)

    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads")
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    app.register_blueprint(materials_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(link_bp)
    app.register_blueprint(callback_bp)
    app.register_blueprint(admin_bp)

    @app.context_processor
    def inject_liff_id():
        return {"LIFF_ID": app.config["LIFF_ID"]}

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
        return "えらぶ材すぽっと is running."

    return app
