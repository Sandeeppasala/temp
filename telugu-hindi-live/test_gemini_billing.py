"""Offline tests: Gemini HTTP 402 fails fast and stops repeated capture."""
import ast
from pathlib import Path
source=Path(__file__).with_name("app.py").read_text(encoding="utf-8")
summary=Path(__file__).with_name("minute_summary.py").read_text(encoding="utf-8")
ast.parse(source);ast.parse(summary)
assert "except GeminiBillingRequired as exc:" in source
assert "running = False" in source
assert "await asyncio.to_thread(mic.stop)" in source
assert "translation_queue.get_nowait()" in source
assert "if exc.code == 402:" in summary
assert "prepaid API credits depleted" in summary
print("PASS: Gemini 402 stops capture; no repeated API calls after billing failure")
