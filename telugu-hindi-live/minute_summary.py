"""Google Gemini one-minute audio understanding: Telugu audio -> concise English summary."""
import base64
import json
import os
from urllib import request, error

MODEL_DEFAULT = "gemini-3.8-flash"
API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

def summarize_telugu_audio(wav: bytes) -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY missing: create a Gemini API key and add it to .env")
    model = os.getenv("GEMINI_SUMMARY_MODEL", MODEL_DEFAULT).strip() or MODEL_DEFAULT
    prompt = (
        "Listen to this roughly one-minute recording of a Telugu spiritual "
        "workshop talk. Produce a faithful, coherent spoken English SUMMARY "
        "of what the speaker actually said, about 90-140 words when enough "
        "speech is present. Preserve essential ideas, people, specific claims, "
        "qualifications, steps and names (Seth, Jane Roberts, Patriji, "
        "Brahmarshi Patriji, Seth Wisdom, Pyramid Spiritual Societies Movement). "
        "Prioritize factual fidelity over eloquence. Do not invent missing "
        "meaning or assume the speaker said anything from Seth books. "
        "Use complete, natural sentences suitable for English voice narration. "
        "Never include preambles, headings or bullet points. "
        "If the audio has no intelligible Telugu speech, answer exactly "
        "'NO_INTELLIGIBLE_SPEECH'."
    )
    body = {
        "model": model,
        "store": False,
        "input": [
            {"type": "text", "text": prompt},
            {"type": "audio", "data": base64.b64encode(wav).decode("ascii"),
             "mime_type": "audio/wav"}
        ]
    }
    req = request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST")
    try:
        with request.urlopen(req, timeout=100) as response:
            payload = json.load(response)
    except error.HTTPError as exc:
        raise RuntimeError(f"Gemini audio summary HTTP {exc.code}; check Gemini API key, model and billing") from None
    # Interactions API returns an output array of typed text blocks.
    parts = payload.get("outputs") or payload.get("output") or []
    chunks = []
    def collect(item):
        if isinstance(item,list):
            for nested in item: collect(nested)
        elif isinstance(item,dict):
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                chunks.append(item["text"])
            for key in ("content","parts","output"):
                if key in item: collect(item[key])
    collect(parts)
    if not chunks:
        # Some response versions expose the model_output as a step.
        for step in payload.get("steps",[]):
            if step.get("type")=="model_output": collect(step.get("content",[]))
    result = " ".join(chunks).strip()
    if not result:
        raise RuntimeError("Gemini returned no text summary; check model response schema")
    return result
