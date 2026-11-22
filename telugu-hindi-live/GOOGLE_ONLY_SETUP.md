# Google-only Telugu → English interpreter (Azure fallback preserved)

Cloud pipeline: Windows default mic → Google Speech-to-Text v1 Telugu (te-IN) streaming → Google Cloud Translation Basic v2 → Google Text-to-Speech en-US-Standard-C → existing authenticated browser listener. The same event and admin codes work. Azure mode is retained by setting TRANSLATION_PROVIDER=azure.

## Google setup
In https://console.cloud.google.com/ select the project where Translation already succeeded. Confirm billing and enable **Cloud Speech-to-Text API**, **Cloud Text-to-Speech API**, and **Cloud Translation API**. Speech streaming uses Google Application Default Credentials (ADC), not the Translation API key.

Install Google Cloud CLI for Windows: https://cloud.google.com/sdk/docs/install
Open a new PowerShell and run:

```powershell
gcloud init
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_GOOGLE_PROJECT_ID
```

Your Google user needs permission to use Speech-to-Text on this project.

The Translation API key you already tested can also access TTS if its API restrictions allow both Cloud Translation and Cloud Text-to-Speech. Otherwise create a separate API key restricted to **Cloud Text-to-Speech API** and set GOOGLE_TTS_API_KEY; never share keys.

## Windows steps
```powershell
cd C:\work\temp\telugu-hindi-live
git pull origin feature/telugu-hindi-live-translation
.\.venv-local\Scripts\Activate.ps1
python -m pip install -r requirements.txt
notepad .env
```

Keep existing Azure credentials for fallback. Set exactly one provider:
```ini
TRANSLATION_PROVIDER=google
GOOGLE_TRANSLATE_API_KEY=your-working-google-translation-key
GOOGLE_ENGLISH_VOICE=en-US-Standard-C
GOOGLE_TTS_API_KEY=
```

Use GOOGLE_TTS_API_KEY only if the translation key isn't permitted to call Text-to-Speech.

Restart your server with Ctrl+C then:

```powershell
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Admin: http://127.0.0.1:8000/admin
Phone: http://192.168.1.41:8000/ if laptop IP is unchanged. Listener taps Start Listening.

First click Send test English voice (Google TTS), then Start microphone and speak Telugu. Share errors from PowerShell, never keys. Google STT starts asynchronously and errors may surface after the Start API returns HTTP 200.

## Known limitations
Google STT v1 Telugu model latest_long (not Chirp 3) may vary in accuracy. Its streaming sessions are limited to ~5 minutes; we renew every ~4 minutes, potentially losing words near the boundary. Test at least 10 consecutive minutes before using at an event. This is not yet tested on your Windows machine. Stop the mic during breaks; Google services are independently metered and your budget alerts are **not hard caps**. No automatic failover is implemented; to switch back to Azure, edit .env provider to azure and restart. Google Cloud Translation pricing and the website's results are not guaranteed identical.

References: https://docs.cloud.google.com/speech-to-text/docs/v1/speech-to-text-supported-languages , https://docs.cloud.google.com/speech-to-text/docs/quotas , https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types , https://cloud.google.com/docs/authentication/provide-credentials-adc
