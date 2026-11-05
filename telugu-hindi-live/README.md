# Telugu → Hindi Live Interpretation (Windows MVP)

A centralized **microphone → Azure Telugu speech translation → Hindi speech synthesis → authenticated browser listeners** application for 5–15 attendees. The speaker uses one microphone; everyone hears the same *Hindi voice segments* on their own phone.

## Features
- Windows laptop microphone input via Azure Speech SDK (uses Windows **default** recording device).
- Continuous Telugu (`te-IN`) → Hindi (`hi`) speech translation.
- Hindi voice (`hi-IN-SwaraNeural`) text-to-speech.
- Ordered translation segments delivered over a FastAPI WebSocket to phones.
- Access code required for every listener, separate administrator key for Start/Stop/Test.
- Hindi captions, volume control, listener count, test-voice button.
- No speech recordings saved by this app; speech is sent to Azure for processing.

## Requirements
- Windows 10/11, Python 3.11 or 3.12, working microphone or mixer USB input.
- Azure subscription, Azure Speech resource **key and region**. Azure processing is **paid** based on usage. Review quotas/prices before the event.
- Stable internet; phones need headphones and browsers (iOS Safari / Android Chrome).
- Optional: Cloudflare Tunnel (HTTPS) or other secure reverse proxy to expose the server externally.
- **RTX 3070 is NOT required for the cloud MVP**; local GPU inference can be added later.

## Setup (Windows PowerShell)
```powershell
git clone https://github.com/Sandeeppasala/temp.git
cd temp\telugu-hindi-live
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```
In `.env`, set `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, and **different long random** `EVENT_CODE` and `ADMIN_KEY`. Never commit `.env`.

Choose **Settings → System → Sound → Input** and set the stage mixer/microphone as your default input.

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```
Open **http://127.0.0.1:8000/admin** on laptop; enter the ADMIN_KEY and click **Start microphone**. Use **Send test Hindi voice** to verify TTS with a listener. Press **Stop microphone** during breaks.

## Participant testing
On the same laptop open **http://127.0.0.1:8000/**, enter `EVENT_CODE`, click **Start Listening** (user interaction enables audio). Use headphones to avoid feedback.

For a **same-Wi-Fi local trial** you can launch `--host 0.0.0.0`, then access `http://LAPTOP_LAN_IP:8000` from phones (Windows Firewall may need approval). HTTP is **not suitable for internet/public deployment**; use HTTPS.

For an **internet trial**, use a secure tunnel (example: Cloudflare named Tunnel) to route a HTTPS hostname to `http://localhost:8000`. Keep the organizer/admin URL and ADMIN_KEY private. A free ephemeral `cloudflared tunnel --url http://localhost:8000` can be used for *temporary testing only*; the URL can change and availability is not guaranteed. For event production use a stable hostname, access controls, and test 15 devices. Do not put the Azure key in browser code or GitHub.

## Workflow
1. Connect stage microphone to mixer/USB input (or use a headset for testing).
2. Check Windows default recording input, connectivity, and Azure credentials.
3. Start server and open `/admin`. Tap **Start microphone**.
4. Send attendees the HTTPS listener link and EVENT_CODE only.
5. Attendees open page, enter code, tap **Start Listening**, connect headphones.
6. The app recognizes complete utterances, synthesizes ordered Hindi audio segments, and broadcasts to connected listeners.
7. Stop transcription during meditation silence/breaks to reduce cost.

## Important limitations (MVP)
- **NOT simultaneous interpretation.** Azure yields completed phrases; translation + synthesis adds several seconds. Test philosophical terminology.
- No reconnect replay: listeners joining late only hear subsequent segments. On interruptions, clients manually reconnect.
- This MVP broadcasts WAV audio (high bandwidth), not low-bitrate Opus. Sufficient for small trials, but use Opus/WebRTC for production.
- Audio decoding is asynchronous in browser; under heavy load a segment may play out of order. Production should serialize decoding.
- If speaker speaks much faster than Hindi speech can be generated, backlog/delay grows. The app drops new recognized phrases if the server queue fills.
- On app restart, all listeners disconnect. No persistence, recording, transcripts, or multi-host redundancy.
- Authentication uses shared event passcodes rather than per-user accounts; don't use the demo as a high-security service. Enforce HTTPS and rotate codes after event.
- WebSocket fanout from the laptop means its upload and stable tunnel are single points of failure. Monitor network and test load.
- The Azure Speech SDK handles input from Windows default mic. Selecting a specific device or loopback routing is a future improvement.
- Do not trust machine interpretation for critical instructions. Have a bilingual human monitor a rehearsal and keep a fallback.

