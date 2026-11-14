"""Optional manually curated Telugu→English proper-name terminology.

Only replace names the operator explicitly supplies. Do not guess nouns.
The canonical English spellings are inserted into the Telugu text before
Google Translation; Google may still change or omit some names.
"""
from pathlib import Path
from functools import lru_cache
import re

TERMS_PATH = Path(__file__).resolve().parent / "proper_names.tsv"

@lru_cache(maxsize=1)
def load_terms():
    names = {}
    if not TERMS_PATH.exists():
        return names
    for number, line in enumerate(TERMS_PATH.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 2 or not all(field.strip() for field in fields):
            raise ValueError(f"proper_names.tsv line {number}: expected Telugu<TAB>English")
        telugu, english = (x.strip() for x in fields)
        if len(telugu) < 2 or len(telugu) > 100 or len(english) > 100:
            raise ValueError(f"proper_names.tsv line {number}: invalid term length")
        if telugu in names and names[telugu] != english:
            raise ValueError(f"Conflicting English spellings for {telugu}")
        names[telugu] = english
    if len(names) > 100:
        raise ValueError("Limit active proper-name substitutions to 100; other terms belong in seth_terms.tsv")
    return names

def replace_known_names(text):
    """Replace exact glossary names without matching inside longer words.

    Only entries from proper_names.tsv are active. Ordinary vocabulary in
    seth_terms.tsv is a reference, not an automatic substitution list.
    """
    terms = load_terms()
    if not terms:
        return text, 0
    names = sorted(terms, key=len, reverse=True)
    # Telugu combining marks, virama and base letters lie in U+0C00–U+0C7F.
    # Zero-width non-joiner/joiner (U+200C/U+200D) can connect a suffix,
    # e.g. సేత్‌తో. None of these may count as a word boundary.
    pattern = re.compile(
        r"(?<![\u0C00-\u0C7F\u200C\u200D])(?:" +
        "|".join(re.escape(name) for name in names) +
        r")(?![\u0C00-\u0C7F\u200C\u200D])"
    )
    substitutions = 0
    def convert(match):
        nonlocal substitutions
        substitutions += 1
        return terms[match.group(0)]
    return pattern.sub(convert, text), substitutions
