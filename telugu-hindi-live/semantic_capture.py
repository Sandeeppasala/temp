"""Continuous 16 kHz capture with pause-aware phrase boundaries.

Audio is partitioned without overlap; a pause is only a candidate boundary.
Gemini subsequently produces the semantic summary. This is not an AI semantic
endpoint detector, and the 18-second cap can split an unfinished sentence.
"""
import audioop
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
        # RMS VAD selects boundaries only; never filters source samples.
        # Cap the noise estimate to prevent speech-driven threshold escalation.
        noise_floor = 100.0
        max_noise_floor = 120.0  # threshold ceiling: 360 PCM RMS
        pcm = bytearray()
        quiet_frames = 0
        dropped = 0
        last_received = time.monotonic()
        frame_s = BLOCK_FRAMES / RATE
        # Diagnostic counters only; callback never performs diagnostic logging.
        callback_count = 0
        callback_samples = 0
        callback_last = None
        callback_max_gap = 0.0
        received_samples = 0
        discarded_samples = 0  # retained diagnostic: VAD never discards samples
        emitted_samples = 0
        rms_sum = 0
        rms_count = 0
        rms_min = None
        rms_max = 0
        peak_depth = 0
        report_at = time.monotonic()
        previous_counts = (0, 0, 0, 0, 0, 0)

        def report():
            nonlocal report_at, previous_counts, rms_sum, rms_count, rms_min, rms_max, peak_depth
            now = time.monotonic()
            elapsed = now - report_at
            if elapsed < 5:
                return
            counts = (callback_count, callback_samples, received_samples,
                      discarded_samples, emitted_samples, dropped)
            delta = tuple(a-b for a,b in zip(counts, previous_counts))
            log.info("DIAG capture wall_s=%.2f callbacks=%d callback_audio_s=%.2f received_s=%.2f vad_discard_s=%.2f emitted_s=%.2f overflow_blocks=%d rms_min=%s rms_avg=%.1f rms_max=%d threshold=%.1f noise_floor=%.1f callback_max_gap_s=%.3f callback_age_s=%.3f queue_depth=%d peak_depth=%d buffered_s=%.2f",
                     elapsed, delta[0], delta[1]/RATE, delta[2]/RATE,
                     delta[3]/RATE, delta[4]/RATE, delta[5],
                     rms_min, rms_sum/max(1,rms_count), rms_max,
                     max(240.0, noise_floor*3.0), noise_floor, callback_max_gap,
                     now-callback_last if callback_last is not None else -1.0,
                     blocks.qsize(), peak_depth,
                     len(pcm)/(RATE*2))
            previous_counts = counts
            report_at = now
            rms_sum = rms_count = rms_max = peak_depth = 0
            rms_min = None

        def callback(indata, frames, time_info, status):
            nonlocal dropped, callback_count, callback_samples, callback_last, callback_max_gap
            if status:
                log.warning("Microphone status: %s", status)
            if self.stop_event.is_set():
                return
            now = time.monotonic()
            if callback_last is not None:
                callback_max_gap = max(callback_max_gap, now-callback_last)
            callback_last = now
            callback_count += 1
            callback_samples += frames
            try:
                blocks.put_nowait(bytes(indata))
            except queue.Full:
                dropped += 1
                if dropped == 1 or dropped % 20 == 0:
                    self.on_error("Microphone overflow: source audio lost")

        def emit():
            nonlocal pcm, quiet_frames, emitted_samples
            if pcm:
                duration = len(pcm) / (RATE * 2)
                self.on_window(wav_bytes(bytes(pcm)))
                emitted_samples += len(pcm)//2
                log.info("Emitted %.1fs real audio at natural pause or maximum duration", duration)
            pcm = bytearray()
            quiet_frames = 0

        try:
            with sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                                   blocksize=BLOCK_FRAMES, callback=callback):
                while not self.stop_event.is_set():
                    try:
                        block = blocks.get(timeout=0.2)
                    except queue.Empty:
                        report()
                        if time.monotonic() - last_received > 2:
                            self.on_error("Microphone stalled: no audio samples received")
                            last_received = time.monotonic()
                        continue
                    last_received = time.monotonic()
                    received_samples += len(block)//2
                    peak_depth = max(peak_depth, blocks.qsize()+1)
                    rms = audioop.rms(block, 2)
                    rms_sum += rms
                    rms_count += 1
                    rms_min = rms if rms_min is None else min(rms_min, rms)
                    rms_max = max(rms_max, rms)
                    threshold = max(240.0, noise_floor * 3.0)
                    speech = rms >= threshold
                    if not speech:
                        noise_floor = min(max_noise_floor, 0.985 * noise_floor + 0.015 * rms)
                    # Preserve every processed block, including quiet speech and silence.
                    pcm.extend(block)
                    quiet_frames = 0 if speech else quiet_frames + 1
                    duration = len(pcm) / (RATE * 2)
                    if duration >= self.max_seconds or (
                        duration >= self.min_seconds
                        and quiet_frames * frame_s >= self.pause_seconds):
                        emit()
                    report()
                # Flush remaining processed audio on stop, even if shorter than minimum.
                emit()
        except Exception as exc:
            log.exception("Continuous microphone capture failed")
            self.on_error("Continuous capture failed: " + type(exc).__name__)
