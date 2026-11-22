# Local Telugu recognition: AI4Bharat IndicConformer

This is the **next-stage Telugu ASR benchmark**, not the completed offline
Telugu→Hindi interpreter. Your existing FastAPI browser listener, Azure
integration, and Sarvam integration are unchanged. No cloud API keys are needed
for this speech-recognition test.

## Why

The original Faster-Whisper medium model produced incorrect Telugu and
processed a 15-second recording in about 103 seconds on the user's machine.
Before changing the central broadcast pipeline, validate a Telugu-specialized
model against exactly the same known recording.

We use **AI4Bharat IndicConformer Telugu**, with an ONNX conversion maintained
by OpenVoiceOS to simplify Windows installation. This is CPU ONNX inference
initially; it does **not** use RTX 4070 acceleration yet. Measure baseline
accuracy and timing first, then consider ONNX Runtime GPU.

Official AI4Bharat model:
https://huggingface.co/ai4bharat/indicconformer_stt_te_hybrid_ctc_rnnt_large

ONNX conversion:
https://huggingface.co/OpenVoiceOS/ai4bharat-indicconformer-te-onnx

ONNX ASR library:
https://github.com/istupakov/onnx-asr

## Windows PowerShell

```powershell
cd C:\work\temp\telugu-hindi-live
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv-local\Scripts\Activate.ps1
python -m pip install "onnx-asr[cpu,hub]" sounddevice numpy soundfile
```

Run with the already-recorded, clear Telugu speech:

```powershell
python test_ai4bharat.py --file telugu_test.wav
```

Or record 15 seconds from Windows default microphone:

```powershell
python test_ai4bharat.py --mic --seconds 15
```

First run downloads the ONNX model to the Hugging Face cache; downloading
requires internet but subsequent inference is local. The test writes a
`telugu_ai4bharat.wav` file for microphone mode; the repo ignores it.

Output includes Telugu transcription, inference processing time and
real-time factor. Share the output **and the exact Telugu words spoken**
to assess accuracy. For live interpretation, inference should run well
under the audio duration and have good recognition accuracy.

## Limitations

- The ONNX model is a third-party conversion of AI4Bharat IndicConformer.
  ONNX inference results should be validated; no result has been verified
  on the user's laptop yet.
- This test handles WAV clips of 30 seconds or shorter; a production live
  feed needs speech activity detection and non-overlapping audio windows.
- CPU-first ONNX inference avoids the Faster-Whisper cuBLAS/cuDNN problem.
  It may be slower than a properly configured CUDA runtime.
- No translation into Hindi, Hindi TTS, or phone streaming has been added
  for the free/local path. Do not set TRANSLATION_PROVIDER=local in app.py:
  the app currently supports only azure/sarvam.
- Check the AI4Bharat model license and upstream ONNX conversion before
  redistribution or commercialization. Store no confidential audio in a
  publicly accessible Git repository.

## Next milestone

Once Telugu speech recognition is demonstrably accurate and reasonably
fast, integrate it with a local IndicTrans2 Telugu→Hindi translation model,
then a local Hindi TTS engine, and finally the existing authenticated
WebSocket listener. The RTX 4070 8 GB memory budget needs evaluation.
