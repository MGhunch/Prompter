"""
Prompter — NEW PIPELINE orchestration
Self-contained blueprint. Purely additive: touches none of the live routes.
The old CONSULT -> CONFIRM -> EXTRACT path keeps serving prompter.hunch.co.nz.

The chain:  CONSULT -> SORT -> CALIBRATE -> SHAPE -> SENSECHECK(=revise)
This file is the CONDUCTOR. It is deterministic Python. It calls each stage in
order and hands the asset along. The model never chooses which stage it's in --
that's what holds the think/render split and keeps the collage shut.

Wire-up in app.py is two lines:
    from pipeline import pipeline_bp
    app.register_blueprint(pipeline_bp)

Routes (all under /api/pipeline, all off the live path):
    POST /api/pipeline/sort       material(+consult) -> brief
    POST /api/pipeline/calibrate  brief              -> dials + forks
    POST /api/pipeline/shape      locked brief       -> profile
    POST /api/pipeline/run        material -> brief -> [calibration] -> profile
                                  (the SORT->SHAPE test path for v1/v2)
"""

from flask import Blueprint, jsonify, request
import anthropic
import os
import json

from prompts import PROMPT_SORT, PROMPT_CALIBRATE, PROMPT_SHAPE

pipeline_bp = Blueprint('pipeline', __name__)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

# Per-stage models. The thinking and the writing want Sonnet; the light,
# mechanical stages can run on Haiku. All overridable by env; all fall back to
# the suite default so a single PROMPTER_MODEL still works if nothing else is set.
_DEFAULT = os.environ.get('PROMPTER_MODEL', 'claude-sonnet-4-6')
MODEL_SORT      = os.environ.get('MODEL_SORT',      _DEFAULT)            # the thinking
MODEL_SHAPE     = os.environ.get('MODEL_SHAPE',     _DEFAULT)            # the writing
MODEL_CALIBRATE = os.environ.get('MODEL_CALIBRATE', 'claude-haiku-4-5-20251001')  # light


def _extract_json_object(text):
    """Pull a JSON object out of a model reply, tolerant of stray prose or
    code fences. Returns a dict, or None."""
    if not text:
        return None
    t = text.replace('```json', '').replace('```', '').strip()
    start = t.find('{')
    end = t.rfind('}')
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return None


