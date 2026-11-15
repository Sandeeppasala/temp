# Speech continues but translation audio stops

Fixed the final-only recognizer starvation in Google Speech streaming v1.
Google often emits changing interim Telugu text while a person speaks
without pausing; a FINAL event might not arrive for a long time.

This update:
- Publishes stable Telugu chunks during long speech when at least 7 seconds
  have passed, a prefix appears in two stable hypotheses (stability >= 0.8),
  and >=8 new words can be emitted with four trailing words retained.
- Uses final transcripts for remaining speech, suppressing already-committed
  words where reconcilable with revised final hypotheses.
- Flushes latest interim words at the 235-second stream renewal, instead of
  dropping the whole unfinalized tail.
- Exposes /api/status speech_health ages: last_partial_age_s,
  last_queued_age_s and last_audio_sent_age_s.

Tradeoffs: provisional chunks can still divide clauses and Google's revised
final recognition can still yield repeats or omissions. This mitigates
prolonged silence but is not guaranteed lossless simultaneous interpretation.
The stream restart has a small microphone discontinuity; bridging still
needs implementing for workshop-grade coverage. Listener remains configured
for 60 seconds scheduled ahead with additional pending FIFO.
