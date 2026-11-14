# No synthetic audio

No artificially generated silent frames are sent to Google Speech-to-Text.

Microphone-captured PCM is forwarded as captured, including legitimate quiet
room audio from the hardware. If PortAudio callbacks stop, after two seconds
the streaming generator raises an error, closes the current stream and the
existing outer retry loop restarts capture/reconnects (with 3-second delay).

This may create a small recognition gap. It does not recover missing speech
or solve errors from system stalls, device suspension or Google stream rollover.
Check input hardware, Windows audio permissions, exclusive-device conflicts,
microphone sample rate and sleep settings if stall warnings continue.