def _call(model, system, user_content, max_tokens):
    """One stage = one model call with one system prompt. The asset comes in as
    user_content; the stage's job is fixed by its system prompt."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{'role': 'user', 'content': user_content}],
    )
    return (resp.content[0].text or '').strip()


# ---------------------------------------------------------------------------
# STAGE CALLS -- each is pure: asset in, asset out. No route logic here, so the
# /run path can chain them directly without going back through HTTP.
# ---------------------------------------------------------------------------

def run_sort(material, consult_notes=''):
    """material (+ consultation) -> brief JSON."""
    user = material
    if consult_notes:
        user += f"\n\n--- CONSULTATION NOTES ---\n{consult_notes}"
    raw = _call(MODEL_SORT, PROMPT_SORT, user, max_tokens=2000)
    return _extract_json_object(raw)


def run_calibrate(brief):
    """brief -> dials + forks. Reads only liveTensions / readerFeeling /
    conflicts -- CALIBRATE never re-reads the brand."""
    seed = {
        'liveTensions': brief.get('liveTensions', []),
        'readerFeeling': brief.get('readerFeeling', ''),
        'conflicts': brief.get('conflicts', []),
    }
    raw = _call(MODEL_CALIBRATE, PROMPT_CALIBRATE, json.dumps(seed), max_tokens=1200)
    return _extract_json_object(raw)


def run_shape(locked_brief):
    """locked brief -> the 5-section profile."""
    raw = _call(MODEL_SHAPE, PROMPT_SHAPE, json.dumps(locked_brief), max_tokens=2500)
    return _extract_json_object(raw)


# ---------------------------------------------------------------------------
# THE WRITE-BACK -- the bit that bit Prompter last time.
# A dial that doesn't reach the engine is decoration. This folds the human's
# answers INTO the brief, as explicit corrections SHAPE is told to weight above
# its own inference. Pure function, no model, no network -- so it's testable
# offline and can't silently no-op.
# ---------------------------------------------------------------------------

def apply_calibration(brief, answers):
    """brief + human answers -> locked brief.

    answers shape (all keys optional -- skipped dials just don't appear):
      {
        "sentences": [{"axis": "...", "value": 0-100}],   # where on the axis
        "feeling":   "<one word>",                        # confirmed feeling
        "forks":     [{"stated": "...", "shown": "...", "choice": "stated"|"shown"}]
      }
    Returns a NEW brief dict with a `calibration` directive list, readerFeeling
    possibly sharpened, and resolved conflicts removed.
    """
    locked = dict(brief)  # shallow copy; we only replace top-level keys
    directives = []

    # Sentence dials -> resolve each liveTension toward the chosen pole.
    tensions = {t.get('axis'): t for t in locked.get('liveTensions', [])}
    for ans in answers.get('sentences', []):
        axis = ans.get('axis')
        val = ans.get('value', 50)
        t = tensions.get(axis)
        if not t:
            continue
        if val < 25:    lean, pole = 'strongly toward', t.get('poleA', 'A')
        elif val < 45:  lean, pole = 'toward',          t.get('poleA', 'A')
        elif val <= 55: lean, pole = 'balanced between', f"{t.get('poleA','A')} and {t.get('poleB','B')}"
        elif val <= 75: lean, pole = 'toward',          t.get('poleB', 'B')
        else:           lean, pole = 'strongly toward',  t.get('poleB', 'B')
        directives.append(f"On {axis}: the human set this {lean} {pole}.")

    # Feeling dial -> sharpen readerFeeling directly (SHAPE already honours it).
    feeling = answers.get('feeling')
    if feeling:
        locked['readerFeeling'] = feeling
        directives.append(f"Reader should feel: {feeling} (human-confirmed).")

    # Forks -> resolve conflicts; the winning side becomes a directive, the
    # conflict is cleared so it can't be re-surfaced downstream.
    if answers.get('forks'):
        remaining = list(locked.get('conflicts', []))
        for fork in answers['forks']:
            choice = fork.get('choice')
            winner = fork.get(choice, '') if choice in ('stated', 'shown') else ''
            if winner:
                directives.append(f"Conflict resolved -- follow the {choice} read: {winner}.")
            remaining = [c for c in remaining
                         if not (c.get('stated') == fork.get('stated')
                                 and c.get('shown') == fork.get('shown'))]
        locked['conflicts'] = remaining

    locked['calibration'] = directives
    return locked


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@pipeline_bp.route('/api/pipeline/sort', methods=['POST'])
def sort_route():
    data = request.get_json() or {}
    material = data.get('material', '').strip()
    if not material:
        return jsonify({'error': 'No material provided'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500
    try:
        brief = run_sort(material, data.get('consultNotes', ''))
        if brief is None:
            return jsonify({'error': 'SORT returned no parseable brief'}), 500
        return jsonify({'success': True, 'brief': brief})
    except Exception as e:
        print(f'[Pipeline] SORT error: {e}')
        return jsonify({'error': str(e)}), 500


@pipeline_bp.route('/api/pipeline/calibrate', methods=['POST'])
def calibrate_route():
    data = request.get_json() or {}
    brief = data.get('brief')
    if not brief:
        return jsonify({'error': 'No brief provided'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500
    try:
        dials = run_calibrate(brief)
        if dials is None:
            return jsonify({'error': 'CALIBRATE returned no parseable dials'}), 500
        return jsonify({'success': True, **dials})
    except Exception as e:
        print(f'[Pipeline] CALIBRATE error: {e}')
        return jsonify({'error': str(e)}), 500


@pipeline_bp.route('/api/pipeline/shape', methods=['POST'])
def shape_route():
    data = request.get_json() or {}
    brief = data.get('brief')
    answers = data.get('answers')  # optional; if present, write back first
    if not brief:
        return jsonify({'error': 'No brief provided'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500
    try:
        locked = apply_calibration(brief, answers) if answers else brief
        profile = run_shape(locked)
        if profile is None:
            return jsonify({'error': 'SHAPE returned no parseable profile'}), 500
        return jsonify({'success': True, 'profile': profile, 'lockedBrief': locked})
    except Exception as e:
        print(f'[Pipeline] SHAPE error: {e}')
        return jsonify({'error': str(e)}), 500


@pipeline_bp.route('/api/pipeline/run', methods=['POST'])
def run_route():
    """The test path for v1/v2: material -> brief -> [optional calibration] ->
    profile, in one call. Skips the human loop so a brand can be run start to
    finish from a script."""
    data = request.get_json() or {}
    material = data.get('material', '').strip()
    if not material:
        return jsonify({'error': 'No material provided'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500
    try:
        brief = run_sort(material, data.get('consultNotes', ''))
        if brief is None:
            return jsonify({'error': 'SORT returned no parseable brief'}), 500
        answers = data.get('answers')
        locked = apply_calibration(brief, answers) if answers else brief
        profile = run_shape(locked)
        if profile is None:
            return jsonify({'error': 'SHAPE returned no parseable profile'}), 500
        return jsonify({'success': True, 'brief': brief, 'lockedBrief': locked, 'profile': profile})
    except Exception as e:
        print(f'[Pipeline] run error: {e}')
        return jsonify({'error': str(e)}), 500
