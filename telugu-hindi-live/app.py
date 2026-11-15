"""Laptop-hosted Telugu → English interpreter with authorized browser listeners.

Start with: python -m uvicorn app:app --host 127.0.0.1 --port 8000
Run from this project directory. Never expose the admin key to listeners.
"""
import asyncio
import base64
import hmac
import html
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional
from urllib import request as urlrequest
from urllib import error as urlerror

import azure.cognitiveservices.speech as speechsdk
from google_stream import GoogleMicrophone
from minute_capture import MinuteCapture
from minute_summary import summarize_telugu_audio, GeminiBillingRequired
from google_tts import google_english_audio
from terminology import replace_known_names, load_terms
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("interpreter")
HERE = Path(__file__).resolve().parent
app = FastAPI(title="Telugu → English Live")
event_code = os.getenv("EVENT_CODE", "")
admin_key = os.getenv("ADMIN_KEY", "")
max_listeners = int(os.getenv("MAX_LISTENERS", "25"))
provider = os.getenv("TRANSLATION_PROVIDER", "google").strip().lower()
interpretation_mode = os.getenv("INTERPRETATION_MODE", "minute_summary").strip().lower()
# Google Cloud Translation Basic converts recognized Telugu text to English.
TARGET_LANGUAGE = "en"
GOOGLE_TRANSLATE_KEY = os.getenv("GOOGLE_TRANSLATE_API_KEY", "").strip()
ENGLISH_VOICE = os.getenv("ENGLISH_VOICE", "en-US-JennyNeural")
control_lock = asyncio.Lock()
loop: Optional[asyncio.AbstractEventLoop] = None
clients: set[WebSocket] = set()
client_languages: dict[WebSocket, str] = {}
running = False
recognizer = None
google_mic = None
minute_mic = None
translation_queue: asyncio.Queue | None = None
worker_task: asyncio.Task | None = None
sequence = 0
metrics = {"queue_wait_s": 0.0, "translate_s": 0.0, "tts_s": 0.0, "total_s": 0.0, "dropped": 0, "processed": 0}
speech_health = {"last_partial": 0.0, "last_queued": 0.0, "last_audio_sent": 0.0, "queued_chunks": 0}


