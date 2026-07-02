from flask import current_app, url_for


def build_liff_url(path="/", liff_id=None):
    resolved_liff_id = liff_id if liff_id is not None else current_app.config.get("LIFF_ID", "")
    if not resolved_liff_id:
        return path

    if not path.startswith("/"):
        path = f"/{path}"

    return f"https://liff.line.me/{resolved_liff_id}{path}"


def liff_url_for(endpoint, **values):
    return build_liff_url(url_for(endpoint, **values))
