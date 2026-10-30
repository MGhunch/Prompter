"""
Prompter v5
Single-stage consultation model.
Dot reads material, asks targeted questions, builds profile through conversation.
"""

from flask import Flask, jsonify, request, send_from_directory, abort
import anthropic
import os
import json
import io
import requests as req
from bs4 import BeautifulSoup
from prompts import CONSULT_PROMPT, EXTRACT_PROMPT, CONFIRM_PROMPT, SUMMARISE_PROMPT, REGEN_SENTENCE_PROMPT, RULES_PROMPT
from revise import revise_bp  # REVISE feature block (tick-it-or-tweak-it)
import guard  # caps, daily ceiling, safe URL fetch

# No automatic static folder: Flask would otherwise serve every file in the
# repo, prompts and code included. The page and its pictures are served by
# the two routes at the bottom, and nothing else.
# No CORS either: the page is served from this same app, so it never needs it,
# and leaving it on let any website call the API on our bill.
app = Flask(__name__, static_folder=None)
guard.install(app)
app.register_blueprint(revise_bp)  # adds /api/revise; touches no existing route

from pipeline import pipeline_bp  # NEW pipeline (SORT->CALIBRATE->SHAPE); off the live path
app.register_blueprint(pipeline_bp)  # adds /api/pipeline/*; touches no existing route

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

# One source of truth for the model. claude-sonnet-4-20250514 retired 15 Jun 2026.
# Override per-environment with PROMPTER_MODEL if needed.
MODEL = os.environ.get('PROMPTER_MODEL', 'claude-sonnet-4-6')
# Light jobs (the two-word file label) don't need Sonnet.
MODEL_LIGHT = os.environ.get('PROMPTER_MODEL_LIGHT', 'claude-haiku-4-5-20251001')

# Dot gets this many replies from the user, then her next message is her last
# and she hands over. Keeps the chat from running away and the bill small.
CONSULT_MAX_REPLIES = int(os.environ.get('PROMPTER_CONSULT_MAX_REPLIES', 10))
CONSULT_LAST_TURN = (
    "\n\nTHIS IS YOUR LAST MESSAGE. You've had your questions. Wrap up in one or "
    "two sentences: that's plenty, let's play. Set \"ready\" to true."
)
# The person pressed OKAY, LET'S PLAY before you said ready. One message.
CONSULT_PUSHBACK = (
    "\n\nTHEY'VE HIT THE BUTTON. This is your one chance to argue, and only if "
    "what you've got is genuinely thin. If it is: say so plainly in one or two "
    "sentences and name the single thing that would help most. No question "
    "needed; they can go anyway. If what you've got is enough: say so, and set "
    "\"ready\" to true."
)
# The front end injects these as user turns: one when new files land, one
# when the button is pressed early. Neither is a reply from the person, so
# neither counts toward the cap.
_MATERIAL_NUDGE = 'More material just landed.'
_PUSHBACK_NUDGE = "I've hit the button."


def _order_blocks(blocks, page_width):
    """Reconstruct reading order for multi-column layouts. Detects column
    separators as vertical whitespace gaps in horizontal coverage, assigns each
    text block to a column, then reads each column top-to-bottom, left-to-right.
    Pure text-layer work -- never touches images, so OCR can never fire."""
    cover = [False] * (int(page_width) + 2)
    for b in blocks:
        for x in range(max(0, int(b[0])), min(len(cover), int(b[2]) + 1)):
            cover[x] = True
    gap = max(18, int(page_width * 0.025))
    edges, run = [0], 0
    for x in range(len(cover)):
        if not cover[x]:
            run += 1
        else:
            if run >= gap:
                edges.append(x - run // 2)
            run = 0
    edges.append(page_width)
    cols = [[] for _ in range(len(edges) - 1)]
    for b in blocks:
        cx = (b[0] + b[2]) / 2
        for ci in range(len(edges) - 1):
            if edges[ci] <= cx < edges[ci + 1]:
                cols[ci].append(b)
                break
    out = []
    for col in cols:
        out += [b[4].strip() for b in sorted(col, key=lambda b: b[1])]
    return '\n'.join(out)


def extract_text_from_pdf(file_bytes):
    import fitz  # pymupdf
    doc = fitz.open(stream=file_bytes, filetype='pdf')
    pages = []
    for page in doc:
        # b[6] == 0 keeps text blocks only (no image blocks -> no OCR path).
        blocks = [b for b in page.get_text('blocks') if b[6] == 0 and b[4].strip()]
        if blocks:
            pages.append(_order_blocks(blocks, page.rect.width))
    doc.close()
    return '\n\n'.join(pages).strip()


def extract_text_from_docx(file_bytes):
    from docx import Document
    doc = Document(io.BytesIO(file_bytes))
    return '\n\n'.join([p.text for p in doc.paragraphs if p.text.strip()])


def extract_text_from_url(url):
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; Prompter/1.0)'}
    _, body = guard.safe_get(url, headers=headers, timeout=12)
    soup = BeautifulSoup(body, 'lxml')
    for tag in soup(['script','style','nav','footer','header','aside','form','iframe']):
        tag.decompose()
    blocks = []
    for tag in soup.find_all(['h1','h2','h3','h4','p','li','blockquote']):
        text = tag.get_text(strip=True)
        if text and len(text) > 20:
            blocks.append(text)
    return '\n\n'.join(blocks)