def check_secret(given: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def admin_auth(x_admin_key: str | None) -> None:
    if not check_secret(x_admin_key or "", admin_key):
        raise HTTPException(401, "Invalid admin key")


def azure_configured() -> bool:
    return bool(os.getenv("AZURE_SPEECH_KEY") and
                os.getenv("AZURE_SPEECH_KEY") != "replace-with-your-speech-resource-key" and
                os.getenv("AZURE_SPEECH_REGION"))


def google_configured() -> bool:
    return bool(GOOGLE_TRANSLATE_KEY) and not GOOGLE_TRANSLATE_KEY.startswith(("replace-", "YOUR_"))


def configured() -> bool:
    if interpretation_mode == "minute_summary":
        return bool(os.getenv("GEMINI_API_KEY", "").strip()) and bool(
            os.getenv("GOOGLE_TTS_API_KEY", "").strip() or GOOGLE_TRANSLATE_KEY)
    return google_configured() and (provider == "google" or (provider == "azure" and azure_configured()))


def google_translate_english(telugu: str) -> str:
    """Translate Telugu text through Google's official, billed Cloud Translation Basic API."""
    adjusted, replaced = replace_known_names(telugu)
    if replaced:
        log.info("Preserved %d configured proper-name occurrences for translation", replaced)
    body = json.dumps({
        "q": adjusted, "source": "te", "target": "en", "format": "text"
    }, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        "https://translation.googleapis.com/language/translate/v2",
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-goog-api-key": GOOGLE_TRANSLATE_KEY,
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=20) as response:
            data = json.load(response)
    except urlerror.HTTPError as exc:
        # Avoid logging URL/query or authentication headers.
        raise RuntimeError(f"Google Translation HTTP {exc.code}; verify billing, API enablement, and key restrictions") from None
    translations = data.get("data", {}).get("translations", [])
    if not translations:
        raise RuntimeError("Google Translation returned no translations")
    return html.unescape(translations[0].get("translatedText", "")).strip()



async def publish(packet: dict) -> None:
    if not clients:
        return
    stale = []
    for ws in list(clients):
        if packet.get("language") and client_languages.get(ws, "en") != packet["language"]:
            continue
        try:
            await asyncio.wait_for(ws.send_json(packet), timeout=3)
        except Exception:
            stale.append(ws)
    for ws in stale:
        clients.discard(ws)
        client_languages.pop(ws, None)
        try:
            await ws.close()
        except Exception:
            pass


def recognition_callback(evt) -> None:
    if not running or loop is None or translation_queue is None:
        return
    if evt.result.reason != speechsdk.ResultReason.RecognizedSpeech:
        return
    telugu = (evt.result.text or "").strip()
    if not telugu:
        return
    def enqueue():
        if running and translation_queue and not translation_queue.full():
            translation_queue.put_nowait((telugu, time.monotonic()))
        else:
            metrics["dropped"] += 1
            log.warning("Translation backlog full: dropping segment")
    loop.call_soon_threadsafe(enqueue)


def google_recognized(telugu: str) -> None:
    if not running or loop is None or translation_queue is None:
        return
    def enqueue():
        if running and translation_queue and not translation_queue.full():
            translation_queue.put_nowait((telugu, time.monotonic()))
            speech_health["last_queued"] = time.monotonic()
            speech_health["queued_chunks"] += 1
            if translation_queue.qsize() > 15:
                log.warning("Google translation backlog: %d phrases", translation_queue.qsize())
        else:
            metrics["dropped"] += 1
            log.error("Google translation queue full (100); phrase was lost")
    loop.call_soon_threadsafe(enqueue)


def minute_audio_received(wav: bytes) -> None:
    if not running or loop is None or translation_queue is None:
        return
    def enqueue():
        if running and translation_queue is not None:
            if translation_queue.full():
                metrics["dropped"] += 1
                log.error("Two-minute summary queue FULL; 120 seconds of speech were lost")
                asyncio.create_task(publish({"type":"warning",
                    "message":"Summary backlog full; two minutes could not be processed"}))
            else:
                translation_queue.put_nowait((wav, time.monotonic()))
                log.info("Captured real 120-second audio window; queued %d bytes", len(wav))
    loop.call_soon_threadsafe(enqueue)


def google_partial(telugu: str) -> None:
    speech_health["last_partial"] = time.monotonic()
    if loop is not None and running:
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(publish({"type": "partial", "telugu": telugu}))
        )


def google_failed(message: str) -> None:
    log.error("%s", message)
    if loop is not None:
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(publish({"type": "warning", "message": message})))


def canceled_callback(evt) -> None:
    log.error("Azure recognition canceled: %s", getattr(evt, "reason", "unknown"))


def synthesize_english(text: str) -> bytes:
    cfg = speechsdk.SpeechConfig(
        subscription=os.environ["AZURE_SPEECH_KEY"],
        region=os.environ["AZURE_SPEECH_REGION"])
    cfg.speech_synthesis_voice_name = ENGLISH_VOICE
    cfg.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm)
    synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
    result = synth.speak_text_async(text).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        raise RuntimeError("English speech synthesis failed: " + str(result.reason))
    return bytes(result.audio_data)


