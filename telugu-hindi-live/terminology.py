"""Optional manually curated Telugu→English proper-name terminology.

Only replace names the operator explicitly supplies. Do not guess nouns.
The canonical English spellings are inserted into the Telugu text before
Google Translation; Google may still change or omit some names.
"""
from pathlib import Path
from functools import lru_cache

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
        names[telugu] = english
    if len(names) > 100:
        raise ValueError("Limit configured terms to 100 to avoid excessive STT hints")
    return names

def replace_known_names(text):
    terms = load_terms()
    count = 0
    # Replace longer terms first to avoid replacing a substring of a longer name.
    for telugu, english in sorted(terms.items(), key=lambda kv: len(kv[0]), reverse=True):
        occurrences = text.count(telugu)
        if occurrences:
            # Restrict to explicitly configured terms, no automatic noun deletion.
            text = text.replace(telugu, english)
            count += occurrences
    return text, count
