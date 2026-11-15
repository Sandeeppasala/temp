# Gemini HTTP 402 handling

Google's Gemini Interactions API returns HTTP 402 Payment Required when
the project's prepaid credits are depleted. It is not a microphone,
WebSocket, Google TTS or audio playback error.

After a 402, the new worker:
1. Displays an actionable listener warning.
2. Stops future 60-second microphone capture.
3. Clears already queued (unprocessed) 60-second windows.
4. Exits the minute-summary worker to avoid repeated paid API failures.

Resolve the billing status for the same Google AI Studio API key project;
restart the interpreter and click Start microphone. The existing Google
Cloud Translation/TTS billing is separate from Gemini API credits.

No synthetic audio, change to microphone PCM, or changes to the
legacy live mode. Source audio in a failed window is not retained,
and unprocessed windows are discarded as noted in the logs.

Reference: https://ai.google.dev/gemini-api/docs/api-errors
