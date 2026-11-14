# Low-latency mode for continuous speakers

Google STT streaming sends *interim* Telugu text while someone is speaking.
The listener now displays that interim Telugu transcript immediately, before
a finalized English translation arrives.

To reduce latency for long uninterrupted speech, GoogleMicrophone emits
short **stable interim chunks** after around 4.5 seconds when recognition
reports stability >=0.85 and at least 7 words. The final segment emits only
words not already submitted for translation. This is a best-effort heuristic:
interim recognition can revise earlier words and can cause duplications,
omissions or unnatural translations at chunk boundaries. It isn't a
perfect simultaneous interpreter.

The English translation and synthesized speech are still produced
sequentially, so a fast speaker can still outrun English audio. The listener
skips additional segments when its already scheduled audio backlog exceeds
12 seconds, trading completeness for proximity to the live speaker.
A translation queue limit of five phrases reduces unbounded server backlog.

For events where **all content must be preserved**, revert to the previous
version or disable interim chunk emission; don't rely on this mode. Check
accuracy and lag during a realistic 10–15 minute uninterrupted Telugu speech
rehearsal. Azure fallback remains selectable with TRANSLATION_PROVIDER=azure
and needs separate latency testing.

Source: https://docs.cloud.google.com/speech-to-text/docs/v1/transcribe-streaming-audio