async def minute_summary_worker() -> None:
    global sequence, running, minute_mic
    assert translation_queue is not None
    while True:
        wav, captured_at = await translation_queue.get()
        try:
            log.info("Processing 120-second Telugu audio window")
            started = time.monotonic()
            summaries = await asyncio.to_thread(summarize_telugu_audio, wav)
            metrics["translate_s"] = round(time.monotonic()-started, 2)
            if all(value == "NO_INTELLIGIBLE_SPEECH" for value in summaries.values()):
                log.info("No intelligible speech in this two-minute window; no TTS audio generated")
                continue
            sequence += 1
            seq = sequence
            for language in ("en", "hi"):
                summary = summaries[language]
                if summary == "NO_INTELLIGIBLE_SPEECH":
                    continue
                await publish({"type": "caption", "seq": seq, "english": summary,
                               "language": language, "telugu": "", "kind": "minute_summary"})
                start_tts = time.monotonic()
                try:
                    output = await asyncio.to_thread(google_english_audio, summary, language)
                except Exception:
                    log.exception("TTS failed for language %s", language)
                    await publish({"type": "warning", "language": language,
                                   "message": "Speech synthesis failed for " + language})
                    continue
                metrics["tts_s"] = round(time.monotonic()-start_tts, 2)
                metrics["total_s"] = round(time.monotonic()-captured_at, 2)
                await publish({"type": "segment", "seq": seq, "english": summary,
                               "language": language, "telugu": "", "kind": "minute_summary",
                               "audio": base64.b64encode(output).decode("ascii"),
                               "mime": "audio/wav", "timing": dict(metrics)})
            metrics["processed"] += 1
            log.info("Two-minute summary %d: understanding %.2fs, TTS %.2fs, post-capture %.2fs",
                     seq,metrics["translate_s"],metrics["tts_s"],metrics["total_s"])
        except asyncio.CancelledError:
            raise
        except GeminiBillingRequired as exc:
            metrics["dropped"] += 1
            running = False
            log.error("%s", exc)
            await publish({"type":"warning", "message":str(exc)})
            await publish({"type":"status", "running":False})
            if minute_mic:
                mic = minute_mic
                minute_mic = None
                await asyncio.to_thread(mic.stop)
            # Drain captured audio rather than retaining unprocessable WAVs.
            while True:
                try:
                    translation_queue.get_nowait()
                    translation_queue.task_done()
                    metrics["dropped"] += 1
                except asyncio.QueueEmpty:
                    break
            break
        except Exception as exc:
            metrics["dropped"] += 1
            log.exception("Two-minute summary processing failed")
            await publish({"type":"warning",
                           "message":"Two-minute summary failed: "+type(exc).__name__+
                           ". Check server logs and Gemini API key."})
        finally:
            translation_queue.task_done()


async def translation_worker() -> None:
    global sequence
    assert translation_queue is not None
    while True:
        telugu, received_at = await translation_queue.get()
        try:
            metrics["queue_wait_s"] = round(time.monotonic() - received_at, 2)
            started = time.monotonic()
            english = await asyncio.to_thread(google_translate_english, telugu)
            metrics["translate_s"] = round(time.monotonic() - started, 2)
            if not english:
                continue
            sequence += 1
            seq = sequence
            # Show English captions immediately; don't wait for audio synthesis.
            await publish({"type": "caption", "seq": seq,
                           "telugu": telugu, "english": english})
            tts_start = time.monotonic()
            audio = await asyncio.to_thread(
                google_english_audio if provider == 'google' else synthesize_english, english)
            metrics["tts_s"] = round(time.monotonic() - tts_start, 2)
            metrics["total_s"] = round(time.monotonic() - received_at, 2)
            metrics["processed"] += 1
            speech_health["last_audio_sent"] = time.monotonic()
            await publish({
                "type": "segment", "seq": seq,
                "telugu": telugu, "english": english,
                "timing": dict(metrics),
                "mime": "audio/wav", "audio": base64.b64encode(audio).decode("ascii")
            })
            log.info("Segment %s: queue %.2fs, translation %.2fs, TTS %.2fs, total %.2fs",
                     seq, metrics["queue_wait_s"], metrics["translate_s"],
                     metrics["tts_s"], metrics["total_s"])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Google translation, TTS or broadcast failed")
            await publish({"type": "warning", "message": "Translation or speech synthesis failed for one phrase. Check server logs."})
        finally:
            translation_queue.task_done()


