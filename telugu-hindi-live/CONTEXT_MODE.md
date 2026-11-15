# Context-preserving interpretation mode (default)

The interpreter previously committed arbitrary fragments from mutable Google
STT interim hypotheses every ~4.5 seconds, and the listener discarded translated
audio when playback backlog exceeded 12 seconds. This can destroy context,
omit clauses, and make the translated narration disjointed.

Changes:
- Google STT interim transcripts still appear as Telugu preview on the listener,
  but only FINAL recognition results are translated and synthesized. Google decides
  these phrase boundaries; a speaker who talks without pausing may cause long gaps.
- Phone schedules every delivered English phrase in order, with no deliberate
  12-second skip. It displays its pending audio backlog and offers 1.0–1.3x speed.
- The server queue holds up to 100 finalized phrases instead of five; a full queue
  still logs a lost phrase. This is a safety limit, not infinite buffering.
- A suspended browser audio context may still fail to play a phrase; keep the
  display open and use 'Resume Audio / Test Beep' if needed.

Tradeoff: fidelity/coherence improved, but true simultaneous interpretation is
not guaranteed. Google's Speech v1 streams renew at ~235 seconds, which can
lose speech at the boundary because audio bridging is not implemented. This
also requires a separate redesign for a production-grade 16-hour workshop.
