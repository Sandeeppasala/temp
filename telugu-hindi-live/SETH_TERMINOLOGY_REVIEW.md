# Reviewed Seth wisdom terminology (November 2026)

The user supplied 137 distinct Telugu spellings in five topic groups.
Reviewed and included all distinct entries in `seth_terms.tsv` as a reference.

Files:
- `seth_terms.tsv`: 137 unique Telugu→English reference entries
  including spiritual concepts, alternative transliterations, authors, books
  and science terms. The reference is NOT automatically injected into speech.
- `proper_names.tsv`: 11 distinctive proper names, book
  titles and organizations that are loaded into Google STT's speech hints
  and conservatively substituted before Google Translation.

Why the separation: blindly translating common terms such as ప్రేమ (love),
ఆత్మ (soul), శరీరం (body) or శక్తి (energy) before Google Translation can
change inflections and context. Term reference does not itself improve the
Cloud Translation Basic v2 quality; such improvement would need a contextual
translation engine, controlled test corpus and evaluation.

Review notes:
- `మనస్సు`: rendered as **Mind** instead of `Psyche`, since `మనస్సు`
  usually means mind; `సైకీ` is retained as Psyche.
- `అణువులు`: **Atoms / Molecules (context-dependent)**. Telugu colloquial
  usage varies; `పరమాణువులు` is generally **Atoms**, not Molecules.
- `మహాత్మ` → Oversoul, `పూర్ణాత్మ` → Entity, and `సమాధి స్థితి` →
  Trance State are presented as user-preferred domain interpretations,
  not universally exact lexical equivalences.
- Multiple Telugu spellings pointing to one English concept (e.g.,
  ఎంటిటీ/పూర్ణాత్మ) are intentional *variants*, not duplicate
  Telugu keys. Prefix overlaps (సేత్ vs సేత్ విజ్ఞానం) are not duplicates.
- Original user's pasted `\\`t` form for two rows was interpreted as
  a tab separator. No empty Telugu entries or duplicate Telugu keys added.
- Active substitutions are matched only as standalone Unicode Telugu words/
  phrases so a name inside an inflected compound is not partly replaced.

The reference list is a terminology resource, NOT a list of guaranteed
word-for-word equivalences. Many terms depend on Seth context. Restart the
server after changing active `proper_names.tsv` entries.