@app.route('/api/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'Can you upload examples first?'}), 400
    file = request.files['file']
    filename = file.filename or 'unknown'
    file_bytes = file.read()
    try:
        ext = filename.rsplit('.', 1)[-1].lower()
        if ext == 'pdf':
            text = extract_text_from_pdf(file_bytes)
        elif ext in ('docx', 'doc'):
            text = extract_text_from_docx(file_bytes)
        else:
            return jsonify({'error': "I can't read that one. Try a PDF or Word doc."}), 400
        if not text.strip():
            return jsonify({'error': "Can't find any words in that file."}), 400
        return jsonify({'success': True, 'filename': filename, 'text': text})
    except Exception as e:
        print(f'[Prompter] Upload error: {e}')
        return jsonify({'error': 'Something went wrong.'}), 500


@app.route('/api/fetch', methods=['POST'])
def fetch_url():
    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    if not url.startswith('http'):
        url = 'https://' + url
    try:
        text = extract_text_from_url(url)
        if not text.strip():
            return jsonify({'error': 'Could not extract text from that URL'}), 400
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace('www.', '')
        filename = f'{domain} (website)'
        return jsonify({'success': True, 'filename': filename, 'text': text})
    except guard.UnsafeURL as e:
        return jsonify({'error': str(e)}), 400
    except req.exceptions.Timeout:
        return jsonify({'error': 'That URL timed out.'}), 400
    except req.exceptions.RequestException as e:
        return jsonify({'error': f'Could not reach that URL: {str(e)}'}), 400
    except Exception as e:
        print(f'[Prompter] Fetch error: {e}')
        return jsonify({'error': str(e)}), 500


def extract_json_object(text):
    """Pull a JSON object out of a model reply, tolerant of stray prose,
    preamble or code fences around it. Returns a dict, or None if there's
    no recoverable object."""
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


# The four kinds of material, under the two piles. The page sends each item's
# type with its text, so the robot knows what it's reading instead of guessing.
MATERIAL_TYPES = {'GUIDELINES': 'STATED', 'NOTES': 'STATED',
                  'EXAMPLES': 'SHOWN', 'WEBSITE': 'SHOWN'}


def material_label(f):
    """'GUIDELINES (STATED)' for a typed item, '' for an untyped one."""
    t = str(f.get('label') or '').strip().upper()
    return f"{t} ({MATERIAL_TYPES[t]})" if t in MATERIAL_TYPES else ''


def material_block(f, limit=None):
    """One item, headed with its name and type, for the robot to read."""
    label = material_label(f)
    head = f"--- {f['filename']}{' [' + label + ']' if label else ''} ---"
    text = f['text'] if limit is None else f['text'][:limit]
    return f"{head}\n{text}"


@app.route('/api/consult', methods=['POST'])
def consult():
    data = request.get_json() or {}
    files = data.get('files', [])
    history = data.get('history', [])

    if not files:
        return jsonify({'error': 'No files provided'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # Build file context
        file_context = "Brand material provided:\n\n"
        for f in files:
            file_context += material_block(f, 3000) + "\n\n"

        system = CONSULT_PROMPT + "\n\n" + file_context

        replies = sum(1 for h in history
                      if h.get('role') == 'user'
                      and not str(h.get('content', '')).startswith(_MATERIAL_NUDGE)
                      and not str(h.get('content', '')).startswith(_PUSHBACK_NUDGE))
        last_turn = replies >= CONSULT_MAX_REPLIES
        pushback = bool(data.get('pushback'))

        # What the rules robot found, and the rules list as it stands. These
        # change as material lands, so they ride in an uncached block.
        rules_found = [str(r).strip() for r in (data.get('rules_found') or []) if str(r).strip()][:8]
        rules_now = [str(r).strip() for r in (data.get('rules') or []) if str(r).strip()][:12]
        rules_block = "\n\nRULES THE RULES ROBOT FOUND IN THE MATERIAL (raise these when you get to rules; don't invent more):\n"
        rules_block += "\n".join(f"- {r}" for r in rules_found) if rules_found else "- none found yet"
        rules_block += "\n\nTHE RULES LIST AS IT STANDS (return the full, updated list in \"rules\" every message):\n"
        rules_block += "\n".join(f"- {r}" for r in rules_now) if rules_now else "- empty"

        # Build message history. Dot's turns are stored by the frontend as her
        # plain message string, not the JSON she emits. Replaying that as-is
        # drops the model out of JSON mode from turn two on (it mirrors the prose
        # it's shown) -- which is what was 500ing the parse. Re-wrap assistant
        # turns in the JSON shape she's meant to speak in so she stays in format.
        messages = []
        for h in history:
            role = h.get('role')
            content = h.get('content', '')
            if role == 'assistant' and extract_json_object(content) is None:
                content = json.dumps({'message': content, 'ready': False, 'rules': rules_now})
            messages.append({'role': role, 'content': content})

        # Anthropic requires the first message to be from the user. After the
        # first exchange the replayed history starts with Dot's turn, which
        # would 400. Prepend a user primer whenever that's the case (this also
        # covers the no-history first call).
        if not messages or messages[0]['role'] != 'user':
            messages.insert(0, {'role': 'user', 'content': 'Please read the material and start.'})

        # The prompt + material is identical on every turn of the chat, so
        # it's cached: turn two onward reads it at a fraction of the price.
        # The last-turn line goes in a second, uncached block so adding it
        # doesn't break the cache.
        system_blocks = [{'type': 'text', 'text': system,
                          'cache_control': {'type': 'ephemeral'}},
                         {'type': 'text', 'text': rules_block}]
        if pushback:
            system_blocks.append({'type': 'text', 'text': CONSULT_PUSHBACK})
        elif last_turn:
            system_blocks.append({'type': 'text', 'text': CONSULT_LAST_TURN})

        response = client.messages.create(
            model=MODEL,
            max_tokens=800,
            system=system_blocks,
            messages=messages
        )

        raw = (response.content[0].text or '').strip()
        result = extract_json_object(raw)

        if result is None:
            # No parseable JSON came back. Don't 500 the user into the error
            # wall over a formatting wobble -- treat the reply as Dot's message
            # and carry on. Log the raw so we can watch how often this happens
            # and what's actually coming back.
            print(f'[Prompter] Consult fell back to raw reply (no JSON): {raw[:300]!r}')
            return jsonify({
                'success': True,
                'message': raw or "Hmm, that one didn't come through. Give it another go?",
                'ready': last_turn,
                'rules': rules_now
            })

        rules_out = result.get('rules')
        if not isinstance(rules_out, list):
            rules_out = rules_now
        rules_out = [str(r).strip() for r in rules_out if str(r).strip()][:12]

        return jsonify({
            'success': True,
            'message': result.get('message', ''),
            'ready': bool(result.get('ready', False)) or last_turn,
            'rules': rules_out
        })

    except Exception as e:
        print(f'[Prompter] Consult error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/extract', methods=['POST'])
def extract():
    data = request.get_json() or {}
    files = data.get('files', [])
    history = data.get('history', [])

    if not files:
        return jsonify({'error': 'No content provided'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        calibration = data.get('calibration', [])
        labelled = ["--- SOURCE: " + material_block(f)[4:] for f in files]
        user_content = "\n\n".join(labelled)

        if history:
            convo = "\n".join([f"{'Dot' if h['role']=='assistant' else 'User'}: {h['content']}" for h in history])
            user_content += f"\n\n--- CONSULTATION NOTES ---\n{convo}"

        if calibration:
            cal_lines = []
            for c in calibration:
                if c.get('skipped'):
                    continue
                ctype = c.get('type')
                dim = c.get('dimension', '')

                if ctype == 'sentence':
                    val = c.get('value', 50)
                    if val < 25:   lean = 'leans strongly toward A'
                    elif val < 45: lean = 'leans toward A'
                    elif val <= 55: lean = 'sits between A and B'
                    elif val <= 75: lean = 'leans toward B'
                    else:          lean = 'leans strongly toward B'
                    cal_lines.append(
                        f"- [{dim}] The brand {lean} ({val}/100):\n"
                        f"    A: \"{c.get('sentenceA','')}\"\n"
                        f"    B: \"{c.get('sentenceB','')}\""
                    )

                elif ctype == 'boundary':
                    opts = c.get('options', [])
                    sel = c.get('selected')
                    if sel is not None and 0 <= sel < len(opts):
                        cal_lines.append(
                            f"- [{dim}] The brand is \"{c.get('trait','')}\" but the user "
                            f"named \"{opts[sel]}\" as the wrong end to steer away from."
                        )

                elif ctype == 'feeling':
                    opts = c.get('options', [])
                    sel = c.get('selected')
                    if sel is not None and 0 <= sel < len(opts):
                        cal_lines.append(
                            f"- [{dim}] After reading, the reader should feel \"{opts[sel]}\"."
                        )

            if cal_lines:
                user_content += (
                    "\n\n--- CALIBRATION (the user's own sense-check choices — treat as "
                    "corrections, not hints; weight above inference and make visible) ---\n"
                    + "\n".join(cal_lines)
                )

        # The person's own rules, from SET THE RULES. Theirs, so they go in
        # exactly as written.
        rules = [str(r).strip() for r in (data.get('rules') or []) if str(r).strip()][:12]
        if rules:
            user_content += (
                "\n\n--- HOUSE RULES THE USER SET (each one goes into houseRules "
                "word for word: don't reword, merge or drop them; add others only "
                "if the material clearly states them) ---\n"
                + "\n".join(f"- {r}" for r in rules)
            )

        response = client.messages.create(
            model=MODEL,
            max_tokens=3000,
            system=EXTRACT_PROMPT,
            messages=[{'role': 'user', 'content': user_content}]
        )

        raw = response.content[0].text
        clean = raw.replace('```json', '').replace('```', '').strip()
        profile = json.loads(clean)

        return jsonify({'success': True, 'profile': profile, 'brandName': profile.get('brandName', 'Brand')})

    except json.JSONDecodeError as e:
        print(f'[Prompter] Extract JSON error: {e}')
        return jsonify({'error': 'Could not parse AI response'}), 500
    except Exception as e:
        print(f'[Prompter] Extract error: {e}')
        return jsonify({'error': str(e)}), 500



@app.route('/api/confirm', methods=['POST'])
def confirm():
    data = request.get_json() or {}
    files = data.get('files', [])
    history = data.get('history', [])

    if not files:
        return jsonify({'error': 'No files provided'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        file_context = "Brand material:\n\n"
        for f in files:
            file_context += material_block(f, 2500) + "\n\n"

        convo = ""
        if history:
            convo = "\n\nConsultation so far:\n" + "\n".join([
                f"{'Dot' if h['role']=='assistant' else 'User'}: {h['content']}"
                for h in history
            ])

        message = client.messages.create(
            model=MODEL,
            max_tokens=1200,
            system=CONFIRM_PROMPT,
            messages=[{'role': 'user', 'content': file_context + convo}]
        )

        raw = message.content[0].text
        clean = raw.replace('```json', '').replace('```', '').strip()
        result = json.loads(clean)

        return jsonify({'success': True, 'checks': result.get('checks', [])})

    except json.JSONDecodeError as e:
        print(f'[Prompter] Confirm JSON error: {e}')
        return jsonify({'error': 'Could not parse response'}), 500
    except Exception as e:
        print(f'[Prompter] Confirm error: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/confirm/regenerate', methods=['POST'])
def confirm_regenerate():
    data = request.get_json() or {}
    files = data.get('files', [])
    history = data.get('history', [])
    reject = data.get('reject') or {}

    if not files:
        return jsonify({'error': 'No files provided'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        file_context = "Brand material:\n\n"
        for f in files:
            file_context += material_block(f, 2500) + "\n\n"

        convo = ""
        if history:
            convo = "\n\nConsultation so far:\n" + "\n".join([
                f"{'Dot' if h['role']=='assistant' else 'User'}: {h['content']}"
                for h in history
            ])

        rejected = (
            "\n\nThe sentence dial the user rejected (do not repeat it):\n"
            f"- axis: More {reject.get('noteA', '?')} <-> More {reject.get('noteB', '?')}\n"
            f"- A: {reject.get('sentenceA', '')}\n"
            f"- B: {reject.get('sentenceB', '')}"
        )

        message = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=REGEN_SENTENCE_PROMPT,
            messages=[{'role': 'user', 'content': file_context + convo + rejected}]
        )

        raw = message.content[0].text
        clean = raw.replace('```json', '').replace('```', '').strip()
        check = json.loads(clean)

        if check.get('type') != 'sentence':
            return jsonify({'error': 'Unexpected response shape'}), 500

        return jsonify({'success': True, 'check': check})

    except json.JSONDecodeError as e:
        print(f'[Prompter] Regenerate JSON error: {e}')
        return jsonify({'error': 'Could not parse response'}), 500
    except Exception as e:
        print(f'[Prompter] Regenerate error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'service': 'prompter'})


@app.route('/api/summarise', methods=['POST'])
def summarise():
    data = request.get_json() or {}
    text = (data.get('text') or '').strip()[:500]
    if not text:
        return jsonify({'success': True, 'label': 'EXAMPLES'})
    if not ANTHROPIC_API_KEY:
        return jsonify({'success': True, 'label': 'EXAMPLES'})
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=MODEL_LIGHT,
            max_tokens=20,
            system=SUMMARISE_PROMPT,
            messages=[{'role': 'user', 'content': text}]
        )
        word = (message.content[0].text or '').strip().upper().strip('.')
        # Only the three types a robot can tell from the text. Anything else,
        # or a wobble, is treated as copy -- shaky material is evidence, never
        # promoted to what the brand says it is.
        label = word if word in ('GUIDELINES', 'NOTES', 'EXAMPLES') else 'EXAMPLES'
        return jsonify({'success': True, 'label': label})
    except Exception as e:
        print(f'[Prompter] Summarise error: {e}')
        return jsonify({'success': True, 'label': 'EXAMPLES'})


@app.route('/api/rules', methods=['POST'])
def suggest_rules():
    """THE RULES: the quiet robot finds the hard rules it can, and
    Dot voices what it finds. Guidelines and Notes are read first,
    because that's where rules are written down."""
    data = request.get_json() or {}
    files = data.get('files', [])
    if not files:
        return jsonify({'success': True, 'rules': []})
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500
    try:
        stated_first = sorted(files, key=lambda f: 0 if MATERIAL_TYPES.get(
            str(f.get('label') or '').upper()) == 'STATED' else 1)
        content = "\n\n".join(material_block(f, 4000) for f in stated_first)
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=MODEL_LIGHT,
            max_tokens=400,
            system=RULES_PROMPT,
            messages=[{'role': 'user', 'content': content}]
        )
        result = extract_json_object(message.content[0].text) or {}
        rules = [str(r).strip() for r in (result.get('rules') or []) if str(r).strip()][:5]
        return jsonify({'success': True, 'rules': rules})
    except Exception as e:
        print(f'[Prompter] Rules error: {e}')
        return jsonify({'error': 'Something went wrong.'}), 500


@app.route('/api/opening', methods=['GET'])
def opening():
    return jsonify({
        'success': True,
        'message': "How you talk is who you are. Let's craft a prompt so you sound like you."
    })


# The only files the public can have: the page, its styles and scripts,
# the favicon, the pictures.
_HERE = os.path.dirname(os.path.abspath(__file__))


@app.route('/')
def serve_index():
    return send_from_directory(_HERE, 'index.html')


@app.route('/favicon.ico')
def serve_favicon():
    return send_from_directory(_HERE, 'favicon.ico')


@app.route('/static/<path:name>')
def serve_static_file(name):
    # The page's styles and scripts. send_from_directory refuses anything
    # that climbs out of static/.
    return send_from_directory(os.path.join(_HERE, 'static'), name)


@app.route('/images/<path:name>')
def serve_image(name):
    # send_from_directory refuses anything that climbs out of images/.
    return send_from_directory(os.path.join(_HERE, 'images'), name)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
