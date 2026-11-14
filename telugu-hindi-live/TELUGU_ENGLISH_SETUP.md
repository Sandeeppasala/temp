# Telugu → English on Azure (Windows)

This app now translates **Telugu microphone speech into English captions and English voice** using Azure Speech Translation and Azure Neural TTS. Your listener URL, admin URL, EVENT_CODE, ADMIN_KEY and microphone setup stay the same.

## Update and run

```powershell
cd C:\work\temp\telugu-hindi-live
git pull origin feature/telugu-hindi-live-translation
notepad .env
```

Keep your existing Azure key and event/admin codes. **Replace or add** the following, making sure there is only one `TRANSLATION_PROVIDER` entry:

```ini
TRANSLATION_PROVIDER=azure
AZURE_SPEECH_REGION=westus2
ENGLISH_VOICE=en-US-JennyNeural
```

`westus2` is the region previously confirmed by the user; change only if the Speech resource is in another region. The old `HINDI_VOICE` variable is ignored in English mode.

Restart the server (Ctrl+C, then):

```powershell
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Laptop admin page: http://127.0.0.1:8000/admin

For a phone on the same Wi-Fi, the earlier LAN address was http://192.168.1.41:8000/ (the DHCP IP may change). Listener must tap **Start Listening** to enable audio playback.

The **Send test English voice** button should display an English caption and play English speech. Then **Start microphone**, speak Telugu, and pause to allow the translated phrase to finalize.

**Important:** Your existing Sarvam code remains Hindi-only and English mode rejects it. Set `TRANSLATION_PROVIDER=azure` for English. Azure service charges still apply. This is a code change; the actual Azure English voice has not been tested on your machine.
