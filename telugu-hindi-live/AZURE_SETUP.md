# Azure mode: Telugu speech -> Hindi voice (recommended workshop setup)

Your existing FastAPI app **already implements Azure Speech translation and
Hindi TTS**. No local Whisper, IndicConformer or IndicTrans2 models are used
in Azure mode. The browser listener and password-protected admin page are the
same as before.

## Switch on Windows

Open PowerShell:

```powershell
cd C:\work\temp\telugu-hindi-live
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv-local\Scripts\Activate.ps1
git pull origin feature/telugu-hindi-live-translation
python -m pip install -r requirements.txt
```

If .env already exists, preserve your previous EVENT_CODE and ADMIN_KEY:

```powershell
notepad .env
```

Set or replace the following values; paste YOUR OWN Azure key locally:

```ini
TRANSLATION_PROVIDER=azure
AZURE_SPEECH_KEY=your-azure-speech-resource-key
AZURE_SPEECH_REGION=your-azure-speech-resource-region
HINDI_VOICE=hi-IN-SwaraNeural
EVENT_CODE=your-private-attendee-code
ADMIN_KEY=your-different-private-organizer-key
```

The `AZURE_SPEECH_REGION` must match the Speech resource's **region**,
such as `westus`. Do not put the key in a chat, source file, GitHub, browser,
or screenshots.

If there is no .env yet:

```powershell
Copy-Item .env.example .env
notepad .env
```

Set the desired stage microphone as the **Windows default input device**
(Settings > System > Sound > Input), then launch:

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

In the laptop browser visit:

- Admin: http://127.0.0.1:8000/admin
- Listener: http://127.0.0.1:8000/
- Status: http://127.0.0.1:8000/health

Enter ADMIN_KEY on /admin and use the voice-test button; enter EVENT_CODE
on the listener page and tap Start Listening. Start microphone on admin to
begin interpreting Telugu to Hindi. **Test with a Hindi-speaking listener.**

For phones on the same Wi-Fi, launch with `--host 0.0.0.0` and use
`http://<laptop-LAN-IP>:8000/`. Windows firewall may need to allow the port.
For off-Wi-Fi/public access, use a secure HTTPS tunnel with an appropriate
host name. Do not distribute /admin or ADMIN_KEY.

## Azure configuration and costs

- Azure Speech resource with **key** and **region**.
- Azure speech translation: input `te-IN` -> translated text `hi`.
- Hindi Neural TTS voice: `hi-IN-SwaraNeural`.
- Stable internet and functional microphone.
- Metered cloud usage: Speech Translation and TTS may be billed separately.
  Broadcast **one synthesized stream** to all 5-15 listeners, instead
  of calling Azure once per listener. Check Azure pricing and set budget alerts.
- Do a complete rehearsal of philosophical terms, pacing, Hindi audio latency,
  device autoplay, and listener connectivity before the workshop.

Docs:
https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-translate-speech
https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support
https://azure.microsoft.com/en-us/pricing/details/cognitive-services/speech-services/

## Existing app limitations

- Phrase-based Hindi speech segments, not simultaneous zero-latency speech.
- Cloud network outage or Azure authentication errors interrupt interpretation.
- On high speech volume the output queue can lag or drop phrases.
- Browser listener may need a user tap to start audio playback.
- Azure mode doesn't use AI4Bharat, even though its benchmark remains in repo.
