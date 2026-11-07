"""Test AI4Bharat's Telugu IndicConformer, converted to ONNX by OpenVoiceOS.

Run with saved speech: python test_ai4bharat.py --file telugu_test.wav
Run from microphone: python test_ai4bharat.py --mic --seconds 15

This is Telugu ASR only. It does not generate Hindi translation/audio.
"""
import argparse
import os
from pathlib import Path
import time

MODEL_ID = "OpenVoiceOS/ai4bharat-indicconformer-te-onnx"


def record_wav(path: Path, seconds: int, sample_rate: int = 16000) -> None:
    import numpy as np
    import sounddevice as sd
    import soundfile as sf

    print(f"Speak Telugu for {seconds} seconds...")
    audio = sd.rec(int(seconds * sample_rate),
                   samplerate=sample_rate, channels=1, dtype="float32")
    sd.wait()
    audio = np.asarray(audio).reshape(-1)
    peak = float(np.max(np.abs(audio))) if audio.size else 0
    rms = float(np.sqrt(np.mean(audio**2))) if audio.size else 0
    print(f"Microphone: peak={peak:.4f} RMS={rms:.4f}")
    if rms < 0.001:
        print("WARNING: Very quiet input; check the selected Windows microphone.")
    sf.write(str(path), audio, sample_rate, subtype="PCM_16")
    print(f"Recording saved: {path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Telugu IndicConformer ASR benchmark")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="Existing WAV recording")
    source.add_argument("--mic", action="store_true", help="Record from default microphone")
    parser.add_argument("--seconds", type=int, default=15,
                        help="Microphone recording duration in seconds (default: 15)")
    parser.add_argument("--save", type=Path, default=Path("telugu_ai4bharat.wav"),
                        help="Save microphone WAV to this filename")
    args = parser.parse_args()
    if args.mic:
        if not 1 <= args.seconds <= 25:
            parser.error("--seconds must be between 1 and 25")
        record_wav(args.save, args.seconds)
        audio_file = args.save
    else:
        audio_file = args.file

    if not audio_file.is_file():
        parser.error(f"WAV file not found: {audio_file}")

    # Local ONNX CPU inference first: avoids CUDA DLL conflicts in Faster-Whisper.
    # We can benchmark ONNX Runtime GPU separately after accuracy is acceptable.
    import soundfile as sf
    samples, sr = sf.read(str(audio_file))
    duration = len(samples) / sr
    if duration > 30:
        parser.error("Use <=30 second WAV clips; long recordings need VAD/segmentation")
    print(f"Input: {audio_file} ({duration:.1f}s, {sr}Hz)")
    print(f"Loading AI4Bharat Telugu ONNX model: {MODEL_ID}")
    import onnx_asr
    model = onnx_asr.load_model(MODEL_ID, quantization="int8")
    print("Transcribing Telugu...")
    start = time.perf_counter()
    result = model.recognize(str(audio_file))
    elapsed = time.perf_counter() - start
    print("\nTELUGU TRANSCRIPTION:")
    print(result if str(result).strip() else "(No text recognized)")
    print(f"Processing time: {elapsed:.2f}s")
    print(f"Audio duration: {duration:.2f}s")
    if duration > 0:
        print(f"Real-time factor: {elapsed / duration:.2f} (lower is better)")
    print("Note: Hindi translation and text-to-speech are not implemented in this test.")


if __name__ == "__main__":
    main()
