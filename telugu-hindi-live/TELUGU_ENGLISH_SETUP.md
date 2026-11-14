# Telugu speech → Google English translation → Azure English voice

The browser and microphone remain unchanged:
- Azure Speech-to-Text transcribes Telugu (`te-IN`) from the default microphone.
- Google Cloud Translation **Basic v2 (NMT)** translates `te` text to `en`.
- Azure Neural TTS (`en-US-JennyNeural`) synthesizes spoken English.
- Existing FastAPI WebSocket broadcasts English captions + WAV audio to phones.

This uses the official **Google Cloud Translation API**, NOT an unofficial scraper
of translate.google.com. Google Translate's website and Cloud Translation may
produce different translations.

## Set up Google Cloud

1. Open https://console.cloud.google.com/ and select/create a project.
2. Link a billing account to the project (even if free characters cover the use).
3. Enable **Cloud Translation API** for the project.
4. Under **APIs & Services → Credentials**, create an API key.
5. Restrict that key to the **Cloud Translation API**. Keep the key on the
   backend; never put it in the webpage or commit it to GitHub.
6. Set API quotas / budget notifications in Google Cloud and Azure separately.
   A budget notification is NOT a hard spending cap.

Docs:
- https://docs.cloud.google.com/translate/docs/setup
- https://docs.cloud.google.com/translate/docs/reference/rest/v2/translate
- https://cloud.google.com/products/translate/pricing

## Windows setup

```powershell
cd C:\work\temp\telugu-hindi-live
git pull origin feature/telugu-hindi-live-translation
notepad .env
```

Preserve your working Azure key and the private event/admin codes. Ensure only
one `TRANSLATION_PROVIDER` entry. Add:

```ini
TRANSLATION_PROVIDER=azure
AZURE_SPEECH_REGION=westus2
ENGLISH_VOICE=en-US-JennyNeural
GOOGLE_TRANSLATE_API_KEY=your-google-cloud-translation-api-key
```

To test the Google translation step independently:

```powershell
python test_google_translate.py
```

Then restart Uvicorn (Ctrl+C first):

```powershell
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

- Admin on laptop: http://127.0.0.1:8000/admin
- Listener on same Wi-Fi: http://192.168.1.41:8000/ (verify laptop IP)
- On listener: tap Start Listening.
- On admin: click Send test English voice, then Start microphone.
- Speak Telugu, pause, check English captions and spoken English.

The test-voice button exercises Azure TTS, not Google translation. The separate
`test_google_translate.py` checks the Google key/translation.

Note: switching from Azure Speech Translation to Azure **Speech-to-Text**
may alter Azure billing; Google Translation is billed separately by submitted
Telugu characters. The existing app does not impose a hard expense cap.
Cloud Translation errors are logged and surfaced as a warning to listeners;
it will not silently fall back to Azure translation.
