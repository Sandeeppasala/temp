# Accuracy-first mode and transcript/audio alignment

Default Google Speech pipeline now translates FINAL Telugu recognition results
only, not prematurely committed interim fragments. The listener still displays
preliminary Telugu so users can distinguish preview from finalized text.

The listener now shows:
- **English currently speaking:** updates when a queued audio clip's scheduled
  playback starts (approximation based on AudioContext clock).
- **Telugu corresponding to this audio:** exact Telugu submitted to Google
  Translation for that clip.
- **Latest translated text:** may be far ahead of spoken audio due to queue.
- **Last 15 translated phrases:** final Telugu input paired with Google
  Translation output, allowing meaningful quality diagnosis.

If 'Telugu corresponding to this audio' differs from correct live Telugu
preview, recognition finalization is degrading the result. If the final
Telugu is accurate but its paired English is not, Google Translation
Basic's sentence-level context limitation is the problem. If translation
and spoken audio are both correct but delayed, it is a playback backlog.
The audio is synthesized from that exact English text by Google Cloud TTS.

This quality-first setting prioritizes finalized speech over uninterrupted
English output. Some speeches without pauses may not trigger FINAL results
for extended periods. It is intentionally not positioned as real-time
simultaneous interpretation. Google streaming restart bridging is not
implemented and can still lose words near 235-second stream renewals.
