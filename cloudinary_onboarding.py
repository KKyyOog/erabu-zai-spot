import os

import cloudinary
import cloudinary.api
import cloudinary.uploader
from cloudinary.utils import cloudinary_url
from dotenv import load_dotenv


load_dotenv()


def require_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


cloudinary.config(
    cloud_name=require_env("CLOUDINARY_CLOUD_NAME"),
    api_key=require_env("CLOUDINARY_API_KEY"),
    api_secret=require_env("CLOUDINARY_API_SECRET"),
    secure=True,
)

result = cloudinary.uploader.upload(
    "https://res.cloudinary.com/demo/image/upload/sample.jpg",
    folder="erabu-zai-spot/onboarding",
)

print("Secure URL:", result["secure_url"])
print("Public ID:", result["public_id"])

details = cloudinary.api.resource(result["public_id"])

print("Width:", details["width"])
print("Height:", details["height"])
print("Format:", details["format"])
print("Bytes:", details["bytes"])

url, _ = cloudinary_url(
    result["public_id"],
    fetch_format="auto",
    quality="auto",
)

print("Optimized URL:", url)
