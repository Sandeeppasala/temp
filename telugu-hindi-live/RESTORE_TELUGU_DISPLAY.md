# Restore previous Telugu recognition and listener UI

Reverted the final-only STT and playback-aligned UI introduced in
224b1f3, because user reported that Telugu text effectively disappeared.

This restores the earlier recognizer's interim text callbacks and its
stable-chunk mode (060e5a0) and shows Live Telugu recognition
prominently rather than far down beneath several sections.

The 60-second scheduled audio queue, browser diagnostics and Google
cloud pipeline remain unchanged. Note that interim chunks may still
be revised and translation/context accuracy is NOT guaranteed.
Work on transcription fidelity should be validated separately on a
fixed test clip before further live event deployment.