@app.on_event("startup")
async def startup() -> None:
    global loop
    loop = asyncio.get_running_loop()
    if not event_code or not admin_key or event_code == admin_key:
        log.warning("Set distinct, strong EVENT_CODE and ADMIN_KEY in .env before sharing.")


@app.on_event("shutdown")
async def shutdown() -> None:
    global running, recognizer, worker_task, google_mic, minute_mic
    running = False
    if minute_mic:
        await asyncio.to_thread(minute_mic.stop)
        minute_mic = None
    if google_mic:
        await asyncio.to_thread(google_mic.stop)
        google_mic = None
    if recognizer:
        await asyncio.to_thread(lambda: recognizer.stop_continuous_recognition_async().get())
        recognizer = None
    if worker_task:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


@app.get("/")
def listener_page():
    return FileResponse(HERE / "web" / "index.html")


@app.get("/admin")
def admin_page():
    return FileResponse(HERE / "web" / "admin.html")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def status(x_admin_key: str | None = Header(default=None)):
    admin_auth(x_admin_key)
    return {"running": running, "listeners": len(clients),
            "azure_configured": azure_configured(),
            "google_configured": google_configured(),
            "translation_engine": "google-cloud-translation-v2",
            "provider": provider, "speech_engine": provider, "tts_engine": provider,
            "configured_names": len(load_terms()),
            "interpretation_mode": interpretation_mode,
            "target_language": TARGET_LANGUAGE,
            "voice": ENGLISH_VOICE, "provider_configured": configured(),
            "metrics": dict(metrics), "queued_phrases": translation_queue.qsize() if translation_queue else 0,
            "speech_health": {**{k+"_age_s": round(time.monotonic()-v, 1) if v else None
                               for k,v in speech_health.items() if k.startswith("last_")},
                              "queued_chunks": speech_health["queued_chunks"]}}


@app.post("/api/start")
async def start(x_admin_key: str | None = Header(default=None)):
    global running, recognizer, translation_queue, worker_task, google_mic, minute_mic
    admin_auth(x_admin_key)
    async with control_lock:
        if running:
            return {"running": True, "provider": provider}
        if not event_code or event_code == admin_key:
            raise HTTPException(400, "Set distinct EVENT_CODE and ADMIN_KEY in .env")
        if interpretation_mode not in ("minute_summary","live"):
            raise HTTPException(400, "INTERPRETATION_MODE must be minute_summary or live")
        if interpretation_mode == "minute_summary" and provider != "google":
            raise HTTPException(400, "Minute summary mode requires TRANSLATION_PROVIDER=google")
        if provider not in ("azure", "google"):
            raise HTTPException(400, "Set TRANSLATION_PROVIDER=google or azure")
        if not configured():
            raise HTTPException(400, "For minute summaries set GEMINI_API_KEY and GOOGLE_TTS_API_KEY in .env, then restart the server")
        translation_queue = asyncio.Queue(maxsize=100 if interpretation_mode=="live" else 12)
        worker_task = asyncio.create_task(
            minute_summary_worker() if interpretation_mode=="minute_summary"
            else translation_worker())
        running = True
        try:
            if interpretation_mode == "minute_summary":
                minute_mic = MinuteCapture(minute_audio_received, google_failed)
                minute_mic.start()
            elif provider == "google":
                google_mic = GoogleMicrophone(google_recognized, google_failed, google_partial)
                google_mic.start()
            else:
                cfg = speechsdk.SpeechConfig(
                    subscription=os.environ["AZURE_SPEECH_KEY"],
                    region=os.environ["AZURE_SPEECH_REGION"])
                cfg.speech_recognition_language = "te-IN"
                mic = speechsdk.audio.AudioConfig(use_default_microphone=True)
                recognizer = speechsdk.SpeechRecognizer(
                    speech_config=cfg, audio_config=mic)
                recognizer.recognized.connect(recognition_callback)
                recognizer.canceled.connect(canceled_callback)
                await asyncio.to_thread(
                    lambda: recognizer.start_continuous_recognition_async().get())
        except Exception as exc:
            running = False
            if google_mic:
                await asyncio.to_thread(google_mic.stop)
                google_mic = None
            if minute_mic:
                await asyncio.to_thread(minute_mic.stop)
                minute_mic = None
            if worker_task:
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass
                worker_task = None
            translation_queue = None
            recognizer = None
            raise HTTPException(502, f"Unable to start {provider} microphone: {exc}") from exc
        await publish({"type": "status", "running": True})
        return {"running": True, "provider": provider}


