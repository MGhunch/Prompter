"""
Prompter — REVISE endpoint
Self-contained blueprint. Purely additive: touches none of the live routes.

Wire-up in app.py is two lines:
    from revise import revise_bp
    app.register_blueprint(revise_bp)

The lab page (revise-lab.html) is served automatically by app.py's existing
static catch-all, so there's no page route to add.
"""

from flask import Blueprint, jsonify, request
import anthropic
import os
import json

from revise_prompt import REVISE_PROMPT, build_revise_context

revise_bp = Blueprint('revise', __name__)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
# Same single source of truth for the model as app.py.
MODEL = os.environ.get('PROMPTER_MODEL', 'claude-sonnet-4-6')


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


@revise_bp.route('/api/revise', methods=['POST'])
def revise():
    data = request.get_json() or {}
    profile = data.get('profile')
    target = data.get('target')          # {"section": "...", "index": n}
    block_value = data.get('blockValue')
    highlight = data.get('highlight')    # optional focus span, or null
    opener = data.get('opener')          # Dot's first line (UI only), for continuity
    history = data.get('history', [])    # the dialogue so far for this block

    if not profile or not target:
        return jsonify({'error': 'Missing profile or target'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        system = REVISE_PROMPT + "\n\n" + build_revise_context(
            profile, target, block_value, highlight, opener
        )

        # Build the message array from the block's dialogue. Dot's stored turns
        # are her plain `message` string, not the JSON she emits. Replaying that
        # as-is drops her out of JSON mode from turn two on (same bug that bit
        # consult). Re-wrap any non-JSON assistant turn back into the shape she
        # speaks in so she stays in format.
        messages = []
        for h in history:
            role = h.get('role')
            content = h.get('content', '')
            if role == 'assistant' and _extract_json_object(content) is None:
                content = json.dumps({'message': content, 'proposal': None, 'pushback': False})
            messages.append({'role': role, 'content': content})

        # Anthropic requires the first message to be from the user. The robot-
        # first opener lives in the UI, not here, so history should already
        # start with the human's feedback — but guard it anyway.
        if not messages or messages[0]['role'] != 'user':
            messages.insert(0, {'role': 'user', 'content': 'Help me tweak this block.'})

        response = client.messages.create(
            model=MODEL,
            max_tokens=900,
            system=system,
            messages=messages
        )

        raw = (response.content[0].text or '').strip()
        result = _extract_json_object(raw)

        if result is None:
            # Don't 500 over a formatting wobble — treat the reply as Dot's
            # message, offer nothing to commit. Log the raw to watch for drift.
            print(f'[Prompter] Revise fell back to raw reply (no JSON): {raw[:300]!r}')
            return jsonify({
                'success': True,
                'message': raw or "Hmm, that didn't come through. Say it again?",
                'proposal': None,
                'pushback': False
            })

        return jsonify({
            'success': True,
            'message': result.get('message', ''),
            'proposal': result.get('proposal', None),
            'pushback': bool(result.get('pushback', False))
        })

    except Exception as e:
        print(f'[Prompter] Revise error: {e}')
        return jsonify({'error': str(e)}), 500
