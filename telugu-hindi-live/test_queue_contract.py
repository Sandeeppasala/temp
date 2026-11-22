"""Regression guard for the Google STT→translation queue shape.

Run: python test_queue_contract.py
No API calls or credentials required.
"""
import ast
from pathlib import Path

source = Path(__file__).with_name("app.py").read_text(encoding="utf-8")
tree = ast.parse(source)
fn = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "google_recognized")
submitted = [call for call in ast.walk(fn) if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "put_nowait"]
assert submitted, "Google recognizer never submits translation work"
assert all(len(c.args) == 1 and isinstance(c.args[0], ast.Tuple) and len(c.args[0].elts) == 2 for c in submitted), "Google recognizer must submit (Telugu text, timestamp)"
worker = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "translation_worker")
assert any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Tuple) and len(t.elts) == 2 for t in n.targets) for n in ast.walk(worker)), "Worker queue contract changed"
print("PASS: Google speech and translation worker queue contracts match.")
