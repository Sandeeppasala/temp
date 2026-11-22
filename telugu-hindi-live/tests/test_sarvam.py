import base64
import io
import unittest
import wave
from sarvam_provider import make_wav, RATE

class SarvamWavTests(unittest.TestCase):
    def test_pcm_chunk_wrapped_in_16k_mono_wav(self):
        pcm = b"\x00\x00" * 8000
        with wave.open(io.BytesIO(base64.b64decode(make_wav(pcm))), "rb") as wav:
            self.assertEqual(wav.getframerate(), RATE)
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.readframes(8000), pcm)

if __name__ == "__main__":
    unittest.main()
