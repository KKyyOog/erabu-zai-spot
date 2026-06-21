from pathlib import Path
import subprocess, textwrap, sys

script = textwrap.dedent("""
#!/usr/bin/env python3

import cloudinary
import cloudinary.uploader
import cloudinary.api
from cloudinary.utils import cloudinary_url

cloudinary.config(
    cloud_name="dfiayiqsz",
    api_key="288728492897488",
    api_secret="HEZSdxXcxEC4s_xaxQPOwGpqTX0",
    secure=True
)

result = cloudinary.uploader.upload(
    "https://res.cloudinary.com/demo/image/upload/sample.jpg"
)

print("Secure URL:", result["secure_url"])
print("Public ID:", result["public_id"])

details = cloudinary.api.resource(result["public_id"])

print("Width:", details["width"])
print("Height:", details["height"])
print("Format:", details["format"])
print("Bytes:", details["bytes"])

# f_auto: automatically chooses the best image format
# q_auto: automatically chooses the best image quality
url, _ = cloudinary_url(
    result["public_id"],
    fetch_format="auto",
    quality="auto"
)

print("Done! Click link below to see optimized version of the image. Check the size and the format.")
print(url)
""")

path = Path("/mnt/data/cloudinary_onboarding.py")
path.write_text(script)

print("chmod +x /mnt/data/cloudinary_onboarding.py")
subprocess.run(["chmod", "+x", str(path)], check=True)

print("Running script...")
proc = subprocess.run([sys.executable, str(path)], capture_output=True, text=True)

print("RETURN_CODE:", proc.returncode)
print("STDOUT:\n", proc.stdout)
print("STDERR:\n", proc.stderr)
