import os
import logging
import secrets
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import truststore
from flask import Flask, abort, redirect, request, session, url_for

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
        raw_state = (request.args.get("liff.state") or "").strip()
        if raw_state:
            target = urlsplit(raw_state)
            if not target.scheme and not target.netloc and target.path.startswith("/") and not target.path.startswith("//"):
                filtered_query = [
                    (key, value)
                    for key, value in parse_qsl(target.query, keep_blank_values=True)
                    if key
                    not in {
                        "liff.referrer",
                        "access_token",
                        "context_token",
                        "feature_token",
                        "id_token",
                        "client_id",
                        "mst_challenge",
                    }
                ]
                filtered_query.append(("liff_entry", "1"))
                return redirect(urlunsplit(("", "", target.path, urlencode(filtered_query), "")), code=302)

        return redirect(url_for("materials.list_materials"), code=302)

    return app
