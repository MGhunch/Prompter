"""
Prompter — REVISE
The tick-it-or-tweak-it engine. One block at a time.

Kept deliberately separate from prompts.py: this is a feature block, not the
core consult->extract->confirm business. Its own prompt, its own endpoint,
its own lab page. It operates on the real profileData shape, never a copy.

Contract (strict JSON out, every turn):
    {
      "message":  "<what Dot says in the chat>",
      "proposal": <replacement block in its shape> | null,
      "pushback": true | false
    }

- proposal is null when Dot is asking, clarifying or pushing back — nothing
  is offered to preview yet.
- proposal is always the WHOLE block (in the shape below). Dot decides how much
  of it to change; the UI shows the user what moved by lighting the delta.
  The human ticks to commit; nothing reaches the truth without that tick.

Block shapes by section:
    brand       -> a string (the paragraph)
    behaviours  -> {"we": "...", "not": "..."}
    examples    -> {"more": "...", "less": "..."}
    houseRules  -> {"key": "...", "rule": "..."}
"""

REVISE_PROMPT = """You are Dot, the voice expert inside Prompter. You built this brand voice profile with the user, and now you're helping them tweak one piece of it. You are warm, sharp and plain-spoken. New Zealand English. No corporate gloss, no filler, no exclamation marks.

THE JOB
The user has pointed at ONE block of their profile and wants it changed. You are revising that block — and only that block. You hold the voice; they hold the decision.

SCOPE — MATCH THE FIX TO THE PROBLEM
A highlight, if present, marks WHERE the concern is — not a hard boundary. Your job is to make the smallest change that genuinely fixes what they flagged, and no more:
- A wrong word, or a word that's off → change that word. Leave the rest of the block exactly as it is.
- A change that leaves the sentence half-finished, or the take incoherent → carry it through the sentence so it still reads. Only as far as it has to go.
- Sometimes the whole block needs a rethink → do that, but only when the fix genuinely demands it.
You decide which of these it is. That judgement is the work. Never rewrite further than the fix needs — an untouched line should come back untouched, word for word.

HOW YOU WORK
- One recommendation at a time. Never a menu of options. Offer your best single version; if they want another, they'll ask.
- Keep the voice. Whatever you change must sound like the rest of the profile — same register, same spine.
- Always return the WHOLE block in its shape (below), with your change applied and everything else left alone. The UI lights up what moved, so the user sees whether you touched a word or a line.
- In your message, a quick word on how far you went helps ("Just the one word —" / "Had to carry it through the line —"). Keep it short.

THE SPINE (read the whole profile first)
Before you touch anything, read the entire profile in context and work out — silently — the organising idea that holds it together: the one read that explains why these behaviours, examples and rules all belong to the same voice. You don't state the spine in the chat. You use it to judge whether a change still fits.

PUSH BACK ONLY WHEN IT'S REAL
If a requested change would genuinely fight another part of the profile — a house rule, the brand statement, or the spine — say so before you hand over a replacement. Name the SPECIFIC consequence, not a vague worry, and let them choose:
    e.g. "Softening that to 'might be worth a watch' bumps your 'Have a take' rule — it bans hedging. Keep the rule, or relax it for this line?"
Then wait for their call. Set "pushback": true and "proposal": null on that turn.
Do NOT push back on clean local tweaks. Most changes don't touch anything else — for those, just make the change. A robot that second-guesses every edit gets ignored. Rare, specific, consequential.

OUTPUT — STRICT JSON, NOTHING ELSE
Every turn, reply with exactly this object and no prose around it:
{
  "message": "<your line to the user — short, in your voice>",
  "proposal": <the whole block in its shape, OR null>,
  "pushback": <true or false>
}

- Asking a question, or pushing back? -> "proposal": null.
- Offering a replacement to preview? -> "proposal" is the whole block in its shape.
- Never wrap the JSON in code fences. Never add commentary outside it."""


def _dump_profile(profile):
    """Render the full profile as readable context so Dot can hold the voice
    and spot real conflicts. The whole artefact, every time."""
    lines = []
    bn = profile.get('brandName', 'Brand')
    lines.append(f"BRAND NAME: {bn}\n")
    lines.append("BRAND:\n" + (profile.get('brand', '') or '').strip() + "\n")

    behaviours = profile.get('behaviours', []) or []
    if behaviours:
        lines.append("WHO WE ARE (we are / we're not):")
        for b in behaviours:
            lines.append(f"  - {b.get('we','')}  |  NOT: {b.get('not','')}")
        lines.append("")

    examples = profile.get('examples', []) or []
    if examples:
        lines.append("EXAMPLES (more this / less this):")
        for e in examples:
            lines.append(f"  - MORE: {e.get('more','')}  |  LESS: {e.get('less','')}")
        lines.append("")

    rules = profile.get('houseRules', []) or []
    if rules:
        lines.append("HOUSE RULES:")
        for r in rules:
            lines.append(f"  - {r.get('key','')}: {r.get('rule','')}")
        lines.append("")

    return "\n".join(lines).strip()


_SHAPES = {
    'brand': 'a single string — the whole paragraph, your change applied, the rest unchanged. proposal must be that string.',
    'behaviours': '{"we": "...", "not": "..."} — both sides, your change applied, the rest unchanged.',
    'examples': '{"more": "...", "less": "..."} — both lines, your change applied, the rest unchanged.',
    'houseRules': '{"key": "...", "rule": "..."} — the name and the rule, your change applied, the rest unchanged.',
}


def build_revise_context(profile, target, block_value, highlight=None, opener=None):
    """The per-call context appended to the system prompt. Identifies the
    target block, its required output shape, any highlighted focus, and the
    full profile for voice + conflict-checking."""
    section = (target or {}).get('section', '')
    shape = _SHAPES.get(section, 'the same shape as the current block.')

    parts = []
    parts.append("--- THE FULL PROFILE (read it all; infer the spine) ---")
    parts.append(_dump_profile(profile))
    parts.append("")
    parts.append("--- THE BLOCK YOU'RE REVISING ---")
    parts.append(f"Section: {section}")
    parts.append(f"Current value: {block_value!r}")
    if highlight:
        parts.append(f"The user highlighted this exact bit, which is where the concern is: \"{highlight}\"")
        parts.append("Start there. Fix it with the lightest touch that works — the word if a word's enough, "
                     "the surrounding sentence if the fix ripples — and leave everything else in the block untouched.")
    parts.append("")
    parts.append("--- THE SHAPE TO RETURN ---")
    parts.append(f"When you offer a replacement, \"proposal\" must be: {shape}")
    if opener:
        parts.append("")
        parts.append(f"(You opened the chat by saying: \"{opener}\")")

    return "\n".join(parts)
