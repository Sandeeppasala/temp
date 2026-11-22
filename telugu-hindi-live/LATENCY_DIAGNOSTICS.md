# Diagnosing continuous-speech lag

The listener shows Google-English captions immediately after translation, before
TTS completes. The server now measures per-segment queue wait, Google
translation time, TTS generation time, total time since recognition, and
the number of phrases lost due to a full server queue.

The phone orders all audio decoding, shows scheduled playback backlog, and
allows selection of 1.0×, 1.15×, 1.25× (default) or 1.4× speed. Speeding
English speech is a pragmatic way to reduce growing backlog, but increases
pitch via AudioBufferSourceNode playbackRate; quality may deteriorate.
The phone still drops incoming segments if its scheduled backlog is >12
seconds. Those losses are counted separately on the listener.

The server timestamps start **when it receives a recognized Telugu chunk**:
the total metric does NOT include microphone capture time, Google STT
recognition delay or network transit to the listener. It is not a true
end-to-end latency measurement. Caption timings are approximate and
cumulative segment counters reset with each server restart.

If you continue seeing 20+ seconds lag:
- High queue wait: server serial translation + TTS cannot keep up.
- High TTS time: voice generation is bottleneck.
- Phone queued >8 s: English speech duration outruns original Telugu speech;
  use 1.15–1.25× playback, shorten translation or accept delay.
- Skipped >0: translation content is being lost; stop and improve
  before relying on the tool during a spiritual workshop.

No new cloud services are added; cloud billing is still usage-based.
