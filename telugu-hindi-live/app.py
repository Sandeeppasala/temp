"""Laptop-hosted Telugu → Hindi interpreter with authorized browser listeners.

Start with: python -m uvicorn app:app --host 127.0.0.1 --port 8000
Run from this project directory. Never expose the admin key to listeners.
"""
import asyncio
import base64
import hmac
import logging
import os
from pathlib import Path
from typing import Optional

import azure.cognitiveservices.speech as speechsdk
from sarvam_provider import SarvamMicrophone, text_translate, hindi_audio
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("interpreter")
HERE = Path(__file__).resolve().parent
app = FastAPI(title="Telugu → Hindi Live")
event_code = os.getenv("EVENT_CODE", "")
admin_key = os.getenv("ADMIN_KEY", "")
max_listeners = int(os.getenv("MAX_LISTENERS", "25"))
provider = os.getenv("TRANSLATION_PROVIDER", "azure").strip().lower()
sarvam_session = None
control_lock = asyncio.Lock()
loop: Optional[asyncio.AbstractEventLoop] = None
clients: set[WebSocket] = set()
running = False
recognizer = None
translation_queue: asyncio.Queue | None = None
worker_task: asyncio.Task | None = None
sequence = 0


def check_secret(given: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def admin_auth(x_admin_key: str | None) -> None:
    if not check_secret(x_admin_key or "", admin_key):
        raise HTTPException(401, "Invalid admin key")


def azure_configured() -> bool:
    return bool(os.getenv("AZURE_SPEECH_KEY") and
                os.getenv("AZURE_SPEECH_KEY") != "replace-with-your-speech-resource-key" and
                os.getenv("AZURE_SPEECH_REGION"))


def configured() -> bool:
    if provider == "sarvam":
        key = os.getenv("SARVAM_API_KEY", "")
        return bool(key) and not key.startswith("replace-")
    return provider == "azure" and azure_configured()


def sarvam_recognized(text: str) -> None:
    if running and translation_queue is not None:
        if not translation_queue.full():
            translation_queue.put_nowait((text, None))
        else:
            log.warning("Sarvam translation backlog full; dropping phrase")


def sarvam_failed(exc: str) -> None:
    global running
    running = False
    log.error("Sarvam transcription stopped: %s", exc)
    asyncio.create_task(publish({"type": "warning", "message": "Sarvam microphone stream stopped; ask organizer to restart."}))
    asyncio.create_task(publish({"type": "status", "running": False}))


async def publish(packet: dict) -> None:
    if not clients:
        return
    stale = []
    for ws in list(clients):
        try:
            await asyncio.wait_for(ws.send_json(packet), timeout=3)
        except Exception:
            stale.append(ws)
    for ws in stale:
        clients.discard(ws)
        try:
            await ws.close()
        except Exception:
            pass


def recognition_callback(evt) -> None:
    if not running or loop is None or translation_queue is None:
        return
    if evt.result.reason != speechsdk.ResultReason.TranslatedSpeech:
        return
    text = (evt.result.translations or {}).get("hi", "").strip()
    telugu = (evt.result.text or "").strip()
    if not text:
        return
    def enqueue():
        if translation_queue and not translation_queue.full():
            translation_queue.put_nowait((telugu, text))
        else:
            log.warning("Translation backlog full: dropping segment")
    loop.call_soon_threadsafe(enqueue)


def canceled_callback(evt) -> None:
    log.error("Azure recognition canceled: %s", getattr(evt, "reason", "unknown"))


def synthesize_hindi(text: str) -> bytes:
    cfg = speechsdk.SpeechConfig(
        subscription=os.environ["AZURE_SPEECH_KEY"],
        region=os.environ["AZURE_SPEECH_REGION"])
    cfg.speech_synthesis_voice_name = os.getenv("HINDI_VOICE", "hi-IN-SwaraNeural")
    cfg.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm)
    synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
    result = synth.speak_text_async(text).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        raise RuntimeError("Hindi speech synthesis failed: " + str(result.reason))
    return bytes(result.audio_data)


