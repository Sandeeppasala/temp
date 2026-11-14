"""Offline tests: python test_terminology.py"""
import tempfile
from unittest.mock import patch
from pathlib import Path
import terminology

with tempfile.TemporaryDirectory() as directory:
    p=Path(directory)/"terms.tsv"
    p.write_text("# names\nసేత్\tSeth\nపాత్రీజీ\tPatriji\n",encoding="utf-8")
    with patch.object(terminology, "TERMS_PATH", p):
        terminology.load_terms.cache_clear()
        assert terminology.load_terms()["సేత్"] == "Seth"
        assert terminology.replace_known_names("సేత్ మాట్లాడారు. పాత్రీజీ వచ్చారు.") == ("Seth మాట్లాడారు. Patriji వచ్చారు.",2)
        assert terminology.replace_known_names("మంచి వ్యక్తి") == ("మంచి వ్యక్తి",0)
        terminology.load_terms.cache_clear()
print("PASS: terminology preserves explicitly configured names without dropping unmatched text")
