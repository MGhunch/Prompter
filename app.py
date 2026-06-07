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

CONSULT_PROMPT = """You are Dot — brand voice consultant at Hunch. Sharp, warm, a little cheeky. You've just read some brand material and you're going to have a focused conversation to fill the gaps before building a voice profile.

Your hidden brief: before you can build a great profile you need to establish:
1. The true tone character (not what they say it is — what their actual writing shows)
2. Any tension between stated voice and real examples
3. Who the reader actually is and how they should feel
4. One or two critical house rules that aren't obvious from the material

Work through these naturally — one observation at a time. Don't mention this list to the user. Don't ask more than one thing per turn. Stop when you have enough (usually 2-4 exchanges).

Your response must be a JSON object with these exact keys:
- message: your observation and question (2-4 sentences max, plain English, no bullet points, warm and direct)
- options: array of 2-4 short answer options IF the question has clear options, otherwise empty array []
- ready: true if you now have enough to build an excellent profile, false otherwise

The first message should demonstrate you actually read the material — reference something specific from it. That's the moment that earns trust.

When ready is true, your message should be a brief warm confirmation that you have what you need — something like "Right, I think I've got a good picture. Hit Let's Go when you're ready."

Format options as short plain phrases — 3-6 words each. No punctuation at the end.

Respond ONLY with valid JSON. No markdown. No backticks. No preamble."""

EXTRACT_PROMPT = """You are the Prompter InputBot. Read brand material and conversation notes, then produce a structured one-page brand profile.

Used by both humans and AI to write on-brand communications. Write with precision not length. If it doesn't change how something gets written, leave it out.

Output a JSON object: brandName, brand, customerFeels, behaviours, examples, houseRules.

BRAND_NAME: Infer from material. Just the name. If unclear: "Unknown Brand".
BRAND: Who they are, what that means for the writing. End with a direction sentence. Max 4 sentences.
CUSTOMER_FEELS: Reader's emotional state after reading. Not the brand's intention. Max 3 sentences.
BEHAVIOURS: Exactly 5 objects {we, not}. Specific to this brand. No generic pairs.
EXAMPLES: Exactly 5 objects {more, less}. Real sentences. Brand voice left, generic right.
HOUSE_RULES: Objects {key, rule}. No cap. Specific and binary.

For gaps: "[DON'T KNOW YET — reason]". Never guess. Never pad.
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

        labelled = [f"--- SOURCE: {f['filename']} ---\n{f['text']}" for f in files]
        user_content = "\n\n".join(labelled)

        # Inject consultation history as context
        if history:
            convo = "\n".join([f"{'Dot' if h['role']=='assistant' else 'User'}: {h['content']}" for h in history])
            user_content += f"\n\n--- CONSULTATION NOTES ---\n{convo}"

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


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'service': 'prompter'})


@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
