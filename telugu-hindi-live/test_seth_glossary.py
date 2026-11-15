"""Run: python test_seth_glossary.py; no cloud credentials required."""
from pathlib import Path
from terminology import load_terms, replace_known_names
root = Path(__file__).resolve().parent
def read_pairs(file):
    pairs = {}
    for line in file.read_text(encoding="utf-8-sig").splitlines():
        if not line or line.startswith("#"):
            continue
        k, v = line.split("\t", 1)
        assert k not in pairs, f"duplicate Telugu key: {k}"
        assert k and v
        pairs[k] = v
    return pairs
reference = read_pairs(root / "seth_terms.tsv")
active = read_pairs(root / "proper_names.tsv")
assert len(reference) == 137, (len(reference), 137)
assert len(active) == 11
assert set(active) <= set(reference)
assert load_terms() == active
assert replace_known_names("సేత్ చెప్పిన ప్రేమ గురించి") == ("Seth చెప్పిన ప్రేమ గురించి", 1)
assert replace_known_names("సేత్ విజ్ఞానం గురించి") == ("Seth Wisdom గురించి", 1)
assert replace_known_names("ప్రేమ శక్తి ఆత్మ") == ("ప్రేమ శక్తి ఆత్మ", 0)
assert replace_known_names("సేత్‌తో కలిసి") == ("సేత్‌తో కలిసి", 0)
assert replace_known_names("మాసేత్") == ("మాసేత్", 0)
assert replace_known_names("సేత్‍తో కలిసి") == ("సేత్‍తో కలిసి", 0)
assert replace_known_names("సేత్ చెప్పారు") == ("Seth చెప్పారు", 1)
print("PASS:", len(reference), "unique reference entries,", len(active), "active proper names, no duplicates")
