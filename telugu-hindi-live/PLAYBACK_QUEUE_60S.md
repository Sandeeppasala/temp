# 60-second browser playback queue

The browser now schedules a maximum 60-second playback-ahead window
(AudioContext time). Any additional received English voice clips remain
in an ordered in-memory FIFO and are scheduled when capacity opens,
rather than being skipped. The phone stays awake/in foreground for
reliable playback. A new device or page refresh does not replay old speech.

Diagnostics:
- received: English WAV packets delivered to this listener page.
- scheduled: packets handed to WebAudio for playback, not proof they were audible.
- browser skips: intentionally skipped browser clips (normally zero).
- packet gaps: gaps in the server's sequence numbers for received AUDIO packets;
  some gaps may come from test voice or server TTS failures and do not prove
  speech recognizer loss.
- scheduled x/60s: WebAudio's scheduled backlog.
- waiting: duration of received English audio buffered in JavaScript.
- buffer overflows: times the total buffered work exceeded 60 seconds; NO
  packets are intentionally thrown away due to that condition.
- errors: playback decoding or scheduling failures.

Important: earlier listener already had no 12-second skip threshold.
The new change makes the 60-second *scheduled* queue explicit and exposes
pending FIFO state, rather than pretending zero skips proves no missing speech.
The browser is NOT a source-of-truth recorder. Original Telugu speech can be
omitted at Google STT finalization or at the ~235-second stream restart.
Google STT v1 streaming restarts presently lack audio bridging, so some
spoken words could be lost without any browser errors or skip counts.
