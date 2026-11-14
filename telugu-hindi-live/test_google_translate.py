"""Simple paid Google Cloud Translation Basic request, using .env (no key printed)."""
from dotenv import load_dotenv
import os
import json
from urllib import request, error
from html import unescape

load_dotenv()
key = os.getenv("GOOGLE_TRANSLATE_API_KEY", "").strip()
if not key or key.startswith(("replace-", "YOUR_")):
    raise SystemExit("Set GOOGLE_TRANSLATE_API_KEY in .env before testing.")
telugu = "నమస్కారం. ధ్యానం మన జీవితంలో చాలా ముఖ్యమైనది."
body = json.dumps({"q": telugu, "source": "te", "target": "en", "format": "text"}, ensure_ascii=False).encode("utf-8")
req = request.Request(
    "https://translation.googleapis.com/language/translate/v2",
    data=body,
    headers={"Content-Type": "application/json; charset=utf-8", "X-goog-api-key": key},
    method="POST",
)
try:
    with request.urlopen(req, timeout=20) as response:
        translated = json.load(response)["data"]["translations"][0]["translatedText"]
except error.HTTPError as exc:
    raise SystemExit(f"Google Translation HTTP {exc.code}: check API enabled, billing and API-key restrictions.") from None
print("Telugu:", telugu)
print("English:", unescape(translated))
