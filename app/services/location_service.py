"""Public location projection. Exact locations remain owner-only data."""
import unicodedata


def public_location(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    for town in ("和泊町", "知名町"):
        if town in value:
            return town
    if value == "島内どこでも可":
        return value
    return "場所は問い合わせ後に相談"


def public_post(record):
    result = dict(record)
    result["location"] = public_location(record.get("location"))
    result.pop("owner_name", None)
    return result
