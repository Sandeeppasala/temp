"""Google Gemini two-minute audio understanding: Telugu audio -> English and Hindi summaries."""
import base64
import json
import os
from urllib import request, error

class GeminiBillingRequired(RuntimeError):
    """Non-retriable Gemini API billing/prepaid-credit failure."""


MODEL_DEFAULT = "gemini-3.8-flash"
API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

def summarize_telugu_audio(wav: bytes) -> dict[str, str]:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY missing: create a Gemini API key and add it to .env")
    model = os.getenv("GEMINI_SUMMARY_MODEL", MODEL_DEFAULT).strip() or MODEL_DEFAULT
    prompt = (
        "Listen to this roughly two-minute Telugu spiritual workshop recording. "
        "Convey what was actually said in BOTH English and Hindi, "
        "each approximately 180-260 words when enough intelligible speech exists. "
        "The Hindi must be natural Hindi written in Devanagari script, not transliteration. "
        "Preserve names and details (Seth, Jane Roberts, Patriji, Brahmarshi Patriji, "
        "Seth Wisdom, Pyramid Spiritual Societies Movement), without inventing facts. "
        "Prioritize accuracy over eloquence. Do not add ideas from Seth books. "
        "Narrate the content directly, preserving the original perspective and meaning. "
        "Do not say 'the speaker says', 'the speaker is saying', 'he explains', "
        "'she mentions', 'according to the speaker', or Hindi equivalents such as "
        "'वक्ता कहते हैं' or 'वक्ता बता रहे हैं'. "
        "Do not frame the message as commentary about a speaker. "
        "Start directly with the content. Condense faithfully without inventing "
        "personal claims, new teachings, or first-person experiences. "
        "Write complete natural sentences suitable for voice narration. "
        "Return ONLY valid JSON with exactly two string keys: english and hindi. "
        "No markdown or code fences. If no intelligible Telugu speech exists, "
        "set BOTH values to NO_INTELLIGIBLE_SPEECH."
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
        # Never log the key or original request/audio. 402 is a non-retryable
        # prepay/billing failure; other codes remain distinguishable.
        if exc.code == 402:
            raise GeminiBillingRequired(
                "Gemini HTTP 402 Payment Required: prepaid API credits depleted. "
                "Check the Gemini API project billing in Google AI Studio. "
                "Summary capture paused until billing is resolved and restarted."
            ) from None
        raise RuntimeError(
            f"Gemini audio summary HTTP {exc.code}; verify API key, "
            "selected model, project billing and quota"
        ) from None
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
    # Require both languages; never send a JSON blob to speech synthesis.
    try:
        summaries = json.loads(result)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Gemini did not return valid bilingual summary JSON") from exc
    if not isinstance(summaries, dict):
        raise RuntimeError("Gemini bilingual summary must be a JSON object")
    english, hindi = summaries.get("english"), summaries.get("hindi")
    if not all(isinstance(v, str) and v.strip() for v in (english, hindi)):
        raise RuntimeError("Gemini did not return both English and Hindi summaries")
    return {"en": english.strip(), "hi": hindi.strip()}
