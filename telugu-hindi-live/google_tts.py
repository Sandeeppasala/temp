"""Google Cloud Text-to-Speech Basic REST API; emits WAV with LINEAR16."""
import base64
import json
import os
from urllib import request, error

def google_english_audio(text: str) -> bytes:
    key = os.getenv("GOOGLE_TTS_API_KEY", "").strip() or os.environ["GOOGLE_TRANSLATE_API_KEY"]
    body = json.dumps({
        "input": {"text": text},
        "voice": {"languageCode": "en-US", "name": os.getenv("GOOGLE_ENGLISH_VOICE", "en-US-Standard-C")},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 16000}
    }).encode("utf-8")
    req = request.Request(
        "https://texttospeech.googleapis.com/v1/text:synthesize",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "X-goog-api-key": key})
    try:
        with request.urlopen(req, timeout=25) as resp:
            encoded = json.load(resp)["audioContent"]
    except error.HTTPError as exc:
        raise RuntimeError(f"Google TTS HTTP {exc.code}; check API, billing and key restrictions") from None
    return base64.b64decode(encoded, validate=True)
