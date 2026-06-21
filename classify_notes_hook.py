"""
NOTES CLASSIFY HOOK  --  paste into app.py

Runs once at material ingestion, BEFORE consult and extract, so both Dot and the
EXTRACT engine see notes already sorted into testimony (stated intent) and
examples (shown copy). This is what makes the CONSULT_PROMPT hierarchy line
("notes arrive pre-sorted") true.

THREE WIRING POINTS -- only you know the exact names:
  1. `client`  -> your existing Anthropic client
  2. `MODEL`   -> your existing model constant (PROMPTER_MODEL env var)
  3. where the split feeds your material payload (bottom of file)
"""

import json
from prompts import NOTES_CLASSIFY_PROMPT
# from app import client, MODEL   <- use whatever you already have


def classify_notes(notes_text):
    """
    Split freeform notes into stated intent and shown copy.
    Returns {"testimony": [str, ...], "examples": [str, ...]}.

    'both' lands in both lists (a tagline is intent AND copy).
    Unsure pieces default to examples -- better to treat shaky material as
    evidence than let it pollute the stated layer. SORT still backstops intent.
    """
    if not notes_text or not notes_text.strip():
        return {"testimony": [], "examples": []}

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,                      # echoes text back; size with paste length in mind
            system=NOTES_CLASSIFY_PROMPT,
            messages=[{"role": "user", "content": notes_text}],
        )
        raw = resp.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()   # belt-and-braces
        pieces = json.loads(raw)
    except Exception as e:
        # Conservative fallback: never lose the words, never pollute intent.
        # Treat the lot as evidence, not testimony.
        print(f"[classify_notes] failed, routing raw notes to examples: {e}")
        return {"testimony": [], "examples": [notes_text.strip()]}

    testimony, examples = [], []
    for p in pieces:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        kind = (p.get("type") or "example").lower()
        if kind == "testimony":
            testimony.append(text)
        elif kind == "both":
            testimony.append(text)
            examples.append(text)
        else:                                     # example, or anything unexpected
            examples.append(text)
    return {"testimony": testimony, "examples": examples}


# ---- WIRING POINT 3 ------------------------------------------------------
# Wherever you currently fold `notes` into the material handed to CONSULT and
# EXTRACT, swap it for this. Field names depend on your material shape.
#
#   split = classify_notes(notes_text)
#   material["testimony"] = split["testimony"]                       # stated layer, sits near guidelines
#   material["examples"]  = material.get("examples", []) + split["examples"]   # shown layer
#
# Then nothing else in the pipeline holds a raw `notes` bucket -- the old
# catch-all is gone, which is exactly what the hierarchy edit now assumes.
