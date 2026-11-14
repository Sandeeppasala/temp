"""Validate microphone stream pacing/fallback syntax without cloud credentials.
Run: python test_audio_stream_contract.py
"""
import ast
from pathlib import Path
source=Path(__file__).with_name("google_stream.py").read_text(encoding="utf-8")
root=ast.parse(source)
fn=next(n for n in ast.walk(root) if isinstance(n,ast.FunctionDef) and n.name=="chunks")
assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="get" for n in ast.walk(fn))
assert "silent_block" in source
assert "Microphone capture stalled" in source
assert "block_seconds = 3200 / 16000" in source
print("PASS: Google streaming audio pacing and silence watchdog code present")
