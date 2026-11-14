"""Google Speech v1 Telugu streaming; ADC credentials; microphone 16 kHz PCM."""
import logging
import queue
import threading
import time

log = logging.getLogger("google-stream")

class GoogleMicrophone:
    def __init__(self, on_text, on_error):
        self.on_text = on_text
        self.on_error = on_error
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
                config=config, interim_results=False)
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
                        for response in responses:
                            if self.stop_event.is_set():
                                break
                            for result in response.results:
                                if result.is_final and result.alternatives:
                                    phrase = result.alternatives[0].transcript.strip()
                                    if phrase:
                                        self.on_text(phrase)
                except Exception as exc:
                    if not self.stop_event.is_set():
                        log.exception("Google Speech streaming failed")
                        self.on_error(f"Google Speech interrupted: {type(exc).__name__}")
                        self.stop_event.wait(3)
        except Exception as exc:
            log.exception("Could not initialize Google Speech")
            self.on_error(f"Google Speech startup failed: {type(exc).__name__}")