@app.post("/api/stop")
async def stop(x_admin_key: str | None = Header(default=None)):
    global running, recognizer, worker_task, translation_queue, google_mic, minute_mic
    admin_auth(x_admin_key)
    async with control_lock:
        running = False
        if google_mic:
            await asyncio.to_thread(google_mic.stop)
            google_mic = None
        if minute_mic:
            await asyncio.to_thread(minute_mic.stop)
            minute_mic = None
        if recognizer:
            await asyncio.to_thread(
                lambda: recognizer.stop_continuous_recognition_async().get())
            recognizer = None
        if translation_queue:
            try:
                await asyncio.wait_for(translation_queue.join(), timeout=20)
            except asyncio.TimeoutError:
                log.warning("Pending translation queue did not drain")
        if worker_task:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
            worker_task = None
        translation_queue = None
        await publish({"type": "status", "running": False})
        return {"running": False}


@app.post("/api/test")
async def test_voice(x_admin_key: str | None = Header(default=None)):
    global sequence
    admin_auth(x_admin_key)
    if not configured():
        raise HTTPException(400, "Configure credentials for selected provider first")
    english = "Hello. The English translation audio test was successful."
    hindi = "नमस्ते। हिंदी आवाज़ की जाँच सफल रही।"
    sequence += 1
    seq = sequence
    sent = []
    for language, sample in (("en", english), ("hi", hindi)):
        try:
            if interpretation_mode == "minute_summary":
                audio = await asyncio.to_thread(google_english_audio, sample, language)
            else:
                if language == "hi":
                    continue
                audio = await asyncio.to_thread(
                    google_english_audio if provider == "google" else synthesize_english, sample)
        except Exception as exc:
            raise HTTPException(502, f"{language} audio test failed: {exc}") from exc
        await publish({"type": "segment", "seq": seq, "telugu": "",
                       "english": sample, "language": language, "mime": "audio/wav",
                       "audio": base64.b64encode(audio).decode("ascii")})
        sent.append(language)
    return {"sent": True, "languages": sent, "listeners": len(clients), "provider": provider}



@app.websocket("/ws")
async def listen(ws: WebSocket):
    await ws.accept()
    try:
        # First message authenticates. Do not put event codes into URLs or query logs.
        msg = await asyncio.wait_for(ws.receive_json(), timeout=10)
        if msg.get("type") != "auth" or not check_secret(str(msg.get("code", "")), event_code):
            await ws.close(code=1008)
            return
        if len(clients) >= max_listeners:
            await ws.close(code=1013)
            return
        language = str(msg.get("language", "en"))
        client_languages[ws] = language if language in ("en", "hi") else "en"
        clients.add(ws)
        await ws.send_json({"type": "status", "running": running})
        while True:
            message = await ws.receive_json()
            if message.get("type") == "language" and message.get("language") in ("en", "hi"):
                client_languages[ws] = message["language"]
    except (WebSocketDisconnect, asyncio.TimeoutError, ValueError):
        pass
    finally:
        clients.discard(ws)
        client_languages.pop(ws, None)
