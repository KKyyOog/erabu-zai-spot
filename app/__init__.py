import os
import logging
import re
import secrets
import time
from datetime import datetime

import truststore
from flask import Flask, abort, g, jsonify, render_template, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from app.routes.materials import materials_bp
from app.routes.users import users_bp
from app.routes.link import link_bp
from app.routes.callback import callback_bp
from app.routes.admin import admin_bp
from app.config import Config
from app.services.db_service import init_database
from app.services.liff_service import liff_url_for
from app.services.line_auth_service import session_identity_is_fresh
from app.services.rate_limit_service import allow_request


def create_app():
    logging.basicConfig(level=logging.INFO)
    truststore.inject_into_ssl()

    app = Flask(__name__)
    app.config.from_object(Config)
    proxy_hops = app.config["TRUSTED_PROXY_HOPS"]
    if not 0 <= proxy_hops <= 10:
        raise RuntimeError("TRUSTED_PROXY_HOPS must be between 0 and 10")
    if proxy_hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_hops, x_proto=0,
            x_host=0, x_port=0, x_prefix=0)
    app.config["LIFF_ID"] = str(app.config.get("LIFF_ID") or "").strip()
    app.logger.info(
        "[LINE CONFIG] login_enabled=%s liff_id_present=%s liff_id_length=%d",
        app.config["LINE_LOGIN_ENABLED"],
        bool(app.config["LIFF_ID"]),
        len(app.config["LIFF_ID"]),
    )
    if app.config["LINE_LOGIN_ENABLED"] and not app.config["LIFF_ID"]:
        app.logger.error(
            "[LINE CONFIG] LIFF_ID is missing; LINE pages cannot initialize LIFF"
        )
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

    @app.cli.command("send-notifications")
    def send_notifications():
        """Deliver up to 100 due notifications; schedule every minute."""
        from app.services.notification_service import drain_notifications
        print(f"Delivered: {drain_notifications()}")

    @app.cli.command("clean-upload-jobs")
    def clean_upload_jobs_command():
        """Reconcile tracked uploads older than 24 hours; schedule daily."""
        from app.routes.materials import clean_upload_jobs
        print(f"Reconciled: {clean_upload_jobs()}")

    @app.errorhandler(413)
    def upload_too_large(error):
        return render_template("error.html", message="写真の合計サイズが大きすぎます。写真を減らすか、小さいサイズで選び直してください。"), 413

    @app.errorhandler(500)
    def server_error(error):
        return render_template("error.html", message="処理を完了できませんでした。マイページで保存状況を確認してから、再度お試しください。"), 500

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
            "LINE_LOGIN_ENABLED": app.config["LINE_LOGIN_ENABLED"],
            "USER_INFO_CACHE_SECONDS": app.config["USER_INFO_CACHE_SECONDS"],
            "liff_url_for": liff_url_for,
            "csrf_token": csrf_token,
            "completed_draft": session.pop("completed_draft", None),
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
    def expire_identity():
        if session.get("line_user_id") and not session_identity_is_fresh():
            if str(session["line_user_id"]).startswith("anon_"):
                # Retain migration provenance without treating it as authenticated.
                session["legacy_guest_user_id"] = session["line_user_id"]
            session.pop("line_user_id", None)
            session.pop("line_authenticated_at", None)

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
    def limit_sensitive_requests():
        if request.method != "POST":
            return None
        endpoint = request.endpoint or ""
        limits = {
            "link.liff_link": (30, 60),
            "link.liff_debug": (30, 60),
            "materials.interest": (20, 3600),
            "materials.visit_interest": (20, 3600),
            "materials.report_post": (10, 3600),
            "users.share_contact": (20, 3600),
            "users.update_match_status": (60, 3600),
            "materials.submit": (20, 3600),
            "materials.submit_request": (20, 3600),
            "materials.submit_demolition": (20, 3600),
        }
        if endpoint not in limits:
            return None
        if endpoint == "link.liff_debug" and not app.config["LIFF_DEBUG_LOGGING"]:
            return None
        limit, seconds = limits[endpoint]
        principal = (request.remote_addr or "unknown") if endpoint.startswith("link.") else session.get("line_user_id", request.remote_addr or "unknown")
        if not allow_request(endpoint, principal, limit, seconds):
            retry_after = seconds - int(time.time()) % seconds
            app.logger.warning("[RATE LIMIT] endpoint=%s limit=%s window_seconds=%s proxy_hops=%s forwarded_present=%s",
                endpoint, limit, seconds, proxy_hops, bool(request.headers.get("X-Forwarded-For")))
            message = f"送信回数の上限に達しました。{retry_after}秒ほど待ってから再度お試しください。"
            headers = {"Retry-After": str(retry_after), "Cache-Control": "no-store"}
            if endpoint.startswith("link."):
                return jsonify(ok=False, code="rate_limited", message=message, retry_after=retry_after), 429, headers
            return message, 429, headers

    @app.before_request
    def log_debug_request():
        if (
            app.config["LIFF_DEBUG_LOGGING"]
            and request.path.startswith(("/link", "/users/me", "/callback"))
            and request.path != "/link/liff-debug"
        ):
            trace_id = request.headers.get("X-LIFF-Trace-ID", "")
            trace_id = re.sub(r"[^A-Za-z0-9_-]", "", trace_id)[:64] or "none"
            g.liff_debug_started_at = time.perf_counter()
            g.liff_debug_trace_id = trace_id
            app.logger.info(
                "[REQUEST DEBUG] started method=%s path=%s trace=%s "
                "remote_addr=%s referer_present=%s user_agent=%s",
                request.method,
                request.path,
                trace_id,
                request.headers.get("X-Forwarded-For", request.remote_addr),
                bool(request.headers.get("Referer", "")),
                request.headers.get("User-Agent", ""),
            )

    @app.after_request
    def add_security_headers(response):
        debug_started_at = getattr(g, "liff_debug_started_at", None)
        if debug_started_at is not None:
            app.logger.info(
                "[REQUEST DEBUG] completed method=%s path=%s trace=%s "
                "status=%s duration_ms=%d",
                request.method,
                request.path,
                getattr(g, "liff_debug_trace_id", "none"),
                response.status_code,
                round((time.perf_counter() - debug_started_at) * 1000),
            )
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
