"""Delivery-only image sizing; stored URLs always refer to the original."""

import re
from urllib.parse import urlsplit, urlunsplit


def image_delivery_url(value, width=640):
    if not value:
        return value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    # Only change ordinary unsigned uploads. Preserve signed/transformed URLs.
    if parsed.scheme != "https" or parsed.netloc != "res.cloudinary.com":
        return value
    match = re.fullmatch(r"(/[^/]+/image/upload/)(v\d+/.*|erabu-zai-spot/.*)", parsed.path)
    if not match:
        return value
    width = max(64, min(int(width), 1600))
    path = f"{match[1]}c_limit,w_{width},h_{width}/q_auto/f_auto/{match[2]}"
    return urlunsplit(parsed._replace(path=path))
