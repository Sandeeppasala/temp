"""Continuous 16 kHz capture with pause-aware phrase boundaries.

Audio is partitioned without overlap; a pause is only a candidate boundary.
Gemini subsequently produces the semantic summary. This is not an AI semantic
endpoint detector, and the 18-second cap can split an unfinished sentence.
"""
import audioop
import collections
import logging
import queue
import threading
import time

from minute_capture import RATE, BLOCK_FRAMES, wav_bytes

log = logging.getLogger("semantic-capture")


class SemanticCapture:
    def __init__(self, on_window, on_error, min_seconds=5.0,
                 pause_seconds=0.8, max_seconds=18.0):
        if not (0 < min_seconds < max_seconds and 0 < pause_seconds < max_seconds):
            raise ValueError("Invalid segmentation settings")
        self.on_window = on_window
        self.on_error = on_error
        self.min_seconds = min_seconds
        self.pause_seconds = pause_seconds
        self.max_seconds = max_seconds
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, daemon=True, name="semantic-audio-capture")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                log.warning("Capture thread still stopping")

    def run(self):
        import sounddevice as sd
        blocks = queue.Queue(maxsize=100)
        # Noise-adaptive RMS VAD: no cloud dependency, 200 ms frames.
        noise_floor = 100.0
        pcm = bytearray()
        pending = collections.deque(maxlen=5)  # one second of leading silence
        has_speech = False
        quiet_frames = 0
        dropped = 0
        last_received = time.monotonic()
        frame_s = BLOCK_FRAMES / RATE

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
                    self.on_error("Microphone overflow: source audio lost")

        def emit():
            nonlocal pcm, has_speech, quiet_frames
            if has_speech and pcm:
                duration = len(pcm) / (RATE * 2)
                self.on_window(wav_bytes(bytes(pcm)))
                log.info("Emitted %.1fs real audio at natural pause or maximum duration", duration)
            pcm = bytearray()
            has_speech = False
            quiet_frames = 0

        try:
            with sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                                   blocksize=BLOCK_FRAMES, callback=callback):
                while not self.stop_event.is_set():
                    try:
                        block = blocks.get(timeout=0.2)
                    except queue.Empty:
                        if time.monotonic() - last_received > 2:
                            self.on_error("Microphone stalled: no audio samples received")
                            last_received = time.monotonic()
                        continue
                    last_received = time.monotonic()
                    rms = audioop.rms(block, 2)
                    threshold = max(240.0, noise_floor * 3.0)
                    speech = rms >= threshold
                    if not speech:
                        noise_floor = 0.985 * noise_floor + 0.015 * rms
                    if not has_speech:
                        if not speech:
                            pending.append(block)
                            continue
                        # Include pre-roll, but never reuse it in another segment.
                        pcm.extend(b"".join(pending))
                        pending.clear()
                        has_speech = True
                    pcm.extend(block)
                    quiet_frames = 0 if speech else quiet_frames + 1
                    duration = len(pcm) / (RATE * 2)
                    if duration >= self.max_seconds or (
                        duration >= self.min_seconds
                        and quiet_frames * frame_s >= self.pause_seconds):
                        emit()
                # Flush real speech on stop, even if shorter than minimum.
                emit()
        except Exception as exc:
            log.exception("Continuous microphone capture failed")
            self.on_error("Continuous capture failed: " + type(exc).__name__)
