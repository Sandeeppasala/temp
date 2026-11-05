"""Sarvam AI microphone input, Telugu transcription, Hindi translation and TTS."""
import asyncio
import base64
import io
import logging
import os
import wave
log = logging.getLogger("sarvam")
RATE = 16000
FRAMES = 8000


def make_wav(pcm: bytes) -> str:
    """Sarvam Python SDK requires base64 WAV chunks (not raw PCM)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes(pcm)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def text_translate(telugu: str) -> str:
    from sarvamai import SarvamAI
    result = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"]).text.translate(
        input=telugu[:2000], source_language_code="te-IN", target_language_code="hi-IN",
        model=os.getenv("SARVAM_TRANSLATE_MODEL", "sarvam-translate:v1"))
    return result.translated_text.strip()


def hindi_audio(hindi: str) -> bytes:
    from sarvamai import SarvamAI
    args = {"text": hindi[:2500], "language_code": "hi-IN",
            "model": os.getenv("SARVAM_TTS_MODEL", "bulbul:v3"),
            "output_audio_codec": "wav"}
    speaker = os.getenv("SARVAM_TTS_SPEAKER", "shubh").strip()
    if speaker:
        args["speaker"] = speaker
    result = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"]).text_to_speech.convert(**args)
    if not result.audios:
        raise RuntimeError("Sarvam returned no synthesized audio")
    data = base64.b64decode(result.audios[0], validate=True)
    if not data.startswith(b"RIFF"):
        raise RuntimeError("Sarvam did not return WAV audio")
    return data


class SarvamMicrophone:
    """One streaming speech recognition session; callbacks enqueue finalized Telugu."""
    def __init__(self, on_text, on_error):
        self.on_text = on_text
        self.on_error = on_error
        self.task = None
        self.ready = None
        self.stop_requested = False

    async def start(self):
        self.ready = asyncio.get_running_loop().create_future()
        self.stop_requested = False
        self.task = asyncio.create_task(self._run())
        try:
            await asyncio.wait_for(asyncio.shield(self.ready), 20)
        except BaseException:
            await self.stop()
            raise

    async def stop(self):
        self.stop_requested = True
        if self.task and not self.task.done():
            self.task.cancel()
        if self.task:
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def _run(self):
        from sarvamai import AsyncSarvamAI
        import sounddevice as sd
        loop = asyncio.get_running_loop()
        chunks = asyncio.Queue(maxsize=12)
        stream = None
        started = False

        def capture(indata, frames, time_info, status):
            if status:
                log.warning("Microphone warning: %s", status)
            audio = bytes(indata)
            def enqueue():
                if self.stop_requested:
                    return
                if chunks.full():
                    chunks.get_nowait()
                    log.warning("Dropping old microphone audio due to backpressure")
                chunks.put_nowait(audio)
            loop.call_soon_threadsafe(enqueue)

        async def send(ws):
            while not self.stop_requested:
                pcm = await chunks.get()
                await ws.transcribe(audio=make_wav(pcm), encoding="audio/wav", sample_rate=RATE)

        async def receive(ws):
            async for message in ws:
                if self.stop_requested:
                    return
                if getattr(message, "type", None) == "data":
                    text = (getattr(getattr(message, "data", None), "transcript", "") or "").strip()
                    if text:
                        self.on_text(text)

        try:
            client = AsyncSarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])
            async with client.speech_to_text_streaming.connect(
                model=os.getenv("SARVAM_STT_MODEL", "saaras:v4"),
                mode="transcribe", language_code="te-IN", sample_rate=RATE,
                high_vad_sensitivity=False
            ) as ws:
                stream = sd.RawInputStream(
                    samplerate=RATE, channels=1, dtype="int16",
                    blocksize=FRAMES, callback=capture)
                stream.start()
                started = True
                if self.ready and not self.ready.done():
                    self.ready.set_result(None)
                sender = asyncio.create_task(send(ws))
                receiver = asyncio.create_task(receive(ws))
                try:
                    done, pending = await asyncio.wait(
                        [sender, receiver], return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                    if not self.stop_requested:
                        raise RuntimeError("Speech recognition socket closed")
                finally:
                    sender.cancel()
                    receiver.cancel()
                    await asyncio.gather(sender, receiver, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Sarvam speech stream failed")
            if self.ready and not self.ready.done():
                self.ready.set_exception(exc)
            elif started and not self.stop_requested:
                self.on_error(str(exc))
        finally:
            self.stop_requested = True
            if stream:
                stream.stop()
                stream.close()
