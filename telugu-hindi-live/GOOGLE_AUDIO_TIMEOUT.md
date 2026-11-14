# Google streaming OUT_OF_RANGE Audio Timeout mitigation

Observed error: `400 Audio Timeout Error: Long duration elapsed without audio.
Audio should be sent close to real time.`

Google Cloud STT streaming needs a continuous flow of 16-kHz PCM, including
quiet microphone periods. The request generator originally ignored queue.Empty
and could leave Google without audio for extended periods if the PortAudio
microphone callback stalled.

Fixes in google_stream.py:
- Normal 200-ms microphone audio blocks remain untouched.
- If the audio queue has no new microphone data, the generator sends a
  200-ms zero-PCM block rather than waiting indefinitely.
- Placeholder frames are paced at roughly real-time speed and trigger a
  visible microphone-stall warning after two seconds.
- A small pace guard avoids sending buffered frames in an uncontrolled burst.

Important: placeholder silence DOES NOT recover any audio that was not
captured. The microphone may still need troubleshooting, and this does not
implement stream restart bridging near the 235-second renewal. A continuous
event-quality stream needs overlap/bridging, capture diagnostics, and a
long-duration test. Also distinguish legitimate silence in the microphone
signal (captured zero samples) from no callbacks at all.

Check Windows input device, microphone access, laptop sleep/power saving,
and whether other software takes exclusive control of the mic.
