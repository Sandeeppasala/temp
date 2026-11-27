"""Laptop-hosted Telugu → English interpreter with authorized browser listeners.

Start with: python -m uvicorn app:app --host 127.0.0.1 --port 8000
Run from this project directory. Never expose the admin key to listeners.
"""
import asyncio
import audioop
import io
import secrets
import shutil
import wave
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
from semantic_capture import SemanticCapture
from minute_summary import summarize_telugu_audio, GeminiBillingRequired
from google_tts import google_english_audio
from terminology import replace_known_names, load_terms
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

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
summary_window_seconds = 120
summary_context = ""
metrics = {"queue_wait_s": 0.0, "translate_s": 0.0, "tts_s": 0.0, "total_s": 0.0, "dropped": 0, "processed": 0}
speech_health = {"last_partial": 0.0, "last_queued": 0.0, "last_audio_sent": 0.0, "queued_chunks": 0}


# Continuous MP3 media stream: HTMLMediaElement remains the playback owner
# while the phone is locked. Requires ffmpeg on the laptop PATH.
stream_sessions: dict[str, tuple[str, float]] = {}
stream_clients: dict[str, set[asyncio.Queue]] = {"en": set(), "hi": set()}
STREAM_RATE = 16000
STREAM_TTL = 18 * 3600

