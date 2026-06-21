"""
Prompter v5
Single-stage consultation model.
Dot reads material, asks targeted questions, builds profile through conversation.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import anthropic
import os
import json
import io
import requests as req
from bs4 import BeautifulSoup
from prompts import CONSULT_PROMPT, EXTRACT_PROMPT, CONFIRM_PROMPT, SUMMARISE_PROMPT
from revise import revise_bp  # REVISE feature block (tick-it-or-tweak-it)

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)
app.register_blueprint(revise_bp)  # adds /api/revise; touches no existing route

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

# One source of truth for the model. claude-sonnet-4-20250514 retired 15 Jun 2026.
# Override per-environment with PROMPTER_MODEL if needed.
MODEL = os.environ.get('PROMPTER_MODEL', 'claude-sonnet-4-6')


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
    resp = req.get(url, headers=headers, timeout=12)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'lxml')
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
        return jsonify({'error': 'No file provided'}), 400
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
            return jsonify({'error': f'Unsupported file type: {ext}'}), 400
        if not text.strip():
            return jsonify({'error': 'Could not extract text from file'}), 400
        return jsonify({'success': True, 'filename': filename, 'text': text})
    except Exception as e:
        print(f'[Prompter] Upload error: {e}')
        return jsonify({'error': str(e)}), 500


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
            file_context += f"--- {f['filename']} ---\n{f['text'][:3000]}\n\n"

        system = CONSULT_PROMPT + "\n\n" + file_context

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
                content = json.dumps({'message': content, 'ready': False})
            messages.append({'role': role, 'content': content})

        # Anthropic requires the first message to be from the user. After the
        # first exchange the replayed history starts with Dot's turn, which
        # would 400. Prepend a user primer whenever that's the case (this also
        # covers the no-history first call).
        if not messages or messages[0]['role'] != 'user':
            messages.insert(0, {'role': 'user', 'content': 'Please read the material and start.'})

        response = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=system,
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
                'ready': False
            })

        return jsonify({
            'success': True,
            'message': result.get('message', ''),
            'ready': result.get('ready', False)
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
        labelled = [f"--- SOURCE: {f['filename']} ---\n{f['text']}" for f in files]
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
            file_context += f"--- {f['filename']} ---\n{f['text'][:2500]}\n\n"

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

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'service': 'prompter'})


@app.route('/api/summarise', methods=['POST'])
def summarise():
    data = request.get_json() or {}
    text = (data.get('text') or '').strip()[:500]
    if not text:
        return jsonify({'success': True, 'label': 'Notes'})
    if not ANTHROPIC_API_KEY:
        return jsonify({'success': True, 'label': 'Notes'})
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=MODEL,
            max_tokens=20,
            system=SUMMARISE_PROMPT,
            messages=[{'role': 'user', 'content': text}]
        )
        label = message.content[0].text.strip()
        return jsonify({'success': True, 'label': label})
    except Exception as e:
        print(f'[Prompter] Summarise error: {e}')
        return jsonify({'success': True, 'label': 'Notes'})


@app.route('/api/opening', methods=['GET'])
def opening():
    return jsonify({
        'success': True,
        'message': "How you talk is who you are. Let's craft a prompt so you sound like you."
    })


@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
