"""Isolate Telugu microphone capture and Google Speech-to-Text without FastAPI.

Run with .venv-local activated: python test_google_speech.py
Records 8 seconds. Uses ADC; do not paste credential files or tokens.
"""
import sys
import traceback
import numpy as np
import sounddevice as sd
from google.cloud import speech

SECONDS = 8
RATE = 16000

try:
    print("Default input:", sd.query_devices(kind="input")["name"])
    print(f"Recording {SECONDS}s: speak Telugu clearly NOW...")
    recording = sd.rec(int(SECONDS * RATE), samplerate=RATE, channels=1, dtype="int16")
    sd.wait()
    peak = int(np.max(np.abs(recording.astype("int32"))))
    rms = float(np.sqrt(np.mean(recording.astype("float64") ** 2)))
    print(f"Mic peak={peak}; RMS={rms:.1f} (16-bit PCM).")
    if peak < 150:
        print("WARNING: Mic seems silent; check Windows microphone permissions and default input.")
    client = speech.SpeechClient()
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE, language_code="te-IN", model="latest_long")
    result = client.recognize(
        config=config,
        audio=speech.RecognitionAudio(content=recording.tobytes()),
        timeout=40)
    transcripts = [part.alternatives[0].transcript for part in result.results if part.alternatives]
    if transcripts:
        print("Telugu transcription:", " ".join(transcripts))
    else:
        print("Google returned no transcript. Verify the input voice, level and language.")
except Exception as exc:
    print("ERROR TYPE:", type(exc).__name__)
    print("ERROR:", str(exc)[:1200])
    sys.exit(1)