def stream_pcm(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        if wav.getcomptype() != "NONE":
            raise ValueError("Compressed WAV is not supported")
        pcm = wav.readframes(wav.getnframes())
    if width != 2:
        pcm = audioop.lin2lin(pcm, width, 2)
    if channels == 2:
        pcm = audioop.tomono(pcm, 2, .5, .5)
    elif channels != 1:
        raise ValueError("Unsupported channel count")
    if rate != STREAM_RATE:
        pcm, _ = audioop.ratecv(pcm, 2, 1, rate, STREAM_RATE, None)
    return pcm

async def broadcast_stream(language: str, wav_bytes: bytes, ready_at=None) -> None:
    if ready_at is None:
        ready_at = time.monotonic()
    if not stream_clients[language]:
        return
    try:
        pcm = await asyncio.to_thread(stream_pcm, wav_bytes)
    except Exception:
        log.exception("Unable to convert TTS WAV to streaming PCM")
        return
    log.info("DIAG broadcast lang=%s pcm_s=%.3f clients=%d", language, len(pcm)/(STREAM_RATE*2), len(stream_clients[language]))
    for queue in tuple(stream_clients[language]):
        try:
            queue.put_nowait((pcm, ready_at))
            log.info("DIAG enqueue lang=%s stream=%x depth=%d queued_pcm_s=%.3f", language, id(queue), queue.qsize(), sum(len(item[0]) for item in queue._queue)/(STREAM_RATE*2))
        except asyncio.QueueFull:
            log.warning("Listener streaming queue full; disconnecting slow stream")
            stream_clients[language].discard(queue)

@app.post("/api/stream-session")
async def create_stream_session(request: Request, response: Response):
    body = await request.json()
    if not check_secret(str(body.get("code", "")), event_code):
        raise HTTPException(401, "Invalid event code")
    if not shutil.which("ffmpeg"):
        raise HTTPException(503, "Install ffmpeg on the laptop to enable lock-screen streaming")
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    for old, (_, created) in list(stream_sessions.items()):
        if now - created > STREAM_TTL:
            stream_sessions.pop(old, None)
    stream_sessions[token] = ("listener", now)
    response.set_cookie("listener_stream", token, httponly=True,
                        secure=request.url.scheme == "https", samesite="strict",
                        max_age=STREAM_TTL, path="/")
    return {"ready": True}

@app.get("/stream/{language}")
async def continuous_stream(language: str, request: Request):
    token = request.cookies.get("listener_stream", "")
    session = stream_sessions.get(token)
    if not session or time.monotonic() - session[1] > STREAM_TTL:
        raise HTTPException(401, "Join with your event code first")
    if language not in ("en", "hi"):
        raise HTTPException(404, "Unknown language")
    if sum(map(len, stream_clients.values())) >= max_listeners:
        raise HTTPException(503, "Audio stream full")
    queue: asyncio.Queue = asyncio.Queue(maxsize=24)
    stream_clients[language].add(queue)
    async def generate():
        proc = None
        writer = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "s16le", "-ar", str(STREAM_RATE), "-ac", "1", "-i", "pipe:0",
                "-codec:a", "libmp3lame", "-b:a", "48k",
                "-f", "mp3", "-flush_packets", "1", "pipe:1",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            # Pace speech and silence on the same real-time PCM clock.
            async def feed():
                frame_bytes = STREAM_RATE * 2 // 10  # 100 ms, mono s16le
                silence = bytes(frame_bytes)
                silent_seconds = 0.0
                last_report = time.monotonic()
                deadline = time.monotonic()
                diag_start = deadline
                diag_last = deadline
                pcm_seconds = 0.0
                last_pcm_seconds = 0.0
                pipe_seconds = 0.0
                pipe_max = 0.0
                reset_seconds = 0.0
                active_remaining = 0.0

                async def write_frame(frame):
                    nonlocal deadline, diag_last, pcm_seconds, last_pcm_seconds
                    nonlocal pipe_seconds, pipe_max, reset_seconds, active_remaining
                    # Do not burst to catch up after a blocked pipe or event-loop stall.
                    now = time.monotonic()
                    reset_seconds += max(0.0, now - deadline)
                    deadline = max(deadline, now)
                    pipe_start = time.monotonic()
                    proc.stdin.write(frame)
                    await proc.stdin.drain()
                    pipe_elapsed = time.monotonic() - pipe_start
                    pipe_seconds += pipe_elapsed
                    pipe_max = max(pipe_max, pipe_elapsed)
                    duration = len(frame) / (STREAM_RATE * 2)
                    deadline += duration
                    await asyncio.sleep(max(0.0, deadline - time.monotonic()))
                    pcm_seconds += duration
                    active_remaining = max(0.0, active_remaining - duration)
                    now = time.monotonic()
                    if now - diag_last >= 5.0:
                        wall = now - diag_last
                        consumed = pcm_seconds - last_pcm_seconds
                        queued = sum(len(item[0]) for item in queue._queue)/(STREAM_RATE*2)
                        log.info("DIAG playback lang=%s stream=%x wall_s=%.3f pcm_s=%.3f pcm_rate=%.4f cumulative_drift_s=%.3f deadline_reset_s=%.3f pipe_write_s=%.3f pipe_max_s=%.3f queued_pcm_s=%.3f active_remaining_s=%.3f pending_pcm_s=%.3f depth=%d", language, id(queue), wall, consumed, consumed/wall, now-diag_start-pcm_seconds, reset_seconds, pipe_seconds, pipe_max, queued, active_remaining, queued+active_remaining, queue.qsize())
                        diag_last = now
                        last_pcm_seconds = pcm_seconds
                        pipe_seconds = pipe_max = reset_seconds = 0.0

                while proc.returncode is None:
                    try:
                        pcm, ready_at = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        await write_frame(silence)
                        silent_seconds += len(silence) / (STREAM_RATE * 2)
                        if time.monotonic() - last_report >= 5:
                            log.info("DIAG starvation lang=%s stream=%x pending_silence_s=%.2f depth=%d", language, id(queue), silent_seconds, queue.qsize())
                            last_report = time.monotonic()
                        continue

                    active_remaining = len(pcm)/(STREAM_RATE*2)
                    log.info("DIAG feed lang=%s stream=%x speech_s=%.3f preceding_silence_s=%.2f depth=%d ready_to_feed_s=%.3f queued_pcm_s=%.3f", language, id(queue), active_remaining, silent_seconds, queue.qsize(), time.monotonic()-ready_at, sum(len(item[0]) for item in queue._queue)/(STREAM_RATE*2))
                    silent_seconds = 0.0
                    for offset in range(0, len(pcm), frame_bytes):
                        await write_frame(pcm[offset:offset + frame_bytes])
            writer = asyncio.create_task(feed())
            while not await request.is_disconnected():
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
        except (BrokenPipeError, ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            stream_clients[language].discard(queue)
            if writer:
                writer.cancel()
                try:
                    await writer
                except (asyncio.CancelledError, Exception):
                    pass
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
    return StreamingResponse(generate(), media_type="audio/mpeg",
        headers={"Cache-Control":"no-store, no-transform", "X-Accel-Buffering":"no"})

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
    if interpretation_mode in ("minute_summary", "semantic_summary"):
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
                log.error("Summary queue FULL; %d seconds of speech were lost", summary_window_seconds)
                asyncio.create_task(publish({"type":"warning",
                    "message":f"Summary backlog full; {summary_window_seconds} seconds could not be processed"}))
            else:
                translation_queue.put_nowait((wav, time.monotonic()))
                log.info("Captured real %.1f-second audio segment; queued %d bytes", (len(wav)-44)/32000, len(wav))
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
    """Two concurrent Gemini calls; publish results in capture order to independent TTS FIFOs.

    A failed request still occupies its ordered slot, so later summaries never
    overtake earlier ones. Parallel requests use the last *delivered* summary
    for context (not an unfinished predecessor).
    """
    global sequence, running, minute_mic, summary_context
    assert translation_queue is not None
    language_queues = {"en": asyncio.Queue(), "hi": asyncio.Queue()}
    completed = asyncio.Queue()
    in_flight = {}
    pending = {}
    next_capture = 0
    next_delivery = 0
    stopping = False

    async def language_worker(language: str) -> None:
        queue = language_queues[language]
        previous_ready = None
        while True:
            seq, summary, captured_at, translate_seconds = await queue.get()
            try:
                await publish({"type": "caption", "seq": seq, "english": summary,
                               "language": language, "telugu": "", "kind": "minute_summary"})
                started = time.monotonic()
                try:
                    output = await asyncio.to_thread(google_english_audio, summary, language)
                except Exception:
                    log.exception("TTS failed for language %s summary %d", language, seq)
                    await publish({"type": "warning", "language": language,
                                   "message": "Speech synthesis failed for " + language})
                    continue
                tts_seconds = round(time.monotonic() - started, 2)
                total_seconds = round(time.monotonic() - captured_at, 2)
                ready = time.monotonic()
                try:
                    with wave.open(io.BytesIO(output), "rb") as diagnostic_wav:
                        audio_seconds = diagnostic_wav.getnframes()/diagnostic_wav.getframerate()
                except Exception:
                    audio_seconds = -1.0
                log.info("DIAG tts lang=%s seq=%d audio_s=%.3f ready_interval_s=%.3f tts_depth=%d", language, seq, audio_seconds, ready-previous_ready if previous_ready is not None else -1.0, queue.qsize())
                previous_ready = ready
                await broadcast_stream(language, output, ready_at=ready)
                await publish({"type": "segment", "seq": seq, "english": summary,
                               "language": language, "telugu": "", "kind": "minute_summary",
                               "audio": base64.b64encode(output).decode("ascii"),
                               "mime": "audio/wav",
                               "timing": {"translate_s": translate_seconds,
                                          "tts_s": tts_seconds, "total_s": total_seconds}})
                log.info("%s summary %d: TTS %.2fs, post-capture %.2fs",
                         language, seq, tts_seconds, total_seconds)
            finally:
                queue.task_done()

    async def gemini_job(index, wav, captured_at, context):
        started = time.monotonic()
        log.info("DIAG gemini_start index=%d queue_wait_s=%.3f active=%d", index, started-captured_at, len(in_flight))
        try:
            result = await asyncio.to_thread(
                summarize_telugu_audio, wav, max(1, round((len(wav)-44)/32000)), context)
            log.info("DIAG gemini_end index=%d elapsed_s=%.3f", index, time.monotonic()-started)
            await completed.put((index, captured_at, round(time.monotonic()-started, 2), result, None))
        except Exception as exc:
            await completed.put((index, captured_at, round(time.monotonic()-started, 2), None, exc))

    language_tasks = [asyncio.create_task(language_worker(lang), name="tts-" + lang)
                      for lang in ("en", "hi")]
    try:
        while True:
            # Dispatch no more than two Gemini requests at a time.
            while not stopping and len(in_flight) < 2:
                try:
                    wav, captured_at = translation_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                index = next_capture
                next_capture += 1
                metrics["queue_wait_s"] = round(time.monotonic()-captured_at, 2)
                task = asyncio.create_task(
                    gemini_job(index, wav, captured_at, summary_context),
                    name="gemini-" + str(index))
                in_flight[index] = task
                log.info("Gemini request %d started; active %d, capture backlog %d",
                         index, len(in_flight), translation_queue.qsize())

            if stopping and not in_flight:
                break
            if not in_flight:
                # Wait for new source audio, without busy-looping.
                wav, captured_at = await translation_queue.get()
                index = next_capture
                next_capture += 1
                metrics["queue_wait_s"] = round(time.monotonic()-captured_at, 2)
                in_flight[index] = asyncio.create_task(
                    gemini_job(index, wav, captured_at, summary_context),
                    name="gemini-" + str(index))
                continue

            # With a free slot, recheck source audio every 50 ms rather than
            # waiting indefinitely for the active request to complete.
            if not stopping and len(in_flight) < 2:
                try:
                    result = await asyncio.wait_for(completed.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
            else:
                result = await completed.get()
            index, captured_at, gemini_seconds, summaries, failure = result
            task = in_flight.pop(index)
            await task
            pending[index] = (captured_at, gemini_seconds, summaries, failure)
            translation_queue.task_done()
            completed.task_done()

            # Gemini responses may arrive out of order. Never reorder speech.
            while next_delivery in pending:
                captured_at, gemini_seconds, summaries, failure = pending.pop(next_delivery)
                next_delivery += 1
                metrics["translate_s"] = gemini_seconds
                if failure is not None:
                    metrics["dropped"] += 1
                    if isinstance(failure, GeminiBillingRequired):
                        running = False
                        stopping = True
                        log.error("%s", failure)
                        await publish({"type": "warning", "message": str(failure)})
                        await publish({"type": "status", "running": False})
                        if minute_mic:
                            mic = minute_mic
                            minute_mic = None
                            await asyncio.to_thread(mic.stop)
                    else:
                        log.error("Gemini segment %d failed: %s", next_delivery-1, failure)
                        await publish({"type": "warning",
                                       "message": "Summary failed. Check Gemini server logs."})
                    continue
                if all(v == "NO_INTELLIGIBLE_SPEECH" for v in summaries.values()):
                    log.info("No intelligible speech for segment %d", next_delivery-1)
                    continue
                summary_context = summaries.get("en", "")[:600]
                sequence += 1
                seq = sequence
                for language in ("en", "hi"):
                    summary = summaries[language]
                    if summary != "NO_INTELLIGIBLE_SPEECH":
                        language_queues[language].put_nowait(
                            (seq, summary, captured_at, gemini_seconds))
                metrics["processed"] += 1
                log.info("Summary %d: Gemini %.2fs, EN backlog %d, HI backlog %d",
                         seq, gemini_seconds,
                         language_queues["en"].qsize(), language_queues["hi"].qsize())
            if stopping:
                # Stop accepting audio after a non-retryable billing failure.
                while True:
                    try:
                        translation_queue.get_nowait()
                        translation_queue.task_done()
                        metrics["dropped"] += 1
                    except asyncio.QueueEmpty:
                        break
    finally:
        # Stop may cancel this worker after its queue has drained; ensure
        # all in-flight jobs are canceled and accounted for.
        for task in in_flight.values():
            task.cancel()
        await asyncio.gather(*in_flight.values(), return_exceptions=True)
        for _ in in_flight:
            translation_queue.task_done()
        try:
            await asyncio.wait_for(
                asyncio.gather(*(q.join() for q in language_queues.values())),
                timeout=20)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        for task in language_tasks:
            task.cancel()
        await asyncio.gather(*language_tasks, return_exceptions=True)


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
            await broadcast_stream("en", audio)
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
            "summary_window_seconds": summary_window_seconds,
            "semantic_segmentation": {"minimum_seconds": 5, "pause_seconds": 0.8, "maximum_seconds": 18}
                if interpretation_mode == "semantic_summary" else None,
            "target_language": TARGET_LANGUAGE,
            "voice": ENGLISH_VOICE, "provider_configured": configured(),
            "metrics": dict(metrics), "queued_phrases": translation_queue.qsize() if translation_queue else 0,
            "speech_health": {**{k+"_age_s": round(time.monotonic()-v, 1) if v else None
                               for k,v in speech_health.items() if k.startswith("last_")},
                              "queued_chunks": speech_health["queued_chunks"]}}


@app.post("/api/summary-window")
async def set_summary_window(request: Request, x_admin_key: str | None = Header(default=None)):
    global summary_window_seconds
    admin_auth(x_admin_key)
    body = await request.json()
    seconds = body.get("seconds")
    if type(seconds) is not int or seconds not in (30, 60, 120):
        raise HTTPException(400, "Choose 30, 60, or 120 seconds")
    async with control_lock:
        if running:
            raise HTTPException(409, "Stop the microphone before changing the interval")
        summary_window_seconds = seconds
    return {"summary_window_seconds": summary_window_seconds}

@app.post("/api/start")
async def start(x_admin_key: str | None = Header(default=None)):
    global running, recognizer, translation_queue, worker_task, google_mic, minute_mic, summary_context
    admin_auth(x_admin_key)
    async with control_lock:
        if running:
            return {"running": True, "provider": provider}
        if not event_code or event_code == admin_key:
            raise HTTPException(400, "Set distinct EVENT_CODE and ADMIN_KEY in .env")
        if interpretation_mode not in ("minute_summary","semantic_summary","live"):
            raise HTTPException(400, "INTERPRETATION_MODE must be minute_summary, semantic_summary or live")
        if interpretation_mode in ("minute_summary", "semantic_summary") and provider != "google":
            raise HTTPException(400, "Minute summary mode requires TRANSLATION_PROVIDER=google")
        if provider not in ("azure", "google"):
            raise HTTPException(400, "Set TRANSLATION_PROVIDER=google or azure")
        if not configured():
            raise HTTPException(400, "For minute summaries set GEMINI_API_KEY and GOOGLE_TTS_API_KEY in .env, then restart the server")
        summary_context = ""
        translation_queue = asyncio.Queue(maxsize=100 if interpretation_mode=="live" else 12)
        worker_task = asyncio.create_task(
            minute_summary_worker() if interpretation_mode in ("minute_summary","semantic_summary")
            else translation_worker())
        running = True
        try:
            if interpretation_mode in ("minute_summary", "semantic_summary"):
                minute_mic = (SemanticCapture(minute_audio_received, google_failed, 5.0, 0.8, 18.0)
                              if interpretation_mode == "semantic_summary"
                              else MinuteCapture(minute_audio_received, google_failed, summary_window_seconds))
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
            if interpretation_mode in ("minute_summary", "semantic_summary"):
                audio = await asyncio.to_thread(google_english_audio, sample, language)
            else:
                if language == "hi":
                    continue
                audio = await asyncio.to_thread(
                    google_english_audio if provider == "google" else synthesize_english, sample)
        except Exception as exc:
            raise HTTPException(502, f"{language} audio test failed: {exc}") from exc
        await broadcast_stream(language, audio)
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
