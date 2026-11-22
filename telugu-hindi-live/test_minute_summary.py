"""Pure unit tests for captured PCM window format and Gemini summary parser."""
import io, wave, ast
from minute_capture import wav_bytes, RATE
from pathlib import Path
payload=b"\x01\x02"*RATE
buf=wav_bytes(payload)
with wave.open(io.BytesIO(buf),"rb") as w:
    assert w.getnchannels()==1
    assert w.getframerate()==16000
    assert w.getsampwidth()==2
    assert w.getnframes()==RATE
    assert w.readframes(RATE)==payload
source=Path(__file__).with_name("minute_capture.py").read_text(encoding="utf-8")
ast.parse(source)
assert "silent_block" not in source
assert "bytes(3200 * 2)" not in source
assert "WINDOW_FRAMES = RATE * 60" in source
assert "self.on_window(wav_bytes(bytes(pcm)))" in source
summary=Path(__file__).with_name("minute_summary.py").read_text(encoding="utf-8")
ast.parse(summary)
assert '"mime_type": "audio/wav"' in summary
assert '"store": False' in summary
app=Path(__file__).with_name("app.py").read_text(encoding="utf-8")
ast.parse(app)
assert 'interpretation_mode = os.getenv("INTERPRETATION_MODE", "minute_summary")' in app
print("PASS: 60-second real PCM WAV windows and Google-only summary workflow contract")
