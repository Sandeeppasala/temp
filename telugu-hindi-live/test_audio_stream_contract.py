"""Static checks for no synthetic audio; run with local Python."""
import ast
from pathlib import Path
source = Path(__file__).with_name("google_stream.py").read_text(encoding="utf-8")
tree = ast.parse(source)
generator = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "chunks")
assert "silent_block" not in source
assert "bytes(3200 * 2)" not in source
assert "audio.get(timeout=0.2)" in source
assert "Microphone produced no PCM" in source
assert any(isinstance(node, ast.Raise) for node in ast.walk(generator))
assert any(isinstance(node, ast.Yield) for node in ast.walk(generator))
print("PASS: only captured microphone PCM is sent; stalls restart recognition")