## Cost notes
Azure Speech Translation and Speech Synthesis are metered separately; check [Azure pricing](https://azure.microsoft.com/en-us/pricing/details/cognitive-services/speech-services/) and set a spending alert. 15 listeners reuse one synthesis; translation is not charged once per listener. Cloud tunnels and mobile data may have separate costs.

## Security
- Keep `.env` secret; use a random EVENT_CODE and a different random ADMIN_KEY.
- HTTPS/WSS for remotely connected phones. The access code is sent in the first WebSocket message, not a URL.
- Anyone who learns the shared attendee code can listen. Rotate between events.
- App does not log transcripts by default, but data is processed remotely by Azure; inform participants.

## Troubleshooting
- **No recognition:** verify Windows default microphone and Azure Speech language/region; speak Telugu distinctly.
- **Speech translated but no Hindi audio:** verify TTS voice is available in your Azure region and subscription.
- **Phones cannot connect:** check tunnel and HTTPS, firewall, then open `/health`.
- **Silence on iPhone:** tap Start Listening manually; keep Safari active, screen awake, volume audible; try a connected headphone.
- **High delay:** shorten speech pauses/phrases; watch speaker pace, network and processing costs.

---
## Sarvam AI provider

To use **Sarvam AI** instead of Azure, reinstall the dependencies from this
branch, copy `.env.example` to `.env`, and set:

```ini
TRANSLATION_PROVIDER=sarvam
SARVAM_API_KEY=your-private-key
SARVAM_STT_MODEL=saaras:v4
SARVAM_TRANSLATE_MODEL=sarvam-translate:v1
SARVAM_TTS_MODEL=bulbul:v3
SARVAM_TTS_SPEAKER=shubh
EVENT_CODE=a-random-listener-code
ADMIN_KEY=a-different-strong-admin-key
```

Restart `python -m uvicorn app:app --host 127.0.0.1 --port 8000`, open
`/admin`, and select **Status**. It should show `provider: sarvam`. With a
participant connected, select **Send test Hindi voice**, then **Start microphone**
and speak Telugu through the Windows default input device.

The Sarvam path is: **Windows default microphone (16 kHz mono, 16-bit PCM)
→ Sarvam Saaras v4 streaming Telugu transcription → Sarvam Translate v1
(`te-IN` to `hi-IN`) → Bulbul v3 Hindi WAV speech → existing WebSocket
listener page**. No changes to attendee URLs, access codes or browser audio
player. This mode uses the `sarvamai` SDK plus `sounddevice` for microphone
capture. It does not require the RTX 3070 GPU.

**Why separate translation?** Sarvam streaming STT mode=`translate` emits
English, not Hindi. We use mode=`transcribe` and a separate Telugu-to-Hindi
text translation call instead. Sarvam's Python streaming SDK expects base64
**WAV** chunks; the app constructs one WAV header per half-second microphone
chunk.

Windows: select the desired microphone or USB mixer under **Settings → Sound →
Input**. The input device must support 16-kHz mono capture or compatible
resampling. If the device fails to open, check the Windows microphone
permissions and available devices. PortAudio is installed through
`sounddevice` and may require system runtimes on Windows.

**Testing:**

```powershell
python -m unittest discover -s tests
```

This verifies audio WAV framing only. Sarvam network requests, microphone
behavior, streaming latency, translations, and Hindi output require live
testing with a valid Sarvam API key. We cannot verify those without a working
microphone and credentials. Test at least a 10-minute Telugu meditation talk
and multiple iPhone/Android browsers before the workshop.

**Limitations:** The stream presently requires manually pressing Start after
network failure; translation occurs on finalized utterances and has a delay.
Long speech or a slow network can fill the translation queue and cause dropped
phrases. WAV audio uses more bandwidth than MP3/Opus. The existing listener
page, access control and HTTPS guidance remain unchanged. Do not share
`SARVAM_API_KEY` or commit the `.env` file. Sarvam and Azure use external
cloud processing and may incur charges.

Try Sarvam Bulbul v4 Flash by setting `SARVAM_TTS_MODEL=bulbul:v4-flash`;
clear `SARVAM_TTS_SPEAKER` or choose a v4-compatible voice (v3 voice IDs are
not interchangeable). For Azure, set `TRANSLATION_PROVIDER=azure` and use
your original Azure credentials.

API references:
- https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/streaming-api
- https://docs.sarvam.ai/api-reference/text/translate-text
- https://docs.sarvam.ai/api-reference/text-to-speech/convert
