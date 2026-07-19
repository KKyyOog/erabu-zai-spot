import os
import logging
import re
import secrets
from datetime import datetime

import truststore
from flask import Flask, abort, render_template, request, session

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
    secret_key = app.config.get("SECRET_KEY") or ""
    if (
        (secret_key == "dev-secret" or len(secret_key) < 32)
        and not app.config["ALLOW_INSECURE_DEV_CONFIG"]
    ):
        raise RuntimeError(
            "FLASK_SECRET_KEY must be set to a random value of at least 32 characters. "
            "Set ALLOW_INSECURE_DEV_CONFIG=true only for isolated local development."
        )
    if (
        not app.config["SESSION_COOKIE_SECURE"]
        and not app.config["ALLOW_INSECURE_DEV_CONFIG"]
    ):
        raise RuntimeError(
            "SESSION_COOKIE_SECURE must be true. "
            "Set ALLOW_INSECURE_DEV_CONFIG=true only for isolated local development."
        )

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
        def csrf_token():
            token = session.get("_csrf_token")
            if not token:
                token = secrets.token_urlsafe(32)
                session["_csrf_token"] = token
            return token

        return {
            "LIFF_ID": app.config["LIFF_ID"],
            "liff_url_for": liff_url_for,
            "csrf_token": csrf_token,
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

    @app.template_filter("size_display")
    def size_display(value):
        if not value:
            return ""

        text = str(value).strip()
        text = text.replace("＊", "*").replace("✕", "x").replace("×", "x")
        text = re.sub(r"\s*[xX*]\s*", "×", text)
        text = re.sub(r"([A-Za-zφ□])\s+(?=\d)", r"\1", text)
        text = re.sub(r"(?<=\d)\s+(?=[A-Za-zφ□])", "", text)
        text = re.sub(r"\s+", " ", text)
        return text

    @app.before_request
    def protect_from_csrf():
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            return None

        exempt_endpoints = {
            "callback.callback",
            "link.liff_link",
            "link.liff_debug",
        }
        if request.endpoint in exempt_endpoints:
            return None

        expected_token = session.get("_csrf_token", "")
        supplied_token = (
            request.form.get("_csrf_token")
            or request.headers.get("X-CSRF-Token")
            or ""
        )
        if not expected_token or not supplied_token or not secrets.compare_digest(expected_token, supplied_token):
            app.logger.warning(
                "[CSRF] rejected method=%s path=%s endpoint=%s",
                request.method,
                request.path,
                request.endpoint,
            )
            abort(400)

        return None

    @app.before_request
    def log_debug_request():
        if app.config["LIFF_DEBUG_LOGGING"] and request.path.startswith(
            ("/link", "/users/me", "/callback")
        ):
            app.logger.info(
                "[REQUEST DEBUG] method=%s path=%s remote_addr=%s referer_present=%s user_agent=%s",
                request.method,
                request.path,
                request.headers.get("X-Forwarded-For", request.remote_addr),
                bool(request.headers.get("Referer", "")),
                request.headers.get("User-Agent", ""),
            )

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://static.line-scdn.net; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://api.line.me https://access.line.me https://*.line.me; "
            "frame-src https://liff.line.me https://access.line.me https://*.line.me; "
            "base-uri 'self'; "
            "form-action 'self';",
        )
        return response

    @app.route("/")
    def index():
        return render_template("users/me.html")

    return app
