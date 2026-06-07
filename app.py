"""
Prompter v4
Two-column layout. Dot chat in right panel.
Brand name inferred. Upload / fetch / notes / chat / extract.
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

EXTRACT_PROMPT = """You are the Prompter InputBot. Read brand material and produce a structured one-page brand profile.

This document will be used by both humans and AI to write on-brand communications. Write with precision, not length. If it doesn't change how something gets written, leave it out.

Output a JSON object with these exact keys: brandName, brand, customerFeels, behaviours, examples, houseRules.

BRAND_NAME: Infer from the material. Just the name. If unclear, use "Unknown Brand".

BRAND: One short paragraph. Who this brand is, what they stand for, what that means for the writing. End with a single direction sentence. Maximum four sentences.

CUSTOMER_FEELS: One short paragraph. The reader's emotional state after reading — not the brand's intention. Maximum three sentences.

BEHAVIOURS: Array of exactly five objects with keys "we" and "not". Specific paired contrasts true to this brand only. No generic pairs.

EXAMPLES: Array of exactly five objects with keys "more" and "less". Real sentences — brand voice on left, generic on right.

HOUSE_RULES: Array of objects with keys "key" and "rule". No cap. Each rule specific and binary.

For insufficient material use "[DON'T KNOW YET — reason]". Never guess. Never pad.
Ignore: photography, logos, colours, internal values, mission statements.
Respond ONLY with valid JSON. No markdown. No backticks. No preamble."""

REVIEW_PROMPT = """You are Dot, the Prompter review bot. Give a quick honest read on brand material.

For each file assess what type it is and how useful for extracting writing voice (not design, not values — writing).

Output JSON with:
- files: array of {filename, verdict (good|warn|miss), summary (one sentence)}
- nudge: one or two sentences. What would most improve the profile? Be specific.

Respond ONLY with valid JSON. No markdown. No backticks. No preamble."""

DOT_CHAT_PROMPT = """You are Dot — a smart, warm, slightly playful brand voice expert working inside Prompter, a Hunch product.

You're looking at brand material a user has uploaded. Your job is to have a helpful conversation about it — answering their questions, giving honest opinions, flagging gaps, and helping them decide when they have enough to extract a great profile.

You know what files they've shared (listed below). Be specific, be honest, be warm. Don't be corporate. Don't be sycophantic. Keep answers short — two or three sentences max unless they ask for more.

If they ask something you can't answer from the material, say so directly.

You are NOT generating the profile — that happens when they hit LET'S GO. Right now you're just talking."""


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


@app.route('/api/review', methods=['POST'])
def review():
    data = request.get_json() or {}
    files = data.get('files', [])
    if not files:
        return jsonify({'error': 'No files to review'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        file_summaries = [f"--- FILE: {f['filename']} ---\n{f['text'][:2000]}" for f in files]
        user_content = "Brand files to review:\n\n" + "\n\n".join(file_summaries)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=REVIEW_PROMPT,
            messages=[{'role': 'user', 'content': user_content}]
        )
        raw = message.content[0].text
        clean = raw.replace('```json', '').replace('```', '').strip()
        return jsonify({'success': True, 'review': json.loads(clean)})
    except json.JSONDecodeError as e:
        print(f'[Prompter] Review JSON error: {e}')
        return jsonify({'error': 'Could not parse review response'}), 500
    except Exception as e:
        print(f'[Prompter] Review error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json() or {}
    files = data.get('files', [])
    history = data.get('history', [])
    message = (data.get('message') or '').strip()

    if not message:
        return jsonify({'error': 'No message provided'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # Build file context
        file_context = ""
        if files:
            file_context = "\n\nFiles the user has shared:\n"
            for f in files:
                file_context += f"\n--- {f['filename']} ---\n{f['text'][:1500]}\n"
        else:
            file_context = "\n\nThe user hasn't shared any files yet."

        system = DOT_CHAT_PROMPT + file_context

        # Build message history
        messages = []
        for h in history:
            messages.append({'role': h['role'], 'content': h['content']})
        messages.append({'role': 'user', 'content': message})

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=system,
            messages=messages
        )

        reply = response.content[0].text
        return jsonify({'success': True, 'reply': reply})

    except Exception as e:
        print(f'[Prompter] Chat error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/extract', methods=['POST'])
def extract():
    data = request.get_json() or {}
    files = data.get('files', [])
    if not files:
        return jsonify({'error': 'No content provided'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        labelled = [f"--- SOURCE: {f['filename']} ---\n{f['text']}" for f in files]
        user_content = "\n\n".join(labelled)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=EXTRACT_PROMPT,
            messages=[{'role': 'user', 'content': user_content}]
        )
        raw = message.content[0].text
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
