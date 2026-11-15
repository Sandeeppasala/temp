"""Continuous real-microphone capture in 120-second windows (no invented silence)."""
import io
import logging
import queue
import threading
import time
import wave

log = logging.getLogger("minute-capture")

RATE = 16000
CHANNELS = 1
BLOCK_FRAMES = 3200  # 200 ms
WINDOW_FRAMES = RATE * 120

def wav_bytes(pcm):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm)
    return buffer.getvalue()

class MinuteCapture:
    def __init__(self, on_window, on_error):
        self.on_window = on_window
        self.on_error = on_error
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, daemon=True, name="minute-audio-capture")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                log.warning("Microphone capture worker still shutting down")

    def run(self):
        import sounddevice as sd
        blocks = queue.Queue(maxsize=100)
        dropped = 0
        def callback(indata, frames, time_info, status):
            nonlocal dropped
            if status:
                log.warning("Microphone status: %s", status)
            if self.stop_event.is_set():
                return
            try:
                blocks.put_nowait(bytes(indata))
            except queue.Full:
                dropped += 1
                if dropped == 1 or dropped % 20 == 0:
                    log.error("Microphone queue overflow: %d actual blocks LOST", dropped)
                    self.on_error("Microphone capture overload; some source audio lost")
        try:
            with sd.RawInputStream(samplerate=RATE, channels=CHANNELS,
                                   dtype="int16", blocksize=BLOCK_FRAMES,
                                   callback=callback):
                remaining = WINDOW_FRAMES
                pcm = bytearray()
                last_received = time.monotonic()
                while not self.stop_event.is_set():
                    try:
                        block = blocks.get(timeout=0.2)
                    except queue.Empty:
                        if time.monotonic() - last_received > 2:
                            log.error("No microphone PCM received for two seconds")
                            self.on_error("Microphone stalled. Check Windows input device; no synthetic audio is sent.")
                            last_received = time.monotonic()
                        continue
                    last_received = time.monotonic()
                    # Blocks are genuine captured PCM. Split exactly on
                    # 120-second sample boundary; nothing overlaps or repeats.
                    offset = 0
                    while offset < len(block):
                        take = min(len(block)-offset, remaining*2)
                        pcm.extend(block[offset:offset+take])
                        offset += take
                        remaining -= take//2
                        if remaining == 0:
                            self.on_window(wav_bytes(bytes(pcm)))
                            pcm = bytearray()
                            remaining = WINDOW_FRAMES
                if pcm:
                    log.info("Stopped with %.1f seconds of incomplete audio window; not sent",len(pcm)/2/RATE)
        except Exception as exc:
            log.exception("Minute audio capture failed")
            self.on_error("Minute audio capture failed: "+type(exc).__name__)