async def translation_worker() -> None:
    global sequence
    assert translation_queue is not None
    while True:
        telugu, hindi = await translation_queue.get()
        try:
            # One ordered producer ensures all listeners hear identical segments.
            if hindi is None:
                hindi = await asyncio.to_thread(text_translate, telugu)
            if not hindi:
                continue
            audio = await asyncio.to_thread(
                hindi_audio if provider == "sarvam" else synthesize_hindi, hindi)
            sequence += 1
            await publish({
                "type": "segment", "seq": sequence,
                "telugu": telugu, "hindi": hindi,
                "mime": "audio/wav", "audio": base64.b64encode(audio).decode("ascii")
            })
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("TTS or broadcast failed")
            await publish({"type": "warning", "message": "One segment could not be played."})
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
    global running, recognizer, worker_task, sarvam_session
    running = False
    if sarvam_session:
        await sarvam_session.stop()
        sarvam_session = None
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
            "provider": provider, "provider_configured": configured()}


@app.post("/api/start")
async def start(x_admin_key: str | None = Header(default=None)):
    global running, recognizer, translation_queue, worker_task, sarvam_session
    admin_auth(x_admin_key)
    async with control_lock:
        if running:
            return {"running": True, "provider": provider}
        if not event_code or event_code == admin_key:
            raise HTTPException(400, "Set distinct EVENT_CODE and ADMIN_KEY in .env")
        if provider not in ("azure", "sarvam"):
            raise HTTPException(400, "TRANSLATION_PROVIDER must be azure or sarvam")
        if not configured():
            raise HTTPException(400, f"Configure {provider} API credentials in .env")
        if sarvam_session:
            await sarvam_session.stop()
            sarvam_session = None
        translation_queue = asyncio.Queue(maxsize=12)
        worker_task = asyncio.create_task(translation_worker())
        running = True
        try:
            if provider == "sarvam":
                sarvam_session = SarvamMicrophone(sarvam_recognized, sarvam_failed)
                await sarvam_session.start()
            else:
                cfg = speechsdk.translation.SpeechTranslationConfig(
                    subscription=os.environ["AZURE_SPEECH_KEY"],
                    region=os.environ["AZURE_SPEECH_REGION"])
                cfg.speech_recognition_language = "te-IN"
                cfg.add_target_language("hi")
                mic = speechsdk.audio.AudioConfig(use_default_microphone=True)
                recognizer = speechsdk.translation.TranslationRecognizer(
                    translation_config=cfg, audio_config=mic)
                recognizer.recognized.connect(recognition_callback)
                recognizer.canceled.connect(canceled_callback)
                await asyncio.to_thread(
                    lambda: recognizer.start_continuous_recognition_async().get())
        except Exception as exc:
            running = False
            if sarvam_session:
                await sarvam_session.stop()
                sarvam_session = None
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
    global running, recognizer, worker_task, translation_queue, sarvam_session
    admin_auth(x_admin_key)
    async with control_lock:
        running = False
        if sarvam_session:
            await sarvam_session.stop()
            sarvam_session = None
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
        raise HTTPException(400, f"Configure {provider} credentials first")
    hindi = "नमस्ते। हिंदी अनुवाद की ध्वनि परीक्षण सफल रहा।"
    try:
        audio = await asyncio.to_thread(
            hindi_audio if provider == "sarvam" else synthesize_hindi, hindi)
    except Exception as exc:
        raise HTTPException(502, f"Audio test failed: {exc}") from exc
    sequence += 1
    await publish({"type": "segment", "seq": sequence, "telugu": "",
                   "hindi": hindi, "mime": "audio/wav",
                   "audio": base64.b64encode(audio).decode("ascii")})
    return {"sent": True, "listeners": len(clients), "provider": provider}


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
        clients.add(ws)
        await ws.send_json({"type": "status", "running": running})
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, asyncio.TimeoutError, ValueError):
        pass
    finally:
        clients.discard(ws)
