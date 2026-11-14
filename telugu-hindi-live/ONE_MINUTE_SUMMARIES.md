# Telugu → English: 60-second meaning summary mode

Default mode: INTERPRETATION_MODE=minute_summary

**This is a new workflow, not simultaneous translation.** The Windows
microphone continuously captures ONLY real 16-kHz mono PCM audio in 60-second
windows. Once each window is complete, its WAV is sent to Google's Gemini
audio understanding API. Gemini creates an English spoken-word summary
of key claims and names. Google Cloud TTS generates English WAV, which
existing authorized phone listeners play in order.

There is no use of synthetic silence. The microphone still captures natural
quiet room audio. Unlike live mode, Google's streaming Speech-to-Text API
is not used. Sending a real clip directly to Gemini avoids 2–3 word
STT chunks and many segmentation/context problems.

## Configure your .env (never commit keys)
INTERPRETATION_MODE=minute_summary
TRANSLATION_PROVIDER=google
GEMINI_API_KEY=<Google AI Studio Gemini API key>
GEMINI_SUMMARY_MODEL=gemini-3.8-flash
GOOGLE_TTS_API_KEY=<existing Google TTS key>

Generate Gemini key in Google AI Studio: https://aistudio.google.com/apikey
It is not automatically the same key as Google Cloud Translation/TTS.

After configuring .env, restart Uvicorn. Open /admin and click Start
microphone, then open phone listener with event code.
The first English summary begins after minute 1 plus Gemini processing,
Google TTS generation and network/playback delay. Following minutes
are captured while prior windows process. Do not promise continuous
audio: a 90–140-word English summary is shorter than one minute,
and silence between summaries is expected, but no silent audio is sent.

Original one-by-one Google live translation can be restored via:
INTERPRETATION_MODE=live

No audio is stored to disk: completed in-memory windows are transient.
Audio is sent to Google Gemini for analysis and English speech is sent
to Google TTS. Google API usage can incur billing; confirm pricing and
quotas and configure Google budget alerts separately. Audio-content
summaries can omit details, hallucinate, or split thoughts at minute
boundaries; they are for substance, not word-for-word interpreting.
Use an actual rehearsal and compare with the source recording before
using during an event. Avoid unexpected public streaming of sensitive talks.

Google docs: https://ai.google.dev/gemini-api/docs/audio
