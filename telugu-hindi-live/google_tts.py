"""Google Cloud Text-to-Speech Basic REST API; emits WAV with LINEAR16."""
import base64
import json
import os
from urllib import request, error

def google_english_audio(text: str, language: str = "en") -> bytes:
    if language not in ("en", "hi"):
        raise ValueError("Unsupported speech language")
    key = os.getenv("GOOGLE_TTS_API_KEY", "").strip() or os.environ["GOOGLE_TRANSLATE_API_KEY"]
    code = "hi-IN" if language == "hi" else "en-IN"
    voice = (os.getenv("GOOGLE_HINDI_VOICE", "hi-IN-Standard-A") if language == "hi"
             else os.getenv("GOOGLE_ENGLISH_VOICE", "en-IN-Standard-A"))
    body = json.dumps({
        "input": {"text": text},
        "voice": {"languageCode": code, "name": voice},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 16000,
                        "speakingRate": float(os.getenv("GOOGLE_TTS_SPEAKING_RATE", "0.85"))}
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
