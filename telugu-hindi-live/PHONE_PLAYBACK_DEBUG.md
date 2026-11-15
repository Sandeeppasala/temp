# Phone English audio diagnostics — intermittent playback

The browser now distinguishes:
- packets: audio segments received over WebSocket;
- scheduled: decoded buffers handed to WebAudio for future playback;
- started: WebAudio-clock based approximation of scheduled audio starts;
- ended: actual AudioBufferSourceNode.onended callback count;
- underruns: transitions from playing English audio to an empty browser queue;
- packet gaps: missing sequence numbers among packets received by this listener.

An underrun is expected when Google STT finalizes only sporadic 1–3 word
phrases; it means no next translated audio packet was available, not that
the browser discarded anything. When the server processed Segments 1–3
successfully and there is no more speaker output, intermittent English
audio is normal. Captions now show the *currently scheduled-to-start*
English audio separately from the latest translation, so a delayed audio
segment won't be compared with more recent recognition.

No synthetic silent PCM or silent WAV is generated or transmitted. The
existing microphone capture-stall recovery remains unchanged.

Test: Send Test English Voice from admin while listening on phone.
If packets increment but started/ended don't, check AudioContext state,
tap Resume Audio and keep browser foreground. If packets don't increment,
inspect WebSocket/network. If all counters advance and underruns increase,
the source isn't producing English packets continuously (STT segmentation).
