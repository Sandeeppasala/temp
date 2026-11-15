# Improving Telugu proper nouns without changing the live UI

Google STT can misrecognize rare proper names, and Google Translation can
misinterpret names that appear in short chunks. These are separate failure
modes. No system can infer a missing name from silence or poor transcription.

This release adds **opt-in terminology**:
1. Create `proper_names.tsv` in the project directory, with exact
   Telugu spelling, TAB, and canonical English name on each line.
2. Stop and restart the Python server after editing names.
3. Google STT receives these Telugu terms as speech-context hints
   with modest boost 6.0. Google docs caution that hints may increase
   false positives and models may not support adaptation equally.
4. Before Google Translation Basic v2, only exact configured Telugu
   occurrences are replaced with their English names. This is not a
   glossary feature of Cloud Translation Basic; Google may still alter
   or omit some terms. It preserves ordinary Telugu nouns unchanged.
5. Compare the phone's Live Telugu recognition against the English
   interpretation. Missing from Telugu preview indicates recognition.
   Present in Telugu but absent in translated English suggests
   translation/segmentation. Present in both but not audible suggests
   playback issues.

Create `proper_names.tsv` yourself. It is intentionally absent by
default, to avoid inventing the speaker's terminology. Start with
3–10 verified names, not all possible nouns.
