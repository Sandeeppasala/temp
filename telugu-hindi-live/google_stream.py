"""Google Speech v1 Telugu streaming; ADC credentials; microphone 16 kHz PCM."""
import logging
import queue
import threading
import time

log = logging.getLogger("google-stream")

class GoogleMicrophone:
    def __init__(self, on_text, on_error, on_partial=None):
        self.on_text = on_text
        self.on_error = on_error
        self.on_partial = on_partial
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, daemon=True, name="telugu-google-stt")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=6)
            if self.thread.is_alive():
                log.warning("Google recognition worker has not yet finished.")

    def run(self):
        import sounddevice as sd
        from google.cloud import speech
        try:
            client = speech.SpeechClient()
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000, language_code="te-IN",
                model="latest_long", enable_automatic_punctuation=True)
            stream_config = speech.StreamingRecognitionConfig(
                config=config, interim_results=True)
            while not self.stop_event.is_set():
                audio = queue.Queue(maxsize=20)
                started = time.monotonic()
                def callback(indata, frames, time_info, status):
                    if status:
                        log.warning("Microphone status: %s", status)
                    if self.stop_event.is_set():
                        return
                    try:
                        audio.put_nowait(bytes(indata))
                    except queue.Full:
                        log.warning("Microphone buffers full; dropping audio block")
                try:
                    with sd.RawInputStream(samplerate=16000, channels=1,
                                           dtype="int16", blocksize=3200,
                                           callback=callback):
                        def chunks():
                            while not self.stop_event.is_set() and time.monotonic() - started < 235:
                                try:
                                    block = audio.get(timeout=0.2)
                                except queue.Empty:
                                    continue
                                yield speech.StreamingRecognizeRequest(audio_content=block)
                        responses = client.streaming_recognize(
                            config=stream_config, requests=chunks(), timeout=260)
                        # A long uninterrupted speech can produce interim
                        # transcripts for many seconds without a FINAL event.
                        # Commit only stable prefixes; retain a short tail for
                        # context, and reconcile with Google's eventual FINAL.
                        from difflib import SequenceMatcher
                        committed = []
                        previous_stable = []
                        latest_words = []
                        last_emit = time.monotonic()
                        last_interim = time.monotonic()

                        def emit(words, provisional=False):
                            nonlocal last_emit
                            if not words:
                                return
                            phrase = " ".join(words)
                            log.info("%s Telugu chunk (%d words)",
                                     "Provisional" if provisional else "Final", len(words))
                            self.on_text(phrase)
                            last_emit = time.monotonic()

                        def unmatched_final(words):
                            if not committed:
                                return words
                            if words[:len(committed)] == committed:
                                return words[len(committed):]
                            # Interim recognition can revise old text.
                            # Find where the already-voiced prefix ends in the
                            # final hypothesis; avoid replaying the entire phrase.
                            matcher = SequenceMatcher(None, committed, words, autojunk=False)
                            matching = matcher.get_matching_blocks()
                            aligned = [m for m in matching if m.size and m.a + m.size >= len(committed)]
                            if aligned:
                                end = max(m.b + m.size for m in aligned)
                                return words[end:]
                            log.warning("Final transcript revised the committed prefix; "
                                        "sending full final to avoid missing words "
                                        "(some repetition possible)")
                            return words

                        for response in responses:
                            if self.stop_event.is_set():
                                break
                            for result in response.results:
                                if not result.alternatives:
                                    continue
                                phrase = result.alternatives[0].transcript.strip()
                                if not phrase:
                                    continue
                                words = phrase.split()
                                if result.is_final:
                                    emit(unmatched_final(words))
                                    committed = []
                                    previous_stable = []
                                    latest_words = []
                                    last_interim = time.monotonic()
                                else:
                                    if self.on_partial:
                                        self.on_partial(phrase)
                                    latest_words = words
                                    last_interim = time.monotonic()
                                    if result.stability < 0.8:
                                        continue
                                    # Require consecutively stable hypotheses,
                                    # not a single mutable interim guess.
                                    shared = 0
                                    for old, new in zip(previous_stable, words):
                                        if old != new:
                                            break
                                        shared += 1
                                    previous_stable = words
                                    now = time.monotonic()
                                    if now - last_emit < 7.0:
                                        continue
                                    # Preserve the last 4 words as context.
                                    end = max(0, shared - 4)
                                    if end - len(committed) >= 8 and words[:len(committed)] == committed:
                                        emit(words[len(committed):end], provisional=True)
                                        committed = words[:end]
                        # On streaming reset, rescue recognized but not yet
                        # finalized words. These are provisional and may have
                        # minor transcription errors; don't silently discard.
                        if latest_words and not self.stop_event.is_set():
                            remaining = unmatched_final(latest_words)
                            if remaining:
                                emit(remaining, provisional=True)
                except Exception as exc:
                    if not self.stop_event.is_set():
                        log.exception("Google Speech streaming failed")
                        self.on_error(f"Google Speech interrupted: {type(exc).__name__}")
                        self.stop_event.wait(3)
        except Exception as exc:
            log.exception("Could not initialize Google Speech")
            self.on_error(f"Google Speech startup failed: {type(exc).__name__}")
