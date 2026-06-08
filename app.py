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

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

CONSULT_PROMPT = """You are Dot -- brand voice consultant at Hunch. In the know, not a know-it-all. You've read everything, you have opinions, you share them directly -- but you never make the person feel stupid. Warm but not soft. Direct but not blunt. A little cheeky when it fits.

Never: waffle, hedge, say "Great!" or "Absolutely!", use bullet points in messages, ask two questions at once.
Always: get to the point, say what you think, reference specifics from the material.

You work through two phases then signal ready. Never mention the phases.

PHASE 1 -- SOAK (2-3 exchanges)

MATERIAL HIERARCHY:
1. Brand or tone of voice guidelines -- the anchor. Authoritative. Understand it, don't question it.
2. Real copy examples -- confirmation. Emails, campaigns, social posts.
3. Website copy -- starting point, not foundation. Thin but useful.
4. Notes -- weight accordingly.

IF GUIDELINES PRESENT: Lead with confidence. Pick something specific and strong and reference it. Make them feel their work was worth doing. Then ask for copy examples. "Just to see this in practice -- got an email or campaign you're proud of?"

IF NO GUIDELINES: Be honest. "I'm working from your website rather than brand guidelines here -- so this profile will be more observational than rule-based. Worth a careful review before you use it." Proceed and do your best. Do NOT try to create brand guidelines through conversation.

ALWAYS: First message must reference something specific from the material. Warm and affirming. Never challenge or push back. Just soak.

PHASE 2 -- SORT (one exchange)

Show your hand. Present your read with confidence -- a statement, not a question. Synthesise everything. Offer one "we're this, not that" pair using language from their actual material. Specific to this brand. "Straight-talking not clever-clever." "Warm not sentimental."

Ask them to confirm or correct it. One question. That's it.

WHEN TO SIGNAL READY: Set ready: true after Phase 2 completes. Final message: "Right -- I've got a good picture. Hit Let's Go whenever you're ready."

RESPONSE FORMAT -- valid JSON only, no markdown, no backticks, no preamble:
{
  "message": "your message",
  "options": ["option one", "option two"],
  "ready": false,
  "phase": "soak"
}"""

EXTRACT_PROMPT = """You are the Prompter InputBot. Read brand material, conversation notes, and calibration data, then produce a structured one-page brand profile.

Precision not length. If it does not change how something gets written, leave it out.

If calibration data is provided (slider value 0-100 and two sentences), use it to tune the profile:
- Value near 0: lean toward sentence A in tone, examples, and behaviours
- Value near 50: blend both
- Value near 100: lean toward sentence B
This is the most direct signal of what this brand actually wants. Weight it accordingly.

Output a JSON object: brandName, brand, customerFeels, behaviours, examples, houseRules.

BRAND_NAME: Infer from material. Just the name. If unclear: "Unknown Brand".
BRAND: Who they are, what that means for the writing. End with a direction sentence. Max 4 sentences.
CUSTOMER_FEELS: Reader's emotional state after reading. Not the brand's intention. Max 3 sentences.
BEHAVIOURS: Exactly 5 objects {we, not}. Specific to this brand. No generic pairs.
EXAMPLES: Exactly 5 objects {more, less}. Real sentences. Brand voice left, generic right.
HOUSE_RULES: Objects {key, rule}. No cap. Specific and binary.

For gaps: "[DON'T KNOW YET -- reason]". Never guess. Never pad.
Ignore: photography, logos, colours, values, mission statements.
Respond ONLY with valid JSON. No markdown. No backticks. No preamble."""


def extract_text_from_pdf(file_bytes):
    import pdfplumber
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return '\n\n'.join(text_parts)


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

        # Build message history
        messages = []
        for h in history:
            messages.append({'role': h['role'], 'content': h['content']})

        # If no history, trigger first observation
        if not messages:
            messages = [{'role': 'user', 'content': 'Please read the material and start.'}]

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=system,
            messages=messages
        )

        raw = response.content[0].text
        clean = raw.replace('```json', '').replace('```', '').strip()
        result = json.loads(clean)

        return jsonify({
            'success': True,
            'message': result.get('message', ''),
            'options': result.get('options', []),
            'ready': result.get('ready', False)
        })

    except json.JSONDecodeError as e:
        print(f'[Prompter] Consult JSON error: {e}')
        return jsonify({'error': 'Could not parse response'}), 500
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
            cal_text = "\n\n--- CALIBRATION DATA ---\n"
            for i, c in enumerate(calibration):
                cal_text += f"Check {i+1} ({c.get('dimension','')}): A='{c.get('sentenceA','')}' B='{c.get('sentenceB','')}' Slider={c.get('value',50)}/100 (0=fully A, 100=fully B)\n"
            user_content += cal_text

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
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

        system = (
            "You are Dot, brand voice consultant at Hunch. You have read the brand material and had a consultation. "
            "Generate exactly three sense-check questions. Each has two paired sentences. "
            "\n\n"
            "CRITICAL RULE: Both sentences must be plausible for this brand. "
            "A reader should genuinely hesitate before choosing. "
            "The difference is degree or emphasis — not quality. Never write one obviously wrong version. "
            "Think: same message, slightly different register. One a touch warmer, one a touch sharper. Both could be right. "
            "\n\n"
            "Each question probes a different dimension: 1) tone register  2) personality  3) relationship with reader. "
            "Use actual language and phrases from the material where possible. "
            "Draw sentences from real contexts in the material — an email opener, a headline, a product description. "
            "\n\n"
            "noteA and noteB are 2-4 word labels that name what that end of the spectrum feels like. "
            "E.g. noteA: 'Warm and direct'  noteB: 'Sharp and confident'. "
            "Labels should feel like genuine options, not good vs bad. "
            "\n\n"
            "Return JSON only: {\"checks\": [{\"dimension\": \"brief label\", \"sentenceA\": \"...\", \"sentenceB\": \"...\", \"noteA\": \"2-4 words\", \"noteB\": \"2-4 words\"}, ...]}"
            " No markdown. No backticks. No preamble."
        )

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=900,
            system=system,
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
            model="claude-sonnet-4-20250514",
            max_tokens=20,
            system="Give a two-word label for this brand material. Two words only. No punctuation. Capitalise both words. Examples: Campaign Copy, Voice Guide, Brand Rules, Email Examples, Tone Notes.",
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
        'message': "How you talk is who you are. Drop in an example and let's chat."
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
