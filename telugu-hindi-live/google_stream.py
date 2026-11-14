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
        self.chunk_seconds = 4.5  # Approximate translation cadence; uses stable interim text
        self.min_words = 5
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
                        consumed = 0
                        last_sent = time.monotonic()
                        for response in responses:
                            if self.stop_event.is_set():
                                break
                            for result in response.results:
                                if not result.alternatives:
                                    continue
                                phrase = result.alternatives[0].transcript.strip()
                                if not phrase:
                                    continue
                                if self.on_partial and not result.is_final:
                                    self.on_partial(phrase)
                                words = phrase.split()
                                # Each final result ends this recognition segment.
                                # Interim hypotheses can change; only stable text is chunked.
                                if result.is_final:
                                    if len(words) > consumed:
                                        self.on_text(" ".join(words[consumed:]))
                                    consumed = 0
                                    last_sent = time.monotonic()
                                elif (result.stability >= 0.85
                                      and len(words) - consumed >= self.min_words + 2
                                      and time.monotonic() - last_sent >= self.chunk_seconds):
                                    # Hold back two words because partial hypotheses
                                    # often revise the end of the phrase.
                                    end = len(words) - 2
                                    self.on_text(" ".join(words[consumed:end]))
                                    consumed = end
                                    last_sent = time.monotonic()
                except Exception as exc:
                    if not self.stop_event.is_set():
                        log.exception("Google Speech streaming failed")
                        self.on_error(f"Google Speech interrupted: {type(exc).__name__}")
                        self.stop_event.wait(3)
        except Exception as exc:
            log.exception("Could not initialize Google Speech")
            self.on_error(f"Google Speech startup failed: {type(exc).__name__}")
