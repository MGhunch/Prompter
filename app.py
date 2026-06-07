"""
Prompter v2
Flask server with file upload, per-file review, and brand profile extraction.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import anthropic
import os
import json
import io

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

EXTRACT_PROMPT = """You are the Prompter InputBot. Your job is to read any brand material and produce a structured one-page brand profile.

This document will be used by both humans and AI to write on-brand communications. Every line must be useful to both audiences simultaneously. Write with precision, not length. If it doesn't change how something gets written, leave it out.

Output exactly five sections as a JSON object with these exact keys: brand, customerFeels, behaviours, examples, houseRules.

BRAND: One short paragraph. Who this brand is, what they stand for, and what that means for the writing. End with a single direction sentence. Maximum four sentences.

CUSTOMER_FEELS: One short paragraph. The reader's emotional state after reading — not the brand's intention. Maximum three sentences.

BEHAVIOURS: Array of exactly five objects with keys "we" and "not". Specific paired contrasts true to this brand only. No generic pairs.

EXAMPLES: Array of exactly five objects with keys "more" and "less". Real sentences — brand voice on left, generic version on right. Include quotation marks.

HOUSE_RULES: Array of objects with keys "key" and "rule". No cap on number. Each rule specific and binary. Cover product names, capitalisation, punctuation, numbers, mandatory inclusions, things that can never appear.

For any section where source material is insufficient, use "[DON'T KNOW YET — reason]" as the value. Never guess. Never pad.

Ignore: photography, logos, colours, internal values, mission statements — anything that doesn't change how words get written.

Respond ONLY with valid JSON. No markdown. No backticks. No preamble."""

REVIEW_PROMPT = """You are Dot, the Prompter review bot. You've just received a set of brand files. Your job is to give a quick, honest read on each one and tell the user what you have, what's missing, and whether it's enough to produce a great brand profile.

For each file, assess:
- What type of material it is (brand guidelines, TOV doc, copy examples, emails, website copy, etc.)
- How useful it is for extracting writing voice (not design, not values — writing)
- What's strong about it
- What's missing

Then give an overall nudge: what one thing would most improve the profile if added?

Output a JSON object with these exact keys:
- files: array of objects with keys: filename, verdict (good|warn|miss), summary (one sentence, plain English)
- nudge: one or two sentences. Specific. Tell them exactly what to add and why. If you have everything you need, say so.

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
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return '\n\n'.join(paragraphs)


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


@app.route('/api/review', methods=['POST'])
def review():
    data = request.get_json() or {}
    files = data.get('files', [])  # [{filename, text}, ...]

    if not files:
        return jsonify({'error': 'No files to review'}), 400

    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        file_summaries = []
        for f in files:
            # Truncate each file to ~2000 chars for the review call
            preview = f['text'][:2000]
            file_summaries.append(f"--- FILE: {f['filename']} ---\n{preview}")

        user_content = "Here are the brand files to review:\n\n" + "\n\n".join(file_summaries)

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=REVIEW_PROMPT,
            messages=[{'role': 'user', 'content': user_content}]
        )

        raw = message.content[0].text
        clean = raw.replace('```json', '').replace('```', '').strip()
        review_data = json.loads(clean)

        return jsonify({'success': True, 'review': review_data})

    except json.JSONDecodeError as e:
        print(f'[Prompter] Review JSON parse error: {e}')
        return jsonify({'error': 'Could not parse review response'}), 500

    except Exception as e:
        print(f'[Prompter] Review error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/extract', methods=['POST'])
def extract():
    data = request.get_json() or {}
    files = data.get('files', [])  # [{filename, text}, ...]
    brand_name = (data.get('brandName') or 'Brand').strip()

    if not files:
        return jsonify({'error': 'No content provided'}), 400

    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # Keep files labelled and separate
        labelled = []
        for f in files:
            labelled.append(f"--- SOURCE: {f['filename']} ---\n{f['text']}")

        user_content = f"Brand name: {brand_name}\n\n" + "\n\n".join(labelled)

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=EXTRACT_PROMPT,
            messages=[{'role': 'user', 'content': user_content}]
        )

        raw = message.content[0].text
        clean = raw.replace('```json', '').replace('```', '').strip()
        profile = json.loads(clean)

        return jsonify({'success': True, 'profile': profile, 'brandName': brand_name})

    except json.JSONDecodeError as e:
        print(f'[Prompter] JSON parse error: {e}')
        return jsonify({'error': 'Could not parse AI response'}), 500

    except Exception as e:
        print(f'[Prompter] Error: {e}')
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
